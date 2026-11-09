"""Check setup: tries every Roblox window once and writes down what happened.

The report is what to send when something doesn't work on a real PC.
"""

from __future__ import annotations

import platform
import sys

from . import __version__
from .engine import DC_OFFSETS, popup_color


def report(io, cfg) -> str:
    lines = [
        f"Tap Quest Multi {__version__} setup check",
        f"Python {sys.version.split()[0]} on {platform.platform()}",
    ]
    try:
        plugged, pct = io.power()
        lines.append(f"Memory in use: {io.memory_pct()}%   Plugged in: {plugged}   Battery: {pct}")
    except Exception as e:
        lines.append(f"Memory/power check failed: {e!r}")
    wins = io.list_windows()
    lines.append(f"Roblox windows found: {len(wins)} (looking for {', '.join(cfg.process_names)})")
    start_fg, start_cur = io.foreground(), io.cursor()
    ok = 0
    for n, (hwnd, title) in enumerate(wins, 1):
        t0 = io.now()
        io.focus(hwnd)
        while io.foreground() != hwnd and io.now() - t0 < 10:
            io.sleep(0.05)
        took = io.now() - t0
        if io.foreground() != hwnd:
            lines.append(f"  {n}. '{title}': could NOT be brought to the front in 10s")
            continue
        ok += 1
        io.sleep(0.3)
        size = io._client(hwnd)[2:] if hasattr(io, "_client") else "?"
        flat = popup_color(io.sample(hwnd, DC_OFFSETS))
        popup = f"flat colour {flat} at centre (pop-up showing?)" if flat else "no pop-up seen"
        lines.append(f"  {n}. '{title}': came to front in {took:.2f}s, game area {size}, {popup}")
    if start_fg:
        io.focus(start_fg)
    io.set_cursor(start_cur)
    lines.append(f"Result: {ok} of {len(wins)} windows reachable")
    if not wins:
        lines.append("No windows found: open Roblox first. If it is open, tell Claude this line.")
    return "\n".join(lines)
