import argparse
import json
import sys
import time
from pathlib import Path


def load_status(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        return {"error": f"json_decode_failed: {exc}"}


def status_ok(status: dict, require: str, require_card_apply: bool) -> bool:
    if require == "live":
        if int(status.get("packets", 0)) <= 0:
            return False
        if int(status.get("parsed", 0)) <= 0:
            return False
        if int(status.get("live", 0)) <= 0:
            return False
        if not status.get("ws_connected", False):
            return False
    if require_card_apply:
        if int(status.get("proxy_target_count", 0)) <= 0:
            return False
        if int(status.get("card_apply_count", 0)) <= 0:
            return False
        if not str(status.get("card_attach_target_id", "")).strip():
            return False
        if not str(status.get("last_proxy_position", "")).strip():
            return False
        if not str(status.get("card_node_position", "")).strip():
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--require", choices=["live"], default="live")
    parser.add_argument("--require-card-apply", action="store_true")
    args = parser.parse_args()

    status_path = Path(args.status_file)
    deadline = time.monotonic() + args.timeout_seconds
    last_status = None

    while time.monotonic() <= deadline:
        loaded = load_status(status_path)
        if isinstance(loaded, dict):
            last_status = loaded
            if status_ok(last_status, args.require, args.require_card_apply):
                print(json.dumps(last_status, ensure_ascii=False, indent=2))
                return 0
        time.sleep(0.1)

    if last_status is None:
        last_status = {"error": "status_file_not_written", "status_file": str(status_path)}
    print(json.dumps(last_status, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
