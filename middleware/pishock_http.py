"""PiShock legacy HTTP client wrapper.

The middleware currently targets the documented legacy `apioperate` endpoint,
while enforcing safety in higher layers (policy engine).
"""

from __future__ import annotations

from dataclasses import dataclass

import requests


# Operation mapping for PiShock legacy API: shock=0, vibrate=1, beep=2.
OPERATION_MAP = {"shock": 0, "vibrate": 1, "beep": 2}


@dataclass
class PiShockResult:
    """Normalized HTTP result for logging and error handling."""

    ok: bool
    status_code: int
    body: str


def send_pishock_http(
    *,
    mode: str,
    intensity: int,
    duration_ms: int,
    username: str,
    apikey: str,
    code: str,
    name: str,
    timeout_s: float = 5.0,
) -> PiShockResult:
    """Send a single PiShock command via legacy HTTP endpoint.

    Args:
        mode: One of `shock`, `vibrate`, or `beep`.
        intensity: Intensity value expected by the endpoint.
        duration_ms: Duration in milliseconds. Converted to whole seconds.
        username, apikey, code, name: PiShock auth and metadata fields.
        timeout_s: Request timeout.
    """

    if mode not in OPERATION_MAP:
        raise ValueError(f"Unsupported PiShock mode: {mode}")

    payload = {
        "Username": username,
        "Apikey": apikey,
        "Code": code,
        "Name": name,
        "Op": OPERATION_MAP[mode],
        "Intensity": intensity,
        # Legacy endpoint expects seconds; clamp minimum to 1 second.
        "Duration": max(1, int(round(duration_ms / 1000))),
    }

    resp = requests.post(
        "https://do.pishock.com/api/apioperate",
        json=payload,
        timeout=timeout_s,
    )
    return PiShockResult(ok=resp.ok, status_code=resp.status_code, body=resp.text)
