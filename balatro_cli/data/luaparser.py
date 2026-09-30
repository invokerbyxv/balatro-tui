"""A small parser for Lua *literal table* syntax (data-only, no execution).

Balatro's decompiled source ships its data as plain Lua tables:
    self.P_CENTERS = { j_x = {name = '...', config = {...}}, ... }
    return { descriptions = {...}, misc = {...} }

These are restricted literals (strings / numbers / booleans / nested tables /
function calls such as `HEX('...')`). We parse them without a Lua runtime.

Any value that is a function call (`name(args)`) is skipped as a runtime
expression; for calls whose first argument is a string (e.g. `HEX('b95b08')`,
`localize('x')`) we keep that string so colour ids stay around if ever wanted.

Keywords true/false map to bool; nil/unknown identifiers map to None and are
dropped from output. Comments (`--` line, `--[[ ]]` long) are skipped.
"""

from __future__ import annotations

import re


class LuaParseError(ValueError):
    pass


class ValueParser:
    """Parses one Lua literal value from `s` starting at `i`."""

    __slots__ = ("s", "i", "n", "warnings")

    def __init__(self, s: str, i: int = 0):
        self.s = s
        self.i = i
        self.n = len(s)
        self.warnings: list[str] = []

    # -- low-level scans ----------------------------------------------------
    def _skip_space(self) -> None:
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n\f\v":
                self.i += 1
            elif c == "-" and self.i + 1 < n and s[self.i + 1] == "-":
                self._skip_comment()
            else:
                break

    def _skip_comment(self) -> None:
        s, n = self.s, self.n
        if self.i + 2 >= n:
            self.i = n
            return
        if s[self.i + 2] == "[":  # long comment --[[ .. ]] or --[=[ .. ]=]
            eqs = 1
            j = self.i + 3
            if j < n and s[j] == "[":
                close = "]]"
                self.i = n
                end = s.find(close, self.i)
                self.i = end + 2 if end != -1 else n
                return
            while j < n and s[j] == "=":
                eqs += 1
                j += 1
            if j < n and s[j] == "[":
                close = "]" + "=" * (eqs - 1) + "]"
                end = s.find(close, j)
                self.i = end + len(close) if end != -1 else n
                return
        # line comment
        nl = s.find("\n", self.i + 2)
        self.i = nl + 1 if nl != -1 else n

    def _read_string(self, quote: str) -> str:
        s, n = self.s, self.n
        self.i += 1  # opening quote
        buf: list[str] = []
        mapping = {
            "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
            "f": "\f", "v": "\v", "0": "\0", "\\": "\\",
            "'": "'", '"': '"', "\n": "",
        }
        while self.i < n:
            c = s[self.i]
            if c == quote:
                self.i += 1
                return "".join(buf)
            if c == "\\":
                self.i += 1
                if self.i >= n:
                    break
                e = s[self.i]
                if e in mapping:
                    buf.append(mapping[e])
                    self.i += 1
                elif e.isdigit():
                    num = ""
                    while self.i < n and len(num) < 3 and s[self.i].isdigit():
                        num += s[self.i]
                        self.i += 1
                    buf.append(chr(int(num, 8) % 256))
                else:
                    buf.append(e)  # unknown escape -> literal char
                    self.i += 1
            else:
                buf.append(c)
                self.i += 1
        raise LuaParseError("unterminated string literal")

    def _read_number(self) -> int | float:
        s, n = self.s, self.n
        start = self.i
        if self.i < n and s[self.i] in "+-":
            self.i += 1
        while self.i < n and (s[self.i].isalnum() or s[self.i] in "._"):
            self.i += 1
        txt = s[start:self.i]
        low = txt.lower()
        try:
            if low.startswith("0x"):
                return int(txt, 16)
            if any(c in "eE." for c in txt):
                return float(txt)
            return int(txt)
        except ValueError:
            return 0

    def _read_ident(self) -> str:
        s, n = self.s, self.n
        start = self.i
        while self.i < n and (s[self.i].isalnum() or s[self.i] == "_"):
            self.i += 1
        return s[start:self.i]

    def _skip_call(self, name: str):
        """We are at `(` of a function call value. Return first string arg or None."""
        s, n = self.s, self.n
        depth = 0
        first_str: str | None = None
        in_str: str | None = None
        idx = self.i
        self.i += 1  # consume '('
        while self.i < n:
            c = s[self.i]
            if in_str:
                if c == "\\":
                    self.i += 2
                    continue
                if c == in_str:
                    in_str = None
                self.i += 1
                continue
            if c in "'\"":
                if first_str is None:
                    first_str = self._read_string(c)
                    continue
                in_str = c
                self.i += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    self.i += 1
                    return first_str
                depth -= 1
            self.i += 1
        return first_str

    # -- value grammar ------------------------------------------------------
    def parse_value(self):
        self._skip_space()
        if self.i >= self.n:
            return None
        c = self.s[self.i]
        if c == "{":
            return self.parse_table()
        if c in "'\"":
            return self._read_string(c)
        if c.isdigit() or (self.i + 1 < self.n and c in "+-" and self.s[self.i + 1].isdigit()):
            return self._read_number()
        if c.isalpha() or c == "_":
            ident = self._read_ident()
            if self.i < self.n and self.s[self.i] == "(":
                return self._skip_call(ident)
            return {"true": True, "false": False}.get(ident)
        return None

    def parse_table(self):
        # self.s[self.i] == '{'
        self.i += 1
        result: dict = {}
        positional: list = []
        has_named = False
        used_int_keys: set[int] = set()

        while True:
            self._skip_space()
            if self.i >= self.n:
                break
            if self.s[self.i] == "}":
                self.i += 1
                break

            # --- parse field key (optional) ---
            key = None
            self._skip_space()
            if self.i < self.n and self.s[self.i] == "[":
                self.i += 1
                key = self.parse_value()
                self._skip_space()
                if self.i < self.n and self.s[self.i] == "]":
                    self.i += 1
                self._skip_space()
                if self.i < self.n and self.s[self.i] == "=":
                    self.i += 1
            else:
                save = self.i
                ident = self._read_ident()
                self._skip_space()
                if ident and self.i < self.n and self.s[self.i] == "=":
                    self.i += 1
                    key = ident
                else:
                    self.i = save  # positional value

            # --- parse the value ---
            self._skip_space()
            before = self.i
            val = self.parse_value()
            if self.i == before and val is None:
                # No progress: bogus char. Advance past it to avoid an infinite
                # loop, and let it appear as None (dropped).
                self.i += 1

            if key is None:
                # positional
                n = len(positional) + 1
                positional.append(val)
                result[str(n)] = val
                used_int_keys.add(n)
            elif isinstance(key, int):
                result[str(key)] = val
                used_int_keys.add(key)
            else:
                result[key] = val
                has_named = True

            # --- separator ---
            self._skip_space()
            if self.i < self.n and self.s[self.i] in ",;":
                self.i += 1

        if not has_named and positional and used_int_keys == set(range(1, len(positional) + 1)):
            return positional
        return result


