from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from PIL import Image

from .errors import AdbNotFoundError, CaptureFailedError


@dataclass(slots=True)
class DeviceInfo:
    serial: str
    state: str
    details: str


class AdbClient:
    def __init__(self, adb_path: str = "adb", timeout_sec: int = 15):
        self.adb_path = adb_path
        self.timeout_sec = timeout_sec

    def _run(self, *args: str, serial: Optional[str] = None, raw: bool = False) -> subprocess.CompletedProcess[bytes]:
        cmd: list[str] = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        try:
            return subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
            )
        except FileNotFoundError as exc:
            raise AdbNotFoundError(
                "ADB binary was not found. Install ADB and ensure it is available in PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.decode(errors="replace").strip()
            if raw:
                raise
            raise CaptureFailedError(f"ADB command failed: {' '.join(cmd)}\n{err}") from exc

    def is_available(self) -> bool:
        try:
            self._run("version")
            return True
        except AdbNotFoundError:
            return False
        except CaptureFailedError:
            # ADB exists but version command may still return non-zero in edge cases.
            return True

    def list_devices(self) -> list[DeviceInfo]:
        proc = self._run("devices", "-l")
        lines = proc.stdout.decode(errors="replace").splitlines()

        devices: list[DeviceInfo] = []
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=2)
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            details = parts[2] if len(parts) > 2 else ""
            devices.append(DeviceInfo(serial=serial, state=state, details=details))
        return devices

    def list_online_device_serials(self) -> list[str]:
        return [d.serial for d in self.list_devices() if d.state == "device"]

    def capture_screen(self, serial: str) -> Image.Image:
        proc = self._run("exec-out", "screencap", "-p", serial=serial)
        raw = proc.stdout

        if not raw:
            raise CaptureFailedError("Received empty screenshot data from ADB.")

        # Try raw payload first. Some devices return already-valid PNG bytes.
        # If decoding fails, fall back to conservative normalization attempts.
        png_sig = b"\x89PNG\r\n\x1a\n"
        candidates: list[bytes] = [raw]

        sig_pos = raw.find(png_sig)
        if sig_pos > 0:
            candidates.append(raw[sig_pos:])

        # Fallbacks for environments that mangle newline bytes.
        candidates.append(raw.replace(b"\r\n", b"\n"))
        if sig_pos > 0:
            candidates.append(raw[sig_pos:].replace(b"\r\n", b"\n"))

        last_error: Exception | None = None
        for payload in candidates:
            try:
                img = Image.open(BytesIO(payload))
                img.load()
                return img.convert("RGB")
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc

        raise CaptureFailedError("Failed to decode screenshot data from ADB output.") from last_error

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self._run(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
            serial=serial,
        )

    def get_display_size(self, serial: str) -> Optional[tuple[int, int]]:
        proc = self._run("shell", "wm", "size", serial=serial)
        out = proc.stdout.decode(errors="replace")
        match = re.search(r"(\d+)x(\d+)", out)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))
