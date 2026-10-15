"""PiShock legacy HTTP client wrapper.

The middleware currently targets the documented legacy `apioperate` endpoint,
while enforcing safety in higher layers (policy engine).
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .config import MIN_DURATION_MS, PISHOCK_MAX_DURATION_MS, PISHOCK_MAX_INTENSITY

API_URL = "https://do.pishock.com/api/apioperate"

# Operation mapping for PiShock legacy API: shock=0, vibrate=1, beep=2.
OPERATION_MAP = {"shock": 0, "vibrate": 1, "beep": 2}

# apioperate answers HTTP 200 even for failures ("Not Authorized.", "This code
# doesn't exist.", "Shocker is Paused ..."), so the body has to be inspected.
# Per https://apidocs.pishock.com/ the only success text is "Operation Succeeded."
_SUCCESS_MARKERS = ("Operation Succeeded",)

# apioperate is documented as whole seconds (1-15). Undocumented, it also reads
# 100-1500 as milliseconds - but old PiShock Plus hubs misread those (e.g. a
# 300 ms request runs for 3 s), so this is only ever used for vibrate/beep.
SUBSECOND_MODES = ("vibrate", "beep")
SUBSECOND_MAX_MS = 1500


def api_duration(mode: str, duration_ms: int, subsecond: bool = False) -> int:
    """The Duration value sent to apioperate for a request of `duration_ms`.

    Whole seconds, rounded down so the requested duration is never exceeded
    (minimum 1 s). With `subsecond`, vibrate/beep of 100-1500 ms are sent as
    milliseconds instead. Shock is always whole seconds.
    """

    duration_ms = max(0, min(PISHOCK_MAX_DURATION_MS, int(duration_ms)))
    if subsecond and mode in SUBSECOND_MODES and MIN_DURATION_MS <= duration_ms <= SUBSECOND_MAX_MS:
        return duration_ms
    return max(1, duration_ms // 1000)


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
    subsecond: bool = False,
) -> PiShockResult:
    """Send a single PiShock command via legacy HTTP endpoint.

    Args:
        mode: One of `shock`, `vibrate`, or `beep`.
        intensity: Intensity value expected by the endpoint.
        duration_ms: Duration in milliseconds. See `api_duration`.
        username, apikey, code, name: PiShock auth and metadata fields.
        timeout_s: Request timeout.
        subsecond: Send short vibrate/beep in milliseconds (see `api_duration`).
    """

    if mode not in OPERATION_MAP:
        raise ValueError(f"Unsupported PiShock mode: {mode}")

    # Last line of defence: device limits regardless of what the caller passed.
    intensity = max(1, min(PISHOCK_MAX_INTENSITY, int(intensity)))

    payload = {
        "Username": username,
        "Apikey": apikey,
        "Code": code,
        "Name": name,
        "Op": OPERATION_MAP[mode],
        "Intensity": intensity,
        "Duration": api_duration(mode, duration_ms, subsecond),
    }

    try:
        resp = requests.post(API_URL, json=payload, timeout=timeout_s)
    except requests.RequestException as exc:
        return PiShockResult(ok=False, status_code=0, body=f"request failed: {exc}")
    ok = resp.ok and any(marker in resp.text for marker in _SUCCESS_MARKERS)
    return PiShockResult(ok=ok, status_code=resp.status_code, body=resp.text)
