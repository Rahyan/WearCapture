from __future__ import annotations

import numpy as np
from PIL import Image


def make_pattern_canvas(width: int = 180, height: int = 2400) -> Image.Image:
    y = np.arange(height, dtype=np.int32)[:, None]
    x = np.arange(width, dtype=np.int32)[None, :]

    r = (x * 3 + y * 5 + (y // 37) * 23) % 256
    g = (x * 7 + y * 2 + ((x // 29) ^ (y // 31)) * 11) % 256
    b = (x * 11 + y * 13 + ((x + y) // 17) * 19) % 256

    arr = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def make_scroll_frames(
    *,
    canvas: Image.Image,
    frame_height: int,
    step: int,
    count: int,
    start_y: int = 0,
) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for idx in range(count):
        y = min(start_y + idx * step, canvas.height - frame_height)
        frames.append(canvas.crop((0, y, canvas.width, y + frame_height)).copy())
    return frames


class FakeAdbSequence:
    def __init__(self, frames: list[Image.Image]):
        if not frames:
            raise ValueError("frames cannot be empty")
        self.frames = [f.copy().convert("RGB") for f in frames]
        self.idx = 0

    def is_available(self) -> bool:
        return True

    def list_online_device_serials(self) -> list[str]:
        return ["fake-serial"]

    def capture_screen(self, serial: str) -> Image.Image:
        _ = serial
        return self.frames[min(self.idx, len(self.frames) - 1)].copy()

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        _ = (serial, x1, y1, x2, y2, duration_ms)
        if self.idx < len(self.frames) - 1:
            self.idx += 1
