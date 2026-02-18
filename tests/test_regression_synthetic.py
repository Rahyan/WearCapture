from __future__ import annotations

from pathlib import Path

from wearcapture.capture_engine import WearCaptureEngine
from wearcapture.config import CaptureConfig
from wearcapture.image_ops import detect_scroll_termination, stitch_frames

from .synthetic_fixtures import FakeAdbSequence, make_pattern_canvas, make_scroll_frames


def test_overlap_stitch_regression_height_baseline() -> None:
    canvas = make_pattern_canvas(width=180, height=2200)
    frame_h = 260
    step = 72
    count = 7

    frames = make_scroll_frames(canvas=canvas, frame_height=frame_h, step=step, count=count)
    cfg = CaptureConfig(
        output_path=Path("synthetic.png"),
        downscale_width=180,
        overlap_min_similarity=0.55,
    )

    stitched = stitch_frames(frames, cfg)
    expected_h = frame_h + step * (count - 1)

    assert stitched.size[0] == 180
    assert abs(stitched.size[1] - expected_h) <= 24


def test_termination_regression_thresholds() -> None:
    canvas = make_pattern_canvas(width=200, height=2400)
    frames = make_scroll_frames(canvas=canvas, frame_height=240, step=84, count=4)

    cfg = CaptureConfig(output_path=Path("synthetic.png"), downscale_width=200, similarity_threshold=0.995)

    moving = detect_scroll_termination(frames[0], frames[1], cfg)
    assert not moving.should_stop
    assert moving.estimated_motion_px > 30

    stationary = detect_scroll_termination(frames[2], frames[2].copy(), cfg)
    assert stationary.should_stop
    assert stationary.estimated_motion_px == 0


def test_engine_regression_stitched_size_baseline(tmp_path) -> None:
    canvas = make_pattern_canvas(width=190, height=2600)
    frame_h = 250
    step = 80

    seq = make_scroll_frames(canvas=canvas, frame_height=frame_h, step=step, count=6)
    seq.append(seq[-1].copy())

    adb = FakeAdbSequence(seq)
    engine = WearCaptureEngine(adb_client=adb)

    out = tmp_path / "engine_regression.png"
    cfg = CaptureConfig(
        output_path=out,
        serial="fake-serial",
        downscale_width=190,
        max_swipes=12,
        overlap_min_similarity=0.55,
    )

    result = engine.capture(cfg)

    # Last duplicated frame should trigger stop before append, leaving 6 useful frames.
    expected_frames = 6
    expected_h = frame_h + step * (expected_frames - 1)

    assert result.frames_captured == expected_frames
    assert result.stop_reason in {
        "frame-to-frame similarity indicates no further scrolling",
        "bottom/top region similarity threshold reached",
    }
    assert abs(result.image_size[1] - expected_h) <= 28
    assert out.exists()
