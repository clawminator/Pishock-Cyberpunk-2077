"""PiShock legacy HTTP client wrapper.

The middleware currently targets the documented legacy `apioperate` endpoint,
while enforcing safety in higher layers (policy engine).
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .config import PISHOCK_MAX_DURATION_MS, PISHOCK_MAX_INTENSITY

API_URL = "https://do.pishock.com/api/apioperate"

# Operation mapping for PiShock legacy API: shock=0, vibrate=1, beep=2.
OPERATION_MAP = {"shock": 0, "vibrate": 1, "beep": 2}

# apioperate answers HTTP 200 even for failures ("Not Authorized.", "This code
# doesn't exist.", "Shocker is Paused ..."), so the body has to be inspected.
# Per https://apidocs.pishock.com/ the only success text is "Operation Succeeded."
_SUCCESS_MARKERS = ("Operation Succeeded",)


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

    # Last line of defence: device limits regardless of what the caller passed.
    intensity = max(1, min(PISHOCK_MAX_INTENSITY, int(intensity)))
    duration_ms = max(0, min(PISHOCK_MAX_DURATION_MS, int(duration_ms)))

    payload = {
        "Username": username,
        "Apikey": apikey,
        "Code": code,
        "Name": name,
        "Op": OPERATION_MAP[mode],
        "Intensity": intensity,
        # Legacy endpoint expects whole seconds. Round down so the configured
        # max_duration_ms is never exceeded (round() sent 2 s for 1500 ms);
        # the device minimum is 1 second.
        "Duration": max(1, duration_ms // 1000),
    }

    try:
        resp = requests.post(API_URL, json=payload, timeout=timeout_s)
    except requests.RequestException as exc:
        return PiShockResult(ok=False, status_code=0, body=f"request failed: {exc}")
    ok = resp.ok and any(marker in resp.text for marker in _SUCCESS_MARKERS)
    return PiShockResult(ok=ok, status_code=resp.status_code, body=resp.text)
