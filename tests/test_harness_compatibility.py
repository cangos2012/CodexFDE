from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler

from workbench.harness_compatibility import HarnessCompatibilityProxy, LegacyHarnessHistory


class HarnessCompatibilityTests(unittest.TestCase):
    def test_http_health_advertises_the_actual_upstream_without_changing_its_identity(self):
        from workbench.platform_server import make_handler
        observed=[]
        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(self.path)
                unavailable='unavailable=1' in self.path
                body=json.dumps({'instance_id':'actual-workbench','status':'ready' if not unavailable else 'blocked'}).encode()
                self.send_response(503 if unavailable else 200)
                self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        upstream_thread=threading.Thread(target=upstream.serve_forever,daemon=True);upstream_thread.start()
        with tempfile.TemporaryDirectory() as temporary:
            upstream_url=f'http://127.0.0.1:{upstream.server_port}'
            proxy=HarnessCompatibilityProxy(Path(temporary)/'absent',upstream_url=upstream_url)
            compatibility=ThreadingHTTPServer(('127.0.0.1',0),make_handler(proxy))
            compatibility_thread=threading.Thread(target=compatibility.serve_forever,daemon=True);compatibility_thread.start()
            opener=build_opener(ProxyHandler({}))
            try:
                url=f'http://127.0.0.1:{compatibility.server_port}/api/v1/health'
                with opener.open(url,timeout=5) as response:
                    result=json.load(response)
                self.assertEqual(upstream_url,result['workbench_url'])
                self.assertTrue(result['compatibility_view'])
                self.assertEqual('actual-workbench',result['instance_id'])
                self.assertEqual('ready',result['status'])
                self.assertEqual('/api/v1/harness/health',observed[0])
                with self.assertRaises(HTTPError) as caught:
                    opener.open(url+'?unavailable=1',timeout=5)
                with caught.exception as response:
                    self.assertEqual(503,response.code)
                    failure=json.load(response)
                self.assertEqual('blocked',failure['status'])
                self.assertNotIn('compatibility_view',failure)
                self.assertFalse((Path(temporary)/'absent').exists())
            finally:
                compatibility.shutdown();compatibility.server_close();compatibility_thread.join(5)
                upstream.shutdown();upstream.server_close();upstream_thread.join(5)

    def test_bootstrap_compatibility_flag_delegates_without_accessing_legacy_stores(self):
        from workbench.platform_server import serve
        server=Mock(); server.serve_forever.side_effect=KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as temporary, patch('workbench.platform_server.create_http_server',return_value=server), patch('workbench.platform_server.bootstrap_default_project') as bootstrap:
            serve(runtime_dir=str(Path(temporary)/'old'),bootstrap=True,upstream_url='http://127.0.0.1:8101')
            bootstrap.assert_not_called()
            self.assertFalse((Path(temporary)/'old').exists())
            server.server_close.assert_called_once()

    def test_empty_history_never_creates_an_old_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'absent'
            result=LegacyHarnessHistory(root).view()
            self.assertEqual([],result['tasks'])
            self.assertFalse(root.exists())

    def test_legacy_reads_preserve_database_bytes_and_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);database=root/'tasks.db'
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE tasks(id TEXT,status TEXT)')
                db.execute("INSERT INTO tasks VALUES ('TASK-OLD','review')")
                db.commit()
            before=hashlib.sha256(database.read_bytes()).hexdigest()
            history=LegacyHarnessHistory(root).view()
            self.assertEqual('TASK-OLD',history['tasks'][0]['id'])
            self.assertTrue(history['read_only'])
            self.assertFalse(history['automatic_replay'])
            self.assertEqual(before,hashlib.sha256(database.read_bytes()).hexdigest())

    def test_proxy_maps_to_shared_api_without_owning_stores(self):
        captured=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.path,self.headers.get('Origin'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body=b'{"same_run":true}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                upstream='http://127.0.0.1:'+str(server.server_port)
                proxy=HarnessCompatibilityProxy(Path(temporary)/'missing',upstream_url=upstream)
                result=proxy.dispatch('POST','/api/v1/sessions/SESSION-A/tools/shell.exec',{'x-workbench-actor':'owner','idempotency-key':'same'}, {'call_id':'one'})
                self.assertEqual(200,result.status)
                self.assertEqual('/api/v1/harness/sessions/SESSION-A/tools/shell.exec',captured[0][0])
                self.assertEqual(upstream,captured[0][1])
                self.assertEqual('owner',captured[0][2]['actor'])
                self.assertEqual('same',captured[0][2]['submission_key'])
                self.assertFalse((Path(temporary)/'missing').exists())
        finally:
            server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':unittest.main()
