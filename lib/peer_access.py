# -*- coding: utf-8 -*-
"""First line of every PEER button:

    import peer_access; peer_access.require_key()

Does nothing until the office turns the lock on (peer_library/access.py)."""


def require_key():
    try:
        from peer_library import access
    except Exception:
        return True
    return access.require_key()
