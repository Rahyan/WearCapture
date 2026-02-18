from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from .adb import AdbClient
from .errors import WearCaptureError
from .logging_utils import configure_logging


def _default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"wearcapture_{ts}.png"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wearcapture", description="Capture long Wear OS screenshots over ADB")
    parser.add_argument("--adb-path", default="adb", help="Path to adb binary (default: adb in PATH)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("devices", help="List connected ADB devices")

    capture = sub.add_parser("capture", help="Capture and stitch a long screenshot")
    capture.add_argument("--serial", help="ADB serial to use")
    capture.add_argument("--output", type=Path, default=_default_output_path(), help="Output PNG path")
    capture.add_argument("--advanced", action="store_true", help="Enable advanced mode")
    capture.add_argument("--swipe-x1", type=int)
    capture.add_argument("--swipe-y1", type=int)
    capture.add_argument("--swipe-x2", type=int)
    capture.add_argument("--swipe-y2", type=int)
    capture.add_argument("--swipe-duration-ms", type=int, default=300)
    capture.add_argument("--scroll-delay-ms", type=int, default=450)
    capture.add_argument("--similarity-threshold", type=float, default=0.995)
    capture.add_argument("--max-swipes", type=int, default=24)
    capture.add_argument("--pixel-diff", action="store_true", help="Use pixel-difference metric instead of SSIM")
    capture.add_argument("--circular-mask", action="store_true", help="Apply circular mask to output")

    sub.add_parser("ui", help="Launch desktop UI")

    return parser


def _run_devices(adb: AdbClient) -> int:
    devices = adb.list_devices()
    if not devices:
        print("No devices found.")
        return 0

    for dev in devices:
        print(f"{dev.serial}\t{dev.state}\t{dev.details}".rstrip())
    return 0


def _run_capture(args: argparse.Namespace, adb: AdbClient) -> int:
    from .capture_engine import WearCaptureEngine
    from .config import CaptureConfig

    cfg = CaptureConfig(
        output_path=args.output,
        serial=args.serial,
        simple_mode=not args.advanced,
        swipe_x1=args.swipe_x1,
        swipe_y1=args.swipe_y1,
        swipe_x2=args.swipe_x2,
        swipe_y2=args.swipe_y2,
        swipe_duration_ms=args.swipe_duration_ms,
        scroll_delay_ms=args.scroll_delay_ms,
        similarity_threshold=args.similarity_threshold,
        max_swipes=args.max_swipes,
        use_ssim=not args.pixel_diff,
        circular_mask=args.circular_mask,
    )

    engine = WearCaptureEngine(adb_client=adb)
    result = engine.capture(cfg, log_fn=print)

    print("Capture completed")
    print(f"Device: {result.device_serial}")
    print(f"Frames: {result.frames_captured}")
    print(f"Swipes: {result.swipes_performed}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Output: {result.output_path}")
    return 0


def _run_ui(args: argparse.Namespace) -> int:
    from .ui import WearCaptureApp

    app = WearCaptureApp(adb_path=args.adb_path)
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    adb = AdbClient(adb_path=args.adb_path)

    try:
        if args.command == "devices":
            return _run_devices(adb)
        if args.command == "capture":
            return _run_capture(args, adb)

        # Default behavior: launch UI
        return _run_ui(args)
    except ModuleNotFoundError as exc:
        print(
            f"Missing dependency: {exc}. Install required packages with: python3 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2
    except WearCaptureError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - top-level safeguard
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
