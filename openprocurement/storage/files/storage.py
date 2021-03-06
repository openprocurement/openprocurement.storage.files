import os
import hashlib
import zipfile
import simplejson as json
from hmac import compare_digest
from fcntl import flock, LOCK_EX, LOCK_NB
from magic import Magic
from time import sleep
from datetime import datetime
from pytz import timezone
from rfc6266 import build_header
from requests import Session
from shutil import copyfileobj
from urllib import quote
from openprocurement.storage.files.dangerous import DANGEROUS_EXT, DANGEROUS_MIME_TYPES
from openprocurement.documentservice.storage import (HashInvalid, KeyNotFound, ContentUploaded,
    StorageUploadError, get_filename)
from openprocurement.documentservice.utils import LOGGER


TZ = timezone(os.environ['TZ'] if 'TZ' in os.environ else 'Europe/Kiev')


def get_now():
    return datetime.now(TZ)


class FilesStorage:
    def __init__(self, settings):
        self.web_root = settings['files.web_root'].strip()
        self.archive_web_root = self.web_root + '.archive'
        self.save_path = settings['files.save_path'].strip()
        self.secret_key = settings['files.secret_key'].strip()
        self.disposition = settings.get('files.disposition', 'inline')
        forbidden_ext = settings.get('files.forbidden_ext', DANGEROUS_EXT)
        self.forbidden_ext = set([s.strip().upper() for s in forbidden_ext.split(',') if s.strip()])
        self.forbidden_mime = DANGEROUS_MIME_TYPES
        self.forbidden_hash = set(['md5:d41d8cd98f00b204e9800998ecf8427e'])     # empty file
        if 'files.forbidden_mime' in settings:
            with open(settings['files.forbidden_mime']) as fp:
                self.forbidden_mime = set([s.strip().lower() for s in fp.readlines() if '/' in s.strip()])
        if 'files.forbidden_hash' in settings:
            with open(settings['files.forbidden_hash']) as fp:
                self.forbidden_hash = set([s.strip().lower() for s in fp.readlines() if s.startswith("md5:")])
        if 'files.get_url_expire' in settings:
            # dirty monkey pathing
            from openprocurement.documentservice import views
            self.old_EXPIRES = views.EXPIRES
            views.EXPIRES = int(settings['files.get_url_expire'])
            LOGGER.warning("Chagne default expire for get_url from {} to {}".format(
                           self.old_EXPIRES, views.EXPIRES))
        self.replica_apis = list()
        if 'files.replica_api' in settings:
            self.replica_apis = [s.strip() for s in settings['files.replica_api'].split(',') if s.strip()]
        self.require_replica_upload = settings.get('files.require_replica_upload', True)
        self.replica_timeout = 300
        self.magic = Magic(mime=True)
        self.session = Session()
        self.dir_mode = 0o2710
        self.file_mode = 0o440
        self.meta_mode = 0o400

    def web_location(self, key, archived=False):
        web_root = self.web_root if not archived else self.archive_web_root
        return os.path.join(web_root, key[-2:], key[-4:], key).encode()

    def file_path(self, key):
        path = os.path.join(self.save_path, key[-2:], key[-4:])
        return path, os.path.join(path, key)

    def hash_to_uuid(self, md5hash):
        return hashlib.sha1(md5hash + ':uuid:' + self.secret_key).hexdigest()

    def uuid_to_file(self, uuid):
        return hashlib.sha1(uuid + ':file:' + self.secret_key).hexdigest()

    def save_meta(self, uuid, meta, overwrite=False):
        key = self.uuid_to_file(uuid)
        path, name = self.file_path(key)
        name += '.meta'
        if not overwrite and os.path.exists(name):
            raise ContentUploaded(uuid)
        meta['modified'] = get_now().isoformat()
        if not os.path.exists(path):
            os.makedirs(path, mode=self.dir_mode)
        with open(name + '~', 'wt') as fp:
            flock(fp, LOCK_EX | LOCK_NB)
            json.dump(meta, fp)
        os.rename(name + '~', name)
        os.chmod(name, self.meta_mode)

    def read_meta(self, uuid):
        key = self.uuid_to_file(uuid)
        path, name = self.file_path(key)
        name += '.meta'
        if not os.path.exists(name):
            raise KeyNotFound(uuid)  # pragma: no cover
        with open(name) as fp:
            return json.load(fp)

    def check_forbidden(self, filename, content_type, fp):
        for ext in filename.rsplit('.', 2)[1:]:
            if ext.upper() in self.forbidden_ext:
                return True
        if content_type.lower() in self.forbidden_mime:
            return True
        fp.seek(0)
        magic_type = self.magic.from_buffer(fp.read(2048))
        if magic_type.lower() in self.forbidden_mime:
            return True
        if filename.upper().endswith('.ZIP') or \
                'application/zip' in (content_type, magic_type):
            fp.seek(0)
            try:
                zipobj = zipfile.ZipFile(fp)
            except zipfile.BadZipfile:
                return
            for filename in zipobj.namelist():
                for ext in filename.rsplit('.', 2)[1:]:
                    if ext.upper() in self.forbidden_ext:
                        return True

    def compute_md5(self, in_file, blocksize=0x10000):
        in_file.seek(0)
        md5hash = hashlib.md5()
        while True:
            block = in_file.read(blocksize)
            if not block or not len(block):
                break
            md5hash.update(block)
        return "md5:" + md5hash.hexdigest()

    def upload_to_replicas(self, post_file, uuid, max_retry=10):
        filename = post_file.filename
        content_type = post_file.type
        in_file = post_file.file

        for replica in self.replica_apis:
            auth = None
            schema = "http"
            if "://" in replica:
                schema, replica = replica.split("://", 1)
            if "@" in replica:
                auth, replica = replica.split('@', 1)
                auth = tuple(auth.split(':', 1))
            post_url = "{}://{}/upload".format(schema, replica)
            timeout = self.replica_timeout
            replica_uuid = None
            for n in range(max_retry):
                try:
                    in_file.seek(0)
                    files = {'file': (filename, in_file, content_type, {})}
                    res = self.session.post(post_url, auth=auth, files=files, timeout=timeout)
                    res.raise_for_status()
                    if res.status_code == 200:
                        data = res.json()
                        get_url, get_params = data['get_url'].split('?', 1)
                        get_host, replica_uuid = get_url.rsplit('/', 1)
                        if uuid != replica_uuid:  # pragma: no cover
                            raise ValueError("Salve uuid mismatch, verify secret_key")
                        LOGGER.info("Upload {} to replica {}".format(uuid, post_url))
                        break
                except Exception as e:  # pragma: no cover
                    LOGGER.warning("Error {}/{} upload {} to {}: {}".format(n + 1, max_retry,
                                    uuid, post_url, e))
                    if n >= max_retry - 1:
                        raise
                    sleep(n + 1)

    def register(self, md5hash):
        if md5hash in self.forbidden_hash:
            raise StorageUploadError('forbidden_file ' + md5hash)
        now_iso = get_now().isoformat()
        uuid = self.hash_to_uuid(md5hash)
        meta = dict(uuid=uuid, hash=md5hash, created=now_iso)
        try:
            self.save_meta(uuid, meta)
        except ContentUploaded:
            pass
        return uuid

    def upload(self, post_file, uuid=None):
        now_iso = get_now().isoformat()
        filename = get_filename(post_file.filename)
        content_type = post_file.type
        in_file = post_file.file
        md5hash = self.compute_md5(in_file)
        if md5hash in self.forbidden_hash:
            LOGGER.warning("Forbidden file by hash {}".format(md5hash))
            raise StorageUploadError('forbidden_file ' + md5hash)

        if uuid is None:
            uuid = self.hash_to_uuid(md5hash)
            meta = dict(uuid=uuid, hash=md5hash, created=now_iso)
        else:
            meta = self.read_meta(uuid)
            if not compare_digest(meta['hash'], md5hash):
                raise HashInvalid(meta['hash'] + "/" + md5hash)

        key = self.uuid_to_file(uuid)
        path, name = self.file_path(key)
        if os.path.exists(name):
            meta = self.read_meta(uuid)
            if meta['filename'] != filename:
                if 'alternatives' not in meta:
                    meta['alternatives'] = list()
                meta['alternatives'].append({
                    'created': now_iso,
                    'filename': filename
                })
                self.save_meta(uuid, meta, overwrite=True)
            return uuid, md5hash, content_type, filename

        if self.check_forbidden(filename, content_type, in_file):
            LOGGER.warning("Forbidden file {} {} {} {}".format(filename, content_type, uuid, md5hash))
            raise StorageUploadError('forbidden_file ' + md5hash)

        meta['filename'] = filename
        meta['Content-Type'] = content_type
        meta['Content-Disposition'] = build_header(
            filename,
            disposition=self.disposition,
            filename_compat=quote(filename.encode('utf-8')))

        self.save_meta(uuid, meta, overwrite=True)

        in_file.seek(0)
        with open(name + '~', 'wb') as out_file:
            flock(out_file, LOCK_EX | LOCK_NB)
            copyfileobj(in_file, out_file)
        os.rename(name + '~', name)
        os.chmod(name, self.file_mode)

        try:
            if self.replica_apis:
                self.upload_to_replicas(post_file, uuid)
        except Exception as e:  # pragma: no cover
            LOGGER.error("Replica failed {}, remove file {} {}".format(e, uuid, md5hash))
            if self.require_replica_upload:
                os.rename(name, name + '~')
                raise StorageUploadError('replica_failed')

        return uuid, md5hash, content_type, filename

    def get(self, uuid):
        meta = self.read_meta(uuid)
        if meta['uuid'] != uuid:
            raise KeyNotFound(uuid)  # pragma: no cover
        if meta['hash'] in self.forbidden_hash:
            raise KeyNotFound(uuid)  # pragma: no cover
        key = self.uuid_to_file(uuid)
        meta['X-Accel-Redirect'] = self.web_location(key, meta.get('archived'))
        return meta
