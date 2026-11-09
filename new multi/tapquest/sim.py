"""A pretend PC with pretend Roblox windows, for tests and the demo mode.

It models the things that go wrong in real life: the 20-minute idle kick,
windows that refuse to come to the front, network disconnects, crashes, and a
person grabbing the mouse and clicking on their own stuff mid-macro.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .config import ROBLOX_IDLE_KICK_S

USER_WINDOW = 1  # the person's own app (browser, Discord...)
DIALOG = (57, 59, 61)


@dataclass
class SimWindow:
    hwnd: int
    last_input: float = 0.0
    disconnected: bool = False
    dc_since: float = 0.0
    rejoin_at: float | None = None
    blocked_until: float = 0.0
    clicks: int = 0
    keys: int = 0
    step_clicks: int = 0


class SimIO:
    def __init__(
        self,
        accounts: int = 4,
        seed: int = 0,
        focus_fail: float = 0.0,  # chance one focus attempt silently fails
        user_per_hour: float = 0.0,  # how often the person starts using the PC
        user_busy_s: tuple = (20, 300),
        netdrop_per_hour: float = 0.0,  # network disconnects per account-hour
        crash_per_hour: float = 0.0,
        block_per_hour: float = 0.0,  # spells where a window can't be focused
        realtime_speed: float | None = None,  # None = run as fast as possible
        reconnect_offset: tuple = (82, 86),
        tap_pos: tuple = (0.5, 0.55),
    ):
        self.rng = random.Random(seed)
        self.t = 0.0
        self.windows = {100 + i: SimWindow(100 + i) for i in range(accounts)}
        self.fg = USER_WINDOW
        self.cur = (5, 5)
        self.focus_fail = focus_fail
        self.user_rate = user_per_hour / 3600
        self.user_busy_s = user_busy_s
        self.net_rate = netdrop_per_hour / 3600
        self.crash_rate = crash_per_hour / 3600
        self.block_rate = block_per_hour / 3600
        self.speed = realtime_speed
        self.reconnect_offset = reconnect_offset
        self.tap_pos = tap_pos
        self.user_until = 0.0
        self.always_user = False
        # What the tests measure
        self.idle_kicks = 0
        self.stray_inputs = 0  # input that landed outside a Roblox window
        self.net_drops = 0
        self.crashes = 0
        self.max_idle = 0.0
        self.max_dc_time = 0.0
        self.beeps = 0
        self._acc = 0.0
        self.pending_hotkey = None

    # ---- time --------------------------------------------------------------
    def now(self) -> float:
        return self.t

    def sleep(self, s: float):
        if self.speed:
            time.sleep(s / self.speed)
        self.t += s
        self._acc += s
        if self._acc >= 0.5:
            self._world(self._acc)
            self._acc = 0.0

    def _world(self, dt: float):
        t, rng = self.t, self.rng
        for w in list(self.windows.values()):
            if w.disconnected:
                if w.rejoin_at is not None and t >= w.rejoin_at:
                    self.max_dc_time = max(self.max_dc_time, t - w.dc_since)
                    w.disconnected, w.rejoin_at, w.last_input = False, None, t
                continue
            idle = t - w.last_input
            self.max_idle = max(self.max_idle, idle)
            if idle >= ROBLOX_IDLE_KICK_S:
                self.idle_kicks += 1
                w.disconnected, w.dc_since = True, t
            elif self.net_rate and rng.random() < self.net_rate * dt:
                self.net_drops += 1
                w.disconnected, w.dc_since = True, t
            elif self.crash_rate and rng.random() < self.crash_rate * dt:
                self.crashes += 1
                del self.windows[w.hwnd]
                if self.fg == w.hwnd:
                    self.fg = USER_WINDOW
            elif self.block_rate and rng.random() < self.block_rate * dt:
                w.blocked_until = t + rng.uniform(10, 120)
        if self.user_rate and rng.random() < self.user_rate * dt:
            self.user_until = t + rng.uniform(*self.user_busy_s)
        if self.always_user or t < self.user_until:
            # The person wiggles the mouse and clicks back onto their own window.
            self.cur = (rng.randrange(2000), rng.randrange(1200))
            if rng.random() < 0.7:
                self.fg = USER_WINDOW

    # ---- windows -----------------------------------------------------------
    def list_windows(self):
        return [(h, "Roblox") for h in self.windows]

    def foreground(self) -> int:
        return self.fg

    def focus(self, hwnd: int):
        w = self.windows.get(hwnd)
        if hwnd == USER_WINDOW:
            self.fg = hwnd
        elif w and self.t >= w.blocked_until and self.rng.random() >= self.focus_fail:
            self.fg = hwnd

    def cursor(self):
        return self.cur

    def set_cursor(self, pos):
        self.cur = tuple(pos)

    # ---- input: always lands on whatever is in front, like a real PC -------
    def _target(self):
        w = self.windows.get(self.fg)
        if w is None:
            self.stray_inputs += 1
        return w

    def click(self, hwnd: int, fx: float, fy: float):
        self.cur = (int(fx * 1000) + hwnd, int(fy * 1000))
        w = self._target()
        if w and not w.disconnected:
            w.last_input = self.t
            w.clicks += 1
            if (fx, fy) != self.tap_pos:
                w.step_clicks += 1

    def click_px(self, hwnd: int, dx: int, dy: int):
        self.cur = (5000 + dx + hwnd, 5000 + dy)
        w = self._target()
        if w and w.disconnected and (dx, dy) == self.reconnect_offset and w.rejoin_at is None:
            w.rejoin_at = self.t + 8.0

    def key(self, name: str, hold_s: float):
        w = self._target()
        if w and not w.disconnected:
            w.last_input = self.t
            w.keys += 1
        self.sleep(hold_s)

    def sample(self, hwnd: int, offsets):
        w = self.windows.get(hwnd)
        if w and w.disconnected:
            cols = [DIALOG] * len(offsets)
            cols[self.rng.randrange(len(cols))] = (255, 255, 255)  # pop-up text
            return cols
        return [tuple(self.rng.randrange(256) for _ in range(3)) for _ in offsets]

    def hotkey(self):
        k, self.pending_hotkey = self.pending_hotkey, None
        return k

    def beep(self):
        self.beeps += 1
