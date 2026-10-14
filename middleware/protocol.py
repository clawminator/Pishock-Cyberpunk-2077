"""Outbox line format shared by the CET emitter, the consumer, and the simulator.

Current format (v1) is JSONL - one JSON object per line:

    {"v":1,"sig":"<64 hex>","event":<event json>}

`sig` is HMAC-SHA256 over the exact bytes of ``<event json>`` as written. The
envelope is always written in exactly this key order, so the raw event bytes
can be recovered with a regex and verified without re-serialising.

The earlier ``<hex_hmac>\\t<json_body>`` format is still accepted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

FORMAT_VERSION = 1

_JSONL_RE = re.compile(r'^\{"v":(\d+),"sig":"([0-9a-fA-F]{64})","event":(\{.*\})\}\s*$')
_LEGACY_RE = re.compile(r"^([0-9a-fA-F]{64})\t(\{.*\})\s*$")


@dataclass(frozen=True)
class ParsedLine:
    """A syntactically valid outbox line whose signature is not yet verified."""

    body: str
    signature: str
    format: str  # "jsonl" or "legacy"
    version: int


def sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8", "surrogateescape"), hashlib.sha256).hexdigest()


def encode_event(event: dict[str, Any]) -> str:
    """Compact, key-sorted JSON - the same shape the Lua encoder produces."""

    return json.dumps(event, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def build_line(event: dict[str, Any], secret: str) -> str:
    """Build one signed v1 outbox line (including the trailing newline)."""

    body = encode_event(event)
    return f'{{"v":{FORMAT_VERSION},"sig":"{sign(body, secret)}","event":{body}}}\n'


def parse_line(line: str) -> ParsedLine | None:
    """Split a raw line into body + signature, or return None if malformed."""

    line = line.rstrip("\r\n")
    match = _JSONL_RE.match(line)
    if match:
        return ParsedLine(body=match.group(3), signature=match.group(2).lower(), format="jsonl", version=int(match.group(1)))
    match = _LEGACY_RE.match(line)
    if match:
        return ParsedLine(body=match.group(2), signature=match.group(1).lower(), format="legacy", version=0)
    return None
