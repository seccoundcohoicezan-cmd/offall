import base64

import pytest

from app.core.encryption import EncryptionError, KeyCipher, generate_master_key, mask_key
from app.core.logging import redact


def test_roundtrip_and_random_nonce():
    cipher = KeyCipher(generate_master_key())
    a = cipher.encrypt("sk-ant-secret-value-1234")
    b = cipher.encrypt("sk-ant-secret-value-1234")
    assert a != b
    assert "secret" not in a
    assert cipher.decrypt(a) == "sk-ant-secret-value-1234"


def test_tampered_ciphertext_rejected():
    cipher = KeyCipher(generate_master_key())
    token = bytearray(base64.b64decode(cipher.encrypt("sk-abcdefgh")))
    token[-1] ^= 1
    with pytest.raises(EncryptionError):
        cipher.decrypt(base64.b64encode(bytes(token)).decode())


def test_wrong_master_key_cannot_decrypt():
    token = KeyCipher(generate_master_key()).encrypt("sk-abcdefgh")
    with pytest.raises(EncryptionError):
        KeyCipher(generate_master_key()).decrypt(token)


@pytest.mark.parametrize("bad", ["", "not-base64!!", base64.b64encode(b"short").decode()])
def test_invalid_master_key(bad):
    with pytest.raises(EncryptionError):
        KeyCipher(bad)


def test_mask_shows_only_last_four():
    assert mask_key("sk-ant-api03-abcdefWXYZ") == "sk-...WXYZ"
    assert mask_key("gsk_1234567890abcd").endswith("abcd")
    assert "1234567890" not in mask_key("gsk_1234567890abcd")
    assert mask_key("abc") == "****"


def test_log_redaction():
    line = 'calling with api_key="sk-ant-api03-SECRETSECRET" Authorization: Bearer eyJabc.def'
    out = redact(line)
    assert "SECRETSECRET" not in out
    assert "eyJabc" not in out
    assert redact("AIzaSyA1234567890abcdefghijklmnop") == "[REDACTED]"
