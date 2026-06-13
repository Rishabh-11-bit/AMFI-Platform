"""AMFI v4 — Symmetric encryption helpers for sensitive credentials stored in DB.

Usage:
    from backend.utils.crypto import encrypt_credential, decrypt_credential
    from backend.config import get_settings

    settings = get_settings()

    # Store:  h.ssh_password = encrypt_credential(plaintext, settings.secret_key)
    # Fetch:  plaintext      = decrypt_credential(h.ssh_password, settings.secret_key)

Encryption: Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from the
            app's secret_key via SHA-256.  If ENCRYPTION_KEY is set in .env,
            that value is used directly (must be a valid Fernet key or a plain
            string — if plain it is SHA-256 derived just like secret_key).

Migration:  decrypt_credential() falls back to returning the ciphertext as-is
            when decryption fails.  This means existing plaintext values in the
            DB are returned unchanged until they are re-saved through the API.
"""
import base64
import hashlib
import logging

logger = logging.getLogger("amfi.crypto")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _FERNET_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FERNET_AVAILABLE = False
    logger.warning("cryptography package not installed — credential encryption disabled")


def _make_fernet_key(key_material: str) -> bytes:
    """Derive a 32-byte URL-safe base64-encoded Fernet key from any string."""
    raw = hashlib.sha256(key_material.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _get_fernet(app_secret: str, encryption_key: str = "") -> "Fernet | None":
    """Return a Fernet instance or None when the library is unavailable."""
    if not _FERNET_AVAILABLE:
        return None
    material = encryption_key.strip() or app_secret
    key      = _make_fernet_key(material)
    return Fernet(key)


# ── Public helpers ─────────────────────────────────────────────────────────────

def encrypt_credential(value: str, app_secret: str, encryption_key: str = "") -> str:
    """Encrypt *value* for DB storage.  Returns the plaintext unchanged when
    the *cryptography* package is unavailable (graceful degradation)."""
    if not value:
        return value
    fernet = _get_fernet(app_secret, encryption_key)
    if fernet is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_credential(value: str, app_secret: str, encryption_key: str = "") -> str:
    """Decrypt a stored credential.  Falls back to returning *value* as-is when
    decryption fails (handles plaintext values from before encryption was added)."""
    if not value:
        return value
    fernet = _get_fernet(app_secret, encryption_key)
    if fernet is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except Exception:
        # Value is plaintext (pre-migration) — return as-is
        return value
