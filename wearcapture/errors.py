"""Custom exceptions for WearCapture."""


class WearCaptureError(Exception):
    """Base exception for the application."""


class AdbNotFoundError(WearCaptureError):
    """Raised when adb cannot be found."""


class DeviceNotFoundError(WearCaptureError):
    """Raised when no connected Android/Wear OS device can be found."""


class MultipleDevicesError(WearCaptureError):
    """Raised when multiple devices are connected and no serial is specified."""


class CaptureFailedError(WearCaptureError):
    """Raised when a screen capture operation fails."""
