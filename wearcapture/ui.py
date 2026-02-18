from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
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
from .capture_engine import WearCaptureEngine
from .config import CaptureConfig


class WearCaptureApp:
    def __init__(self, adb_path: str = "adb"):
        self.adb = AdbClient(adb_path=adb_path)
        self.engine = WearCaptureEngine(adb_client=self.adb)

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.window = QMainWindow()
        self.window.setWindowTitle("WearCapture Studio")
        self.window.resize(980, 760)
        self.window.setMinimumSize(860, 640)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None

        self._build_ui()
        self._apply_styles()
        self._refresh_devices()

        self.log_timer = QTimer(self.window)
        self.log_timer.setInterval(120)
        self.log_timer.timeout.connect(self._drain_logs)
        self.log_timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        self.window.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel("WearCapture Studio")
        title.setObjectName("title")
        subtitle = QLabel("Wear OS long screenshots over local ADB")
        subtitle.setObjectName("subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        top_card = QFrame()
        top_card.setObjectName("card")
        top_grid = QGridLayout(top_card)
        top_grid.setContentsMargins(14, 14, 14, 14)
        top_grid.setHorizontalSpacing(10)
        top_grid.setVerticalSpacing(10)

        top_grid.addWidget(QLabel("Device"), 0, 0)
        self.device_combo = QComboBox()
        self.device_combo.setEditable(False)
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

        top_grid.setColumnStretch(1, 1)
        outer.addWidget(top_card)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
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
        outer.addLayout(mode_row)

        common_box = QGroupBox("Common Controls")
        common_box.setObjectName("box")
        common_form = QFormLayout(common_box)
        common_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        common_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        self.scroll_delay_input = QLineEdit("450")
        self.similarity_input = QLineEdit("0.995")
        self.max_swipes_input = QLineEdit("24")
        self.circular_checkbox = QCheckBox("Circular export mask")

        common_form.addRow("Scroll delay (ms)", self.scroll_delay_input)
        common_form.addRow("Similarity threshold", self.similarity_input)
        common_form.addRow("Max swipe count", self.max_swipes_input)
        common_form.addRow("", self.circular_checkbox)

        outer.addWidget(common_box)

        self.advanced_box = QGroupBox("Advanced Controls")
        self.advanced_box.setObjectName("box")
        adv_form = QFormLayout(self.advanced_box)
        adv_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        adv_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

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

        outer.addWidget(self.advanced_box)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Start Capture")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_capture)

        self.stop_button = QPushButton("Stop & Save")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_capture)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("status")

        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.status_label)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        logs_box = QGroupBox("Logs")
        logs_box.setObjectName("box")
        logs_layout = QVBoxLayout(logs_box)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        logs_layout.addWidget(self.logs)
        outer.addWidget(logs_box, 1)

        self._toggle_mode()

    def _apply_styles(self) -> None:
        self.app.setStyleSheet(
            """
            QWidget {
              background: #0f141b;
              color: #e6edf3;
              font-size: 13px;
            }
            QLabel#title {
              font-size: 24px;
              font-weight: 700;
              color: #f0f6fc;
            }
            QLabel#subtitle {
              color: #94a3b8;
              margin-bottom: 4px;
            }
            QFrame#card, QGroupBox#box {
              background: #151c26;
              border: 1px solid #2b3646;
              border-radius: 10px;
              margin-top: 4px;
            }
            QGroupBox#box {
              padding-top: 14px;
              font-weight: 600;
            }
            QGroupBox#box::title {
              subcontrol-origin: margin;
              left: 10px;
              padding: 0 4px;
              color: #bcd0e8;
            }
            QLineEdit, QComboBox, QTextEdit {
              background: #0b1119;
              border: 1px solid #2b3646;
              border-radius: 8px;
              padding: 6px 8px;
              selection-background-color: #2f6dd6;
            }
            QComboBox::drop-down {
              border: none;
              width: 20px;
            }
            QRadioButton, QCheckBox, QLabel#status {
              color: #d7e2f0;
            }
            QPushButton {
              background: #2d394a;
              border: 1px solid #3f5068;
              border-radius: 8px;
              padding: 7px 13px;
              font-weight: 600;
            }
            QPushButton:hover {
              background: #34445a;
            }
            QPushButton:disabled {
              background: #222b38;
              color: #7f90a6;
            }
            QPushButton#primary {
              background: #2f6dd6;
              border-color: #2f6dd6;
              color: white;
            }
            QPushButton#primary:hover {
              background: #265fbd;
            }
            QPushButton#danger {
              background: #c94040;
              border-color: #c94040;
              color: white;
            }
            QPushButton#danger:hover {
              background: #af3737;
            }
            QProgressBar {
              border: 1px solid #2b3646;
              border-radius: 8px;
              background: #0b1119;
              text-align: center;
              color: #9fb0c5;
            }
            QProgressBar::chunk {
              border-radius: 8px;
              background: #2f6dd6;
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

    def _refresh_devices(self) -> None:
        try:
            devices = [d for d in self.adb.list_devices() if d.state == "device"]
        except Exception as exc:
            self._append_log(f"Device refresh failed: {exc}")
            return

        current = self.device_combo.currentText()
        self.device_combo.clear()
        for dev in devices:
            self.device_combo.addItem(dev.serial)

        if devices:
            index = self.device_combo.findText(current)
            self.device_combo.setCurrentIndex(index if index >= 0 else 0)
            self._append_log("Detected devices: " + ", ".join(d.serial for d in devices))
        else:
            self._append_log("No online ADB devices found.")

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
        advanced = self.advanced_radio.isChecked()
        self.advanced_box.setEnabled(advanced)

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
        if running:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
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

        self.stop_event = threading.Event()
        self._set_running_state(True)
        self._append_log("Starting capture...")

        def _work() -> None:
            try:
                result = self.engine.capture(cfg, log_fn=self.log_queue.put, stop_event=self.stop_event)
                self.log_queue.put(f"Capture done: {result.output_path}")
                self.log_queue.put(
                    f"Frames={result.frames_captured}, Swipes={result.swipes_performed}, Stop='{result.stop_reason}'"
                )
            except Exception as exc:  # pragma: no cover - UI thread boundary
                self.log_queue.put(f"Capture failed: {exc}")
            finally:
                self.log_queue.put("__DONE__")

        self.worker = threading.Thread(target=_work, daemon=True)
        self.worker.start()

    def _stop_capture(self) -> None:
        if not self.worker or not self.worker.is_alive() or not self.stop_event:
            return

        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping and saving...")
        self.stop_event.set()
        self._append_log("Stop requested by user. Finishing current step and saving partial result...")

    def _drain_logs(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "__DONE__":
                    self._set_running_state(False)
                    self.stop_event = None
                else:
                    self._append_log(item)
        except queue.Empty:
            pass

    def run(self) -> None:
        self.window.show()
        self.app.exec()
