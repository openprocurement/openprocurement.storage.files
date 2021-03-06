# -*- coding: utf-8 -*-

import binascii
import unittest
from hashlib import md5
from openprocurement.storage.files.tests.base import BaseWebTest


class SimpleTest(BaseWebTest):

    def test_root(self):
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'text/plain')
        self.assertEqual(response.body, '')

    def test_register_get(self):
        response = self.app.get('/register', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'text/plain')

    def test_upload_get(self):
        response = self.app.get('/upload', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'text/plain')

    def test_upload_file_get(self):
        response = self.app.get('/upload/uuid', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'text/plain')

    def test_register_invalid(self):
        url = '/register'
        response = self.app.post(url, 'data', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'location': u'body', u'name': u'hash'}
        ])

        response = self.app.post(url, {'not_md5': 'hash'}, status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'location': u'body', u'name': u'hash'}
        ])

        response = self.app.post(url, {'hash': 'hash'}, status=422)
        self.assertEqual(response.status, '422 Unprocessable Entity')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': [u'Hash type is not supported.'], u'name': u'hash', u'location': u'body'}
        ])

        response = self.app.post(url, {'hash': 'md5:hash'}, status=422)
        self.assertEqual(response.status, '422 Unprocessable Entity')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': [u'Hash value is wrong length.'], u'name': u'hash', u'location': u'body'}
        ])

        response = self.app.post(url, {'hash': 'md5:' + 'o' * 32}, status=422)
        self.assertEqual(response.status, '422 Unprocessable Entity')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': [u'Hash value is not hexadecimal.'], u'name': u'hash', u'location': u'body'}
        ])

    def test_register_post(self):
        response = self.app.post('/register', {'hash': 'md5:' + '0' * 32, 'filename': 'file.txt'})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/upload/', response.json['upload_url'])

        # check second
        response = self.app.post('/register', {'hash': 'md5:' + '0' * 32, 'filename': 'file.txt'})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/upload/', response.json['upload_url'])

        # check forbidden hash
        md5hash = 'md5:' + md5('forbidden').hexdigest()
        response = self.app.post('/register', {'hash': md5hash, 'filename': 'file.txt'}, status=502)
        self.assertEqual(response.status, '502 Bad Gateway')

    def test_upload_invalid(self):
        url = '/upload'
        response = self.app.post(url, 'data', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'location': u'body', u'name': u'file'}
        ])

    def test_upload_post(self):
        response = self.app.post('/upload', upload_files=[('file', u'file.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

        # sencod time
        response = self.app.post('/upload', upload_files=[('file', u'file2.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

    def test_upload_forbidden(self):
        response = self.app.post('/upload', upload_files=[('file', u'file.exe', 'content')], status=502)
        self.assertEqual(response.status, '502 Bad Gateway')
        response = self.app.post('/upload', upload_files=[('file', u'file.txt', 'forbidden')], status=502)
        self.assertEqual(response.status, '502 Bad Gateway')
        exe_file = ("4D5A90000300000004000000FFFF0000B8000000000000004000000000000000"
                    "00000000000000000000000000000000000000000000000000000000E8000000"
                    "0E1FBA0E00B409CD21B8014CCD21546869732070726F6772616D2063616E6E6F"
                    "742062652072756E20696E20444F53206D6F64652E0D0D0A2400000000000000"
                    "E453C0D8A032AE8BA032AE8BA032AE8B87F4D58BA332AE8BA032AF8BFB32AE8B"
                    "1D7D388BA432AE8BBE602A8B8432AE8BBE603B8BB232AE8BBE602D8BD132AE8B"
                    "BE603F8BA132AE8B52696368A032AE8B00000000000000000000000000000000"
                    "0000000000000000504500004C01030001B18B510000000000000000E0000301")
        exe_file = binascii.unhexlify(exe_file)
        response = self.app.post('/upload', upload_files=[('file', u'file.txt', exe_file)], status=502)
        self.assertEqual(response.status, '502 Bad Gateway')
        response = self.app.post('/upload', upload_files=[('file', u'file.js', 'alert("!")')], status=502)
        self.assertEqual(response.status, '502 Bad Gateway')
        zip_file = open(self.app.relative_to + '/test.zip').read()
        response = self.app.post('/upload', upload_files=[('file', u'file.zip', zip_file)], status=502)
        self.assertEqual(response.status, '502 Bad Gateway')
        response = self.app.post('/upload', upload_files=[('file', u'file.zip', "Bad Zip File")])
        self.assertEqual(response.status, '200 OK')

    def test_upload_file_invalid(self):
        url = '/upload/uuid'
        response = self.app.post(url, 'data', status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'location': u'body', u'name': u'file'}
        ])

        response = self.app.post(url, upload_files=[('file', u'file.doc', 'content')], status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'name': u'Signature', u'location': u'url'}
        ])

        response = self.app.post(url + '?KeyID=test', upload_files=[('file', u'file.doc', 'content')], status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Key Id does not exist', u'name': u'KeyID', u'location': u'url'}
        ])

        response = self.app.post(url + '?Signature=', upload_files=[('file', u'file.doc', 'content')], status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Signature does not match', u'name': u'Signature', u'location': u'url'}
        ])

    def test_upload_file_md5(self):
        response = self.app.post('/register', {'hash': 'md5:' + '0' * 32, 'filename': 'file.txt'})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/upload/', response.json['upload_url'])

        response = self.app.post(response.json['upload_url'], upload_files=[('file', u'file.doc', 'content')], status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Invalid checksum', u'name': u'file', u'location': u'body'}
        ])

    def test_upload_file_post(self):
        content = 'content'
        md5hash = 'md5:' + md5(content).hexdigest()
        response = self.app.post('/register', {'hash': md5hash, 'filename': 'file.txt'})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/upload/', response.json['upload_url'])
        upload_url = response.json['upload_url']

        response = self.app.post(upload_url, upload_files=[('file', u'file.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

        response = self.app.post(upload_url.replace('?', 'a?'), upload_files=[('file', u'file.doc', 'content')], status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Signature does not match', u'name': u'Signature', u'location': u'url'}
        ])

    def test_get_invalid(self):
        response = self.app.get('/get/uuid', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'name': u'Signature', u'location': u'url'}
        ])

        response = self.app.get('/get/uuid?KeyID=test', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Key Id does permit to get private document', u'name': u'KeyID', u'location': u'url'}
        ])

        response = self.app.get('/get/uuid?Expires=1', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Request has expired', u'name': u'Expires', u'location': u'url'}
        ])

        response = self.app.get('/get/uuid?Expires=2000000000', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'name': u'Signature', u'location': u'url'}
        ])

        response = self.app.get('/get/uuid?Expires=2000000000&Signature=', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Signature does not match', u'name': u'Signature', u'location': u'url'}
        ])

        response = self.app.get('/get/uuid?Expires=2000000000&Signature=&KeyID=test', status=403)
        self.assertEqual(response.status, '403 Forbidden')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Key Id does not exist', u'name': u'KeyID', u'location': u'url'}
        ])

        response = self.app.post('/upload', upload_files=[('file', u'file.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

        response = self.app.get(response.json['get_url'])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn('X-Accel-Redirect', response.headers)

    def test_file_get(self):
        md5hash = 'md5:' + md5('content').hexdigest()
        response = self.app.post('/register', {'hash': md5hash, 'filename': 'file.txt'})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/upload/', response.json['upload_url'])

        response = self.app.post(response.json['upload_url'], upload_files=[('file', u'file.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

        response = self.app.get(response.json['get_url'])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn('Content-Disposition', response.headers)
        self.assertEqual(response.headers['Content-Disposition'], "inline; filename=file.txt")
        self.assertIn('X-Accel-Redirect', response.headers)

    def test_get(self):
        response = self.app.post('/upload', upload_files=[('file', u'file.txt', 'content')])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('http://localhost/get/', response.json['get_url'])

        response = self.app.get(response.json['get_url'])
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn('X-Accel-Redirect', response.headers)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(SimpleTest))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
