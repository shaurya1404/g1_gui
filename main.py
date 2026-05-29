#!/usr/bin/env python3
"""
G1 GR00T Control GUI
=====================
Desktop application for initializing and managing the Unitree G1 humanoid
robot's Whole Body Control (locomotion) and XR Teleoperation (hands) systems.

Run:  python main.py
"""

import sys
import os
import yaml
from functools import partial

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QPushButton, QLabel, QTextEdit, QComboBox,
    QSplitter, QFrame, QSizePolicy, QMessageBox, QLineEdit,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCursor, QIcon, QPalette

from process_manager import ManagedProcess
from preflight import (
    check_usb_adapter, fix_routing, verify_routing,
    ping_robot, check_cyclonedds,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
STYLE = """
QMainWindow {
    background-color: #1a1b26;
}
QGroupBox {
    font-weight: bold;
    font-size: 13px;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 18px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #3b4261;
    color: #c0caf5;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #545c7e;
}
QPushButton:disabled {
    background-color: #292e42;
    color: #565f89;
}
QPushButton[cssClass="start"] {
    background-color: #1a8a4a;
}
QPushButton[cssClass="start"]:hover {
    background-color: #1fb85e;
}
QPushButton[cssClass="stop"] {
    background-color: #9d3040;
}
QPushButton[cssClass="stop"]:hover {
    background-color: #c53b4e;
}
QPushButton[cssClass="fix"] {
    background-color: #e0a020;
    color: #1a1b26;
}
QTextEdit {
    background-color: #16161e;
    color: #a9b1d6;
    border: 1px solid #3b4261;
    border-radius: 4px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 4px;
}
QLabel {
    color: #c0caf5;
    font-size: 12px;
}
QLabel[cssClass="heading"] {
    font-size: 18px;
    font-weight: bold;
    color: #7aa2f7;
}
QLabel[cssClass="status-pass"] { color: #9ece6a; font-weight: bold; }
QLabel[cssClass="status-fail"] { color: #f7768e; font-weight: bold; }
QLabel[cssClass="status-warn"] { color: #e0af68; font-weight: bold; }
QLabel[cssClass="status-idle"] { color: #565f89; }
QLabel[cssClass="status-running"] { color: #9ece6a; font-weight: bold; }
QLabel[cssClass="status-error"] { color: #f7768e; font-weight: bold; }
QLabel[cssClass="status-stopped"] { color: #e0af68; font-weight: bold; }
QComboBox {
    background-color: #3b4261;
    color: #c0caf5;
    border: 1px solid #545c7e;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background-color: #1a1b26;
    color: #c0caf5;
    selection-background-color: #3b4261;
}
QLineEdit {
    background-color: #16161e;
    color: #a9b1d6;
    border: 1px solid #3b4261;
    border-radius: 4px;
    padding: 4px 6px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 11px;
}
QSplitter::handle {
    background-color: #3b4261;
}
"""


# ---------------------------------------------------------------------------
# Preflight check worker (runs in a thread so GUI doesn't freeze)
# ---------------------------------------------------------------------------
class PreflightWorker(QThread):
    result_ready = pyqtSignal(str, bool, str)  # check_name, passed, message

    def __init__(self, check_name: str, func, args: tuple, parent=None):
        super().__init__(parent)
        self.check_name = check_name
        self.func = func
        self.args = args

    def run(self):
        passed, msg = self.func(*self.args)
        self.result_ready.emit(self.check_name, passed, msg)


# ---------------------------------------------------------------------------
# Process Card widget
# ---------------------------------------------------------------------------
class ProcessCard(QGroupBox):
    """One card per managed process: status, start/stop, editable command, terminal."""

    def __init__(self, proc_key: str, proc_cfg: dict, config: dict, parent=None):
        super().__init__(proc_cfg["name"], parent)
        self.proc_key = proc_key
        self.proc_cfg = proc_cfg
        self.config = config
        self._depends_on: list[str] = proc_cfg.get("depends_on", [])

        env_key = proc_cfg["env"]
        activate_cmd = config["environments"][env_key]["activate"]
        cwd = config["paths"][proc_cfg["cwd_key"]]

        # Resolve placeholders in command
        raw_cmd = proc_cfg["command"]
        cmd = raw_cmd.format(
            interface=config["network"]["interface"],
            img_server_ip=config["network"]["img_server_ip"],
        )

        self._managed = ManagedProcess(
            name=proc_cfg["name"],
            activate_cmd=activate_cmd,
            run_cmd=cmd,
            cwd=cwd,
        )

        self._build_ui(env_key, cwd, cmd)
        self._connect_signals()

    def _build_ui(self, env_key: str, cwd: str, cmd: str):
        layout = QVBoxLayout(self)

        # -- Info row
        info_row = QHBoxLayout()
        env_label = QLabel(f"env: {env_key}")
        env_label.setStyleSheet("color: #bb9af7; font-size: 11px;")
        self._status_label = QLabel("● IDLE")
        self._status_label.setProperty("cssClass", "status-idle")
        info_row.addWidget(env_label)
        info_row.addStretch()
        info_row.addWidget(self._status_label)
        layout.addLayout(info_row)

        # -- Editable command
        self._cmd_edit = QLineEdit(cmd)
        self._cmd_edit.setToolTip("Edit the command before starting")
        layout.addWidget(self._cmd_edit)

        # -- Buttons
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setProperty("cssClass", "start")
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setProperty("cssClass", "stop")
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # -- Terminal output
        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setMinimumHeight(100)
        self._terminal.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._terminal)

    def _connect_signals(self):
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        self._managed.output.connect(self._append_output)
        self._managed.state_changed.connect(self._on_state_changed)

    def _on_start(self):
        # Update command from the edit field in case user changed it
        new_cmd = self._cmd_edit.text().strip()
        if new_cmd:
            self._managed._run_cmd = new_cmd
        self._managed.start()

    def _on_stop(self):
        self._managed.stop()

    def _append_output(self, line: str):
        self._terminal.append(line)
        # Auto-scroll to bottom
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._terminal.setTextCursor(cursor)

    def _on_state_changed(self, state: str):
        state_display = {
            "idle": ("● IDLE", "status-idle"),
            "running": ("● RUNNING", "status-running"),
            "error": ("● ERROR", "status-error"),
            "stopped": ("● STOPPED", "status-stopped"),
        }
        text, css_class = state_display.get(state, ("● ???", "status-idle"))
        self._status_label.setText(text)
        self._status_label.setProperty("cssClass", css_class)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        is_running = state == "running"
        self._start_btn.setEnabled(not is_running)
        self._stop_btn.setEnabled(is_running)
        self._cmd_edit.setEnabled(not is_running)

    @property
    def depends_on(self) -> list[str]:
        return self._depends_on

    def is_running(self) -> bool:
        return self._managed.is_running()

    def set_start_enabled(self, enabled: bool):
        """External dependency enforcement — disable start if deps not met."""
        if self._managed.is_running():
            return  # don't re-enable start while running
        self._start_btn.setEnabled(enabled)

    def clear_terminal(self):
        self._terminal.clear()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("G1 GR00T Control — Deepak-System")
        self.setMinimumSize(960, 760)
        self.resize(1100, 850)

        self._config = load_config()
        self._preflight_workers: list[PreflightWorker] = []
        self._process_cards: dict[str, ProcessCard] = {}

        self._build_ui()
        self.setStyleSheet(STYLE)

        # Periodically enforce dependency rules
        self._dep_timer = QTimer(self)
        self._dep_timer.timeout.connect(self._enforce_dependencies)
        self._dep_timer.start(500)

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)

        # Title
        title = QLabel("G1 GR00T Humanoid — Control Dashboard")
        title.setProperty("cssClass", "heading")
        title.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(title)

        # Splitter: left = preflight + mode, right = process cards
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)

        # -- Left panel --
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(self._build_preflight_panel())
        left_layout.addWidget(self._build_mode_panel())
        left_layout.addStretch()

        splitter.addWidget(left)

        # -- Right panel: process cards --
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        proc_order = ["mixer", "wbc", "hand_driver", "teleop"]
        for key in proc_order:
            if key in self._config["processes"]:
                card = ProcessCard(key, self._config["processes"][key], self._config)
                self._process_cards[key] = card
                right_layout.addWidget(card)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root_layout.addWidget(splitter, stretch=1)

        # -- Bottom: global controls --
        bottom_row = QHBoxLayout()
        stop_all_btn = QPushButton("■  Stop All Processes")
        stop_all_btn.setProperty("cssClass", "stop")
        stop_all_btn.clicked.connect(self._stop_all)
        clear_btn = QPushButton("Clear All Terminals")
        clear_btn.clicked.connect(self._clear_all)
        bottom_row.addStretch()
        bottom_row.addWidget(clear_btn)
        bottom_row.addWidget(stop_all_btn)
        root_layout.addLayout(bottom_row)

    # -- Preflight panel --
    def _build_preflight_panel(self) -> QGroupBox:
        group = QGroupBox("Preflight Checks")
        layout = QVBoxLayout(group)

        self._preflight_labels: dict[str, QLabel] = {}
        checks = [
            ("usb_adapter", "USB Adapter"),
            ("routing", "Route Verification"),
            ("ping", "Robot Ping"),
            ("cyclonedds", "CycloneDDS Topics"),
        ]
        for key, label_text in checks:
            row = QHBoxLayout()
            name_label = QLabel(label_text)
            name_label.setMinimumWidth(130)
            status_label = QLabel("—  not checked")
            status_label.setProperty("cssClass", "status-idle")
            status_label.setWordWrap(True)
            self._preflight_labels[key] = status_label
            row.addWidget(name_label)
            row.addWidget(status_label, stretch=1)
            layout.addLayout(row)

        # Buttons
        btn_row = QHBoxLayout()
        run_btn = QPushButton("Run All Checks")
        run_btn.clicked.connect(self._run_preflight)
        self._fix_route_btn = QPushButton("Fix Routing")
        self._fix_route_btn.setProperty("cssClass", "fix")
        self._fix_route_btn.setEnabled(False)
        self._fix_route_btn.clicked.connect(self._fix_route)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(self._fix_route_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return group

    # -- Mode panel --
    def _build_mode_panel(self) -> QGroupBox:
        group = QGroupBox("Deployment Mode")
        layout = QVBoxLayout(group)

        self._mode_combo = QComboBox()
        for mode_key, mode_cfg in self._config["modes"].items():
            self._mode_combo.addItem(mode_cfg["label"], mode_key)

        self._mode_desc = QLabel("")
        self._mode_desc.setWordWrap(True)
        self._mode_desc.setStyleSheet("color: #7dcfff; font-size: 11px;")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        launch_btn = QPushButton("▶  Launch Mode")
        launch_btn.setProperty("cssClass", "start")
        launch_btn.clicked.connect(self._launch_mode)

        layout.addWidget(self._mode_combo)
        layout.addWidget(self._mode_desc)
        layout.addWidget(launch_btn)

        # Trigger initial description
        self._on_mode_changed(0)

        return group

    # -----------------------------------------------------------------------
    # Preflight logic
    # -----------------------------------------------------------------------
    def _run_preflight(self):
        net = self._config["network"]

        checks = [
            ("usb_adapter", check_usb_adapter, (net["usb_adapter"],)),
            ("routing", verify_routing, (net["robot_ip"], net["interface"])),
            ("ping", ping_robot, (net["robot_ip"], net["interface"])),
            ("cyclonedds", check_cyclonedds, (self._config["paths"]["cyclonedds_setup"],)),
        ]

        for key, func, args in checks:
            lbl = self._preflight_labels[key]
            lbl.setText("⏳  checking…")
            lbl.setProperty("cssClass", "status-warn")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

            worker = PreflightWorker(key, func, args)
            worker.result_ready.connect(self._on_preflight_result)
            self._preflight_workers.append(worker)
            worker.start()

    def _on_preflight_result(self, name: str, passed: bool, message: str):
        lbl = self._preflight_labels[name]
        prefix = "✓" if passed else "✗"
        lbl.setText(f"{prefix}  {message}")
        css = "status-pass" if passed else "status-fail"
        lbl.setProperty("cssClass", css)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

        # Enable fix-routing button if USB adapter check failed
        if name == "usb_adapter" and not passed:
            self._fix_route_btn.setEnabled(True)

    def _fix_route(self):
        net = self._config["network"]
        passed, msg = fix_routing(net["usb_adapter"], net["subnet"])
        status = "status-pass" if passed else "status-fail"
        self._preflight_labels["usb_adapter"].setText(f"{'✓' if passed else '✗'}  {msg}")
        self._preflight_labels["usb_adapter"].setProperty("cssClass", status)
        self._preflight_labels["usb_adapter"].style().unpolish(self._preflight_labels["usb_adapter"])
        self._preflight_labels["usb_adapter"].style().polish(self._preflight_labels["usb_adapter"])
        if passed:
            self._fix_route_btn.setEnabled(False)
            # Re-run routing check
            worker = PreflightWorker(
                "routing", verify_routing,
                (net["robot_ip"], net["interface"]),
            )
            worker.result_ready.connect(self._on_preflight_result)
            self._preflight_workers.append(worker)
            worker.start()

    # -----------------------------------------------------------------------
    # Mode selector
    # -----------------------------------------------------------------------
    def _on_mode_changed(self, index: int):
        mode_key = self._mode_combo.currentData()
        if mode_key and mode_key in self._config["modes"]:
            self._mode_desc.setText(self._config["modes"][mode_key]["description"])

    def _launch_mode(self):
        mode_key = self._mode_combo.currentData()
        if not mode_key:
            return
        mode = self._config["modes"][mode_key]
        proc_keys = mode["processes"]

        # Launch in dependency order (the list in config is already ordered)
        for key in proc_keys:
            card = self._process_cards.get(key)
            if card and not card.is_running():
                card._on_start()

    # -----------------------------------------------------------------------
    # Dependency enforcement
    # -----------------------------------------------------------------------
    def _enforce_dependencies(self):
        """Disable start buttons for processes whose dependencies aren't running."""
        for key, card in self._process_cards.items():
            deps_met = all(
                self._process_cards[dep].is_running()
                for dep in card.depends_on
                if dep in self._process_cards
            )
            card.set_start_enabled(deps_met)

    # -----------------------------------------------------------------------
    # Global controls
    # -----------------------------------------------------------------------
    def _stop_all(self):
        # Stop in reverse order
        for key in reversed(["mixer", "wbc", "hand_driver", "teleop"]):
            card = self._process_cards.get(key)
            if card and card.is_running():
                card._on_stop()

    def _clear_all(self):
        for card in self._process_cards.values():
            card.clear_terminal()

    def closeEvent(self, event):
        running = [c.proc_key for c in self._process_cards.values() if c.is_running()]
        if running:
            reply = QMessageBox.question(
                self,
                "Processes still running",
                f"These processes are still running:\n{', '.join(running)}\n\nStop all and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._stop_all()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("G1 GR00T Control")

    # Use fusion style for cross-platform consistency
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
