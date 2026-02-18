from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .adb import AdbClient
from .capture_engine import WearCaptureEngine
from .config import CaptureConfig


class WearCaptureApp:
    def __init__(self, adb_path: str = "adb"):
        self.adb = AdbClient(adb_path=adb_path)
        self.engine = WearCaptureEngine(adb_client=self.adb)

        self.root = tk.Tk()
        self.root.title("WearCapture Studio")
        self.root.geometry("900x700")
        self.root.minsize(840, 620)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None

        self._setup_style()
        self._build_ui()
        self._refresh_devices()
        self.root.after(120, self._drain_logs)

    def _setup_style(self) -> None:
        bg = "#0E1117"
        panel = "#151B23"
        panel_alt = "#1B2430"
        fg = "#E6EDF3"
        muted = "#97A6BA"
        accent = "#3B82F6"

        self.root.configure(bg=bg)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("AltPanel.TFrame", background=panel_alt)
        style.configure("App.TLabelframe", background=panel, foreground=fg, bordercolor="#2A3340")
        style.configure("App.TLabelframe.Label", background=panel, foreground=fg, font=("Segoe UI", 10, "bold"))
        style.configure("App.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 16, "bold"))
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI", 10))

        style.configure(
            "App.TEntry",
            fieldbackground="#0F1722",
            foreground=fg,
            insertcolor=fg,
            bordercolor="#2A3340",
            lightcolor="#2A3340",
            darkcolor="#2A3340",
            padding=6,
        )
        style.map("App.TEntry", fieldbackground=[("disabled", "#2B313A")], foreground=[("disabled", "#7E8B9A")])

        style.configure(
            "App.TCombobox",
            fieldbackground="#0F1722",
            background="#0F1722",
            foreground=fg,
            bordercolor="#2A3340",
            arrowsize=14,
            padding=6,
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", "#0F1722"), ("disabled", "#2B313A")],
            foreground=[("readonly", fg), ("disabled", "#7E8B9A")],
            selectbackground=[("readonly", "#0F1722")],
            selectforeground=[("readonly", fg)],
        )

        style.configure(
            "App.TButton",
            background="#2B3543",
            foreground=fg,
            bordercolor="#3B4658",
            lightcolor="#3B4658",
            darkcolor="#3B4658",
            padding=(10, 8),
            focusthickness=0,
        )
        style.map(
            "App.TButton",
            background=[("active", "#364155"), ("disabled", "#252C36")],
            foreground=[("disabled", "#718197")],
        )

        style.configure(
            "Primary.TButton",
            background=accent,
            foreground="#FFFFFF",
            bordercolor=accent,
            lightcolor=accent,
            darkcolor=accent,
            padding=(12, 9),
            focusthickness=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#2F6ED0"), ("disabled", "#2B3E63")],
            foreground=[("disabled", "#AFC6EF")],
        )

        style.configure(
            "Danger.TButton",
            background="#D14343",
            foreground="#FFFFFF",
            bordercolor="#D14343",
            lightcolor="#D14343",
            darkcolor="#D14343",
            padding=(12, 9),
            focusthickness=0,
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#B83838"), ("disabled", "#5B2C2C")],
            foreground=[("disabled", "#F0C1C1")],
        )

        style.configure("App.TRadiobutton", background=bg, foreground=fg, font=("Segoe UI", 10))

        style.configure("App.Horizontal.TProgressbar", troughcolor="#1C2330", background=accent, bordercolor="#1C2330")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="WearCapture Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Long screenshot capture for Wear OS via local ADB",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        top = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Device", style="App.TLabel").grid(row=0, column=0, sticky="w")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(top, textvariable=self.device_var, state="readonly", width=48, style="App.TCombobox")
        self.device_combo.grid(row=0, column=1, sticky="ew", padx=(8, 10))
        ttk.Button(top, text="Refresh", style="App.TButton", command=self._refresh_devices).grid(row=0, column=2, sticky="e")

        ttk.Label(top, text="Output", style="App.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.output_var = tk.StringVar(value=str(self._default_output()))
        ttk.Entry(top, textvariable=self.output_var, style="App.TEntry").grid(row=1, column=1, sticky="ew", padx=(8, 10), pady=(10, 0))
        ttk.Button(top, text="Browse", style="App.TButton", command=self._browse_output).grid(row=1, column=2, sticky="e", pady=(10, 0))

        top.columnconfigure(1, weight=1)

        mode_row = ttk.Frame(outer, style="App.TFrame")
        mode_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(mode_row, text="Mode", style="App.TLabel").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="simple")
        ttk.Radiobutton(mode_row, text="Simple", value="simple", variable=self.mode_var, style="App.TRadiobutton", command=self._toggle_mode).pack(side=tk.LEFT, padx=(10, 8))
        ttk.Radiobutton(mode_row, text="Advanced", value="advanced", variable=self.mode_var, style="App.TRadiobutton", command=self._toggle_mode).pack(side=tk.LEFT)

        body = ttk.Frame(outer, style="App.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        settings_panel = ttk.Frame(body, style="Panel.TFrame", padding=12)
        settings_panel.pack(fill=tk.X)

        common = ttk.LabelFrame(settings_panel, text="Common Controls", style="App.TLabelframe", padding=10)
        common.pack(fill=tk.X)

        self.scroll_delay_var = tk.StringVar(value="500")
        self.similarity_var = tk.StringVar(value="0.995")
        self.max_swipes_var = tk.StringVar(value="30")
        self.circular_var = tk.BooleanVar(value=False)

        self._add_labeled_entry(common, "Scroll delay (ms)", self.scroll_delay_var, 0)
        self._add_labeled_entry(common, "Similarity threshold", self.similarity_var, 1)
        self._add_labeled_entry(common, "Max swipe count", self.max_swipes_var, 2)
        ttk.Checkbutton(common, text="Circular export mask", variable=self.circular_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 2)
        )

        self.advanced = ttk.LabelFrame(settings_panel, text="Advanced Controls", style="App.TLabelframe", padding=10)
        self.advanced.pack(fill=tk.X, pady=(10, 0))

        self.swipe_x1_var = tk.StringVar()
        self.swipe_y1_var = tk.StringVar()
        self.swipe_x2_var = tk.StringVar()
        self.swipe_y2_var = tk.StringVar()
        self.swipe_duration_var = tk.StringVar(value="300")

        self._add_labeled_entry(self.advanced, "Swipe x1", self.swipe_x1_var, 0)
        self._add_labeled_entry(self.advanced, "Swipe y1", self.swipe_y1_var, 1)
        self._add_labeled_entry(self.advanced, "Swipe x2", self.swipe_x2_var, 2)
        self._add_labeled_entry(self.advanced, "Swipe y2", self.swipe_y2_var, 3)
        self._add_labeled_entry(self.advanced, "Swipe duration (ms)", self.swipe_duration_var, 4)

        action_bar = ttk.Frame(body, style="App.TFrame")
        action_bar.pack(fill=tk.X, pady=(12, 0))

        self.capture_btn = ttk.Button(action_bar, text="Start Capture", style="Primary.TButton", command=self._start_capture)
        self.capture_btn.pack(side=tk.LEFT)

        self.stop_btn = ttk.Button(action_bar, text="Stop & Save", style="Danger.TButton", command=self._stop_capture, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(action_bar, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=(14, 0))

        self.progress = ttk.Progressbar(body, mode="indeterminate", style="App.Horizontal.TProgressbar")
        self.progress.pack(fill=tk.X, pady=(10, 0))

        log_wrap = ttk.Frame(body, style="AltPanel.TFrame", padding=10)
        log_wrap.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        ttk.Label(log_wrap, text="Logs", style="App.TLabel").pack(anchor="w", pady=(0, 6))

        self.log_text = tk.Text(
            log_wrap,
            height=14,
            wrap=tk.WORD,
            bg="#0A0F17",
            fg="#C7D2E0",
            insertbackground="#C7D2E0",
            relief=tk.FLAT,
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground="#253042",
            highlightcolor="#253042",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self._toggle_mode()

    @staticmethod
    def _add_labeled_entry(parent: ttk.LabelFrame, label: str, var: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label, style="App.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(parent, textvariable=var, width=18, style="App.TEntry").grid(row=row, column=1, sticky="w", pady=5)

    @staticmethod
    def _default_output() -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path.cwd() / f"wearcapture_{ts}.png"

    def _append_log(self, line: str) -> None:
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)

    def _refresh_devices(self) -> None:
        try:
            devices = [d for d in self.adb.list_devices() if d.state == "device"]
        except Exception as exc:
            self._append_log(f"Device refresh failed: {exc}")
            return

        values = [d.serial for d in devices]
        self.device_combo["values"] = values
        if values:
            if self.device_var.get() not in values:
                self.device_combo.set(values[0])
            self._append_log(f"Detected devices: {', '.join(values)}")
        else:
            self.device_combo.set("")
            self._append_log("No online ADB devices found.")

    def _browse_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Save PNG",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile=Path(self.output_var.get()).name,
        )
        if selected:
            self.output_var.set(selected)

    def _toggle_mode(self) -> None:
        state = tk.NORMAL if self.mode_var.get() == "advanced" else tk.DISABLED
        for child in self.advanced.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state=state)

    def _int_or_none(self, value: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        return int(value)

    def _build_config(self) -> CaptureConfig:
        return CaptureConfig(
            output_path=Path(self.output_var.get()),
            serial=self.device_var.get().strip() or None,
            simple_mode=self.mode_var.get() != "advanced",
            swipe_x1=self._int_or_none(self.swipe_x1_var.get()),
            swipe_y1=self._int_or_none(self.swipe_y1_var.get()),
            swipe_x2=self._int_or_none(self.swipe_x2_var.get()),
            swipe_y2=self._int_or_none(self.swipe_y2_var.get()),
            swipe_duration_ms=int(self.swipe_duration_var.get().strip() or "300"),
            scroll_delay_ms=int(self.scroll_delay_var.get().strip() or "500"),
            similarity_threshold=float(self.similarity_var.get().strip() or "0.995"),
            max_swipes=int(self.max_swipes_var.get().strip() or "30"),
            circular_mask=self.circular_var.get(),
        )

    def _set_running_state(self, running: bool) -> None:
        self.capture_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_var.set("Capturing..." if running else "Idle")
        if running:
            self.progress.start(14)
        else:
            self.progress.stop()

    def _start_capture(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("WearCapture", "Capture is already running")
            return

        try:
            cfg = self._build_config()
            cfg.validate()
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc))
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
            except Exception as exc:
                self.log_queue.put(f"Capture failed: {exc}")
            finally:
                self.log_queue.put("__DONE__")

        self.worker = threading.Thread(target=_work, daemon=True)
        self.worker.start()

    def _stop_capture(self) -> None:
        if not self.worker or not self.worker.is_alive() or not self.stop_event:
            return
        self.status_var.set("Stopping and saving...")
        self.stop_btn.configure(state=tk.DISABLED)
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
        finally:
            self.root.after(120, self._drain_logs)

    def run(self) -> None:
        self.root.mainloop()
