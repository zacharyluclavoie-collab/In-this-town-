"""The real PC: finds Roblox windows and sends them clicks and keys (Windows only).

Uses only what ships with Python (ctypes), so there is nothing extra to install.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import c_int32, c_size_t, c_uint16, c_uint32

# --- SendInput structures (fixed-width so the layout is checkable anywhere) ---


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", c_int32),
        ("dy", c_int32),
        ("mouseData", c_uint32),
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", c_uint16),
        ("wScan", c_uint16),
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", c_uint32), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class RECT(ctypes.Structure):
    _fields_ = [("left", c_int32), ("top", c_int32), ("right", c_int32), ("bottom", c_int32)]


VK = {chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)}
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({"space": 0x20, "enter": 0x0D, "tab": 0x09})
VK.update({"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28})
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})
EXTENDED = {"left", "up", "right", "down"}

HOTKEYS = {"stop": "f8", "pause": "f6", "capture": "f7"}

MOUSE_MOVE, MOUSE_DOWN, MOUSE_UP = 0x0001, 0x0002, 0x0004
KEY_EXTENDED, KEY_UP, KEY_SCANCODE = 0x0001, 0x0002, 0x0008


class WinIO:
    def __init__(self, process_names):
        self.u = ctypes.windll.user32
        self.k = ctypes.windll.kernel32
        self.g = ctypes.windll.gdi32
        self.ps = ctypes.windll.psapi
        self.names = {n.lower() for n in process_names}
        self._held = {name: False for name in HOTKEYS}
        self._declare()
        try:  # so window coordinates are real pixels on scaled displays
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            self.u.SetProcessDPIAware()

    def _declare(self):
        u, k, g = self.u, self.k, self.g
        H, B, I, D = ctypes.c_void_p, ctypes.c_int, ctypes.c_int, c_uint32
        sig = {
            u.GetForegroundWindow: (H, []),
            u.SetForegroundWindow: (B, [H]),
            u.BringWindowToTop: (B, [H]),
            u.IsWindowVisible: (B, [H]),
            u.IsIconic: (B, [H]),
            u.ShowWindow: (B, [H, I]),
            u.GetWindow: (H, [H, D]),
            u.GetWindowTextW: (I, [H, ctypes.c_wchar_p, I]),
            u.GetWindowThreadProcessId: (D, [H, ctypes.POINTER(D)]),
            u.AttachThreadInput: (B, [D, D, B]),
            u.GetClientRect: (B, [H, ctypes.POINTER(RECT)]),
            u.ClientToScreen: (B, [H, ctypes.POINTER(POINT)]),
            u.GetCursorPos: (B, [ctypes.POINTER(POINT)]),
            u.SetCursorPos: (B, [I, I]),
            u.SendInput: (D, [D, ctypes.POINTER(INPUT), I]),
            u.MapVirtualKeyW: (D, [D, D]),
            u.GetAsyncKeyState: (ctypes.c_short, [I]),
            u.GetDC: (H, [H]),
            u.ReleaseDC: (I, [H, H]),
            u.MessageBeep: (B, [D]),
            g.GetPixel: (D, [H, I, I]),
            k.OpenProcess: (H, [D, B, D]),
            k.CloseHandle: (B, [H]),
            k.QueryFullProcessImageNameW: (B, [H, D, ctypes.c_wchar_p, ctypes.POINTER(D)]),
            k.GetCurrentThreadId: (D, []),
            k.SetThreadExecutionState: (D, [D]),
            u.SetWindowPos: (B, [H, H, I, I, I, I, D]),
            k.SetPriorityClass: (B, [H, D]),
            k.GetCurrentProcess: (H, []),
            self.ps.EmptyWorkingSet: (B, [H]),
        }
        for fn, (res, args) in sig.items():
            fn.restype, fn.argtypes = res, args

    # ---- time --------------------------------------------------------------
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, s: float):
        time.sleep(s)

    def keep_awake(self, on: bool):
        """Stop Windows sleeping or locking the screen while the macro runs."""
        ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x1, 0x2
        self.k.SetThreadExecutionState(ES_CONTINUOUS | ((ES_SYSTEM | ES_DISPLAY) if on else 0))

    # ---- windows -----------------------------------------------------------
    def _is_roblox(self, pid: int) -> bool:
        ok = False
        h = self.k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            size = c_uint32(1024)
            if self.k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                ok = os.path.basename(buf.value).lower() in self.names
            self.k.CloseHandle(h)
        return ok

    def list_windows(self):
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def each(hwnd, _):
            if self.u.IsWindowVisible(hwnd) and not self.u.GetWindow(hwnd, 4):  # no owner
                pid = c_uint32()
                self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if self._is_roblox(pid.value):
                    title = ctypes.create_unicode_buffer(256)
                    self.u.GetWindowTextW(hwnd, title, 256)
                    if title.value:
                        found.append((hwnd, title.value))
            return 1

        self.u.EnumWindows(proto(each), 0)
        return found

    def foreground(self):
        return self.u.GetForegroundWindow()

    # ---- weak PC helpers ---------------------------------------------------
    def _with_process(self, hwnd, access, fn):
        pid = c_uint32()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = self.k.OpenProcess(access, False, pid.value)
        if h:
            try:
                fn(h)
            finally:
                self.k.CloseHandle(h)

    def minimize(self, hwnd):
        self.u.ShowWindow(hwnd, 7)  # minimise without stealing focus

    def resize(self, hwnd, w, h):
        """Small windows cost far less GPU and memory than big ones."""
        self.u.ShowWindow(hwnd, 4)  # un-maximise without stealing focus
        self.u.SetWindowPos(hwnd, None, 0, 0, w, h, 0x0002 | 0x0004 | 0x0010)  # keep place/order

    def tune(self, hwnd):
        """Roblox below normal priority, the macro above: taps stay on time."""
        self._with_process(hwnd, 0x0200, lambda h: self.k.SetPriorityClass(h, 0x4000))
        self.k.SetPriorityClass(self.k.GetCurrentProcess(), 0x8000)

    def trim(self, hwnd):
        """Ask Windows to move this account's unused memory out of RAM."""
        self._with_process(hwnd, 0x0400 | 0x0100, lambda h: self.ps.EmptyWorkingSet(h))

    def focus(self, hwnd):
        u = self.u
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)  # restore a minimised window
        u.SetForegroundWindow(hwnd)
        if u.GetForegroundWindow() == hwnd:
            return
        # Windows refuses focus changes from background apps; borrow the
        # foreground thread's permission, then try again.
        fg = u.GetForegroundWindow()
        mine = self.k.GetCurrentThreadId()
        theirs = u.GetWindowThreadProcessId(fg, None) if fg else 0
        if theirs and theirs != mine:
            u.AttachThreadInput(mine, theirs, True)
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if theirs and theirs != mine:
                u.AttachThreadInput(mine, theirs, False)
        if u.GetForegroundWindow() != hwnd:
            self._key_event(0x12, 0, 0)  # tapping Alt also unlocks focus changes
            self._key_event(0x12, 0, KEY_UP)
            u.SetForegroundWindow(hwnd)

    def _client(self, hwnd):
        r, p = RECT(), POINT(0, 0)
        self.u.GetClientRect(hwnd, ctypes.byref(r))
        self.u.ClientToScreen(hwnd, ctypes.byref(p))
        return p.x, p.y, r.right, r.bottom

    def cursor(self):
        p = POINT()
        self.u.GetCursorPos(ctypes.byref(p))
        return (p.x, p.y)

    def set_cursor(self, pos):
        self.u.SetCursorPos(int(pos[0]), int(pos[1]))

    def point_fraction(self):
        """Mouse position as a fraction of the Roblox window under it, or None."""
        cx, cy = self.cursor()
        for hwnd, _ in self.list_windows():
            x, y, w, h = self._client(hwnd)
            if w > 0 and h > 0 and x <= cx < x + w and y <= cy < y + h:
                return round((cx - x) / w, 4), round((cy - y) / h, 4)
        return None

    # ---- input -------------------------------------------------------------
    def _mouse(self, flags, dx=0, dy=0):
        inp = INPUT(type=0)
        inp.u.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
        self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _key_event(self, vk, scan, flags):
        inp = INPUT(type=1)
        inp.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _click_at(self, x, y):
        self.u.SetCursorPos(x, y)
        # Roblox ignores clicks unless the mouse really moved onto the spot.
        self._mouse(MOUSE_MOVE, 1, 0)
        self._mouse(MOUSE_MOVE, -1, 0)
        self._mouse(MOUSE_DOWN)
        time.sleep(0.015)
        self._mouse(MOUSE_UP)

    def click(self, hwnd, fx, fy):
        x, y, w, h = self._client(hwnd)
        self._click_at(x + int(fx * (w - 1)), y + int(fy * (h - 1)))

    def click_px(self, hwnd, dx, dy):
        x, y, w, h = self._client(hwnd)
        self._click_at(x + w // 2 + dx, y + h // 2 + dy)

    def key(self, name, hold_s):
        vk = VK[name]
        scan = self.u.MapVirtualKeyW(vk, 0)
        flags = KEY_SCANCODE | (KEY_EXTENDED if name in EXTENDED else 0)
        self._key_event(0, scan, flags)
        time.sleep(hold_s)
        self._key_event(0, scan, flags | KEY_UP)

    def sample(self, hwnd, offsets):
        x, y, w, h = self._client(hwnd)
        cx, cy = x + w // 2, y + h // 2
        dc = self.u.GetDC(None)
        try:
            out = []
            for dx, dy in offsets:
                c = self.g.GetPixel(dc, cx + dx, cy + dy)
                out.append((c & 255, (c >> 8) & 255, (c >> 16) & 255))
            return out
        finally:
            self.u.ReleaseDC(None, dc)

    def pressed(self, name) -> bool:
        """True once each time the hotkey goes down."""
        down = bool(self.u.GetAsyncKeyState(VK[HOTKEYS[name]]) & 0x8000)
        was, self._held[name] = self._held[name], down
        return down and not was

    def hotkey(self):
        for name in ("stop", "pause"):
            if self.pressed(name):
                return name
        return None

    def beep(self):
        self.u.MessageBeep(0x30)
