"""Install the CET emitter into a Cyberpunk 2077 game directory.

    python -m middleware.install_mod --game-dir "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Cyberpunk 2077"

Copies ``emitter/cet/mods/pishock_emitter`` into
``<game>/bin/x64/plugins/cyber_engine_tweaks/mods/pishock_emitter``, writes its
``config.json`` with the shared secret from your middleware config, and prints
the command that starts the consumer on the right outbox file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO_MOD_DIR = Path(__file__).resolve().parent.parent / "emitter" / "cet" / "mods" / "pishock_emitter"
CET_MODS_SUBDIR = Path("bin") / "x64" / "plugins" / "cyber_engine_tweaks" / "mods"
MOD_NAME = "pishock_emitter"

COMMON_GAME_DIRS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077",
    r"C:\Program Files\Steam\steamapps\common\Cyberpunk 2077",
    r"C:\GOG Games\Cyberpunk 2077",
    r"C:\Program Files (x86)\GOG Galaxy\Games\Cyberpunk 2077",
    r"C:\Program Files\Epic Games\Cyberpunk2077",
]

# Never copied from the repo: user config and runtime files.
_SKIP_NAMES = {"config.json", "events.jsonl", "consumer_status.txt", "pishock_events.jsonl"}


def find_game_dir() -> Path | None:
    for candidate in COMMON_GAME_DIRS:
        path = Path(candidate)
        if (path / "bin" / "x64" / "Cyberpunk2077.exe").exists():
            return path
    return None


def install(game_dir: Path, secret: str, source: Path = REPO_MOD_DIR, force_config: bool = False) -> Path:
    """Copy the mod and write config.json. Returns the installed mod directory."""

    mods_dir = game_dir / CET_MODS_SUBDIR
    if not mods_dir.is_dir():
        raise FileNotFoundError(
            f"{mods_dir} not found - is Cyber Engine Tweaks installed and has the game been launched once?"
        )
    target = mods_dir / MOD_NAME

    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _SKIP_NAMES or n.endswith(".tmp")}

    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)
    (target / "outbox").mkdir(exist_ok=True)

    config_path = target / "config.json"
    if force_config or not config_path.exists():
        cfg = json.loads((source / "config.example.json").read_text(encoding="utf-8"))
    else:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["shared_secret"] = secret
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the PiShock CET emitter into Cyberpunk 2077")
    parser.add_argument("--game-dir", help="Cyberpunk 2077 install directory (auto-detected if omitted)")
    parser.add_argument("--config", default=os.getenv("MIDDLEWARE_CONFIG", "middleware/config.local.yaml"),
                        help="middleware config to take shared_secret from")
    parser.add_argument("--secret", help="shared secret (overrides --config)")
    parser.add_argument("--force-config", action="store_true", help="reset config.json to the example defaults")
    args = parser.parse_args(argv)

    game_dir = Path(args.game_dir) if args.game_dir else find_game_dir()
    if game_dir is None:
        print("could not find Cyberpunk 2077; pass --game-dir", file=sys.stderr)
        return 2

    secret = args.secret
    if secret is None:
        from .config import load_config  # pylint: disable=import-outside-toplevel

        try:
            secret = load_config(args.config).shared_secret
        except (OSError, ValueError) as exc:
            print(f"could not read shared_secret from {args.config}: {exc}; pass --secret", file=sys.stderr)
            return 2
    if '"' in secret or "\\" in secret:
        print("shared_secret must not contain quotes or backslashes", file=sys.stderr)
        return 2

    try:
        target = install(game_dir, secret, force_config=args.force_config)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2

    outbox = target / "outbox" / "events.jsonl"
    print(f"installed: {target}")
    print("start the consumer with:")
    print(f'  middleware-file-ingest --config {args.config} --outbox "{outbox}"')
    print("or set ingest.outbox_path in your config to that path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
