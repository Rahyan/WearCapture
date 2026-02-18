from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .adb import AdbClient, DeviceInfo
from .config import CaptureConfig

PROFILE_FILE_VERSION = 1

PROFILE_CONFIG_KEYS = {
    "simple_mode",
    "swipe_x1",
    "swipe_y1",
    "swipe_x2",
    "swipe_y2",
    "swipe_duration_ms",
    "scroll_delay_ms",
    "max_swipes",
    "similarity_threshold",
    "use_ssim",
    "stop_region_ratio",
    "low_motion_px",
    "low_motion_similarity",
    "low_motion_consecutive",
    "min_overlap_ratio",
    "max_overlap_ratio",
    "overlap_min_similarity",
    "downscale_width",
    "circular_mask",
}


@dataclass(slots=True)
class CaptureProfile:
    name: str
    description: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    model_regex: Optional[str] = None
    display_size: Optional[tuple[int, int]] = None
    source: str = "builtin"

    def matches(self, device_model: Optional[str], display_size: Optional[tuple[int, int]]) -> int:
        score = 0

        if self.display_size and display_size and self.display_size == display_size:
            score += 4

        if self.model_regex and device_model:
            try:
                if re.search(self.model_regex, device_model):
                    score += 3
            except re.error:
                pass

        return score


def default_profiles_path() -> Path:
    return Path.home() / ".wearcapture" / "profiles.json"


def extract_model_from_details(details: str) -> Optional[str]:
    match = re.search(r"model:([^\s]+)", details)
    if match:
        return match.group(1)
    return None


def _parse_display_size(value: Any) -> Optional[tuple[int, int]]:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _sanitize_profile_config(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in config.items() if k in PROFILE_CONFIG_KEYS}


def _profile_from_json(item: dict[str, Any], source: str) -> CaptureProfile:
    return CaptureProfile(
        name=str(item.get("name", "")).strip(),
        description=str(item.get("description", "")).strip(),
        config=_sanitize_profile_config(dict(item.get("config", {}))),
        model_regex=item.get("model_regex"),
        display_size=_parse_display_size(item.get("display_size")),
        source=source,
    )


def _profile_to_json(profile: CaptureProfile) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": profile.name,
        "description": profile.description,
        "config": _sanitize_profile_config(profile.config),
    }
    if profile.model_regex:
        payload["model_regex"] = profile.model_regex
    if profile.display_size:
        payload["display_size"] = [profile.display_size[0], profile.display_size[1]]
    return payload


def builtin_profiles() -> list[CaptureProfile]:
    return [
        CaptureProfile(
            name="generic",
            description="Default balanced profile",
            config={
                "simple_mode": True,
                "scroll_delay_ms": 450,
                "max_swipes": 24,
                "similarity_threshold": 0.995,
                "low_motion_px": 20,
                "low_motion_similarity": 0.93,
                "low_motion_consecutive": 2,
                "use_ssim": True,
            },
            source="builtin",
        ),
        CaptureProfile(
            name="galaxy_watch_450",
            description="Samsung Galaxy Watch 450x450 tuned profile",
            config={
                "simple_mode": True,
                "scroll_delay_ms": 450,
                "max_swipes": 24,
                "similarity_threshold": 0.995,
                "low_motion_px": 20,
                "low_motion_similarity": 0.93,
                "low_motion_consecutive": 2,
                "use_ssim": True,
            },
            model_regex=r"^SM_R",
            display_size=(450, 450),
            source="builtin",
        ),
        CaptureProfile(
            name="pixel_watch_384",
            description="Pixel Watch style 384x384 profile",
            config={
                "simple_mode": True,
                "scroll_delay_ms": 430,
                "max_swipes": 22,
                "similarity_threshold": 0.994,
                "low_motion_px": 18,
                "low_motion_similarity": 0.93,
                "low_motion_consecutive": 2,
                "use_ssim": True,
            },
            display_size=(384, 384),
            source="builtin",
        ),
    ]


def load_user_profiles(path: Optional[Path] = None) -> list[CaptureProfile]:
    file_path = path or default_profiles_path()
    if not file_path.exists():
        return []

    data = json.loads(file_path.read_text(encoding="utf-8"))
    profiles = data.get("profiles", [])

    parsed: list[CaptureProfile] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        profile = _profile_from_json(item, source="user")
        if profile.name:
            parsed.append(profile)
    return parsed


def save_user_profiles(profiles: list[CaptureProfile], path: Optional[Path] = None) -> Path:
    file_path = path or default_profiles_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": PROFILE_FILE_VERSION,
        "profiles": [_profile_to_json(profile) for profile in profiles if profile.name],
    }
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return file_path


