"""Refuse non-loopback sockets. Loopback stays open for an optional local model."""

import socket

_INSTALLED = False
_ORIGINAL = None
remote_attempts = []


def install():
    """Patch socket.connect. A second call does nothing."""
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    _ORIGINAL = socket.socket.connect

    def connect(self, address):
        host = ""
        if isinstance(address, tuple) and address:
            host = str(address[0])
        if host not in {"127.0.0.1", "::1", "localhost", ""}:
            remote_attempts.append(address)
            raise OSError("离线模式拒绝联网：" + str(address))
        return _ORIGINAL(self, address)

    socket.socket.connect = connect
    _INSTALLED = True


def uninstall():
    """Restore connect. Tests call this so later cases can use the network."""
    global _INSTALLED, _ORIGINAL
    if _ORIGINAL is not None:
        socket.socket.connect = _ORIGINAL
    _ORIGINAL = None
    _INSTALLED = False
    remote_attempts.clear()
