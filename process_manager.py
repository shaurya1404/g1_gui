"""
Process lifecycle management.
Each ManagedProcess wraps a subprocess.Popen in a QThread that
streams stdout/stderr line-by-line back to the GUI via Qt signals.
"""

import os
import signal
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal, QObject


class OutputReader(QThread):
    """Reads stdout from a Popen process and emits each line."""
    line_ready = pyqtSignal(str)
    finished = pyqtSignal(int)  # exit code

    def __init__(self, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self._process = process

    def run(self):
        try:
            for raw_line in iter(self._process.stdout.readline, ""):
                if raw_line:
                    self.line_ready.emit(raw_line.rstrip("\n"))
                if self._process.poll() is not None:
                    break
            # Drain remaining output
            remaining = self._process.stdout.read()
            if remaining:
                for line in remaining.splitlines():
                    self.line_ready.emit(line)
        except Exception as e:
            self.line_ready.emit(f"[reader error] {e}")

        exit_code = self._process.wait()
        self.finished.emit(exit_code)


class ManagedProcess(QObject):
    """
    Manages a single subprocess: start, stop, and stdout streaming.
    """
    output = pyqtSignal(str)           # each line of stdout/stderr
    state_changed = pyqtSignal(str)    # "idle" | "running" | "error" | "stopped"

    def __init__(self, name: str, activate_cmd: str, run_cmd: str, cwd: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._activate_cmd = activate_cmd
        self._run_cmd = run_cmd
        self._cwd = cwd
        self._process: subprocess.Popen | None = None
        self._reader: OutputReader | None = None
        self._state = "idle"

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, s: str):
        self._state = s
        self.state_changed.emit(s)

    def start(self):
        if self._state == "running":
            self.output.emit(f"[{self.name}] Already running.")
            return

        full_cmd = f"bash -c '{self._activate_cmd} && cd {self._cwd} && {self._run_cmd}'"
        self.output.emit(f"[{self.name}] Starting…")
        self.output.emit(f"  cwd: {self._cwd}")
        self.output.emit(f"  cmd: {self._run_cmd}")
        self.output.emit("")

        try:
            self._process = subprocess.Popen(
                full_cmd,
                shell=True,
                cwd=self._cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,  # so we can kill the whole process group
            )
        except Exception as e:
            self.output.emit(f"[{self.name}] Failed to start: {e}")
            self._set_state("error")
            return

        self._reader = OutputReader(self._process)
        self._reader.line_ready.connect(lambda line: self.output.emit(line))
        self._reader.finished.connect(self._on_finished)
        self._reader.start()
        self._set_state("running")

    def stop(self):
        if self._process is None:
            return
        self.output.emit(f"[{self.name}] Stopping…")
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            self.output.emit(f"[{self.name}] Error stopping: {e}")
        self._set_state("stopped")

    def _on_finished(self, exit_code: int):
        if self._state == "stopped":
            self.output.emit(f"[{self.name}] Process terminated.")
        elif exit_code == 0:
            self.output.emit(f"[{self.name}] Exited normally (code 0).")
            self._set_state("idle")
        else:
            self.output.emit(f"[{self.name}] Exited with code {exit_code}.")
            self._set_state("error")
        self._process = None
        self._reader = None

    def is_running(self) -> bool:
        return self._state == "running"
