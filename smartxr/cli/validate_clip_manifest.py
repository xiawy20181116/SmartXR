"""Validate clip-level capture manifests in the schema gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from smartxr.clip_manifest_schema import load_manifest, validate_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate clip-level capture manifests.")
    parser.add_argument("--input", action="append", required=True, type=Path, help="JSON manifest file to validate.")
    args = parser.parse_args(argv)

    ok = True
    for input_path in args.input:
        errors = validate_manifest(load_manifest(input_path))
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
