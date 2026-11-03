"""PTY-backed child process: a real terminal device, not a pipe."""

from __future__ import annotations

import fcntl
import os
import pty
import signal
import struct
import termios
import threading

from PyQt6.QtCore import QObject, pyqtSignal


class PtyProcess(QObject):
    """Run ``argv`` on a pseudo-terminal and stream its output.

    Unlike a pipe, a PTY gives the child a controlling terminal, so job
    control (Ctrl+C / Ctrl+Z), ``isatty()``, window size queries and
    full-screen programs all behave like a normal terminal.
    """

    output = pyqtSignal(bytes)
    exited = pyqtSignal(int)

    def __init__(self, argv: tuple[str, ...], cwd: str, env: dict[str, str], rows: int, columns: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.argv = tuple(argv)
        self.cwd = cwd
        self.env = dict(env)
        self.rows = max(1, rows)
        self.columns = max(1, columns)
        self.pid: int | None = None
        self._fd: int | None = None
        self._lock = threading.Lock()
        self._finished = False
        self._closing = False
        self._reader: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Fork the child onto a fresh PTY and begin reading."""
        if self._fd is not None:
            return
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - executed in the child process
            try:
                os.chdir(self.cwd)
                os.execvpe(self.argv[0], list(self.argv), self.env)
            except BaseException as error:
                try:
                    message = f"[DeepTerminal] cannot start {' '.join(self.argv)}: {error}\r\n".encode("utf-8", "replace")
                    os.write(2, message)
                except OSError:
                    pass
                os._exit(127)
        self.pid = pid
        self._fd = fd
        self.resize(self.rows, self.columns)
        self._reader = threading.Thread(target=self._read_loop, name="deepterminal-pty", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        fd = self._fd
        if fd is None:
            return
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            except ValueError:
                break
            if not chunk:
                break
            self.output.emit(chunk)
        self._finish()

    def _finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            fd, self._fd = self._fd, None
            pid = self.pid
        try:
            if fd is not None:
                os.close(fd)
        except OSError:
            pass
        status = 0
        if pid is not None:
            try:
                _, status = os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                status = 0
        self.exited.emit(os.waitstatus_to_exitcode(status))

    def terminate(self) -> None:
        """Hang up the child, then make sure it cannot linger."""
        if self._finished:
            return
        self._closing = True
        pid = self.pid
        if pid is not None:
            try:
                os.killpg(os.getpgid(pid), signal.SIGHUP)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        with self._lock:
            fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        timer = threading.Timer(0.4, self._force_kill)
        timer.daemon = True
        timer.start()

    def _force_kill(self) -> None:
        if self._finished or self.pid is None:
            return
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGKILL)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        if self._finished or self.pid is None:
            return False
        try:
            os.kill(self.pid, 0)
        except OSError:
            return False
        return True

    # -- io --------------------------------------------------------------
    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            fd = self._fd
        if fd is None:
            return
        try:
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                if written <= 0:
                    break
                offset += written
        except OSError:
            pass

    def resize(self, rows: int, columns: int) -> None:
        """Tell the child the new character grid (SIGWINCH carries it)."""
        rows = max(1, int(rows))
        columns = max(1, int(columns))
        self.rows, self.columns = rows, columns
        with self._lock:
            fd = self._fd
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        except OSError:
            pass
