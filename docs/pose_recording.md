# SmartXR Pose Recording Sidecar

This workflow records a Godot/OpenXR head-pose sidecar next to a Windows VST
stereo package. V1 records `XRCamera3D.global_transform` in Godot and uses the
Python recorder's per-frame `read_system_unix_time_us` values as the primary
frame clock for offline matching.

## Capture

Run from the repository root in PowerShell:

```powershell
$dir = "C:\Users\wyxia\SmartXR_recordings\YAN-115\pose_sync_$(Get-Date -Format yyyyMMdd-HHmmss)"
./tools/run_antman_vst_stereo_package_recorder_with_pose.ps1 -OutDir $dir -DurationSeconds 30 -SmartXROptionsPath "config\smartxr_options.json"
```

The unified runner sets `SMARTXR_XR_POSE_TRACE_PATH` to
`$dir\xr_pose_trace.jsonl`, starts the Windows PCMR/Godot pose logger, records
the Antman VST stereo package, stops PCMR, then merges the stereo frame timing
with the nearest pose samples.

## Outputs

- `xr_pose_trace.jsonl`: Godot pose samples with `timestamp_kind =
  godot_sample_time`, `pose_time_clock = system_unix_time_usec`,
  `pose_time_us`, `godot_ticks_usec`, `system_unix_time_usec`,
  `world_from_head`, `head_position_m`, and cumulative `flush_drops`.
- `xr_pose_trace_status.json`: final recorder status, including
  `flush_drops`. Use this for the final `pose_flush_drops` acceptance check,
  because the last flush can fail after the last successful JSONL row.
- `left/metadata.json` and `right/metadata.json`: stereo frame metadata. New
  captures include `read_system_unix_time_us` arrays aligned with
  `frame_ids` and `timestamps_us`.
- `frame_pose_assoc.jsonl`: one merged row per matched stereo pair, including
  exposure times, `frame_match_time_source`, `frame_match_time_us`,
  `matched_pose_sample_index`, `matched_pose_time_us`,
  `matched_pose_delta_ms`, `sync_quality`, and `world_from_head`.

## Timing Summary

Use `xr_pose_trace.jsonl` for pose sample rate, `xr_pose_trace_status.json` for
final recorder health, and `frame_pose_assoc.jsonl` for frame-to-pose matching
health. Compute `pose_sample_hz` from the first and last `pose_time_us` values,
compute `pose_flush_drops` from the final status file, then compute percentiles
from `matched_pose_delta_ms` and report `frame_match_time_source` counts plus
`timestamp_kind` values. A quick PowerShell check:

```powershell
$poseRows = Get-Content "$dir\xr_pose_trace.jsonl" | ForEach-Object { $_ | ConvertFrom-Json }
$poseStatus = Get-Content "$dir\xr_pose_trace_status.json" | ConvertFrom-Json
$poseRows = @($poseRows | Sort-Object pose_time_us)
$firstPoseUs = [int64]$poseRows[0].pose_time_us
$lastPoseUs = [int64]$poseRows[-1].pose_time_us
$durationSeconds = ($lastPoseUs - $firstPoseUs) / 1000000.0
$poseSampleHz = ($poseRows.Count - 1) / $durationSeconds
$poseFlushDrops = [int]$poseStatus.flush_drops
$rows = Get-Content "$dir\frame_pose_assoc.jsonl" | ForEach-Object { $_ | ConvertFrom-Json }
$d = @($rows | ForEach-Object { [double]$_.matched_pose_delta_ms } | Sort-Object)
$p50 = $d[[math]::Floor(($d.Count - 1) * 0.50)]
$p95 = $d[[math]::Floor(($d.Count - 1) * 0.95)]
$max = ($d | Measure-Object -Maximum).Maximum
$rows | Group-Object frame_match_time_source | Select-Object Name,Count
$rows | Group-Object timestamp_kind | Select-Object Name,Count
"pose_sample_hz=$poseSampleHz pose_flush_drops=$poseFlushDrops"
"matched_pose_delta_ms p50=$p50 p95=$p95 max=$max"
```

Acceptance criteria:

- `pose_sample_hz >= 90Hz`
- `pose_flush_drops == 0`
- `matched_pose_delta_ms p50 <= 3ms`
- `p95 <= 8ms`
- `max <= 15ms`
- `timestamp_kind = godot_sample_time or better`

## Clock Model

V1 does not assume VST exposure timestamps and the Godot system Unix clock are
the same clock. Offline merge uses the left/right `read_system_unix_time_us`
midpoint when available. Exposure midpoint is retained as a fallback for older
metadata and as a diagnostic signal, not as the preferred V1 matching clock.

If the timing summary misses the acceptance criteria, move to V2 with a
native OpenXR/QPC timestamp path instead of treating exposure time as
equivalent to the Godot system Unix clock.

## Legacy Data

Old recordings without `world_from_head` pose rows cannot reconstruct true historical head pose.
They can still be inspected for stereo exposure timing, but there is no offline
way to recover the user's real head transform after the fact.
