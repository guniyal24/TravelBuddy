from app.api import security

KEY = "test-secret-key-at-least-16-chars"


def test_password_roundtrip():
    h = security.hash_password("s3cret")
    assert security.verify_password("s3cret", h)
    assert not security.verify_password("wrong", h)


def test_long_password_is_truncated_consistently():
    pw = "x" * 100
    h = security.hash_password(pw)
    assert security.verify_password(pw, h)


def test_verify_handles_garbage_hash():
    assert security.verify_password("a", "not-a-hash") is False


def test_token_roundtrip():
    tok = security.create_access_token({"sub": "a@b.com"}, KEY)
    assert security.decode_token(tok, KEY)["sub"] == "a@b.com"


def test_token_rejects_wrong_key_and_expired():
    tok = security.create_access_token({"sub": "a@b.com"}, KEY)
    assert security.decode_token(tok, "another-secret-key-123456") is None
    expired = security.create_access_token({"sub": "a@b.com"}, KEY, expires_minutes=-1)
    assert security.decode_token(expired, KEY) is None
