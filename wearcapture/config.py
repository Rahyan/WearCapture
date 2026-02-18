from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class CaptureConfig:
    output_path: Path
    serial: Optional[str] = None

    # Mode
    simple_mode: bool = True

    # Swipe controls (used directly in advanced mode)
    swipe_x1: Optional[int] = None
    swipe_y1: Optional[int] = None
    swipe_x2: Optional[int] = None
    swipe_y2: Optional[int] = None
    swipe_duration_ms: int = 300

    # Loop controls
    scroll_delay_ms: int = 500
    max_swipes: int = 30

    # Similarity controls
    similarity_threshold: float = 0.995
    use_ssim: bool = True
    stop_region_ratio: float = 0.20
    low_motion_px: int = 20
    low_motion_similarity: float = 0.93
    low_motion_consecutive: int = 2

    # Stitch controls
    min_overlap_ratio: float = 0.08
    max_overlap_ratio: float = 0.92
    overlap_min_similarity: float = 0.70

    # Processing controls
    downscale_width: int = 320
    circular_mask: bool = False

    def validate(self) -> None:
        if self.max_swipes < 1:
            raise ValueError("max_swipes must be >= 1")
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in [0, 1]")
        if not 0 <= self.low_motion_px <= 200:
            raise ValueError("low_motion_px must be in [0, 200]")
        if not 0.0 <= self.low_motion_similarity <= 1.0:
            raise ValueError("low_motion_similarity must be in [0, 1]")
        if self.low_motion_consecutive < 1:
            raise ValueError("low_motion_consecutive must be >= 1")
        if not 0.0 < self.stop_region_ratio < 1.0:
            raise ValueError("stop_region_ratio must be in (0, 1)")
        if not 0.0 < self.min_overlap_ratio < 1.0:
            raise ValueError("min_overlap_ratio must be in (0, 1)")
        if not 0.0 < self.max_overlap_ratio < 1.0:
            raise ValueError("max_overlap_ratio must be in (0, 1)")
        if self.min_overlap_ratio >= self.max_overlap_ratio:
            raise ValueError("min_overlap_ratio must be < max_overlap_ratio")
        if self.downscale_width < 64:
            raise ValueError("downscale_width must be >= 64")


@dataclass(slots=True)
class SwipeSpec:
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int


@dataclass(slots=True)
class CaptureResult:
    output_path: Path
    device_serial: str
    frames_captured: int
    swipes_performed: int
    stop_reason: str
    image_size: tuple[int, int]
