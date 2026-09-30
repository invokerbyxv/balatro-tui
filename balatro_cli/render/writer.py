"""Line emitter for the covert transcript.

Ordinary scrolling stdout output — never clears the screen, never moves the
cursor, never uses box-drawing. Optional ANSI dim (SGR 2) for secondary lines.
"""

from __future__ import annotations

import sys
from typing import TextIO

DIM = "\x1b[2m"
RESET = "\x1b[0m"


class Writer:
    def __init__(self, stream: TextIO | None = None, dim: bool = False):
        self.stream = stream or sys.stdout
        self.dim = dim

    def out(self, line: str = "", dim: bool = False) -> None:
        s = line
        if dim and self.dim:
            s = DIM + s + RESET
        print(s, file=self.stream, flush=True)
        self.stream.flush()

    def prompt(self, hint: str = ">") -> str:
        return hint