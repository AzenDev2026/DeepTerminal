"""``codeout`` — DeepTerminal's fake "system boot" show, just for fun.

The Bash and PowerShell profiles define a tiny ``codeout`` function that
prints an invisible OSC marker. The terminal view catches that marker and
runs :class:`CodeoutRunner` client-side: a QTimer floods the screen with
colourful nonsense log lines at the chosen speed for the chosen time, and
every 60 lines the oldest 30 are deleted so the flood never piles up.

Tuning (command line wins over the config file):

* ``codeout``            -> config file settings
* ``codeout 3s``         -> run for 3 seconds
* ``codeout fast``       -> fast speed, default time
* ``codeout 3s super``   -> both
* speeds: ``slow``, ``normal``, ``fast``, ``super``
* ``codeout stop``       -> stop the current show
* ``codeout conf``       -> print the config file path
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

#: OSC marker the shell-side ``codeout`` function prints. pyte silently
#: swallows unknown OSC sequences, so nothing of this ever reaches the screen.
TRIGGER_RE = re.compile(rb"\x1b\]663;codeout([^\x07]*)\x07")

DEFAULT_TIME_S = 3.0
DEFAULT_SPEED = "normal"
MIN_TIME_S = 0.5
MAX_TIME_S = 60.0

#: Milliseconds between lines for each speed word.
SPEEDS: dict[str, int] = {
    "slow": 260,
    "normal": 110,
    "fast": 30,
    "super": 6,
}

#: A flood is 60 lines, then the oldest 30 are cleaned up.
CLEAN_AT = 60
CLEAN_LINES = 30

HELP_TEXT = (
    "\r\n"
    "codeout - the fake system-boot show (just for fun)\r\n"
    "  codeout              run with codeout-conf.txt settings\r\n"
    "  codeout 3s           run for 3 seconds\r\n"
    "  codeout 3s fast      run 3 seconds at fast speed\r\n"
    "  codeout super        top speed, default time\r\n"
    "  speeds: slow, normal, fast, super\r\n"
    "  codeout stop         stop the current show\r\n"
    "  codeout conf         print the config file path\r\n"
)

#: Status word -> ANSI colour code for the ``[status]`` prefix. Kept to just
#: four colours so the flood reads like a real kernel log: vivid red for
#: errors, bright green for successes, orange for loading, and bright white
#: for everything else.
_TRUE_WHITE = "38;2;255;255;255"
_STATUS_COLORS = {
    "successful": "1;38;2;0;255;90",  # bright green
    "ok": "1;38;2;0;255;90",
    "error": "1;38;2;255;60;60",  # vivid red
    "failed": "1;38;2;255;60;60",
    "loading": "1;38;2;255;150;30",  # orange
    "warning": f"1;{_TRUE_WHITE}",
    "info": f"1;{_TRUE_WHITE}",
    "debug": f"1;{_TRUE_WHITE}",
}

#: (status, message) pool — the "crazy code" the flood prints. Short silly
#: lines are mixed with longer kernel-log style lines (paths, addresses,
#: timestamps) so the stream looks like a real boot console.
_LINES: list[tuple[str, str]] = [
    ("loading", "system DeepTerminal"),
    ("loading", "loading kernel modules"),
    ("loading", "mounting /dev/snacks"),
    ("loading", "waking up..."),
    ("loading", "starting homework daemon..."),
    ("loading", "downloading motivation..."),
    ("loading", "connecting to the moon"),
    ("loading", "compiling 1000 lines of pure imagination"),
    ("loading", "mounting /mnt/brain..."),
    ("loading", "starting DeepTerminal vibes..."),
    ("loading", "rebooting weekend..."),
    ("loading", "loading 3, 2, 1..."),
    ("loading", "starting the pizza engine"),
    ("loading", "unpacking the backpack"),
    ("loading", "warming up the RGB lights"),
    ("loading", "booting the daydream module"),
    ("successful", "eating a pizza"),
    ("successful", "pizza consumed in 0.0001s"),
    ("successful", "woke up successfully"),
    ("successful", "found the missing sock"),
    ("successful", "moon says hi"),
    ("successful", "cleaned 999MB of bad vibes"),
    ("successful", "dog.exe approved the code"),
    ("successful", "keyboard rescued from the floor"),
    ("successful", "imagination compiled"),
    ("successful", "solved 2+2: it's 4 (probably)"),
    ("successful", "vibes are excellent"),
    ("successful", "game saved"),
    ("successful", "backup restored from a secret drawer"),
    ("successful", "kernel version: awesome"),
    ("successful", "user logged in as: legend"),
    ("successful", "legendary status confirmed"),
    ("successful", "homework daemon restarted with more snacks"),
    ("successful", "procrastination daemon stopped for a snack break"),
    ("successful", "the fridge door opened all by itself"),
    ("successful", "found the TV remote"),
    ("successful", "weekend loaded successfully"),
    ("error", "dont want to go to school"),
    ("error", "homework.exe not responding"),
    ("error", "game download failed: bed time"),
    ("error", "segmentation fault (core dumped in my backpack)"),
    ("error", "alarm clock ignored"),
    ("error", "motivation not found"),
    ("error", "rocket lost in the garage"),
    ("error", "bedtime scheduled but you ignored it"),
    ("error", "homework daemon crashed: too boring"),
    ("error", "cat.exe pushed keyboard off desk"),
    ("error", "keyboard not found on desk"),
    ("error", "math.js returned NaN feelings"),
    ("error", "too much fun detected, fun quota exceeded"),
    ("error", "save file corrupted by little brother"),
    ("error", "monday incoming: shields up"),
    ("error", "brain.exe ran out of RAM"),
    ("error", "sock not found (again)"),
    ("error", "video game boss crashed the system"),
    ("warning", "battery low: need snacks"),
    ("warning", "fan speed critical: it's hot outside"),
    ("warning", "memory leak detected: forgot homework at home"),
    ("warning", "wifi signal: emotional support"),
    ("warning", "disk almost full: memes are heavy"),
    ("warning", "daydreaming thread has high CPU usage"),
    ("warning", "temperature rising: gaming too hard"),
    ("warning", "procrastination daemon running at 99%"),
    ("warning", "swap memory: trading stickers with friends"),
    ("warning", "homework folder is empty (suspicious)"),
    ("warning", "school bus approaching the driveway"),
    ("info", "system time: nap o'clock"),
    ("info", "uptime: 5 minutes of attention span"),
    ("info", "dog.exe is watching you"),
    ("info", "user is awesome"),
    ("info", "the code writes itself when nobody looks"),
    ("info", "terminal happiness level: 100%"),
    ("debug", "debugging why the toast burned"),
    ("debug", "tracing the path of a flying paper plane"),
    ("debug", "breakpoint hit: snack break"),
    ("debug", "step into the puddle, not over it"),
    ("failed", "trying to wake up before 7am"),
    ("failed", "resisting the urge to press every key"),
    ("failed", "hiding vegetables under the rice"),
    ("ok", "socks match today (miracles happen)"),
    ("ok", "backpack packed without drama"),
    # -- longer, kernel-log style lines (paths, addresses, timestamps) -----
    ("loading", "kernel: [ 0.184207] mount: /dev/nvme0n1p2 on /home type ext4 (rw,relatime,discard=async,errors=remount-ro)"),
    ("loading", "systemd[1]: Started Load Kernel Modules - 147 modules, 3 of them are still asleep."),
    ("loading", "kernel: [ 1.204881] input: AT Translated Set 2 keyboard as /devices/platform/i8042/serio0/input/input3"),
    ("loading", "kernel: [ 0.847112] random: crng init done - trust the chaos"),
    ("loading", "mount: /dev/sdb1 on /mnt/homework type vfat (ro,noexec,guilt=on)"),
    ("loading", "kernel: [ 2.446078] usb 3-2: new high-speed USB device number 7 using xhci_hcd"),
    ("loading", "systemd[1]: Starting Network Name Resolution... resolving the mystery of the lost sock."),
    ("loading", "kernel: [ 0.112004] Booting Linux on physical CPU 0x0000000000000000 (built different)"),
    ("loading", "kernel: [ 1.887774] EXT4-fs (nvme0n1p2): mounted filesystem with ordered data mode. Snacks queued."),
    ("successful", "systemd[1]: Reached target Multi-User System - 42 units loaded, 0 failed, 1 pizza consumed."),
    ("successful", "kernel: [ 0.052917] pci 0000:00:02.0: vgaarb: VGA device found (rev 09, 16384 MB prefetchable, RGB lights included)"),
    ("successful", "pizza.service: Consumed 812ms CPU time, 3 slices of pepperoni, 0 regrets."),
    ("successful", "NetworkManager[633]: device (wlan0): state change: disconnected -> connected (reason 'snacks nearby')"),
    ("successful", "systemd-logind[487]: New session c2 of user legend - seat seat0, pizza level: high"),
    ("successful", "kernel: [ 3.110592] raid6: using algorithm avx2x4 - homework protection level: maximum"),
    ("successful", "kernel: [ 0.498101] Console: colour dummy device 80x25 - looks cooler than it sounds"),
    ("error", "kernel: [ 3.718823] alarm-clock.service: Failed with result 'ignored' - user requested 5 more minutes."),
    ("error", "hwclock.service: Cannot access the Hardware Clock via any known method. (Tried the attic, the garage and under the bed.)"),
    ("error", "systemd[1]: homework.service: Main process exited, code=exited, status=1/FAILURE (reason: too boring)"),
    ("error", "pcieport 0000:00:1c.4: AER: Corrected error received: 0000:00:1c.4 (blame the little brother)"),
    ("error", "kernel: [ 4.020135] EXT4-fs error (device nvme0n1p2): snack_daemon: committed 999 blocks of chocolate"),
    ("error", "systemd[1]: Failed to start Deep Sleep Service - someone pressed every key at once."),
    ("warning", "kernel: [ 9.401777] thermal thermal_zone0: critical temperature reached (100 C), shutting down game.exe"),
    ("warning", "kernel: [ 12.003331] CPU1: Package temperature above threshold, cpu clock throttled (game.exe is hungry)"),
    ("warning", "systemd[1]: /proc/sys/vm/dirty_ratio: value '100' out of range - the room is dirty enough already"),
    ("warning", "NetworkManager[633]: wlan0: wifi signal weak - moving the router closer to the snacks"),
    ("warning", "kernel: [ 7.771905] watchdog: watchdog0: watchdog did not stop! (the dog is still watching you)"),
    ("info", "systemd-journald[214]: Journal started - 1.2M entries collected since you woke up."),
    ("info", "systemd[1]: Listening on D-Bus System Message Bus Socket (id=@e32b0f0c)"),
    ("info", "kernel: [ 0.000000] Linux version 6.9.0-awesome (azen@fun) (gcc 13.2.0) #1 SMP PREEMPT_DYNAMIC"),
    ("info", "systemd[1]: Detected architecture x86-64 (with extra RGB)"),
    ("info", "kernel: [ 0.607834] Spectre V2: Enabling mitigation: waking up is scary enough already"),
    ("debug", "kernel: [ 1.554209] psmouse serio1: elantech: assuming hardware version 4 - the mouse is plotting something"),
    ("debug", "usb 3-2: new high-speed USB device number 7 using xhci_hcd (vendor 0xfeed, product 0xbeef)"),
    ("ok", "fsck.ext4: /dev/sda1: clean, 524288/26214400 files, 0 problems, homework still missing"),
]


def random_line() -> str:
    """One coloured log line: ``[successful] eating a pizza``.

    Only four colours are used (red / green / orange tags, bright white
    message) and the line ends with a full reset so shell output afterwards
    keeps its normal colours.
    """
    status, message = random.choice(_LINES)
    return (
        f"\x1b[{_STATUS_COLORS[status]}m[{status}]\x1b[0m"
        f"\x1b[{_TRUE_WHITE}m{message}\x1b[0m"
    )


# -- config file ---------------------------------------------------------
def config_path() -> Path:
    """Path of ``codeout-conf.txt`` (sits next to the QSettings file)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "AzenDev" / "DeepTerminal" / "codeout-conf.txt"


