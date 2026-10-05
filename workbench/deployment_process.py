"""Process ownership for local services that outlive their startup probe."""
import json
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler

from .managed_process import ManagedProcess


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url, health, timeout=2):
    """A local probe cannot follow a service's redirect to another authority."""
    try:
        target = urlparse(url)
        if target.scheme != 'http' or target.hostname not in {'localhost', '127.0.0.1', '::1'} or target.username or target.password or target.path not in {'', '/'} or target.query or target.fragment:
            raise ValueError('健康检查仅支持登记的本机HTTP根地址')
        path = health['path']
        if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
            raise ValueError('健康检查路径不可改变登记地址')
        with build_opener(ProxyHandler({}), _NoRedirect()).open(url.rstrip('/') + path, timeout=timeout) as response:
            actual = json.load(response)
        if not isinstance(actual, dict):
            raise ValueError('健康检查须返回JSON对象')
        return {'passed': all(actual.get(k) == v for k, v in health['expected'].items()), 'actual': actual}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {'passed': False, 'error': str(exc)}


class OwnedCommand(ManagedProcess):
    def __init__(self, command, cwd):
        from .codex_options import headless_environment
        super().__init__(command, cwd, env=headless_environment(), capture_limit=100_000)
        self.start()
