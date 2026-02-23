"""Security helpers shared by app and tests."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(body: bytes, signature: str | None, shared_secret: str) -> bool:
    """Validate HMAC-SHA256 signature against raw request body."""

    if not signature:
        return False
    expected = hmac.new(shared_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
