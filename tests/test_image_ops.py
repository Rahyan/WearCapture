from pathlib import Path

from PIL import Image

from wearcapture.config import CaptureConfig
from wearcapture.image_ops import detect_scroll_termination, stitch_frames


def _frame(color: tuple[int, int, int], size: tuple[int, int] = (120, 120)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_stop_detects_no_movement() -> None:
    cfg = CaptureConfig(output_path=Path("out.png"))
    a = _frame((80, 90, 100))
    b = _frame((80, 90, 100))

    result = detect_scroll_termination(a, b, cfg)
    assert result.should_stop


def test_stitch_preserves_width() -> None:
    cfg = CaptureConfig(output_path=Path("out.png"))
    a = _frame((255, 0, 0), (140, 120))
    b = _frame((0, 255, 0), (140, 120))

    stitched = stitch_frames([a, b], cfg)
    assert stitched.size[0] == 140
    assert stitched.size[1] >= 120