# -- module-level convenience ------------------------------------------------


def parse_literal(text: str, i: int = 0):
    """Parse a single Lua literal (table/string/number/bool) from `text[i:]`."""
    p = ValueParser(text, i)
    val = p.parse_value()
    return val, p.i, p.warnings


def parse_assignment_table(text: str, key: str) -> dict:
    """Parse the table assigned to `key = { ... }` appearing in `text`.

    Locates the first occurrence of `<key>` that is followed by an `=` (with
    optional whitespace) then a `{`, and parses the whole balanced literal.
    Returns the parsed value (expected dict).
    """
    idx = 0
    while True:
        pos = text.find(key, idx)
        if pos == -1:
            raise LuaParseError(f"marker {key!r} not found")
        if pos + len(key) < len(text) and (text[pos + len(key)].isalnum() or text[pos + len(key)] == "_"):
            idx = pos + len(key)  # partial match like P_CENTERS vs P_CENTER_POOLS
            continue
        start = pos + len(key)
        start = _skip_ws(text, start)
        if start < len(text) and text[start] == "=":
            start = _skip_ws(text, start + 1)
        if start >= len(text) or text[start] != "{":
            idx = pos + len(key)
            continue
        val, end, warnings = parse_literal(text, start)
        if val is None:
            idx = pos + len(key)
            continue
        return val
    raise LuaParseError(f"failed to parse table for {key!r}")


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    return i


def parse_top_table(text: str) -> dict:
    """Parse a leading `return <table>` or standalone `<table>` literal."""
    return parse_assignment_table(text, "return")