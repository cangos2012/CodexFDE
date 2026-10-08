"""Validate the local HTTP authority before serving data or accepting input."""
from urllib.parse import urlsplit


def _authority(value, port):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit('http://' + value)
        if (parsed.netloc != value or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or
                parsed.username is not None or parsed.password is not None or
                parsed.path or parsed.query or parsed.fragment or
                (parsed.port if parsed.port is not None else 80) != port):
            return None
        return parsed.hostname, port
    except ValueError:
        return None


def local_request_error(headers, port, *, write=False):
    """Require one loopback Host and, when supplied, the same HTTP Origin.

    Origin may be absent for local CLI clients. Host is always checked, so an
    attacker-controlled hostname cannot become trusted by repeating it in Origin.
    """
    hosts = headers.get_all('Host', [])
    authority = _authority(hosts[0], port) if len(hosts) == 1 else None
    if authority is None:
        return {'error': 'invalid_host', 'message': '请使用当前端口的本机工作台地址。',
                'automatic_replay': False, 'result_unknown': False}
    if write:
        origins = headers.get_all('Origin', [])
        if len(origins) > 1:
            origin_authority = None
        elif origins:
            origin = origins[0]
            origin_authority = _authority(origin[7:], port) if origin.startswith('http://') else None
        else:
            return None
        if origin_authority != authority:
            return {'error': 'cross_origin', 'message': '请从当前本机工作台页面操作。',
                    'automatic_replay': False, 'result_unknown': False}
    return None
