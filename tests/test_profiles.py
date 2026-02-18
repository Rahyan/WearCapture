from __future__ import annotations

from pathlib import Path

from wearcapture.profiles import (
    CaptureProfile,
    config_to_profile_config,
    export_profile,
    get_profile_by_name,
    import_profile,
    load_profiles,
    suggest_profile,
    upsert_profile,
)


def test_profile_upsert_and_load_user_profile(tmp_path) -> None:
    profile_file = tmp_path / "profiles.json"

    upsert_profile(
        name="my-watch",
        description="custom",
        config={"scroll_delay_ms": 410, "max_swipes": 18},
        model_regex=r"^SM_R890$",
        display_size=(450, 450),
        path=profile_file,
    )

    loaded = load_profiles(profile_file)
    profile = next(p for p in loaded if p.name == "my-watch")

    assert profile.config["scroll_delay_ms"] == 410
    assert profile.config["max_swipes"] == 18
    assert profile.display_size == (450, 450)


def test_profile_suggestion_prefers_match(tmp_path) -> None:
    profile_file = tmp_path / "profiles.json"

    upsert_profile(
        name="exact-match",
        config={"scroll_delay_ms": 440},
        model_regex=r"^SM_R890$",
        display_size=(450, 450),
        path=profile_file,
    )

    profiles = load_profiles(profile_file)
    suggested = suggest_profile("SM_R890", (450, 450), profiles)

    assert suggested is not None
    assert suggested.name == "exact-match"


def test_profile_import_export_roundtrip(tmp_path) -> None:
    profile_file = tmp_path / "profiles.json"

    upsert_profile(
        name="roundtrip",
        config={"max_swipes": 12, "similarity_threshold": 0.994},
        path=profile_file,
    )

    original = get_profile_by_name("roundtrip", profile_file)
    assert original is not None

    exported_path = tmp_path / "roundtrip_export.json"
    export_profile(original, exported_path)

    imported = import_profile(exported_path, path=profile_file, rename="roundtrip-imported")
    assert imported.name == "roundtrip-imported"

    loaded = get_profile_by_name("roundtrip-imported", profile_file)
    assert loaded is not None
    assert loaded.config["max_swipes"] == 12


def test_config_to_profile_config_has_expected_keys() -> None:
    from wearcapture.config import CaptureConfig

    cfg = CaptureConfig(output_path=Path("out.png"))
    data = config_to_profile_config(cfg)

    for key in ["scroll_delay_ms", "max_swipes", "similarity_threshold", "use_ssim"]:
        assert key in data

    assert "output_path" not in data
