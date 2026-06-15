# SmartXR

[![CI](https://github.com/xiawy20181116/SmartXR/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiawy20181116/SmartXR/actions/workflows/ci.yml)

## PCMR overlay visual check

For manual headset inspection of the Antman passthrough overlay:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_windows_pcmr_overlay_visual_check.ps1
```

See `docs/pcmr_overlay_visual_check.md` for expected headset visuals, status
files, and how this differs from the automated proxy_targets live validation
runner.
