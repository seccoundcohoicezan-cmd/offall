"""AES-256-GCM for provider API keys. Stored format: base64(nonce || ciphertext+tag)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


class EncryptionError(Exception):
    pass


def _load_key(master_key_b64: str) -> bytes:
    try:
        key = base64.b64decode(master_key_b64, validate=True)
    except ValueError as exc:
        raise EncryptionError("MASTER_ENCRYPTION_KEY must be base64") from exc
    if len(key) != 32:
        raise EncryptionError("MASTER_ENCRYPTION_KEY must decode to 32 bytes")
    return key


class KeyCipher:
    def __init__(self, master_key_b64: str) -> None:
        self._aes = AESGCM(_load_key(master_key_b64))

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(NONCE_SIZE)
        sealed = self._aes.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + sealed).decode()

    def decrypt(self, token: str) -> str:
        try:
            raw = base64.b64decode(token)
            return self._aes.decrypt(raw[:NONCE_SIZE], raw[NONCE_SIZE:], None).decode()
        except Exception as exc:  # InvalidTag, binascii errors, ...
            raise EncryptionError("cannot decrypt key") from exc


def mask_key(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    prefix = secret[:3] if secret[:3].isalpha() or secret.startswith("sk-") else ""
    return f"{prefix}...{secret[-4:]}"


def generate_master_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()
