"""仅供 --net-probe 使用的连通性探测。业务代码不得调用。"""

from __future__ import annotations

import socket


def net_probe(host: str = "1.1.1.1", port: int = 443, timeout: float = 3.0) -> int:
    """能连上返回 2，连不上返回 0。"""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError:
        return 0
    else:
        return 2
    finally:
        sock.close()
