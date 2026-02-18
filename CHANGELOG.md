# Changelog

## v0.1.0 - 2026-02-18

### Added
- Modular capture engine with overlap-aware stitching and robust termination detection
- CLI for device listing and capture flow
- Desktop UI with simple/advanced controls and `Stop & Save`
- Live preview and progress metrics panel (frames, swipes, elapsed, similarity, motion)
- Optional circular mask export
- Cross-platform packaging script using PyInstaller
- GitHub Actions CI and binary build workflows
- Real watch-generated screenshot examples in docs

### Changed
- Desktop UI migrated to `PySide6`
- Default capture tuning adjusted for live watch behavior (`scroll_delay_ms=450`, `max_swipes=24`)

### Notes
- ADB must be installed separately and available in `PATH`
