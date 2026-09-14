"""Request signing per the Roostoo API docs.

totalParams = parameters sorted by key, each as ``key=value`` (values NOT URL-encoded),
joined with ``&``. Signature = hex HMAC-SHA256(secret, totalParams).
"""
import hashlib
import hmac


def canonical_query(params: dict) -> str:
    """Build totalParams. ``None`` values are dropped (e.g. price on MARKET orders)."""
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)


def sign(secret: str, total_params: str) -> str:
    return hmac.new(secret.encode(), total_params.encode(), hashlib.sha256).hexdigest()
