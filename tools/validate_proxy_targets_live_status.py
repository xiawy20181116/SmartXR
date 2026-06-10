from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Dict


def default_status_path(appdata: Path | None = None) -> Path:
    if appdata is None:
        appdata_value = os.environ.get("APPDATA", "")
        appdata = Path(appdata_value) if appdata_value else Path.home() / "AppData" / "Roaming"
    return appdata / "Godot" / "app_userdata" / "demo_run" / "proxy_targets_live_status.json"


def load_status(status_path: Path) -> Dict:
    return json.loads(status_path.read_text(encoding="utf-8"))


def _status_count(status: Dict, key: str) -> int:
    try:
        return int(status.get(key, 0))
    except (TypeError, ValueError):
        return 0


def requirement_met(status: Dict, requirement: str) -> bool:
    if requirement == "packets":
        return _status_count(status, "packets") > 0
    if requirement == "parsed":
        return _status_count(status, "parsed") > 0
    if requirement == "live":
        return _status_count(status, "live") > 0
    if requirement == "attached":
        card_target_id = str(status.get("card_target_id", "")).strip()
        card_attach_target_id = str(status.get("card_attach_target_id", "")).strip()
        return (
            _status_count(status, "live") > 0
            and _status_count(status, "attachments") > 0
            and _status_count(status, "card_apply_count") > 0
            and _status_count(status, "proxy_target_count") > 0
            and status.get("anchor_mode") == "target"
            and bool(card_target_id)
            and card_attach_target_id == card_target_id
        )
    raise ValueError(f"unknown requirement: {requirement}")


def wait_for_requirement(status_path: Path, requirement: str, timeout_s: float, interval_s: float) -> Dict:
    deadline = time.monotonic() + timeout_s
    last_status: Dict = {}
    while time.monotonic() <= deadline:
        if status_path.exists():
            try:
                last_status = load_status(status_path)
            except (OSError, json.JSONDecodeError) as exc:
                last_status = {"error": f"status_read_failed:{exc}"}
            if requirement_met(last_status, requirement):
                return last_status
        time.sleep(interval_s)
    return last_status


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Godot proxy_targets live status without visual inspection.")
    parser.add_argument("--status-file", type=Path, default=default_status_path())
    parser.add_argument("--require", choices=["packets", "parsed", "live", "attached"], default="live")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--interval", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = wait_for_requirement(args.status_file, args.require, args.timeout, args.interval)
    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    if requirement_met(status, args.require):
        return 0
    print(
        f"proxy_targets live validation failed: require={args.require} status_file={args.status_file}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
