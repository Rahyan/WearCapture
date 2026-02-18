from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from .adb import AdbClient
from .errors import WearCaptureError
from .logging_utils import configure_logging
from .profiles import (
    config_to_profile_config,
    export_profile,
    extract_model_from_details,
    get_profile_by_name,
    import_profile,
    load_profiles,
    suggest_profile_for_serial,
    upsert_profile,
)


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
    capture.add_argument("--profile-file", type=Path, help="Path to profile JSON store")
    capture.add_argument("--profile", help="Profile name to apply before other overrides")
    capture.add_argument("--save-profile", help="Save effective capture settings into this profile name")
    capture.add_argument("--save-profile-description", default="", help="Optional profile description")

    mode_group = capture.add_mutually_exclusive_group()
    mode_group.add_argument("--advanced", dest="simple_mode", action="store_false", help="Enable advanced mode")
    mode_group.add_argument("--simple", dest="simple_mode", action="store_true", help="Force simple mode")
    capture.set_defaults(simple_mode=None)

    capture.add_argument("--swipe-x1", type=int)
    capture.add_argument("--swipe-y1", type=int)
    capture.add_argument("--swipe-x2", type=int)
    capture.add_argument("--swipe-y2", type=int)
    capture.add_argument("--swipe-duration-ms", type=int)
    capture.add_argument("--scroll-delay-ms", type=int)
    capture.add_argument("--similarity-threshold", type=float)
    capture.add_argument("--max-swipes", type=int)

    metric_group = capture.add_mutually_exclusive_group()
    metric_group.add_argument("--pixel-diff", dest="use_ssim", action="store_false", help="Use pixel-difference metric")
    metric_group.add_argument("--ssim", dest="use_ssim", action="store_true", help="Use SSIM similarity metric")
    capture.set_defaults(use_ssim=None)

    mask_group = capture.add_mutually_exclusive_group()
    mask_group.add_argument("--circular-mask", dest="circular_mask", action="store_true", help="Apply circular mask")
    mask_group.add_argument("--no-circular-mask", dest="circular_mask", action="store_false", help="Disable circular mask")
    capture.set_defaults(circular_mask=None)

    profiles = sub.add_parser("profiles", help="Manage capture profiles")
    profiles_sub = profiles.add_subparsers(dest="profiles_command", required=True)

    p_list = profiles_sub.add_parser("list", help="List available profiles")
    p_list.add_argument("--profile-file", type=Path, help="Path to profile JSON store")

    p_suggest = profiles_sub.add_parser("suggest", help="Suggest profile for a connected device")
    p_suggest.add_argument("--serial", help="ADB serial to evaluate")
    p_suggest.add_argument("--profile-file", type=Path, help="Path to profile JSON store")

    p_export = profiles_sub.add_parser("export", help="Export a profile to a JSON file")
    p_export.add_argument("--name", required=True, help="Profile name")
    p_export.add_argument("--output", required=True, type=Path, help="Output profile JSON path")
    p_export.add_argument("--profile-file", type=Path, help="Path to profile JSON store")

    p_import = profiles_sub.add_parser("import", help="Import a profile from a JSON file")
    p_import.add_argument("--input", required=True, type=Path, help="Input profile JSON path")
    p_import.add_argument("--rename", help="Override imported profile name")
    p_import.add_argument("--profile-file", type=Path, help="Path to profile JSON store")

    ui = sub.add_parser("ui", help="Launch desktop UI")
    ui.add_argument("--profile-file", type=Path, help="Path to profile JSON store")

    return parser


def _run_devices(adb: AdbClient) -> int:
    devices = adb.list_devices()
    if not devices:
        print("No devices found.")
        return 0

    for dev in devices:
        print(f"{dev.serial}\t{dev.state}\t{dev.details}".rstrip())
    return 0


def _resolve_serial_for_suggestion(adb: AdbClient, preferred: str | None) -> str | None:
    if preferred:
        return preferred

    serials = adb.list_online_device_serials()
    if len(serials) == 1:
        return serials[0]
    return None


