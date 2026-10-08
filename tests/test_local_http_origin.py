"""Local-authority admission on real sockets, with isolated persistence only."""
import json
import sys
import tempfile
import threading
import unittest
from email.message import Message
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from workbench.http_origin import local_request_error
from workbench.http_reliability import WorkbenchHTTPServer
from workbench.platform_server import make_handler as compatibility_handler
from workbench.workbench_server import WorkbenchApp, make_handler


class LocalHTTPOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = WorkbenchApp(self.temp.name)
        self.server = WorkbenchHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.app.initiative_workflow.learning_generation.close()
        self.app.delivery_runtime.close()
        self.app.deployments.close()
        self.app.previews.close()

    def request(self, method, path, *, host=None, origin=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if host is not None:
            headers['Host'] = host
        if origin is not None:
            headers['Origin'] = origin
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def configuration(self):
        return {'actor': 'fixture', 'submission_key': 'fixture-config',
                'expected_configuration_revision': 0,
                'preview_config': {'command': [sys.executable, '-c', 'pass'],
                                   'health': {'path': '/api/health', 'expected': {'status': 'ok'}}},
                'deployment_profiles': []}

    def test_foreign_matching_host_and_origin_cannot_read_or_save_configuration(self):
        host = f'audit-untrusted.invalid:{self.server.server_port}'
        for path in ('/', '/api/health', '/api/v1/projects'):
            with self.subTest(path=path):
                status, data = self.request('GET', path, host=host)
                self.assertEqual((403, 'invalid_host'), (status, data['error']))
        status, data = self.request('POST', f'/api/v1/projects/{self.app.default_project}/settings',
                                    host=host, origin='http://' + host, body=self.configuration())
        self.assertEqual((403, 'invalid_host'), (status, data['error']))
        self.assertFalse(data['result_unknown'])
        self.assertEqual(0, self.app.configurations.get(self.app.default_project)['configuration_revision'])

    def test_same_origin_and_local_cli_can_still_save_configuration(self):
        host = f'localhost:{self.server.server_port}'
        self.assertEqual(200, self.request('GET', '/api/health', host=host)[0])
        body = self.configuration()
        status, _ = self.request('POST', f'/api/v1/projects/{self.app.default_project}/settings',
                                  host=host, origin='http://' + host, body=body)
        self.assertEqual(200, status)
        body.update(submission_key='fixture-cli-config', expected_configuration_revision=1)
        status, _ = self.request('POST', f'/api/v1/projects/{self.app.default_project}/settings', body=body)
        self.assertEqual(200, status)
        self.assertEqual(2, self.app.configurations.get(self.app.default_project)['configuration_revision'])

    def test_cross_origin_is_rejected_on_previously_unguarded_initiative_route(self):
        for origin in ('http://foreign.invalid', 'null', f'https://127.0.0.1:{self.server.server_port}'):
            with self.subTest(origin=origin):
                status, data = self.request('POST', '/api/v1/initiatives', origin=origin,
                                            body={'actor': 'fixture', 'data': {'title': 'must not persist'}})
                self.assertEqual((403, 'cross_origin'), (status, data['error']))
        self.assertEqual([], self.app.initiatives.list())

    def test_ambiguous_or_wrong_authorities_are_rejected(self):
        port = self.server.server_port
        for host in (f'localhost:{port + 1}', f'127.0.0.1:{port}/x',
                     f'fixture@127.0.0.1:{port}', f'localhost.:{port}', f'127.0.0.1.evil:{port}',
                     f'localhost:{port}?', f'localhost:{port}#'):
            with self.subTest(host=host):
                status, data = self.request('GET', '/api/health', host=host)
                self.assertEqual((403, 'invalid_host'), (status, data['error']))
        # Duplicate headers must not let a proxy and this server disagree.
        connection = HTTPConnection('127.0.0.1', port, timeout=3)
        connection.putrequest('GET', '/api/health', skip_host=True)
        connection.putheader('Host', f'127.0.0.1:{port}')
        connection.putheader('Host', f'foreign.invalid:{port}')
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(403, response.status)
        self.assertEqual('invalid_host', json.loads(response.read())['error'])
        connection.close()

    def test_loopback_authority_formats_and_duplicate_origins(self):
        for authority in ('127.0.0.1:8001', 'LOCALHOST:8001', '[::1]:8001'):
            headers = Message()
            headers['Host'] = authority
            headers['Origin'] = 'http://' + authority.lower()
            self.assertIsNone(local_request_error(headers, 8001, write=True))
        headers = Message()
        self.assertEqual('invalid_host', local_request_error(headers, 8001)['error'])
        headers['Host'] = 'localhost:8001'
        headers['Origin'] = 'http://localhost:8001'
        headers['Origin'] = 'http://localhost:8001'
        self.assertEqual('cross_origin', local_request_error(headers, 8001, write=True)['error'])

    def test_compatibility_view_cannot_forward_foreign_authority(self):
        calls = []
        class API:
            def dispatch(self, *args):
                calls.append(args)
                return SimpleNamespace(status=200, body={'ok': True})
        server = ThreadingHTTPServer(('127.0.0.1', 0), compatibility_handler(API()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for method in ('GET', 'POST'):
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                host = f'foreign.invalid:{server.server_port}'
                connection.request(method, '/api/v1/sessions', '{}' if method == 'POST' else None,
                                   {'Host': host, 'Origin': 'http://' + host, 'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual(403, response.status)
                self.assertEqual('invalid_host', json.loads(response.read())['error'])
                connection.close()
            self.assertEqual([], calls)
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            connection.request('GET', '/api/v1/sessions')
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            connection.close()
            self.assertEqual(1, len(calls))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
