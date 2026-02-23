"""HMAC signature verification tests."""

import hashlib
import hmac

from middleware.security import verify_signature


def test_verify_signature_ok():
    """A valid HMAC must be accepted."""

    body = b'{"event_type":"x"}'
    secret = "abc"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, secret)


def test_verify_signature_bad():
    """A non-matching signature must be rejected."""

    assert not verify_signature(b"x", "bad", "abc")