def _apply_capture_overrides(cfg, args: argparse.Namespace) -> None:
    for key in [
        "swipe_x1",
        "swipe_y1",
        "swipe_x2",
        "swipe_y2",
        "swipe_duration_ms",
        "scroll_delay_ms",
        "similarity_threshold",
        "max_swipes",
    ]:
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)

    if args.use_ssim is not None:
        cfg.use_ssim = args.use_ssim
    if args.circular_mask is not None:
        cfg.circular_mask = args.circular_mask
    if args.simple_mode is not None:
        cfg.simple_mode = args.simple_mode


def _derive_profile_match_metadata(adb: AdbClient, serial: str) -> tuple[str | None, tuple[int, int] | None]:
    model: str | None = None
    for device in adb.list_devices():
        if device.serial == serial:
            raw = extract_model_from_details(device.details)
            if raw:
                model = f"^{re.escape(raw)}$"
            break
    return model, adb.get_display_size(serial)


def _run_capture(args: argparse.Namespace, adb: AdbClient) -> int:
    from .capture_engine import WearCaptureEngine
    from .config import CaptureConfig
    from .profiles import apply_profile_to_config

    cfg = CaptureConfig(
        output_path=args.output,
        serial=args.serial,
    )

    selected_profile = None
    if args.profile:
        selected_profile = get_profile_by_name(args.profile, args.profile_file)
        if not selected_profile:
            raise WearCaptureError(f"Profile '{args.profile}' not found")
    else:
        serial_for_suggestion = _resolve_serial_for_suggestion(adb, args.serial)
        if serial_for_suggestion:
            selected_profile = suggest_profile_for_serial(adb, serial_for_suggestion, args.profile_file)

    if selected_profile:
        apply_profile_to_config(cfg, selected_profile)
        print(f"Using profile: {selected_profile.name}")

    _apply_capture_overrides(cfg, args)

    engine = WearCaptureEngine(adb_client=adb)
    result = engine.capture(cfg, log_fn=print)

    if args.save_profile:
        model_regex, display_size = _derive_profile_match_metadata(adb, result.device_serial)
        profile_path = upsert_profile(
            name=args.save_profile,
            description=args.save_profile_description,
            config=config_to_profile_config(cfg),
            model_regex=model_regex,
            display_size=display_size,
            path=args.profile_file,
        )
        print(f"Saved profile '{args.save_profile}' to {profile_path}")

    print("Capture completed")
    print(f"Device: {result.device_serial}")
    print(f"Frames: {result.frames_captured}")
    print(f"Swipes: {result.swipes_performed}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Output: {result.output_path}")
    return 0


def _run_profiles(args: argparse.Namespace, adb: AdbClient) -> int:
    if args.profiles_command == "list":
        profiles = load_profiles(args.profile_file)
        for profile in profiles:
            display = f"{profile.display_size[0]}x{profile.display_size[1]}" if profile.display_size else "-"
            model = profile.model_regex or "-"
            print(f"{profile.name}\t{profile.source}\t{display}\t{model}\t{profile.description}".rstrip())
        return 0

    if args.profiles_command == "suggest":
        serial = _resolve_serial_for_suggestion(adb, args.serial)
        if not serial:
            print("Unable to suggest profile: provide --serial or connect exactly one online device.")
            return 1

        profile = suggest_profile_for_serial(adb, serial, args.profile_file)
        if not profile:
            print("No profiles available.")
            return 1

        print(f"Suggested profile for {serial}: {profile.name}")
        return 0

    if args.profiles_command == "export":
        profile = get_profile_by_name(args.name, args.profile_file)
        if not profile:
            raise WearCaptureError(f"Profile '{args.name}' not found")

        out = export_profile(profile, args.output)
        print(f"Exported profile '{profile.name}' to {out}")
        return 0

    if args.profiles_command == "import":
        profile = import_profile(args.input, path=args.profile_file, rename=args.rename)
        print(f"Imported profile '{profile.name}'")
        return 0

    return 1


def _run_ui(args: argparse.Namespace) -> int:
    from .ui import WearCaptureApp

    app = WearCaptureApp(adb_path=args.adb_path, profile_path=getattr(args, "profile_file", None))
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
        if args.command == "profiles":
            return _run_profiles(args, adb)

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
