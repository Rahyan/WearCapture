from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event
from typing import Callable, Optional

from PIL import Image

from .adb import AdbClient
from .config import CaptureConfig, CaptureResult, SwipeSpec
from .errors import DeviceNotFoundError, MultipleDevicesError
from .image_ops import apply_circular_mask, detect_scroll_termination, stitch_frames

LogFn = Optional[Callable[[str], None]]


class WearCaptureEngine:
    def __init__(self, adb_client: Optional[AdbClient] = None, logger: Optional[logging.Logger] = None):
        self.adb = adb_client or AdbClient()
        self.logger = logger or logging.getLogger("wearcapture.engine")

    def _log(self, message: str, log_fn: LogFn = None) -> None:
        self.logger.info(message)
        if log_fn:
            log_fn(message)

    def _resolve_serial(self, preferred: Optional[str]) -> str:
        serials = self.adb.list_online_device_serials()

        if preferred:
            if preferred not in serials:
                raise DeviceNotFoundError(
                    f"Requested device '{preferred}' is not online. Online devices: {serials or 'none'}"
                )
            return preferred

        if not serials:
            raise DeviceNotFoundError("No online ADB devices found. Connect a Wear OS device and try again.")

        if len(serials) > 1:
            raise MultipleDevicesError(
                f"Multiple devices found: {', '.join(serials)}. Use --serial or select a device in the UI."
            )

        return serials[0]

    @staticmethod
    def _auto_swipe_spec(frame: Image.Image) -> SwipeSpec:
        w, h = frame.size
        x = w // 2
        y1 = int(h * 0.78)
        y2 = int(h * 0.24)
        return SwipeSpec(x1=x, y1=y1, x2=x, y2=y2, duration_ms=300)

    @staticmethod
    def _advanced_swipe_spec(config: CaptureConfig, frame: Image.Image) -> SwipeSpec:
        w, h = frame.size
        return SwipeSpec(
            x1=config.swipe_x1 if config.swipe_x1 is not None else w // 2,
            y1=config.swipe_y1 if config.swipe_y1 is not None else int(h * 0.78),
            x2=config.swipe_x2 if config.swipe_x2 is not None else w // 2,
            y2=config.swipe_y2 if config.swipe_y2 is not None else int(h * 0.24),
            duration_ms=config.swipe_duration_ms,
        )

    @staticmethod
    def _sleep_with_cancel(delay_ms: int, stop_event: Event | None) -> bool:
        if delay_ms <= 0:
            return False
        if stop_event is None:
            time.sleep(delay_ms / 1000.0)
            return False

        remaining = delay_ms / 1000.0
        while remaining > 0:
            if stop_event.is_set():
                return True
            step = min(0.05, remaining)
            time.sleep(step)
            remaining -= step
        return stop_event.is_set()

    def capture(self, config: CaptureConfig, log_fn: LogFn = None, stop_event: Event | None = None) -> CaptureResult:
        config.validate()

        if not self.adb.is_available():
            raise RuntimeError("ADB is not available in PATH. Install platform-tools and retry.")

        serial = self._resolve_serial(config.serial)
        self._log(f"Using device: {serial}", log_fn)

        frames: list[Image.Image] = []
        first = self.adb.capture_screen(serial)
        frames.append(first)
        self._log(f"Captured initial frame: {first.size[0]}x{first.size[1]}", log_fn)

        swipe = self._auto_swipe_spec(first) if config.simple_mode else self._advanced_swipe_spec(config, first)
        self._log(
            f"Swipe config: ({swipe.x1},{swipe.y1}) -> ({swipe.x2},{swipe.y2}), duration={swipe.duration_ms}ms",
            log_fn,
        )

        prev = first
        stop_reason = "max swipes reached"
        performed_swipes = 0
        low_motion_hits = 0

        for idx in range(config.max_swipes):
            if stop_event and stop_event.is_set():
                stop_reason = "user requested stop"
                self._log(f"Stopping capture: {stop_reason}", log_fn)
                break

            self.adb.swipe(serial, swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.duration_ms)
            performed_swipes += 1
            canceled_during_delay = self._sleep_with_cancel(config.scroll_delay_ms, stop_event)
            if canceled_during_delay:
                stop_reason = "user requested stop"
                self._log(f"Stopping capture: {stop_reason}", log_fn)
                break

            curr = self.adb.capture_screen(serial)
            if curr.size != first.size:
                curr = curr.resize(first.size, Image.Resampling.BILINEAR)

            if stop_event and stop_event.is_set():
                frames.append(curr)
                stop_reason = "user requested stop"
                self._log(f"Stopping capture: {stop_reason}", log_fn)
                break

            stop = detect_scroll_termination(prev, curr, config)
            self._log(
                "Iteration "
                f"{idx + 1}: bottom-top={stop.bottom_top_similarity:.4f}, "
                f"full={stop.full_similarity:.4f}, motion_px={stop.estimated_motion_px}, "
                f"overlap_sim={stop.overlap_similarity:.4f}",
                log_fn,
            )

            if stop.should_stop:
                stop_reason = stop.reason
                self._log(f"Stopping capture: {stop_reason}", log_fn)
                break

            if stop.low_motion_candidate:
                low_motion_hits += 1
                self._log(
                    f"Low-motion candidate detected ({low_motion_hits}/{config.low_motion_consecutive})",
                    log_fn,
                )
                if low_motion_hits >= config.low_motion_consecutive:
                    stop_reason = (
                        f"estimated motion <= {config.low_motion_px}px for "
                        f"{config.low_motion_consecutive} consecutive frames"
                    )
                    self._log(f"Stopping capture: {stop_reason}", log_fn)
                    break
            else:
                low_motion_hits = 0

            frames.append(curr)
            prev = curr

        stitched = stitch_frames(frames, config)
        if config.circular_mask:
            stitched = apply_circular_mask(stitched)

        output = Path(config.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        stitched.save(output, format="PNG")

        self._log(f"Saved stitched image: {output} ({stitched.size[0]}x{stitched.size[1]})", log_fn)

        return CaptureResult(
            output_path=output,
            device_serial=serial,
            frames_captured=len(frames),
            swipes_performed=performed_swipes,
            stop_reason=stop_reason,
            image_size=stitched.size,
        )