def load_profiles(path: Optional[Path] = None) -> list[CaptureProfile]:
    merged: dict[str, CaptureProfile] = {profile.name.lower(): profile for profile in builtin_profiles()}
    for profile in load_user_profiles(path):
        merged[profile.name.lower()] = profile
    return sorted(merged.values(), key=lambda p: p.name.lower())


def get_profile_by_name(name: str, path: Optional[Path] = None) -> Optional[CaptureProfile]:
    target = name.strip().lower()
    for profile in load_profiles(path):
        if profile.name.lower() == target:
            return profile
    return None


def suggest_profile(
    device_model: Optional[str],
    display_size: Optional[tuple[int, int]],
    profiles: list[CaptureProfile],
) -> Optional[CaptureProfile]:
    scored = [(profile.matches(device_model, display_size), profile) for profile in profiles]
    scored.sort(key=lambda item: (item[0], item[1].name != "generic"), reverse=True)

    if scored and scored[0][0] > 0:
        return scored[0][1]

    for profile in profiles:
        if profile.name.lower() == "generic":
            return profile
    return profiles[0] if profiles else None


def _device_info_for_serial(adb: AdbClient, serial: str) -> Optional[DeviceInfo]:
    for device in adb.list_devices():
        if device.serial == serial:
            return device
    return None


def suggest_profile_for_serial(
    adb: AdbClient,
    serial: str,
    path: Optional[Path] = None,
) -> Optional[CaptureProfile]:
    info = _device_info_for_serial(adb, serial)
    model = extract_model_from_details(info.details) if info else None
    display_size = adb.get_display_size(serial)
    return suggest_profile(model, display_size, load_profiles(path))


def apply_profile_to_config(config: CaptureConfig, profile: CaptureProfile) -> CaptureConfig:
    for key, value in profile.config.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def config_to_profile_config(config: CaptureConfig) -> dict[str, Any]:
    return _sanitize_profile_config(
        {
            "simple_mode": config.simple_mode,
            "swipe_x1": config.swipe_x1,
            "swipe_y1": config.swipe_y1,
            "swipe_x2": config.swipe_x2,
            "swipe_y2": config.swipe_y2,
            "swipe_duration_ms": config.swipe_duration_ms,
            "scroll_delay_ms": config.scroll_delay_ms,
            "max_swipes": config.max_swipes,
            "similarity_threshold": config.similarity_threshold,
            "use_ssim": config.use_ssim,
            "stop_region_ratio": config.stop_region_ratio,
            "low_motion_px": config.low_motion_px,
            "low_motion_similarity": config.low_motion_similarity,
            "low_motion_consecutive": config.low_motion_consecutive,
            "min_overlap_ratio": config.min_overlap_ratio,
            "max_overlap_ratio": config.max_overlap_ratio,
            "overlap_min_similarity": config.overlap_min_similarity,
            "downscale_width": config.downscale_width,
            "circular_mask": config.circular_mask,
        }
    )


def upsert_profile(
    *,
    name: str,
    config: dict[str, Any],
    description: str = "",
    model_regex: Optional[str] = None,
    display_size: Optional[tuple[int, int]] = None,
    path: Optional[Path] = None,
) -> Path:
    if not name.strip():
        raise ValueError("Profile name cannot be empty")

    profile = CaptureProfile(
        name=name.strip(),
        description=description.strip(),
        config=_sanitize_profile_config(config),
        model_regex=model_regex,
        display_size=display_size,
        source="user",
    )

    existing = load_user_profiles(path)
    replaced = False
    for idx, item in enumerate(existing):
        if item.name.lower() == profile.name.lower():
            existing[idx] = profile
            replaced = True
            break
    if not replaced:
        existing.append(profile)

    return save_user_profiles(existing, path)


def export_profile(profile: CaptureProfile, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PROFILE_FILE_VERSION,
        "profiles": [_profile_to_json(profile)],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def import_profile(
    input_path: Path,
    *,
    path: Optional[Path] = None,
    rename: Optional[str] = None,
) -> CaptureProfile:
    data = json.loads(input_path.read_text(encoding="utf-8"))

    candidate: Optional[dict[str, Any]] = None
    if isinstance(data, dict) and isinstance(data.get("profiles"), list) and data["profiles"]:
        first = data["profiles"][0]
        if isinstance(first, dict):
            candidate = first
    elif isinstance(data, dict) and "name" in data and "config" in data:
        candidate = data

    if candidate is None:
        raise ValueError("Import file does not contain a valid profile payload")

    profile = _profile_from_json(candidate, source="user")
    if rename:
        profile.name = rename.strip()

    if not profile.name:
        raise ValueError("Imported profile has no name")

    upsert_profile(
        name=profile.name,
        config=profile.config,
        description=profile.description,
        model_regex=profile.model_regex,
        display_size=profile.display_size,
        path=path,
    )
    return profile
