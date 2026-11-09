"""The macro's brain. Decides which account to visit and what to send it.

It talks to the PC only through an `io` object (see win.py for the real one and
sim.py for the simulated one used in tests), so every decision here is testable
without Roblox.

Rules it never breaks:
  * input is only sent after confirming the target Roblox window is in front;
  * every open account receives input at least every `safe_idle_s` seconds,
    whatever else is going on (paused, you using the PC, other accounts stuck).
"""

from __future__ import annotations

import random
import threading
from collections import deque
from dataclasses import dataclass, field

from .config import Config

REFRESH_S = 3.0  # how often to look for opened/closed Roblox windows
DC_CHECK_S = 20.0  # how often to look for the disconnect pop-up on an account
VISIT_OVERHEAD_S = 0.6  # rough cost of switching windows
# Points (pixels from the window centre) sampled to spot the disconnect pop-up.
DC_OFFSETS = [(dx, dy) for dy in (-40, -15, 10) for dx in (-110, -55, 0, 55, 110)]


class _Abort(Exception):
    """Stop the current visit without sending anything more."""


@dataclass
class Account:
    hwnd: int
    name: str
    state: str = "ok"  # ok | reconnecting | blocked | closed
    last_input: float | None = None  # None = never touched by us yet
    seen_at: float = 0.0
    visits: int = 0
    taps: int = 0
    eggs: int = 0
    reconnects: int = 0
    focus_fails: int = 0
    dc_streak: int = 0
    retry_at: float = 0.0
    next_dc_check: float = 0.0
    warned: bool = False
    step_last: dict = field(default_factory=dict)

    def idle(self, now: float) -> float:
        return float("inf") if self.last_input is None else now - self.last_input


