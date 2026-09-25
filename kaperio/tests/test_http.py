import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

from app import Handler, Library


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.library=Library(self.tmp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.library=self.library
        self.server.token='test-capability'
        self.server.tls=False
        self.server.authority=f'127.0.0.1:{self.server.server_port}'
        self.server.origin='http://'+self.server.authority
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.library.close();self.tmp.cleanup()

    def request(self,method,path,body=None,headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        client.request(method,path,body=body,headers=headers or {})
        response=client.getresponse();data=response.read();status=response.status;client.close()
        return status,data

    def test_authentication_origin_and_paths(self):
        self.assertEqual(self.request('GET','/api/jobs')[0],403)
        self.assertEqual(self.request('GET','/launch?token=wrong')[0],403)
        self.assertEqual(self.request('GET','/launch?token=test-capability')[0],303)
        headers={'Cookie':'kaperio_session=test-capability'}
        self.assertEqual(self.request('GET','/api/jobs',headers=headers)[0],200)
        status, license_text = self.request('GET','/api/licenses',headers=headers)
        self.assertEqual(status,200)
        self.assertIn(b'Copyright (c) 2026 Lucide',license_text)
        self.assertIn(b'MIT License',license_text)
        self.assertEqual(self.request('GET','/../app.py',headers=headers)[0],404)
        self.assertEqual(self.request('POST','/api/settings','{}',headers)[0],403)
        headers.update({'X-Kaperio':'1','Origin':'https://other.example'})
        self.assertEqual(self.request('POST','/api/settings','{}',headers)[0],403)
        headers.pop('Origin');headers['Host']='other.example'
        self.assertEqual(self.request('GET','/api/jobs',headers=headers)[0],403)

    def test_invalid_import(self):
        headers={'Cookie':'kaperio_session=test-capability','X-Kaperio':'1','X-Filename':'test.pdf'}
        self.assertEqual(self.request('POST','/api/import',b'not a pdf',headers)[0],400)
        self.assertEqual(self.library.snapshot(),[])

    def test_guided_estimate_requires_auth_and_does_not_store_hints(self):
        data = json.dumps({'strategy': 'guided', 'words': 'PrivateHint', 'numbers': '2024'})
        self.assertEqual(self.request('POST', '/api/recovery/estimate', data)[0], 403)
        headers = {'Cookie': 'kaperio_session=test-capability', 'X-Kaperio': '1'}
        status, body = self.request('POST', '/api/recovery/estimate', data, headers)
        self.assertEqual(status, 200)
        self.assertNotIn(b'PrivateHint', body)
        self.assertGreater(int(json.loads(body)['candidates']), 1)
        self.assertFalse(list(Path(self.tmp.name).glob('**/candidates.hex')))

    def test_external_settings_without_hashcat(self):
        headers={'Cookie':'kaperio_session=test-capability','X-Kaperio':'1'}
        self.assertEqual(self.request('POST','/api/settings',json.dumps({'hashcat':'','zip2john':''}),headers)[0],200)
        self.assertIsNone(self.library.hashcat)
        self.assertIsNone(self.library.zip2john)
        self.assertEqual(self.request('POST','/api/settings',json.dumps({'zip2john':'not-existing.exe'}),headers)[0],400)
