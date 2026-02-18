# WearCapture

WearCapture is a cross-platform desktop + CLI application for generating long, vertically scrollable screenshots from a connected Wear OS device over local ADB.

No watch app. No root. No cloud.

## Stack

- Engine: Python (`adb` subprocess + in-memory stitching)
- Desktop UI: `PySide6` (Qt)
- CLI: `argparse`

## Core Features

- Device detection via `adb devices -l` (USB and Wi-Fi ADB)
- Frame capture via `adb exec-out screencap -p`
- Scroll simulation via `adb shell input swipe ...`
- Robust stop detection using region similarity, frame similarity, low-motion checks, and max-swipe safeguard
- Overlap detection + deduplicated in-memory stitching
- `Stop & Save` while capture is running (saves partial stitched result)
- Optional circular mask output

## Example Outputs (Real Watch Data)

Generated from a Samsung Galaxy Watch4 Classic Wear OS 5 device.

![User capture example](docs/examples/watch_capture_user.png)
![Smoke capture example](docs/examples/watch_capture_smoke.png)
![Stop-and-save partial capture example](docs/examples/watch_capture_stop_save.png)

## Requirements

- Python 3.10+
- ADB available in `PATH` (or pass `--adb-path`)

Install runtime dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Install dev/build dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

## Run

List devices:

```bash
python3 -m wearcapture devices
```

Simple capture:

```bash
python3 -m wearcapture capture --output out.png
```

Advanced capture:

```bash
python3 -m wearcapture capture \
  --advanced \
  --serial 192.168.1.77:5555 \
  --swipe-x1 220 --swipe-y1 340 \
  --swipe-x2 220 --swipe-y2 110 \
  --swipe-duration-ms 320 \
  --scroll-delay-ms 450 \
  --similarity-threshold 0.995 \
  --max-swipes 24 \
  --output out.png
```

Launch desktop UI:

```bash
python3 -m wearcapture ui
```

## Tuned Defaults (Live Device)

Defaults were tuned against the connected watch on February 18, 2026.

- `scroll_delay_ms=450`
- `similarity_threshold=0.995`
- `max_swipes=24`
- Low-motion guard enabled (`low_motion_px=20`, `low_motion_similarity=0.93`)

## Packaging (Windows/macOS/Linux)

Build binaries with PyInstaller:

```bash
python3 scripts/package.py --clean
```

Outputs:

- CLI binary: `dist/wearcapture-cli*`
- Desktop binary: `dist/wearcapture-studio*`

## CI

- `.github/workflows/ci.yml`:
  - compile checks
  - unit tests
  - CLI smoke checks
- `.github/workflows/build-binaries.yml`:
  - builds binaries on Linux/macOS/Windows
  - runs on tag push (`v*`) or manual dispatch

## Architecture

- `wearcapture/adb.py`: ADB wrapper (devices, screenshots, swipe)
- `wearcapture/capture_engine.py`: capture loop, stop logic, cancellation, final export
- `wearcapture/image_ops.py`: similarity + overlap detection + stitching + circular mask
- `wearcapture/ui.py`: PySide6 desktop UI
- `wearcapture/cli.py`: CLI entrypoints
- `wearcapture/config.py`: capture configuration and validation

## Troubleshooting

- `ADB binary was not found`: install Android platform-tools and verify `adb version`.
- `No online ADB devices found`: verify `adb devices -l` and watch authorization.
- UI fails with missing `PySide6`: install `requirements.txt`.
- Capture runs too long: reduce `max_swipes` or raise `similarity_threshold`.
- Stops too early: lower `similarity_threshold` and/or increase swipe distance in advanced mode.