DEFAULT_CONF_TEXT = "#code output config\n#just for fun\n[time]:3s\n[speed]:super\n"


def ensure_config_file() -> Path:
    """Create ``codeout-conf.txt`` with the default settings if missing."""
    path = config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_CONF_TEXT, encoding="utf-8")
        except OSError:  # pragma: no cover - read-only home dirs
            pass
    return path


def read_config() -> dict[str, str]:
    """Parse ``[time]`` / ``[speed]`` values out of ``codeout-conf.txt``."""
    values: dict[str, str] = {}
    try:
        ensure_config_file()
        for raw in config_path().read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*\[(\w+)\]\s*:\s*(\S+)\s*$", raw)
            if match:
                values[match.group(1).lower()] = match.group(2)
    except OSError:
        pass
    return values


# -- argument parsing ----------------------------------------------------
def parse_duration(token: str) -> float | None:
    """``3s`` -> 3.0, ``500ms`` -> 0.5, ``3`` -> 3.0; None when not a time."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)?", token.strip(), re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    if unit == "ms":
        value /= 1000.0
    return min(MAX_TIME_S, max(MIN_TIME_S, value))


def parse_speed(token: str) -> str | None:
    """``fast`` -> "fast"; None when the token is not a speed word."""
    word = token.strip().lower()
    return word if word in SPEEDS else None


@dataclass(frozen=True)
class CodeoutOptions:
    """Resolved settings for one flood: how long and how fast."""

    duration_s: float
    interval_ms: int
    speed: str


def build_options(tokens: list[str], conf: dict[str, str] | None = None) -> CodeoutOptions:
    """Merge config-file defaults with command-line tokens (tokens win)."""
    conf = conf if conf is not None else read_config()
    duration = parse_duration(conf.get("time", "")) or DEFAULT_TIME_S
    speed = parse_speed(conf.get("speed", "")) or DEFAULT_SPEED
    for token in tokens:
        parsed_time = parse_duration(token)
        if parsed_time is not None:
            duration = parsed_time
            continue
        parsed_speed = parse_speed(token)
        if parsed_speed is not None:
            speed = parsed_speed
    return CodeoutOptions(duration_s=duration, interval_ms=SPEEDS[speed], speed=speed)


# -- shell-side trigger functions ---------------------------------------
def bash_codeout_setup() -> str:
    """Bash function that emits the invisible OSC trigger (one line)."""
    return "codeout() { printf '\\033]663;codeout %s\\007' \"$*\"; }"


def pwsh_codeout_setup() -> str:
    """PowerShell function that emits the invisible OSC trigger."""
    return 'function codeout { Write-Host -NoNewline "$([char]27)]663;codeout $args$([char]7)" }'


# -- the animator --------------------------------------------------------
class CodeoutRunner(QObject):
    """A QTimer that floods the terminal with fake log lines.

    The view feeds every ``line_ready`` line into its own pyte screen, so
    the whole show stays client-side: exact timing, no shell involved.
    """

    line_ready = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._deadline = 0.0
        self._lines = 0

    def start(self, options: CodeoutOptions) -> None:
        """(Re)start the flood with the given duration and speed."""
        self.stop()
        self._deadline = time.monotonic() + options.duration_s
        self._lines = 0
        self._timer.setInterval(options.interval_ms)
        self._timer.start()
        self._tick()  # first line appears immediately

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.finished.emit()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def lines(self) -> int:
        """Number of lines emitted by the current run."""
        return self._lines

    def _tick(self) -> None:
        if time.monotonic() >= self._deadline:
            self.stop()
            return
        self._lines += 1
        self.line_ready.emit(random_line())
