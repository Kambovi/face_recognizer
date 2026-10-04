"""CSV writer that can't be turned into a spreadsheet formula attack.

A name like `=HYPERLINK("http://evil","click")` or `+cmd|' /C calc'!A0`
typed into the staff list would run as a formula when HR opens the export
in Excel. Text cells that start with = + - @ TAB or CR get a leading
apostrophe (Excel shows the text as-is). Numbers are left alone.
"""
from __future__ import annotations

import csv
from typing import Any, Iterable

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(_DANGEROUS):
        try:
            float(v)  # "-12.5" is a number, keep it
            return v
        except ValueError:
            return "'" + v
    return v


class SafeWriter:
    def __init__(self, buf: Any) -> None:
        self._w = csv.writer(buf)

    def writerow(self, row: Iterable[Any]) -> None:
        self._w.writerow([safe_cell(c) for c in row])

    def writerows(self, rows: Iterable[Iterable[Any]]) -> None:
        for r in rows:
            self.writerow(r)


def writer(buf: Any) -> SafeWriter:
    return SafeWriter(buf)