class Engine:
    def __init__(self, cfg: Config, io, log=None, seed=None, strict=False):
        cfg.validate()
        self.cfg = cfg
        self.io = io
        self.accounts: dict[int, Account] = {}
        self.mode = "run"  # "run" = full macro, "keepalive" = only stay connected
        self.events: deque = deque(maxlen=300)
        self.alarms = 0
        self.user_until = 0.0
        self._log_cb = log
        self._rng = random.Random(seed)
        self._stop = threading.Event()
        self._strict = strict
        self._next_refresh = 0.0
        self._cursor = None  # where we last left the mouse
        self._counter = 0
        self._errors = 0
        self._overhead = VISIT_OVERHEAD_S  # measured cost of switching to an account
        self._focus_ema = 0.1  # measured time for a window to come to the front
        self._front = None  # account window we last brought forward
        self._next_trim = 0.0
        self._slow_warned = False

    # ---- control -----------------------------------------------------------
    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def set_mode(self, mode: str):
        if mode not in ("run", "keepalive"):
            raise ValueError(mode)
        if mode != self.mode:
            self.mode = mode
            self.log("Tapping resumed" if mode == "run" else "Keep-alive only (tapping paused)")

    def log(self, msg: str):
        self.events.append((self.io.now(), msg))
        if self._log_cb:
            self._log_cb(msg)

    def alarm(self, msg: str):
        self.alarms += 1
        self.log("ALERT: " + msg)
        self.io.beep()

    def snapshot(self) -> dict:
        now = self.io.now()
        return {
            "mode": self.mode,
            "user_active": now < self.user_until,
            "dwell": self.dwell(),
            "lap": len(self.live()) * (self.dwell() + self._overhead),
            "accounts": [
                {
                    "name": a.name,
                    "state": a.state,
                    "idle": None if a.last_input is None else now - a.last_input,
                    "visits": a.visits,
                    "taps": a.taps,
                    "eggs": a.eggs,
                    "reconnects": a.reconnects,
                }
                for a in list(self.accounts.values())
            ],
        }

    # ---- main loop ---------------------------------------------------------
    def run(self, until: float | None = None):
        """Run until stop() (or until io.now() reaches `until`)."""
        self._cursor = self.io.cursor()
        while not self.stopped and (until is None or self.io.now() < until):
            try:
                self.tick()
                self._errors = 0
            except Exception as e:  # keep the accounts alive through one-off glitches
                if self._strict:
                    raise
                self._errors += 1
                self.log(f"Error: {e!r}")
                if self._errors % 200 == 20:
                    # Keep trying anyway: stopping would guarantee disconnects.
                    self.alarm("The macro keeps hitting errors - check the log")
                self.io.sleep(1.0)

    def tick(self):
        self._hotkeys()
        if self.stopped:
            return
        now = self.io.now()
        if now >= self._next_refresh:
            self._refresh()
            self._next_refresh = now + REFRESH_S
        self._watch_user()
        self._watch_idle()
        self._housekeep()
        acc, full = self._pick()
        if acc is None:
            self.io.sleep(0.25)
        else:
            self._visit(acc, full)

    def _hotkeys(self):
        k = self.io.hotkey()
        if k == "stop":
            self.log("Stop key pressed")
            self.stop()
        elif k == "pause":
            self.set_mode("keepalive" if self.mode == "run" else "run")

    def _refresh(self):
        wins = dict(self.io.list_windows())
        for hwnd in sorted(wins):
            a = self.accounts.get(hwnd)
            if a is None:
                self._counter += 1
                a = Account(hwnd, f"Account {self._counter}", seen_at=self.io.now())
                self.accounts[hwnd] = a
                self.log(f"{a.name} found")
                if self.cfg.weak_pc and self.cfg.weak_low_priority:
                    self._quiet(self.io.tune, hwnd)
                if self.cfg.weak_pc and self.cfg.weak_minimize and hwnd != self.io.foreground():
                    self._quiet(self.io.minimize, hwnd)
            elif a.state == "closed":
                a.state, a.last_input, a.retry_at, a.warned = "ok", None, 0.0, False
                a.seen_at = self.io.now()
                self.log(f"{a.name} is back")
        for hwnd, a in self.accounts.items():
            if hwnd not in wins and a.state != "closed":
                a.state = "closed"
                self.alarm(f"{a.name}: its Roblox window closed")

    def _watch_user(self):
        """Back off when the mouse moved and it wasn't us."""
        if not self.cfg.pause_on_user_input:
            return
        cur = self.io.cursor()
        if self._cursor is not None and _dist(cur, self._cursor) > 3:
            if self.io.now() >= self.user_until:
                self.log("You're using the PC - tapping waits, accounts stay connected")
            self.user_until = self.io.now() + self.cfg.user_grace_s
        self._cursor = cur

    def _watch_idle(self):
        now = self.io.now()
        for a in self.accounts.values():
            if a.state == "closed":
                continue
            # an account we never managed to touch is timed from when it appeared
            idle = now - (a.seen_at if a.last_input is None else a.last_input)
            if idle >= self.cfg.warn_idle_s:
                if not a.warned:
                    a.warned = True
                    self.alarm(
                        f"{a.name} has had no input for {int(idle // 60)} min - "
                        "it will disconnect soon, check its window"
                    )
            else:
                a.warned = False

    def _quiet(self, fn, *args):
        """Run a nice-to-have PC tweak; a failure must never stop the macro."""
        try:
            fn(*args)
        except Exception as e:
            self.log(f"Skipped {fn.__name__}: {e!r}")

    def _housekeep(self):
        cfg, now = self.cfg, self.io.now()
        live = self.live()
        if cfg.weak_pc and cfg.weak_trim_s and now >= self._next_trim:
            self._next_trim = now + cfg.weak_trim_s
            front = self.io.foreground()
            for a in live:
                if a.hwnd != front:
                    self._quiet(self.io.trim, a.hwnd)
        load = len(live) * self._overhead / cfg.safe_idle_s
        too_slow = load > (0.7 if self._slow_warned else 0.9)  # no flapping at the edge
        if too_slow and not self._slow_warned:
            self.alarm(
                f"This PC takes {self._overhead:.0f}s to switch accounts - too slow to keep "
                f"{len(live)} accounts safe. Close a few."
            )
        self._slow_warned = too_slow

    def live(self) -> list:
        return [a for a in self.accounts.values() if a.state != "closed"]

    def dwell(self) -> float:
        """Seconds of tapping per visit, shrunk so a full lap fits the safe window."""
        n = max(1, len(self.live()))
        budget = self.cfg.safe_idle_s * 0.8 / n - self._overhead
        return max(0.3, min(self.cfg.dwell_s, budget))

    def _pick(self):
        """Returns (account, full_visit). The account idle longest goes first."""
        now = self.io.now()
        ready = [a for a in self.live() if a.retry_at <= now]
        if not ready:
            return None, False
        keepalive_only = self.mode == "keepalive" or now < self.user_until
        if keepalive_only:
            # start early enough that the last account in the queue is still on time
            due = max(60.0, self.cfg.safe_idle_s - len(self.live()) * self._overhead)
            # (an account that just pressed Reconnect is always checked on promptly)
            ready = [a for a in ready if a.idle(now) >= due or a.state == "reconnecting"]
            if not ready:
                return None, False
        acc = max(ready, key=lambda a: a.idle(now))
        return acc, not keepalive_only

    # ---- visiting one account ----------------------------------------------
    def _visit(self, a: Account, full: bool):
        io, cfg = self.io, self.cfg
        restore = None if full else (io.foreground(), io.cursor())
        try:
            if not self._focus(a):
                return
            if cfg.weak_pc and cfg.weak_minimize and self._front not in (None, a.hwnd):
                if self._front in self.accounts and self.accounts[self._front].state != "closed":
                    self._quiet(io.minimize, self._front)
            self._front = a.hwnd
            a.visits += 1
            sent = False
            if cfg.reconnect_enabled and io.now() >= a.next_dc_check:
                a.next_dc_check = io.now() + DC_CHECK_S
                if self._handle_disconnect(a):
                    return
            if full:
                sent |= self._run_steps(a)
                if cfg.tap_enabled or cfg.egg_enabled:
                    sent |= self._tap(a)
            if not sent:
                self._nudge(a)
        except _Abort:
            pass
        finally:
            if restore:
                fg, cur = restore
                if fg and fg != a.hwnd and io.foreground() == a.hwnd:
                    io.focus(fg)
                    if cfg.weak_pc and cfg.weak_minimize:
                        self._quiet(io.minimize, a.hwnd)
                        self._front = None
                io.set_cursor(cur)
            self._cursor = io.cursor()

    def _focus(self, a: Account) -> bool:
        io, cfg = self.io, self.cfg
        t0 = io.now()
        if io.foreground() != a.hwnd:
            # A slow PC can take seconds to bring a window forward: ask, then wait
            # patiently, asking again twice more before giving up for now.
            timeout = max(cfg.focus_timeout_s, 10.0 if cfg.weak_pc else 0.0)
            deadline, ok = t0 + timeout, False
            while not ok and io.now() < deadline and not self.stopped:
                io.focus(a.hwnd)
                retry = min(deadline, io.now() + timeout / 3)
                while io.now() < retry:
                    io.sleep(0.04)
                    if io.foreground() == a.hwnd:
                        ok = True
                        break
            if not ok:
                a.focus_fails += 1
                a.retry_at = io.now() + min(15.0, 2.0 * a.focus_fails)
                if a.focus_fails == 3:
                    a.state = "blocked"
                    self.log(f"{a.name}: can't bring its window to the front, retrying")
                return False
            self._focus_ema += 0.2 * (io.now() - t0 - self._focus_ema)
            # the slower the window was to appear, the longer it needs before it listens
            settle = max(cfg.settle_s, 0.4 if cfg.weak_pc else 0.0, min(2.0, 0.5 * self._focus_ema))
            io.sleep(settle)
            self._overhead = max(0.3, self._overhead + 0.1 * (io.now() - t0 + 0.2 - self._overhead))
        if a.state == "blocked":
            a.state = "ok"
            self.log(f"{a.name}: window reachable again")
        a.focus_fails = 0
        return True

    def _send(self, a: Account, fn, guard_user: bool = True):
        """Send one input, but only if the right window is still in front."""
        io = self.io
        if self.stopped:
            raise _Abort
        if io.foreground() != a.hwnd:
            raise _Abort  # something else took focus: never type into it
        if guard_user and self.cfg.pause_on_user_input and self._cursor is not None:
            if _dist(io.cursor(), self._cursor) > 3:
                self._watch_user()
                raise _Abort
        fn()
        a.last_input = io.now()
        self._cursor = io.cursor()

    def _looks_disconnected(self, a: Account) -> bool:
        ref, tol = self.cfg.reconnect_color, self.cfg.reconnect_tolerance
        cols = self.io.sample(a.hwnd, DC_OFFSETS)
        hits = sum(1 for c in cols if all(abs(c[i] - ref[i]) <= tol for i in range(3)))
        return bool(cols) and hits >= 0.8 * len(cols)

    def _handle_disconnect(self, a: Account) -> bool:
        io, cfg = self.io, self.cfg
        if not self._looks_disconnected(a):
            if a.state == "reconnecting":
                a.state = "ok"
                self.log(f"{a.name}: back in the game")
            a.dc_streak = 0
            return False
        io.sleep(0.4)  # look twice so one odd frame can't trigger a click
        if not self._looks_disconnected(a):
            return False
        self._send(a, lambda: io.click_px(a.hwnd, cfg.reconnect_dx, cfg.reconnect_dy), False)
        a.reconnects += 1
        a.dc_streak += 1
        a.state = "reconnecting"
        a.retry_at = io.now() + cfg.reconnect_wait_s
        a.next_dc_check = 0.0
        if a.dc_streak == 3:
            self.alarm(f"{a.name}: Reconnect isn't working, it needs you")
        else:
            self.log(f"{a.name}: disconnect pop-up seen, pressed Reconnect")
        return True

    def _run_steps(self, a: Account) -> bool:
        io = self.io
        sent = False
        for s in self.cfg.steps:
            if not s.enabled:
                continue
            last = a.step_last.get(s.name)
            if last is not None and io.now() - last < s.every_s:
                continue
            for i in range(s.count):
                if s.kind == "click":
                    self._send(a, lambda: io.click(a.hwnd, s.x, s.y))
                else:
                    self._send(a, lambda: io.key(s.key, 0.05))
                sent = True
                io.sleep(s.gap_ms / 1000)
            a.step_last[s.name] = io.now()
        return sent

    def _tap(self, a: Account) -> bool:
        io, cfg = self.io, self.cfg
        gap = 1.0 / cfg.taps_per_second
        end = io.now() + self.dwell()
        sent, next_egg = False, 0.0
        while io.now() < end:
            self._hotkeys()
            if self.mode != "run":
                break
            if cfg.egg_enabled and io.now() >= next_egg:
                self._send(a, lambda: io.key(cfg.egg_key, 0.04))
                next_egg = io.now() + cfg.egg_every_s
                a.eggs += 1
                sent = True
            if cfg.tap_enabled:
                self._send(a, lambda: io.click(a.hwnd, cfg.tap_x, cfg.tap_y))
                a.taps += 1
                sent = True
            io.sleep(gap * self._rng.uniform(0.85, 1.15))
        return sent

    def _nudge(self, a: Account):
        """Smallest possible input that resets Roblox's idle timer."""
        io, cfg = self.io, self.cfg
        # A lagging PC can swallow a key press, so weak PC mode sends it twice.
        for i in range(2 if cfg.weak_pc else 1):
            if i:
                io.sleep(0.3)
            self._send(a, lambda: io.key(cfg.nudge_key, 0.06), False)
            if cfg.nudge_back_key:
                self._send(a, lambda: io.key(cfg.nudge_back_key, 0.06), False)


def _dist(p, q) -> float:
    return max(abs(p[0] - q[0]), abs(p[1] - q[1]))
