"""Encryption for user API keys (Fernet = AES-128-CBC + HMAC). Plain keys exist only in memory while a
job runs or a key is tested; they are never returned to the browser, logged or stored in job logs."""
import re

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class KeyVaultError(RuntimeError):
    pass


def _fernet():
    secret = get_settings().key_encryption_secret
    if not secret:
        raise KeyVaultError("KEY_ENCRYPTION_SECRET is not set on the server, so API keys cannot be stored.")
    try:
        return Fernet(secret.encode())
    except Exception as e:
        raise KeyVaultError("KEY_ENCRYPTION_SECRET is not a valid Fernet key") from e


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise KeyVaultError("stored key cannot be decrypted (was KEY_ENCRYPTION_SECRET changed?)") from e


def last4(plain: str) -> str:
    return plain[-4:] if len(plain) >= 8 else "****"


_KEYLIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk_[0-9A-Za-z_\-]{16,}|[0-9a-f]{32,})")


def redact(text: str, *secrets: str) -> str:
    """Remove known secrets and anything that looks like an API key from text that may be logged or shown."""
    text = str(text)
    for s in secrets:
        if s:
            text = text.replace(s, "[key]")
    return _KEYLIKE.sub("[key]", text)
