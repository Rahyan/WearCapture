from __future__ import annotations

import queue
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .adb import AdbClient
from .capture_engine import CaptureProgress, WearCaptureEngine
from .config import CaptureConfig
from .profiles import (
    CaptureProfile,
    config_to_profile_config,
    default_profiles_path,
    export_profile,
    extract_model_from_details,
    import_profile,
    load_profiles,
    suggest_profile_for_serial,
    upsert_profile,
)


class WearCaptureApp:
    def __init__(self, adb_path: str = "adb", profile_path: Path | None = None):
        self.adb = AdbClient(adb_path=adb_path)
        self.engine = WearCaptureEngine(adb_client=self.adb)
        self.profile_path = profile_path or default_profiles_path()

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.window = QMainWindow()
        self.window.setWindowTitle("WearCapture")
        self.window.resize(1120, 790)
        self.window.setMinimumSize(940, 650)

        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.current_max_swipes = 24
        self.profile_map: dict[str, CaptureProfile] = {}

        self._build_ui()
        self._apply_styles()
        self._reload_profiles()
        self._refresh_devices()

        self.event_timer = QTimer(self.window)
        self.event_timer.setInterval(100)
        self.event_timer.timeout.connect(self._drain_events)
        self.event_timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        self.window.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        title = QLabel("WearCapture")
        title.setObjectName("title")
        subtitle = QLabel("Wear OS long screenshots over local ADB")
        subtitle.setObjectName("subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        top_card = QFrame()
        top_card.setObjectName("card")
        top_grid = QGridLayout(top_card)
        top_grid.setContentsMargins(10, 10, 10, 10)
        top_grid.setHorizontalSpacing(8)
        top_grid.setVerticalSpacing(8)

        top_grid.addWidget(QLabel("Device"), 0, 0)
        self.device_combo = QComboBox()
        self.device_combo.setEditable(False)
        self.device_combo.currentTextChanged.connect(self._on_device_changed)
        top_grid.addWidget(self.device_combo, 0, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_devices)
        top_grid.addWidget(refresh_btn, 0, 2)

        top_grid.addWidget(QLabel("Output"), 1, 0)
        self.output_input = QLineEdit(str(self._default_output()))
        top_grid.addWidget(self.output_input, 1, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_output)
        top_grid.addWidget(browse_btn, 1, 2)

        top_grid.addWidget(QLabel("Profile"), 2, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(False)
        top_grid.addWidget(self.profile_combo, 2, 1)
        self.apply_profile_btn = QPushButton("Apply")
        self.apply_profile_btn.clicked.connect(self._apply_selected_profile)
        top_grid.addWidget(self.apply_profile_btn, 2, 2)

        profile_actions_widget = QWidget()
        profile_actions = QHBoxLayout(profile_actions_widget)
        profile_actions.setContentsMargins(0, 0, 0, 0)
        profile_actions.setSpacing(6)

        self.save_profile_btn = QPushButton("Save")
        self.save_profile_btn.clicked.connect(self._save_current_profile)
        self.import_profile_btn = QPushButton("Import")
        self.import_profile_btn.clicked.connect(self._import_profile)
        self.export_profile_btn = QPushButton("Export")
        self.export_profile_btn.clicked.connect(self._export_selected_profile)

        profile_actions.addWidget(self.save_profile_btn)
        profile_actions.addWidget(self.import_profile_btn)
        profile_actions.addWidget(self.export_profile_btn)
        profile_actions.addStretch(1)

        top_grid.addWidget(profile_actions_widget, 3, 1, 1, 2)

        top_grid.setColumnStretch(1, 1)
        outer.addWidget(top_card)

        split = QHBoxLayout()
        split.setSpacing(10)
        outer.addLayout(split, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        split.addLayout(left, 3)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("Mode"))
        self.simple_radio = QRadioButton("Simple")
        self.advanced_radio = QRadioButton("Advanced")
        self.simple_radio.setChecked(True)

        self.mode_group = QButtonGroup(self.window)
        self.mode_group.addButton(self.simple_radio)
        self.mode_group.addButton(self.advanced_radio)
        self.simple_radio.toggled.connect(self._toggle_mode)

        mode_row.addWidget(self.simple_radio)
        mode_row.addWidget(self.advanced_radio)
        mode_row.addStretch(1)
        left.addLayout(mode_row)

        common_box = QGroupBox("Common Controls")
        common_box.setObjectName("box")
        common_form = QFormLayout(common_box)
        common_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.scroll_delay_input = QLineEdit("450")
        self.similarity_input = QLineEdit("0.995")
        self.max_swipes_input = QLineEdit("24")
        self.circular_checkbox = QCheckBox("Circular export mask")

        common_form.addRow("Scroll delay (ms)", self.scroll_delay_input)
        common_form.addRow("Similarity threshold", self.similarity_input)
        common_form.addRow("Max swipe count", self.max_swipes_input)
        common_form.addRow("", self.circular_checkbox)
        left.addWidget(common_box)

        self.advanced_box = QGroupBox("Advanced Controls")
        self.advanced_box.setObjectName("box")
        adv_form = QFormLayout(self.advanced_box)
        adv_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.swipe_x1_input = QLineEdit("")
        self.swipe_y1_input = QLineEdit("")
        self.swipe_x2_input = QLineEdit("")
        self.swipe_y2_input = QLineEdit("")
        self.swipe_duration_input = QLineEdit("300")

        self.swipe_x1_input.setPlaceholderText("auto")
        self.swipe_y1_input.setPlaceholderText("auto")
        self.swipe_x2_input.setPlaceholderText("auto")
        self.swipe_y2_input.setPlaceholderText("auto")

        adv_form.addRow("Swipe x1", self.swipe_x1_input)
        adv_form.addRow("Swipe y1", self.swipe_y1_input)
        adv_form.addRow("Swipe x2", self.swipe_x2_input)
        adv_form.addRow("Swipe y2", self.swipe_y2_input)
        adv_form.addRow("Swipe duration (ms)", self.swipe_duration_input)
        left.addWidget(self.advanced_box)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Start Capture")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_capture)

        self.stop_button = QPushButton("Stop and Save")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_capture)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("status")

        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.status_label)
        action_row.addStretch(1)
        left.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, self.current_max_swipes)
        self.progress.setValue(0)
        left.addWidget(self.progress)

        logs_box = QGroupBox("Logs")
        logs_box.setObjectName("box")
        logs_layout = QVBoxLayout(logs_box)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        logs_layout.addWidget(self.logs)
        left.addWidget(logs_box, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        split.addLayout(right, 2)

        preview_box = QGroupBox("Live Preview")
        preview_box.setObjectName("box")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_label = QLabel("No preview yet")
        self.preview_label.setObjectName("preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(320, 320)
        preview_layout.addWidget(self.preview_label)
        right.addWidget(preview_box)

        metrics_box = QGroupBox("Live Metrics")
        metrics_box.setObjectName("box")
        metrics_layout = QGridLayout(metrics_box)

        self.frames_metric = QLabel("0")
        self.swipes_metric = QLabel("0")
        self.elapsed_metric = QLabel("0.0s")
        self.bottom_top_metric = QLabel("--")
        self.full_metric = QLabel("--")
        self.motion_metric = QLabel("--")
        self.overlap_metric = QLabel("--")

        metrics_layout.addWidget(QLabel("Frames"), 0, 0)
        metrics_layout.addWidget(self.frames_metric, 0, 1)
        metrics_layout.addWidget(QLabel("Swipes"), 1, 0)
        metrics_layout.addWidget(self.swipes_metric, 1, 1)
        metrics_layout.addWidget(QLabel("Elapsed"), 2, 0)
        metrics_layout.addWidget(self.elapsed_metric, 2, 1)

        metrics_layout.addWidget(QLabel("Bottom/Top sim"), 3, 0)
        metrics_layout.addWidget(self.bottom_top_metric, 3, 1)
        metrics_layout.addWidget(QLabel("Full-frame sim"), 4, 0)
        metrics_layout.addWidget(self.full_metric, 4, 1)
        metrics_layout.addWidget(QLabel("Estimated motion"), 5, 0)
        metrics_layout.addWidget(self.motion_metric, 5, 1)
        metrics_layout.addWidget(QLabel("Overlap sim"), 6, 0)
        metrics_layout.addWidget(self.overlap_metric, 6, 1)

        metrics_layout.setColumnStretch(1, 1)
        right.addWidget(metrics_box)
        right.addStretch(1)

        self._toggle_mode()

    def _apply_styles(self) -> None:
        self.app.setStyleSheet(
            """
            QWidget {
              background: #11151a;
              color: #e6edf3;
              font-size: 13px;
            }
            QLabel#title {
              font-size: 22px;
              font-weight: 700;
              color: #f8fafc;
            }
            QLabel#subtitle {
              color: #9fb0c3;
              margin-bottom: 2px;
            }
            QFrame#card, QGroupBox#box {
              background: #171d26;
              border: 1px solid #2e3746;
              border-radius: 0px;
              margin-top: 2px;
            }
            QGroupBox#box {
              padding-top: 14px;
              font-weight: 600;
            }
            QGroupBox#box::title {
              subcontrol-origin: margin;
              left: 8px;
              padding: 0 4px;
              color: #c8d4e2;
            }
            QLineEdit, QComboBox, QTextEdit, QLabel#preview {
              background: #0d1117;
              border: 1px solid #2e3746;
              border-radius: 0px;
              padding: 6px;
              selection-background-color: #2b63c7;
            }
            QLabel#preview {
              padding: 0px;
            }
            QPushButton {
              background: #2a3342;
              border: 1px solid #3f4d63;
              border-radius: 0px;
              padding: 6px 10px;
              font-weight: 600;
            }
            QPushButton:hover {
              background: #344156;
            }
            QPushButton:disabled {
              background: #242d3a;
              color: #8292a6;
            }
            QPushButton#primary {
              background: #2b63c7;
              border-color: #2b63c7;
              color: #ffffff;
            }
            QPushButton#primary:hover {
              background: #2457ae;
            }
            QPushButton#danger {
              background: #b63e3e;
              border-color: #b63e3e;
              color: #ffffff;
            }
            QPushButton#danger:hover {
              background: #9d3636;
            }
            QProgressBar {
              border: 1px solid #2e3746;
              border-radius: 0px;
              background: #0d1117;
              text-align: center;
            }
            QProgressBar::chunk {
              background: #2b63c7;
              border-radius: 0px;
            }
            """
        )

    @staticmethod
    def _default_output() -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path.cwd() / f"wearcapture_{ts}.png"

    def _append_log(self, line: str) -> None:
        self.logs.append(line)
        self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())

    @staticmethod
    def _fmt_optional_float(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:.4f}"

    @staticmethod
    def _fmt_elapsed(elapsed: float) -> str:
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        minutes = int(elapsed // 60)
        seconds = elapsed - (minutes * 60)
        return f"{minutes}m {seconds:.1f}s"

    def _set_preview_from_png(self, preview_png: bytes | None) -> None:
        if not preview_png:
            return

        image = QImage.fromData(preview_png, "PNG")
        if image.isNull():
            return

        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)

    def _reset_live_metrics(self) -> None:
        self.frames_metric.setText("0")
        self.swipes_metric.setText("0")
        self.elapsed_metric.setText("0.0s")
        self.bottom_top_metric.setText("--")
        self.full_metric.setText("--")
        self.motion_metric.setText("--")
        self.overlap_metric.setText("--")
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("No preview yet")

    def _update_live_progress(self, progress: CaptureProgress) -> None:
        self.frames_metric.setText(str(progress.frames_captured))
        self.swipes_metric.setText(str(progress.swipes_performed))
        self.elapsed_metric.setText(self._fmt_elapsed(progress.elapsed_sec))

        self.bottom_top_metric.setText(self._fmt_optional_float(progress.bottom_top_similarity))
        self.full_metric.setText(self._fmt_optional_float(progress.full_similarity))
        self.motion_metric.setText("--" if progress.estimated_motion_px is None else f"{progress.estimated_motion_px}px")
        self.overlap_metric.setText(self._fmt_optional_float(progress.overlap_similarity))

        self.progress.setValue(min(progress.swipes_performed, self.current_max_swipes))
        self._set_preview_from_png(progress.preview_png)

        if progress.phase == "stopping":
            self.status_label.setText("Stopping and saving...")

    def _reload_profiles(self, selected_name: str | None = None) -> None:
        profiles = load_profiles(self.profile_path)
        self.profile_map = {profile.name.lower(): profile for profile in profiles}

        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(profile.name)

        target = selected_name or ""
        if target:
            idx = self.profile_combo.findText(target)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)

    def _selected_profile(self) -> CaptureProfile | None:
        return self.profile_map.get(self.profile_combo.currentText().strip().lower())

    def _apply_profile_to_form(self, profile: CaptureProfile) -> None:
        cfg = profile.config

        if "simple_mode" in cfg:
            self.simple_radio.setChecked(bool(cfg["simple_mode"]))
            self.advanced_radio.setChecked(not bool(cfg["simple_mode"]))

        if "swipe_x1" in cfg:
            self.swipe_x1_input.setText("" if cfg["swipe_x1"] is None else str(cfg["swipe_x1"]))
        if "swipe_y1" in cfg:
            self.swipe_y1_input.setText("" if cfg["swipe_y1"] is None else str(cfg["swipe_y1"]))
        if "swipe_x2" in cfg:
            self.swipe_x2_input.setText("" if cfg["swipe_x2"] is None else str(cfg["swipe_x2"]))
        if "swipe_y2" in cfg:
            self.swipe_y2_input.setText("" if cfg["swipe_y2"] is None else str(cfg["swipe_y2"]))

        if "swipe_duration_ms" in cfg:
            self.swipe_duration_input.setText(str(cfg["swipe_duration_ms"]))
        if "scroll_delay_ms" in cfg:
            self.scroll_delay_input.setText(str(cfg["scroll_delay_ms"]))
        if "similarity_threshold" in cfg:
            self.similarity_input.setText(str(cfg["similarity_threshold"]))
        if "max_swipes" in cfg:
            self.max_swipes_input.setText(str(cfg["max_swipes"]))
        if "circular_mask" in cfg:
            self.circular_checkbox.setChecked(bool(cfg["circular_mask"]))

    def _apply_selected_profile(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return
        self._apply_profile_to_form(profile)
        self._append_log(f"Applied profile '{profile.name}'")

    def _save_current_profile(self) -> None:
        name, ok = QInputDialog.getText(self.window, "Save Profile", "Profile name")
        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.information(self.window, "WearCapture", "Profile name cannot be empty")
            return

        try:
            cfg = self._build_config()
            cfg.validate()
        except Exception as exc:
            QMessageBox.critical(self.window, "Invalid Configuration", str(exc))
            return

        serial = self.device_combo.currentText().strip()
        model_regex: str | None = None
        display_size: tuple[int, int] | None = None
        if serial:
            for dev in self.adb.list_devices():
                if dev.serial == serial:
                    raw_model = extract_model_from_details(dev.details)
                    if raw_model:
                        model_regex = f"^{re.escape(raw_model)}$"
                    break
            display_size = self.adb.get_display_size(serial)

        path = upsert_profile(
            name=name,
            description=f"Saved from UI ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            config=config_to_profile_config(cfg),
            model_regex=model_regex,
            display_size=display_size,
            path=self.profile_path,
        )
        self._reload_profiles(selected_name=name)
        self._append_log(f"Saved profile '{name}' to {path}")

    def _import_profile(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self.window,
            "Import Profile",
            str(Path.cwd()),
            "JSON Files (*.json)",
        )
        if not selected:
            return

        profile = import_profile(Path(selected), path=self.profile_path)
        self._reload_profiles(selected_name=profile.name)
        self._append_log(f"Imported profile '{profile.name}' from {selected}")

    def _export_selected_profile(self) -> None:
        profile = self._selected_profile()
        if not profile:
            return

        selected, _ = QFileDialog.getSaveFileName(
            self.window,
            "Export Profile",
            str(Path.cwd() / f"{profile.name}.json"),
            "JSON Files (*.json)",
        )
        if not selected:
            return

        out = export_profile(profile, Path(selected))
        self._append_log(f"Exported profile '{profile.name}' to {out}")

    def _auto_suggest_profile_for_device(self) -> None:
        serial = self.device_combo.currentText().strip()
        if not serial:
            return

        profile = suggest_profile_for_serial(self.adb, serial, self.profile_path)
        if not profile:
            return

        idx = self.profile_combo.findText(profile.name)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
            self._apply_profile_to_form(profile)
            self._append_log(f"Suggested profile '{profile.name}' for {serial}")

    def _refresh_devices(self) -> None:
        try:
            devices = [d for d in self.adb.list_devices() if d.state == "device"]
        except Exception as exc:
            self._append_log(f"Device refresh failed: {exc}")
            return

        current = self.device_combo.currentText()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for dev in devices:
            self.device_combo.addItem(dev.serial)

        if devices:
            idx = self.device_combo.findText(current)
            self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._append_log("Detected devices: " + ", ".join(d.serial for d in devices))
        else:
            self._append_log("No online ADB devices found.")
        self.device_combo.blockSignals(False)

        if devices:
            self._auto_suggest_profile_for_device()

    def _on_device_changed(self, _text: str) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._auto_suggest_profile_for_device()

    def _browse_output(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self.window,
            "Save PNG",
            self.output_input.text(),
            "PNG Files (*.png)",
        )
        if selected:
            self.output_input.setText(selected)

    def _toggle_mode(self) -> None:
        self.advanced_box.setEnabled(self.advanced_radio.isChecked())

    @staticmethod
    def _int_or_none(value: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        return int(value)

    def _build_config(self) -> CaptureConfig:
        return CaptureConfig(
            output_path=Path(self.output_input.text().strip()),
            serial=self.device_combo.currentText().strip() or None,
            simple_mode=self.simple_radio.isChecked(),
            swipe_x1=self._int_or_none(self.swipe_x1_input.text()),
            swipe_y1=self._int_or_none(self.swipe_y1_input.text()),
            swipe_x2=self._int_or_none(self.swipe_x2_input.text()),
            swipe_y2=self._int_or_none(self.swipe_y2_input.text()),
            swipe_duration_ms=int(self.swipe_duration_input.text().strip() or "300"),
            scroll_delay_ms=int(self.scroll_delay_input.text().strip() or "450"),
            similarity_threshold=float(self.similarity_input.text().strip() or "0.995"),
            max_swipes=int(self.max_swipes_input.text().strip() or "24"),
            circular_mask=self.circular_checkbox.isChecked(),
        )

    def _set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.status_label.setText("Capturing..." if running else "Idle")
        self.progress.setRange(0, self.current_max_swipes)
        if not running:
            self.progress.setValue(0)

    def _start_capture(self) -> None:
        if self.worker and self.worker.is_alive():
            QMessageBox.information(self.window, "WearCapture", "Capture is already running")
            return

        try:
            cfg = self._build_config()
            cfg.validate()
        except Exception as exc:
            QMessageBox.critical(self.window, "Invalid Configuration", str(exc))
            return

        self.current_max_swipes = cfg.max_swipes
        self.progress.setRange(0, self.current_max_swipes)
        self._reset_live_metrics()
        self.stop_event = threading.Event()
        self._set_running_state(True)
        self._append_log("Starting capture...")

        def _work() -> None:
            try:
                result = self.engine.capture(
                    cfg,
                    log_fn=lambda m: self.event_queue.put(("log", m)),
                    stop_event=self.stop_event,
                    progress_fn=lambda p: self.event_queue.put(("progress", p)),
                )
                self.event_queue.put(("log", f"Capture done: {result.output_path}"))
                self.event_queue.put(
                    (
                        "log",
                        f"Frames={result.frames_captured}, Swipes={result.swipes_performed}, Stop='{result.stop_reason}'",
                    )
                )
            except Exception as exc:  # pragma: no cover - UI thread boundary
                self.event_queue.put(("log", f"Capture failed: {exc}"))
            finally:
                self.event_queue.put(("done", None))

        self.worker = threading.Thread(target=_work, daemon=True)
        self.worker.start()

    def _stop_capture(self) -> None:
        if not self.worker or not self.worker.is_alive() or not self.stop_event:
            return

        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping and saving...")
        self.stop_event.set()
        self._append_log("Stop requested by user. Finishing current step and saving partial result...")

    def _drain_events(self) -> None:
        try:
            while True:
                event_type, payload = self.event_queue.get_nowait()
                if event_type == "done":
                    self._set_running_state(False)
                    self.stop_event = None
                elif event_type == "log":
                    self._append_log(str(payload))
                elif event_type == "progress":
                    self._update_live_progress(payload)
        except queue.Empty:
            pass

    def run(self) -> None:
        self.window.show()
        self.app.exec()
