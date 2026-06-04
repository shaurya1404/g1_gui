"""
Process lifecycle management.
Each ManagedProcess wraps a subprocess in a pseudo-terminal (pty) so that
child scripts that read keyboard input directly (e.g. WBC control loop)
receive keystrokes sent via send_key().
"""

import os
import pty
import signal
import subprocess
import select
from PyQt5.QtCore import QThread, pyqtSignal, QObject


class PtyReader(QThread):
    """Reads output from the master side of a pty and emits each line."""
    line_ready = pyqtSignal(str)
    finished = pyqtSignal(int)  # exit code

    def __init__(self, master_fd: int, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self._master_fd = master_fd
        self._process = process
        self._running = True

    def run(self):
        buf = ""
        try:
            while self._running:
                # Wait for data or process exit
                ready, _, _ = select.select([self._master_fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(self._master_fd, 4096)
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        buf += text
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            self.line_ready.emit(line)
                    except OSError:
                        break
                if self._process.poll() is not None:
                    break
        except Exception as e:
            self.line_ready.emit(f"[reader error] {e}")

        # Emit any remaining partial line
        if buf.strip():
            self.line_ready.emit(buf)

        exit_code = self._process.wait()
        self.finished.emit(exit_code)

    def stop(self):
        self._running = False


class ManagedProcess(QObject):
    """
    Manages a single subprocess running inside a pty.
    Supports start, stop, stdout streaming, and sending keystrokes.
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
        self._reader: PtyReader | None = None
        self._master_fd: int | None = None
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

        full_cmd = f"{self._activate_cmd} && cd {self._cwd} && {self._run_cmd}"
        self.output.emit(f"[{self.name}] Starting…")
        self.output.emit(f"  cwd: {self._cwd}")
        self.output.emit(f"  cmd: {self._run_cmd}")
        self.output.emit("")

        try:
            # Create a pseudo-terminal pair
            master_fd, slave_fd = pty.openpty()

            self._process = subprocess.Popen(
                ["bash", "-c", full_cmd],
                cwd=self._cwd,
                stdout=slave_fd,
                stderr=slave_fd,
                stdin=slave_fd,
                preexec_fn=os.setsid,
            )

            # Close slave in parent — the child owns it
            os.close(slave_fd)
            self._master_fd = master_fd

        except Exception as e:
            self.output.emit(f"[{self.name}] Failed to start: {e}")
            self._set_state("error")
            return

        self._reader = PtyReader(master_fd, self._process)
        self._reader.line_ready.connect(lambda line: self.output.emit(line))
        self._reader.finished.connect(self._on_finished)
        self._reader.start()
        self._set_state("running")

    def stop(self):
        if self._process is None:
            return
        self.output.emit(f"[{self.name}] Stopping…")
        if self._reader:
            self._reader.stop()
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            self.output.emit(f"[{self.name}] Error stopping: {e}")
        # Clean up master fd
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        self._set_state("stopped")

    def send_key(self, key: str):
        """Send a keystroke to the process via the pty."""
        if self._master_fd is not None and self._state == "running":
            try:
                os.write(self._master_fd, key.encode("utf-8"))
                self.output.emit(f"[sent key: '{key}']")
            except OSError as e:
                self.output.emit(f"[send_key error] {e}")
        else:
            self.output.emit(f"[{self.name}] Not running — cannot send key.")

    def _on_finished(self, exit_code: int):
        # Clean up master fd
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

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
