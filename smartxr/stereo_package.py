"""Offline stereo capture package utilities for YAN-119.

A stereo package is a root directory with ``stereo.json`` plus two ordinary
mono NV12 sessions:

    stereo.json
    left/metadata.json
    left/nv12_packets/packet_*.bin
    right/metadata.json
    right/nv12_packets/packet_*.bin

The package layer pairs eyes by stable shared frame ids from each eye's
``metadata.json``. It does not use wall-clock time; timestamps are recorded only
as packet metadata for diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .nv12_reader import (
    HEADER_SIZE,
    iter_session,
    load_session_metadata,
    parse_header,
    session_packet_paths,
)
from .stereo_depth import (
    FRAME_ID_SOURCE,
    PAIR_ID_SCHEME,
    SCHEMA_VERSION,
    format_pair_id,
)


STEREO_METADATA_FILE = "stereo.json"
LEFT_EYE_DIR = "left"
RIGHT_EYE_DIR = "right"
EYE_DIRS = (LEFT_EYE_DIR, RIGHT_EYE_DIR)


class StereoPackageError(ValueError):
    """Raised when a stereo package cannot be interpreted deterministically."""


@dataclass(frozen=True)
class EyePacketRef:
    """One eye packet plus the stable shared frame id used for L/R pairing."""

    eye: str
    frame_id: int
    path: Path
    index: int
    timestamp_us: int

    def __post_init__(self) -> None:
        if self.eye not in EYE_DIRS:
            raise StereoPackageError(f"eye must be one of {EYE_DIRS}, got {self.eye!r}")
        if self.frame_id < 0:
            raise StereoPackageError(f"frame_id must be non-negative, got {self.frame_id}")
        if self.index < 1:
            raise StereoPackageError(f"index must be 1-based, got {self.index}")
        if self.timestamp_us < 0:
            raise StereoPackageError(
                f"timestamp_us must be non-negative, got {self.timestamp_us}"
            )


@dataclass(frozen=True)
class StereoPair:
    """A deterministic L/R pair keyed by shared frame id."""

    pair_id: str
    frame_id: int
    left: EyePacketRef
    right: EyePacketRef
    skew_frames: int
    timestamp_skew_us: int

    def __post_init__(self) -> None:
        if self.left.eye != LEFT_EYE_DIR:
            raise StereoPackageError(f"left ref has eye={self.left.eye!r}")
        if self.right.eye != RIGHT_EYE_DIR:
            raise StereoPackageError(f"right ref has eye={self.right.eye!r}")
        if self.left.frame_id != self.right.frame_id:
            raise StereoPackageError(
                f"pair frame ids differ: {self.left.frame_id} != {self.right.frame_id}"
            )
        if self.frame_id != self.left.frame_id:
            raise StereoPackageError(
                f"pair frame_id {self.frame_id} != ref frame_id {self.left.frame_id}"
            )
        if self.pair_id != format_pair_id(self.frame_id):
            raise StereoPackageError(
                f"pair_id {self.pair_id!r} does not match frame_id {self.frame_id}"
            )
        if self.skew_frames < 0:
            raise StereoPackageError(f"skew_frames must be non-negative, got {self.skew_frames}")
        if self.timestamp_skew_us < 0:
            raise StereoPackageError(
                f"timestamp_skew_us must be non-negative, got {self.timestamp_skew_us}"
            )


@dataclass(frozen=True)
class StereoPackageSummary:
    """Computed package pairing result."""

    pairs: tuple[StereoPair, ...]
    dropped_unpaired_left: int
    dropped_unpaired_right: int
    max_skew_frames: int

    @property
    def pair_count(self) -> int:
        return len(self.pairs)

    def pairing_stats(self) -> dict[str, int]:
        return {
            "pair_count": self.pair_count,
            "dropped_unpaired_left": self.dropped_unpaired_left,
            "dropped_unpaired_right": self.dropped_unpaired_right,
        }


def load_stereo_metadata(package_dir: Path) -> dict[str, Any]:
    """Load package-level ``stereo.json``."""
    return _read_json(Path(package_dir) / STEREO_METADATA_FILE)


def load_eye_packet_refs(session_dir: Path, eye: str) -> list[EyePacketRef]:
    """Load ordered packet refs for one eye session.

    The mono session remains readable by :func:`nv12_reader.iter_session`; this
    function only adds the shared ``frame_id`` binding from metadata.
    """
    session_dir = Path(session_dir)
    metadata = load_session_metadata(session_dir)
    paths = session_packet_paths(session_dir)
    frame_ids = _extract_frame_ids(metadata)
    if len(frame_ids) != len(paths):
        raise StereoPackageError(
            f"{eye}/ metadata frame_ids count {len(frame_ids)} != files count {len(paths)}"
        )

    refs: list[EyePacketRef] = []
    for index, (path, frame_id) in enumerate(zip(paths, frame_ids), start=1):
        header = _read_packet_header(path)
        refs.append(
            EyePacketRef(
                eye=eye,
                frame_id=frame_id,
                path=path,
                index=index,
                timestamp_us=int(header["timestamp_us"]),
            )
        )
    return refs


def pair_eye_packets(
    left_refs: Sequence[EyePacketRef],
    right_refs: Sequence[EyePacketRef],
    *,
    max_skew_frames: int | None = None,
) -> StereoPackageSummary:
    """Pair L/R refs by shared frame id.

    ``max_skew_frames`` bounds the absolute difference between each eye's
    1-based packet index. Shared ids beyond the bound are dropped from both
    eyes; ids present on only one side are counted as unpaired for that side.
    """
    if max_skew_frames is not None:
        max_skew_frames = _coerce_non_negative_int(max_skew_frames, "max_skew_frames")
    left_by_frame_id = _refs_by_frame_id(left_refs, LEFT_EYE_DIR)
    right_by_frame_id = _refs_by_frame_id(right_refs, RIGHT_EYE_DIR)

    pairs: list[StereoPair] = []
    dropped_unpaired_left = 0
    dropped_unpaired_right = 0
    for frame_id in sorted(set(left_by_frame_id) | set(right_by_frame_id)):
        left = left_by_frame_id.get(frame_id)
        right = right_by_frame_id.get(frame_id)
        if left is None:
            dropped_unpaired_right += 1
            continue
        if right is None:
            dropped_unpaired_left += 1
            continue

        skew_frames = abs(left.index - right.index)
        if max_skew_frames is not None and skew_frames > max_skew_frames:
            dropped_unpaired_left += 1
            dropped_unpaired_right += 1
            continue

        pairs.append(
            StereoPair(
                pair_id=format_pair_id(frame_id),
                frame_id=frame_id,
                left=left,
                right=right,
                skew_frames=skew_frames,
                timestamp_skew_us=abs(left.timestamp_us - right.timestamp_us),
            )
        )

    return StereoPackageSummary(
        pairs=tuple(pairs),
        dropped_unpaired_left=dropped_unpaired_left,
        dropped_unpaired_right=dropped_unpaired_right,
        max_skew_frames=max((pair.skew_frames for pair in pairs), default=0),
    )


def load_stereo_package(package_dir: Path) -> StereoPackageSummary:
    """Load a package and return the computed L/R pairing summary."""
    package_dir = Path(package_dir)
    metadata = load_stereo_metadata(package_dir)
    max_skew_frames = _declared_max_skew_frames(metadata)
    left_refs = load_eye_packet_refs(package_dir / LEFT_EYE_DIR, LEFT_EYE_DIR)
    right_refs = load_eye_packet_refs(package_dir / RIGHT_EYE_DIR, RIGHT_EYE_DIR)
    return pair_eye_packets(
        left_refs,
        right_refs,
        max_skew_frames=max_skew_frames,
    )


def validate_stereo_package(package_dir: Path) -> list[str]:
    """Return validation errors for a stereo package, or ``[]`` when valid."""
    package_dir = Path(package_dir)
    errors: list[str] = []

    metadata: dict[str, Any] | None = None
    stereo_path = package_dir / STEREO_METADATA_FILE
    if not stereo_path.exists():
        errors.append(f"missing {STEREO_METADATA_FILE}")
    else:
        try:
            metadata = load_stereo_metadata(package_dir)
        except Exception as exc:  # pragma: no cover - exact JSON errors vary by version.
            errors.append(f"invalid {STEREO_METADATA_FILE}: {exc}")
        else:
            _validate_stereo_metadata_shape(metadata, errors)

    refs_by_eye: dict[str, list[EyePacketRef]] = {}
    for eye in EYE_DIRS:
        eye_dir = package_dir / eye
        if not eye_dir.exists():
            errors.append(f"missing {eye}/ mono session")
            continue
        try:
            refs = load_eye_packet_refs(eye_dir, eye)
        except Exception as exc:
            errors.append(f"{eye}/ metadata invalid: {exc}")
            continue
        refs_by_eye[eye] = refs

        try:
            frames = list(iter_session(eye_dir))
        except Exception as exc:
            errors.append(f"{eye}/ NV12 round-trip failed: {exc}")
            continue
        if len(frames) != len(refs):
            errors.append(
                f"{eye}/ iter_session frame count {len(frames)} != metadata refs {len(refs)}"
            )

    if metadata is not None and all(eye in refs_by_eye for eye in EYE_DIRS):
        try:
            max_skew_frames = _declared_max_skew_frames(metadata)
            summary = pair_eye_packets(
                refs_by_eye[LEFT_EYE_DIR],
                refs_by_eye[RIGHT_EYE_DIR],
                max_skew_frames=max_skew_frames,
            )
        except Exception as exc:
            errors.append(f"pairing invalid: {exc}")
        else:
            _validate_pairing_stats(metadata, summary, errors)

    return errors


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StereoPackageError(f"missing {path.name}") from exc
    if not isinstance(data, dict):
        raise StereoPackageError(f"{path.name} must contain a JSON object")
    return data


def _read_packet_header(path: Path) -> Mapping[str, Any]:
    with Path(path).open("rb") as handle:
        return parse_header(handle.read(HEADER_SIZE))


def _extract_frame_ids(metadata: Mapping[str, Any]) -> list[int]:
    if "frame_ids" in metadata:
        raw_frame_ids = metadata["frame_ids"]
        if not isinstance(raw_frame_ids, list):
            raise StereoPackageError("metadata.frame_ids must be a list")
        return [
            _coerce_non_negative_int(frame_id, f"frame_ids[{index}]")
            for index, frame_id in enumerate(raw_frame_ids)
        ]

    raise StereoPackageError("metadata.json must include frame_ids")


def _refs_by_frame_id(
    refs: Sequence[EyePacketRef],
    expected_eye: str,
) -> dict[int, EyePacketRef]:
    by_frame_id: dict[int, EyePacketRef] = {}
    for ref in refs:
        if ref.eye != expected_eye:
            raise StereoPackageError(
                f"expected {expected_eye} ref, got {ref.eye!r} for frame_id {ref.frame_id}"
            )
        if ref.frame_id in by_frame_id:
            raise StereoPackageError(f"{expected_eye}/ duplicate frame_id {ref.frame_id}")
        by_frame_id[ref.frame_id] = ref
    return by_frame_id


def _declared_max_skew_frames(metadata: Mapping[str, Any]) -> int:
    pairing = _pairing(metadata)
    if "max_skew_frames" not in pairing:
        raise StereoPackageError("stereo.json pairing.max_skew_frames missing")
    return _coerce_non_negative_int(
        pairing["max_skew_frames"],
        "pairing.max_skew_frames",
    )


def _pairing(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    pairing = metadata.get("pairing")
    if not isinstance(pairing, Mapping):
        raise StereoPackageError("stereo.json pairing must be an object")
    return pairing


def _stats(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    pairing = _pairing(metadata)
    stats = pairing.get("stats")
    if not isinstance(stats, Mapping):
        raise StereoPackageError("stereo.json pairing.stats must be an object")
    return stats


def _coerce_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StereoPackageError(f"{name} must be a non-negative integer, got {value!r}")
    if value < 0:
        raise StereoPackageError(f"{name} must be non-negative, got {value}")
    return value


def _validate_stereo_metadata_shape(metadata: Mapping[str, Any], errors: list[str]) -> None:
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version {metadata.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    if not metadata.get("device_id"):
        errors.append("device_id missing")
    if not metadata.get("frame_provenance"):
        errors.append("frame_provenance missing")

    calibration = metadata.get("calibration")
    if not isinstance(calibration, Mapping):
        errors.append("calibration must be an object")
    else:
        if not calibration.get("kind"):
            errors.append("calibration.kind missing")
        for eye in EYE_DIRS:
            if not isinstance(calibration.get(eye), Mapping):
                errors.append(f"calibration.{eye} missing")
        if not isinstance(calibration.get("left_to_right_extrinsic"), Mapping):
            errors.append("calibration.left_to_right_extrinsic missing")

    try:
        pairing = _pairing(metadata)
    except StereoPackageError as exc:
        errors.append(str(exc))
        return
    if pairing.get("pair_id_scheme") != PAIR_ID_SCHEME:
        errors.append(
            f"pairing.pair_id_scheme {pairing.get('pair_id_scheme')!r} != {PAIR_ID_SCHEME!r}"
        )
    if pairing.get("frame_id_source") != FRAME_ID_SOURCE:
        errors.append(
            f"pairing.frame_id_source {pairing.get('frame_id_source')!r} != {FRAME_ID_SOURCE!r}"
        )
    try:
        _declared_max_skew_frames(metadata)
    except StereoPackageError as exc:
        errors.append(str(exc))
    try:
        stats = _stats(metadata)
    except StereoPackageError as exc:
        errors.append(str(exc))
    else:
        for key in (
            "pair_count",
            "dropped_unpaired_left",
            "dropped_unpaired_right",
        ):
            if key not in stats:
                errors.append(f"pairing.stats.{key} missing")
            else:
                try:
                    _coerce_non_negative_int(stats[key], f"pairing.stats.{key}")
                except StereoPackageError as exc:
                    errors.append(str(exc))


def _validate_pairing_stats(
    metadata: Mapping[str, Any],
    summary: StereoPackageSummary,
    errors: list[str],
) -> None:
    try:
        stats = _stats(metadata)
    except StereoPackageError as exc:
        errors.append(str(exc))
        return

    expected = summary.pairing_stats()
    for key, expected_value in expected.items():
        actual = stats.get(key)
        if actual != expected_value:
            errors.append(
                f"pairing.stats.{key} {actual!r} != computed {expected_value}"
            )
