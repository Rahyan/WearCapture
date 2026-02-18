from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from .config import CaptureConfig


@dataclass(slots=True)
class OverlapResult:
    overlap_px: int
    similarity: float


@dataclass(slots=True)
class StopCheckResult:
    should_stop: bool
    reason: str
    bottom_top_similarity: float
    full_similarity: float
    estimated_motion_px: int
    overlap_similarity: float
    low_motion_candidate: bool


def _resize_gray(image: Image.Image, target_width: int) -> np.ndarray:
    gray = image.convert("L")
    w, h = gray.size
    if w <= target_width:
        resized = gray
    else:
        target_height = max(1, int(h * (target_width / w)))
        resized = gray.resize((target_width, target_height), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float32)


def similarity_score(a: np.ndarray, b: np.ndarray, use_ssim: bool) -> float:
    if a.shape != b.shape:
        raise ValueError("Arrays for similarity must have same shape")
    if use_ssim:
        return ssim_score(a, b)
    diff = np.mean(np.abs(a - b))
    return float(max(0.0, 1.0 - diff / 255.0))


def ssim_score(a: np.ndarray, b: np.ndarray) -> float:
    # Global SSIM variant for fast stop checks.
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2

    mu_a = float(a.mean())
    mu_b = float(b.mean())

    var_a = float(((a - mu_a) ** 2).mean())
    var_b = float(((b - mu_b) ** 2).mean())
    cov = float(((a - mu_a) * (b - mu_b)).mean())

    numerator = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    denominator = (mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2)

    if denominator == 0:
        return 1.0
    return float(max(-1.0, min(1.0, numerator / denominator)))


def detect_scroll_termination(prev: Image.Image, curr: Image.Image, config: CaptureConfig) -> StopCheckResult:
    arr_prev = _resize_gray(prev, config.downscale_width)
    arr_curr = _resize_gray(curr, config.downscale_width)

    h = min(arr_prev.shape[0], arr_curr.shape[0])
    arr_prev = arr_prev[:h, :]
    arr_curr = arr_curr[:h, :]

    strip_h = max(8, int(h * config.stop_region_ratio))
    prev_bottom = arr_prev[-strip_h:, :]
    curr_top = arr_curr[:strip_h, :]

    bottom_top_similarity = similarity_score(prev_bottom, curr_top, config.use_ssim)
    full_similarity = similarity_score(arr_prev, arr_curr, config.use_ssim)
    motion_px, overlap_similarity = estimate_scroll_motion(prev, curr, config)
    low_motion_candidate = (
        overlap_similarity >= config.low_motion_similarity and motion_px <= config.low_motion_px
    )

    # Required stop condition: bottom of previous frame vs top of new frame.
    if bottom_top_similarity >= config.similarity_threshold:
        return StopCheckResult(
            should_stop=True,
            reason="bottom/top region similarity threshold reached",
            bottom_top_similarity=bottom_top_similarity,
            full_similarity=full_similarity,
            estimated_motion_px=motion_px,
            overlap_similarity=overlap_similarity,
            low_motion_candidate=low_motion_candidate,
        )

    # Additional robust check for edge-case no-movement swipes.
    if full_similarity >= max(0.98, config.similarity_threshold - 0.01):
        return StopCheckResult(
            should_stop=True,
            reason="frame-to-frame similarity indicates no further scrolling",
            bottom_top_similarity=bottom_top_similarity,
            full_similarity=full_similarity,
            estimated_motion_px=motion_px,
            overlap_similarity=overlap_similarity,
            low_motion_candidate=low_motion_candidate,
        )

    return StopCheckResult(
        should_stop=False,
        reason="continue",
        bottom_top_similarity=bottom_top_similarity,
        full_similarity=full_similarity,
        estimated_motion_px=motion_px,
        overlap_similarity=overlap_similarity,
        low_motion_candidate=low_motion_candidate,
    )


def estimate_scroll_motion(prev: Image.Image, curr: Image.Image, config: CaptureConfig) -> tuple[int, float]:
    prev_small = _resize_gray(prev, config.downscale_width)
    curr_small = _resize_gray(curr, config.downscale_width)

    h = min(prev_small.shape[0], curr_small.shape[0])
    prev_small = prev_small[:h, :]
    curr_small = curr_small[:h, :]

    min_overlap = max(8, int(h * 0.55))
    max_overlap = h
    step = max(1, h // 240)

    best_overlap = min_overlap
    best_similarity = -2.0

    for overlap in range(min_overlap, max_overlap + 1, step):
        a = prev_small[-overlap:, :]
        b = curr_small[:overlap, :]
        sim = similarity_score(a, b, use_ssim=False)
        if sim > best_similarity:
            best_similarity = sim
            best_overlap = overlap

    scale = prev.height / prev_small.shape[0]
    overlap_px = max(1, int(best_overlap * scale))
    motion_px = max(0, prev.height - overlap_px)
    return motion_px, float(best_similarity)


def find_best_overlap(prev: Image.Image, curr: Image.Image, config: CaptureConfig) -> OverlapResult:
    prev_small = _resize_gray(prev, config.downscale_width)
    curr_small = _resize_gray(curr, config.downscale_width)

    h = min(prev_small.shape[0], curr_small.shape[0])
    prev_small = prev_small[:h, :]
    curr_small = curr_small[:h, :]

    min_overlap = max(8, int(h * config.min_overlap_ratio))
    max_overlap = min(h - 1, int(h * config.max_overlap_ratio))
    step = max(1, h // 220)

    best_overlap = min_overlap
    best_similarity = -2.0

    # Pixel-difference matching is used for overlap search for speed.
    for overlap in range(min_overlap, max_overlap + 1, step):
        a = prev_small[-overlap:, :]
        b = curr_small[:overlap, :]
        sim = similarity_score(a, b, use_ssim=False)
        if sim > best_similarity:
            best_similarity = sim
            best_overlap = overlap

    scale = prev.height / prev_small.shape[0]
    overlap_px = max(1, int(best_overlap * scale))
    return OverlapResult(overlap_px=overlap_px, similarity=float(best_similarity))


def stitch_frames(frames: list[Image.Image], config: CaptureConfig) -> Image.Image:
    if not frames:
        raise ValueError("No frames to stitch")

    base_w, base_h = frames[0].size
    normalized = [frame.resize((base_w, base_h), Image.Resampling.BILINEAR) for frame in frames]

    strips: list[np.ndarray] = [np.asarray(normalized[0], dtype=np.uint8)]

    prev = normalized[0]
    for curr in normalized[1:]:
        overlap = find_best_overlap(prev, curr, config)
        curr_arr = np.asarray(curr, dtype=np.uint8)

        if overlap.similarity < config.overlap_min_similarity:
            strips.append(curr_arr)
        else:
            crop_start = min(max(overlap.overlap_px, 1), curr_arr.shape[0] - 1)
            strips.append(curr_arr[crop_start:, :, :])
        prev = curr

    stitched_arr = np.vstack(strips)
    return Image.fromarray(stitched_arr, mode="RGB")


def apply_circular_mask(image: Image.Image) -> Image.Image:
    w, h = image.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2

    square = image.crop((left, top, left + side, top + side)).convert("RGBA")
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, side - 1, side - 1), fill=255)
    square.putalpha(mask)
    return square
