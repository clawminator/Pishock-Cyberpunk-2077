"""Consumer-side safety mechanisms: emergency stop and global rate limiting.

The emergency stop is a file on disk so it can be engaged from anywhere: the
in-game hotkey (via an ``emergency_stop`` event), the ``middleware-estop`` CLI,
or by simply creating the file. While it exists no output is produced. It is
only ever cleared explicitly (``middleware-estop --clear``), never by the game.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path


class EmergencyStop:
    """File-backed emergency stop latch."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # Set if the file could not be written, so the latch still holds.
        self._memory_latch = False

    def is_engaged(self) -> bool:
        return self._memory_latch or self.path.exists()

    def reason(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return "engaged" if self._memory_latch else ""

    def engage(self, reason: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self.path.write_text(f"{stamp} {reason}\n", encoding="utf-8")
        except OSError:
            self._memory_latch = True

    def clear(self) -> bool:
        """Clear the stop. Returns True if it was engaged."""

        was = self.is_engaged()
        self._memory_latch = False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return was


class RateLimiter:
    """Global limit across all events: max N per minute and a minimum gap."""

    def __init__(self, max_per_minute: int, min_gap_ms: int) -> None:
        self.max_per_minute = max_per_minute
        self.min_gap_ms = min_gap_ms
        self._sent: deque[float] = deque()

    def check(self, now_s: float) -> str | None:
        """Return a reason string if an output now would exceed the limits."""

        while self._sent and now_s - self._sent[0] >= 60.0:
            self._sent.popleft()
        if self._sent and (now_s - self._sent[-1]) * 1000 < self.min_gap_ms:
            return "global_cooldown"
        if len(self._sent) >= self.max_per_minute:
            return "rate_limit"
        return None

    def record(self, now_s: float) -> None:
        self._sent.append(now_s)


def main(argv: list[str] | None = None) -> int:
    """`middleware-estop`: engage, clear, or show the emergency stop."""

    parser = argparse.ArgumentParser(description="Engage or clear the PiShock consumer emergency stop")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--clear", action="store_true", help="clear the emergency stop")
    group.add_argument("--status", action="store_true", help="show whether the stop is engaged")
    parser.add_argument("--config", help="config YAML to take safety.estop_file from (default: same as the consumer)")
    parser.add_argument("--estop-file", help="override the e-stop file path (default: from config)")
    args = parser.parse_args(argv)

    path = args.estop_file
    if path is None:
        # pylint: disable-next=import-outside-toplevel
        from .config import SafetyConfig, default_config_path, load_config

        cfg_path = args.config or default_config_path()
        try:
            path = load_config(cfg_path).safety.estop_file
        except (OSError, ValueError, RuntimeError) as exc:
            path = SafetyConfig.estop_file
            print(f"warning: could not read {cfg_path} ({exc}); using the default e-stop file", file=sys.stderr)

    estop = EmergencyStop(path)
    if args.status:
        if estop.is_engaged():
            print(f"ENGAGED ({estop.path}): {estop.reason()}")
            return 1
        print(f"clear ({estop.path})")
        return 0
    if args.clear:
        was = estop.clear()
        print("emergency stop cleared" if was else "emergency stop was not engaged")
        return 0
    estop.engage("engaged via middleware-estop CLI")
    # Relative paths resolve against the working directory; show the real file
    # so it is obvious if this is not the one the consumer is watching.
    print(f"EMERGENCY STOP ENGAGED: {estop.path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
