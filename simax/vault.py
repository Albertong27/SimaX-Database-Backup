"""Authenticated catalog encryption with a persistent, host-local key."""

import ctypes
import json
import os
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken


class VaultError(ValueError):
    pass


def protect_windows(data, decrypt=False):
    """DPAPI current-user scope; never enable machine-wide access or UI prompts."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming, outgoing = Blob(len(data), buffer), Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise VaultError("The local encryption key cannot be protected or unlocked by this OS account.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(outgoing.data)


class Vault:
    def __init__(self, directory: Path, existing=False):
        self.path = directory / "credentials.key"
        if not self.path.exists():
            if existing:
                raise VaultError("Encryption key is missing. Restore credentials.key; do not generate a replacement.")
            key = Fernet.generate_key()
            content = b"DPAPI1\n" + protect_windows(key) if os.name == "nt" else b"FERNET1\n" + key
            temporary = directory / (".key-" + uuid4().hex)
            try:
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Publish an already complete file without replacing a concurrent winner.
                try:
                    os.link(temporary, self.path)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        try:
            content = self.path.read_bytes()
            if content.startswith(b"DPAPI1\n") and os.name == "nt":
                key = protect_windows(content[7:], decrypt=True)
            elif content.startswith(b"FERNET1\n") and os.name != "nt":
                if self.path.stat().st_mode & 0o077:
                    raise VaultError("Encryption key permissions must be restricted to its owner (0600).")
                key = content[8:]
            else:
                raise VaultError("Encryption key format or OS account is incompatible.")
            self.cipher = Fernet(key)
        except (OSError, ValueError):
            raise VaultError("Cannot unlock credentials.key. Restore the original key and OS account; no replacement was generated.") from None

    def encode(self, body):
        return "simax:v1:" + self.cipher.encrypt(json.dumps(body, ensure_ascii=False).encode()).decode("ascii")

    def decode(self, body):
        try:
            if not body.startswith("simax:v1:"):
                raise ValueError()
            return json.loads(self.cipher.decrypt(body[9:].encode("ascii")))
        except (InvalidToken, ValueError, UnicodeError):
            raise VaultError("Catalog authentication failed. Restore the matching catalog and encryption key.") from None


SECRET_FIELDS = {"password", "event_secret", "mqtt_password"}


def public(value):
    """Keep secrets out of every API response, including nested job snapshots."""
    if isinstance(value, list):
        return [public(item) for item in value]
    if isinstance(value, dict):
        result = {key: public(item) for key, item in value.items() if key not in SECRET_FIELDS}
        for key in SECRET_FIELDS & value.keys():
            result[key + "_saved"] = value[key] is not None and value[key] != ""
        return result
    return value


def import_legacy(value, secrets):
    if isinstance(value, list):
        return [import_legacy(item, secrets) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: import_legacy(item, secrets) for key, item in value.items()}
    for old, new in (("password_env", "password"), ("event_secret_env", "event_secret"),
                     ("mqtt_password_env", "mqtt_password")):
        reference = result.pop(old, None)
        needed = (new == "password" or new == "event_secret" and result.get("trigger") in {"webhook", "mqtt"}
                  or new == "mqtt_password" and bool(result.get("mqtt_username")))
        if reference and needed:
            if reference not in secrets or secrets[reference] is None:
                raise VaultError("Legacy credentials need importing. Stop SimaX and run with --migrate-env-file PATH once.")
            result[new] = secrets[reference]
    return result
