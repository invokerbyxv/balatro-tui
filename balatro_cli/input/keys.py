"""Single-key (raw-mode) reader for the IDE terminal.

Only the terminal is put into raw mode *around* each blocking read, then
restored — so all the ordinary scrolling `print` output stays line-buffered
and echo-free. Ctrl+C (which raw mode exposes as byte 0x03) and EOF are treated
as a quit signal.

No extra dependency: uses stdlib `termios`/`tty`/`os` (POSIX). Falls back to
line-based `input()` (normal mode) if termios is unavailable, so the app still
runs on non-POSIX terminals at the cost of the single-key UX.
"""

from __future__ import annotations

import os
import sys

_ctrl_c = "\x03"
_enter = {"\r", "\n"}
_keymap_visible = {
    "n": "next", " ": "play", "p": "play", "d": "discard", "x": "discard",
    "s": "shop", "r": "reroll", "c": "consume", "v": "voucher", "q": "quit",
    "?": "help", "\x03": "quit", "\x1a": "quit",
}


class RawUnavailable(Exception):
    pass


def _raw_available() -> bool:
    return sys.platform != "win32"


def read_key_raw() -> str:
    """Read a single key. Enter -> '\n'; Ctrl+C -> '\x03'."""
    fd = sys.stdin.fileno()
    import termios
    import tty
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        data = os.read(fd, 1)
        if not data:
            return "q"  # EOF
        return data.decode("utf-8", "replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    if _raw_available():
        try:
            return read_key_raw()
        except Exception:
            return _read_line_key()
    return _read_line_key()


def _read_line_key() -> str:
    """Line-mode fallback: returns the trimmed line so `c1` / `x2` work."""
    try:
        line = input("")
    except EOFError:
        return "q"
    line = (line or "").strip().lower()
    if not line:
        return "enter"
    return line


def key_name(ch: str) -> str:
    if ch in _enter:
        return "enter"
    if ch.isdigit():
        return ch
    return _keymap_visible.get(ch, ch)