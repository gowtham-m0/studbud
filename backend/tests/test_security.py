from datetime import UTC, datetime, timedelta

from studbud_backend.security import (
    generate_access_key,
    hash_access_key,
    hash_session_token,
    key_prefix,
    normalize_access_key,
    session_expiry,
)


def test_key_format_and_normalization() -> None:
    key = generate_access_key()
    assert key.startswith("sb_")
    assert len(key) > 50

    assert normalize_access_key(key) == normalize_access_key(key.lower())
    assert normalize_access_key("sb_abcd-efgh") == "SB_ABCDEFGH"
    assert key_prefix(key) == normalize_access_key(key)[:8]


def test_key_hash_is_stable_and_peppered() -> None:
    key = generate_access_key()
    first = hash_access_key(key)
    second = hash_access_key(normalize_access_key(key).lower())
    assert first == second
    assert len(first) == 64
    assert first != hash_access_key(key[:-1] + "X")


def test_session_token_hash_is_not_plaintext() -> None:
    token = "secret-token"
    assert hash_session_token(token) != token
    assert hash_session_token(token) == hash_session_token(token)


def test_session_expiry_is_clamped_to_key_expiry() -> None:
    now = datetime.now(UTC)
    short_key = now + timedelta(hours=2)
    long_key = now + timedelta(days=30)

    assert session_expiry(short_key, now) == short_key
    expected_window = now + timedelta(days=7)
    assert session_expiry(long_key, now) == expected_window
