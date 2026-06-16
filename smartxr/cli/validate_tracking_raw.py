"""Validate canonical tracking_raw (C1) payloads in the schema gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from smartxr.tracking_raw_schema import load_message, validate_message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate canonical tracking_raw (C1) payloads."
    )
    parser.add_argument("--input", action="append", required=True, type=Path, help="JSON payload file to validate.")
    args = parser.parse_args(argv)

    ok = True
    for input_path in args.input:
        errors = validate_message(load_message(input_path))
        if errors:
            ok = False
            print(f"{input_path}: invalid")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"{input_path}: ok")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
