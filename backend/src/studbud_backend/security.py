import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from .config import get_settings

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _crockford_encode(data: bytes) -> str:
    bits = "".join(f"{byte:08b}" for byte in data)
    padding = (-len(bits)) % 5
    bits += "0" * padding
    return "".join(CROCKFORD_ALPHABET[int(bits[i : i + 5], 2)] for i in range(0, len(bits), 5))


def generate_access_key() -> str:
    raw = _crockford_encode(secrets.token_bytes(32))
    groups = "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))
    return f"sb_{groups}"


def normalize_access_key(key: str) -> str:
    cleaned = "".join(ch for ch in key.strip() if not ch.isspace() and ch != "-")
    upper = cleaned.upper()
    if not upper.startswith("SB_"):
        upper = f"SB_{upper}"
    return upper


def hash_access_key(key: str) -> str:
    pepper = get_settings().key_pepper.encode("utf-8")
    normalized = normalize_access_key(key).encode("utf-8")
    return hmac.new(pepper, normalized, hashlib.sha256).hexdigest()


def key_prefix(key: str) -> str:
    return normalize_access_key(key)[:8]


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def session_expiry(key_expires_at: datetime, now: datetime | None = None) -> datetime:
    settings = get_settings()
    current = now or utcnow()
    window = current + timedelta(days=settings.session_ttl_days)
    return min(window, key_expires_at)
