from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any


SAMPLE_TARGET_ID = "person-7"
SAMPLE_CARD_POSITION = "0.50 0.25 -1.20"


def default_pcmr_status_path(appdata: Path | None = None) -> Path:
    if appdata is None:
        appdata_value = os.environ.get("APPDATA", "")
        appdata = Path(appdata_value) if appdata_value else Path.home() / "AppData" / "Roaming"
    return appdata / "Godot" / "app_userdata" / "demo_run" / "proxy_targets_live_status.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_depth_trace(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "available": False,
            "accepted_count": 0,
            "rejected_count": 0,
            "active_target_ids": [],
            "raw_track_pairs": [],
            "target_switch_count": 0,
            "raw_track_switch_count": 0,
            "held_last_pose_count": 0,
            "last_switch_reason": None,
            "last_active_age_frames": None,
        }
    accepted = 0
    rejected = 0
    active_target_ids: set[str] = set()
    raw_track_pairs: set[str] = set()
    last_target_id: str | None = None
    last_raw_pair: str | None = None
    target_switch_count = 0
    raw_track_switch_count = 0
    held_last_pose_count = 0
    last_switch_reason: str | None = None
    last_active_age_frames: int | None = None
    max_candidate_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            rejected += 1
            continue
        if event.get("event") != "accepted":
            rejected += 1
            continue
        accepted += 1
        target_id = event.get("target_id")
        if isinstance(target_id, str):
            if last_target_id is not None and target_id != last_target_id:
                target_switch_count += 1
            last_target_id = target_id
        active_target_id = event.get("active_target_id")
        if isinstance(active_target_id, str) and active_target_id:
            active_target_ids.add(active_target_id)
        raw_left = event.get("raw_left_track_id")
        raw_right = event.get("raw_right_track_id")
        if raw_left is not None and raw_right is not None:
            raw_pair = f"{raw_left}-{raw_right}"
            raw_track_pairs.add(raw_pair)
            if last_raw_pair is not None and raw_pair != last_raw_pair:
                raw_track_switch_count += 1
            last_raw_pair = raw_pair
        if _truthy(event.get("held_last_pose")):
            held_last_pose_count += 1
        if isinstance(event.get("switch_reason"), str):
            last_switch_reason = event["switch_reason"]
        try:
            last_active_age_frames = int(event["active_age_frames"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            max_candidate_count = max(max_candidate_count, int(event.get("candidate_count", 0)))
        except (TypeError, ValueError):
            pass
    return {
        "available": True,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "active_target_ids": sorted(active_target_ids),
        "raw_track_pairs": sorted(raw_track_pairs),
        "target_switch_count": target_switch_count,
        "raw_track_switch_count": raw_track_switch_count,
        "held_last_pose_count": held_last_pose_count,
        "last_switch_reason": last_switch_reason,
        "last_active_age_frames": last_active_age_frames,
        "max_candidate_count": max_candidate_count,
    }


def decode_log_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    if b"\x00" in data[:256]:
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def read_log_text(path: Path) -> str:
    return decode_log_text(path.read_bytes())


def _count(status: dict[str, Any], key: str) -> int:
    try:
        return int(status.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_vector3(value: Any) -> list[float] | None:
    if isinstance(value, list) and len(value) >= 3:
        try:
            return [round(float(value[0]), 3), round(float(value[1]), 3), round(float(value[2]), 3)]
        except (TypeError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    parts = value.strip().split()
    if len(parts) < 3:
        return None
    try:
        return [round(float(parts[0]), 3), round(float(parts[1]), 3), round(float(parts[2]), 3)]
    except ValueError:
        return None


def _sign_label(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def _z_sign_from_vector(value: Any) -> str:
    vector = _parse_vector3(value)
    return _sign_label(vector[2] if vector else None)


def _card_pose_summary(pcmr_status: dict[str, Any]) -> dict[str, Any]:
    proxy_world = _parse_vector3(pcmr_status.get("proxy_world_position"))
    card_node = _parse_vector3(pcmr_status.get("card_node_position"))
    card_minus_proxy_world = None
    if proxy_world is not None and card_node is not None:
        card_minus_proxy_world = [round(card_node[index] - proxy_world[index], 3) for index in range(3)]

    source_coordinate = pcmr_status.get("source_coordinate", {})
    if not isinstance(source_coordinate, dict):
        source_coordinate = {}
    return {
        "proxy_local_position": pcmr_status.get("proxy_local_position"),
        "proxy_world_position": pcmr_status.get("proxy_world_position"),
        "card_node_position": pcmr_status.get("card_node_position"),
        "card_resolved_position": pcmr_status.get("card_resolved_position"),
        "card_minus_proxy_world": card_minus_proxy_world,
        "head_z_sign": _z_sign_from_vector(source_coordinate.get("head_position_m")),
        "camera_z_sign": _z_sign_from_vector(source_coordinate.get("camera_position_m")),
        "world_z_sign": _z_sign_from_vector(pcmr_status.get("proxy_world_position")),
    }


def _sender_summary(sender_log_text: str) -> dict[str, Any]:
    sent_matches = re.findall(
        r"sent stereo seq=(?P<sequence>\d+)\s+target=(?P<target>\S+)\s+"
        r"depth_source=(?P<depth_source>\S+)\s+depth_confidence=(?P<depth_confidence>\S+)",
        sender_log_text,
    )
    diagnostic_matches = re.findall(
        r"stereo diagnostics: reason=(?P<reason>\S+)\s+reads=(?P<reads>\d+)\s+"
        r"left_frames=(?P<left_frames>\d+)\s+right_frames=(?P<right_frames>\d+)",
        sender_log_text,
    )
    last_sent = sent_matches[-1] if sent_matches else None
    last_diagnostic = diagnostic_matches[-1] if diagnostic_matches else None
    return {
        "ready": "proxy_targets live publisher listening" in sender_log_text,
        "sent_count": len(sent_matches),
        "last_sequence": int(last_sent[0]) if last_sent else None,
        "last_target_id": last_sent[1] if last_sent else None,
        "last_depth_source": last_sent[2] if last_sent else None,
        "last_depth_confidence": last_sent[3] if last_sent else None,
        "last_empty_reason": last_diagnostic[0] if last_diagnostic else None,
        "last_empty_reads": int(last_diagnostic[1]) if last_diagnostic else None,
        "last_left_frames": int(last_diagnostic[2]) if last_diagnostic else None,
        "last_right_frames": int(last_diagnostic[3]) if last_diagnostic else None,
        "mentions_left": bool(re.search(r"\b(left|Left)\b", sender_log_text)),
        "mentions_right": bool(re.search(r"\b(right|Right)\b", sender_log_text)),
        "no_target": "no_target" in sender_log_text,
        "low_confidence": "low confidence" in sender_log_text or "depth_confidence=low" in sender_log_text,
    }


def _raw_stream_ok(raw_status: dict[str, Any], min_packets: int) -> bool:
    target_ids = _list_strings(raw_status.get("target_ids"))
    return (
        _truthy(raw_status.get("ok"))
        and _count(raw_status, "packets") >= min_packets
        and _count(raw_status, "parsed") >= min_packets
        and _truthy(raw_status.get("sequence_contiguous"))
        and _truthy(raw_status.get("position_changed"))
        and any(target_id.startswith("vst_stereo-") for target_id in target_ids)
        and _count(raw_status, "missing_depth_confidence_count") == 0
        and _count(raw_status, "missing_depth_source_count") == 0
    )


def _pcmr_connected(pcmr_status: dict[str, Any]) -> bool:
    return (
        _truthy(pcmr_status.get("ws_connected"))
        and _truthy(pcmr_status.get("ws_subscribed"))
        and _count(pcmr_status, "packets") > 0
        and _count(pcmr_status, "parsed") > 0
        and _count(pcmr_status, "live") > 0
    )


def _sample_fallback_active(pcmr_status: dict[str, Any]) -> bool:
    card_target_id = str(pcmr_status.get("card_target_id", "")).strip()
    card_attach_target_id = str(pcmr_status.get("card_attach_target_id", "")).strip()
    card_node_position = str(pcmr_status.get("card_node_position", "")).strip()
    card_resolved_position = str(pcmr_status.get("card_resolved_position", "")).strip()
    return (
        str(pcmr_status.get("last_command", "")).strip() == "proxy_sample"
        or card_target_id == SAMPLE_TARGET_ID
        or card_attach_target_id == SAMPLE_TARGET_ID
        or card_node_position == SAMPLE_CARD_POSITION
        or card_resolved_position == SAMPLE_CARD_POSITION
    )


def _card_bound_to_live_target(pcmr_status: dict[str, Any], raw_status: dict[str, Any]) -> bool:
    card_target_id = str(pcmr_status.get("card_target_id", "")).strip()
    card_attach_target_id = str(pcmr_status.get("card_attach_target_id", "")).strip()
    proxy_target_ids = set(_list_strings(pcmr_status.get("proxy_target_ids")))
    raw_target_ids = set(_list_strings(raw_status.get("target_ids")))
    return (
        str(pcmr_status.get("last_command", "")).strip() == "proxy_live"
        and card_target_id.startswith("vst_stereo-")
        and card_attach_target_id == card_target_id
        and card_target_id in proxy_target_ids
        and (not raw_target_ids or card_target_id in raw_target_ids)
        and str(pcmr_status.get("card_node_position", "")).strip() != SAMPLE_CARD_POSITION
        and str(pcmr_status.get("card_resolved_position", "")).strip() != SAMPLE_CARD_POSITION
    )


def _low_confidence_only(raw_status: dict[str, Any]) -> bool:
    depth_confidences = raw_status.get("depth_confidences", {})
    if not isinstance(depth_confidences, dict):
        return False
    nonzero = {str(key): int(value) for key, value in depth_confidences.items() if int(value) > 0}
    return bool(nonzero) and set(nonzero) == {"low"}


def evaluate_health(
    sender_log_text: str,
    raw_status: dict[str, Any],
    pcmr_status: dict[str, Any],
    *,
    min_packets: int = 10,
    depth_trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verdicts: list[str] = []
    errors: list[str] = []
    sender = _sender_summary(sender_log_text)

    if sender["ready"]:
        verdicts.append("SENDER_READY")
    else:
        verdicts.append("SENDER_NOT_READY")
        errors.append("sender did not report proxy_targets live publisher listening")

    if sender["sent_count"] > 0 and str(sender.get("last_target_id", "")).startswith("vst_stereo-"):
        verdicts.append("SENDER_STEREO_TARGETS")
    elif sender.get("last_left_frames") == 0 and sender.get("last_right_frames") == 0:
        verdicts.append("SENDER_NO_FRAMES")
        errors.append("sender reported no Left/Right VST frames; live target source did not produce stereo pairs")
    else:
        errors.append("sender did not report sent stereo target=vst_stereo-*")

    if _raw_stream_ok(raw_status, min_packets=min_packets):
        verdicts.append("STREAM_OK")
    else:
        verdicts.append("STREAM_NOT_OK")
        errors.append("raw proxy_targets stream did not meet end-to-end monitor requirements")

    if _pcmr_connected(pcmr_status):
        verdicts.append("GODOT_CONNECTED")
        verdicts.append("TRANSPORT_TO_GODOT_OK")
    else:
        verdicts.append("GODOT_NOT_CONNECTED")
        errors.append("Godot/PCMR did not report ws_connected/ws_subscribed/packets/parsed/live")

    if _sample_fallback_active(pcmr_status):
        verdicts.append("SAMPLE_FALLBACK_ACTIVE")
        errors.append("PCMR/card is still on proxy_sample/person-7")

    if _card_bound_to_live_target(pcmr_status, raw_status):
        verdicts.append("CARD_BOUND_TO_LIVE_TARGET")
    else:
        errors.append("card_target_id is not bound to a live vst_stereo-* target")

    if _low_confidence_only(raw_status):
        verdicts.append("LOW_CONFIDENCE_DEPTH_ONLY")

    ok = (
        "SENDER_READY" in verdicts
        and "SENDER_STEREO_TARGETS" in verdicts
        and "STREAM_OK" in verdicts
        and "GODOT_CONNECTED" in verdicts
        and "CARD_BOUND_TO_LIVE_TARGET" in verdicts
        and "SAMPLE_FALLBACK_ACTIVE" not in verdicts
    )
    return {
        "ok": ok,
        "verdicts": verdicts,
        "errors": errors if not ok else [],
        "sender": sender,
        "raw": {
            "packets": _count(raw_status, "packets"),
            "parsed": _count(raw_status, "parsed"),
            "sequence_contiguous": _truthy(raw_status.get("sequence_contiguous")),
            "position_changed": _truthy(raw_status.get("position_changed")),
            "target_ids": _list_strings(raw_status.get("target_ids")),
            "depth_confidences": raw_status.get("depth_confidences", {}),
            "depth_sources": raw_status.get("depth_sources", {}),
            "missing_depth_confidence_count": _count(raw_status, "missing_depth_confidence_count"),
            "missing_depth_source_count": _count(raw_status, "missing_depth_source_count"),
            "client_label": raw_status.get("client_label"),
            "ws_connected": _truthy(raw_status.get("ws_connected")),
            "ws_subscribed": _truthy(raw_status.get("ws_subscribed")),
            "first_packet_seen": _truthy(raw_status.get("first_packet_seen")),
            "first_sequence": raw_status.get("first_sequence"),
            "last_sequence": raw_status.get("last_sequence"),
            "packets_before_close": _count(raw_status, "packets_before_close"),
            "close_reason": raw_status.get("close_reason") or raw_status.get("reason"),
        },
        "pcmr": {
            "last_command": pcmr_status.get("last_command"),
            "ws_connected": _truthy(pcmr_status.get("ws_connected")),
            "ws_subscribed": _truthy(pcmr_status.get("ws_subscribed")),
            "packets": _count(pcmr_status, "packets"),
            "parsed": _count(pcmr_status, "parsed"),
            "live": _count(pcmr_status, "live"),
            "sequence": pcmr_status.get("sequence"),
            "card_target_id": pcmr_status.get("card_target_id"),
            "card_attach_target_id": pcmr_status.get("card_attach_target_id"),
            "proxy_target_ids": _list_strings(pcmr_status.get("proxy_target_ids")),
            **_card_pose_summary(pcmr_status),
        },
        "tracking": depth_trace_summary if depth_trace_summary is not None else summarize_depth_trace(None),
    }


def wait_for_health(
    sender_log_path: Path,
    raw_status_path: Path,
    pcmr_status_path: Path,
    *,
    min_packets: int = 10,
    timeout_s: float = 0.0,
    interval_s: float = 0.25,
    depth_trace_path: Path | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_s)
    last_status: dict[str, Any] = {}
    while True:
        sender_log_text = read_log_text(sender_log_path) if sender_log_path.exists() else ""
        raw_status = load_json(raw_status_path) if raw_status_path.exists() else {"ok": False, "errors": ["raw status file missing"]}
        pcmr_status = load_json(pcmr_status_path) if pcmr_status_path.exists() else {"error": "pcmr status file missing"}
        last_status = evaluate_health(
            sender_log_text,
            raw_status,
            pcmr_status,
            min_packets=min_packets,
            depth_trace_summary=summarize_depth_trace(depth_trace_path),
        )
        if last_status.get("ok") or time.monotonic() >= deadline:
            return last_status
        time.sleep(max(0.01, interval_s))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate end-to-end stereo proxy_targets health across sender, raw stream, and Godot/card status.")
    parser.add_argument("--sender-log", type=Path, required=True)
    parser.add_argument("--raw-status", type=Path, required=True)
    parser.add_argument("--pcmr-status", type=Path, default=default_pcmr_status_path())
    parser.add_argument("--min-packets", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    parser.add_argument("--depth-trace", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = wait_for_health(
        args.sender_log,
        args.raw_status,
        args.pcmr_status,
        min_packets=max(1, args.min_packets),
        timeout_s=max(0.0, args.timeout_seconds),
        interval_s=max(0.01, args.interval_seconds),
        depth_trace_path=args.depth_trace,
    )
    text = json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
