# -*- coding: utf-8 -*-
"""Personal library key, encrypted with Windows DPAPI (current user scope).

File: %APPDATA%/PEER/library_key.bin. Only this Windows user on this computer
can decrypt it. The key never goes to logs or error messages.
In Revit: System.Security.Cryptography.ProtectedData; under CPython (tests): ctypes.
"""

import os

from peer_library import config

ENTROPY = b'PEER-Library-v1'


def key_file():
    return os.path.join(config.appdata_dir(), 'library_key.bin')


# ---- DPAPI ---------------------------------------------------------------------
def _protect_dotnet(data, decrypt):
    import clr
    clr.AddReference('System.Security')
    from System import Array, Byte
    from System.Security.Cryptography import DataProtectionScope, ProtectedData
    src = Array[Byte](bytearray(data))
    ent = Array[Byte](bytearray(ENTROPY))
    fn = ProtectedData.Unprotect if decrypt else ProtectedData.Protect
    out = fn(src, ent, DataProtectionScope.CurrentUser)
    return bytes(bytearray(out))


def _protect_ctypes(data, decrypt):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    src, _keep1 = blob(data)
    ent, _keep2 = blob(ENTROPY)
    out = BLOB()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if decrypt:
        ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), u'PEER Library', ctypes.byref(ent), None, None, 0,
                ctypes.byref(out))
    if not ok:
        raise OSError('DPAPI failed')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _dpapi(data, decrypt=False):
    try:
        import clr  # noqa: F401  IronPython
    except ImportError:
        return _protect_ctypes(data, decrypt)
    return _protect_dotnet(data, decrypt)


# ---- key ------------------------------------------------------------------------
def save(key):
    path = key_file()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    blob = _dpapi(key.strip().encode('utf-8'))
    with open(path, 'wb') as f:
        f.write(blob)


def load():
    """The key or None (no file / another user / damaged)."""
    try:
        with open(key_file(), 'rb') as f:
            blob = f.read()
        return _dpapi(blob, decrypt=True).decode('utf-8')
    except Exception:
        return None


def forget():
    try:
        os.remove(key_file())
    except OSError:
        pass


def mask(key):
    return (key[:9] + u'…') if key else u''
