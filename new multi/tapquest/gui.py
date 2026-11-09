"""The window you see: start/pause/stop, live account table, settings, log."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from . import config as cfgmod
from .config import ROBLOX_IDLE_KICK_S, Config, ConfigError, Step
from .alerts import Notifier
from .engine import DC_OFFSETS, Engine, popup_color

BG, PANEL, FG, DIM = "#14161c", "#1e222b", "#e8eaf0", "#8b93a5"
GREEN, AMBER, RED, BLUE = "#3ddc84", "#ffb347", "#ff5c5c", "#5aa9ff"


def _mmss(s) -> str:
    if s is None:
        return "-"
    s = int(max(0, s))
    return f"{s // 60}:{s % 60:02d}"


class App:
    def __init__(self, io, settings_path: str, demo: bool = False):
        self.io, self.path, self.demo = io, settings_path, demo
        self.engine: Engine | None = None
        self.thread: threading.Thread | None = None
        self.logq: queue.Queue = queue.Queue()
        self.capture = None  # callback waiting for an F7 position
        try:
            self.cfg = cfgmod.load(settings_path)
            load_error = None
        except ConfigError as e:
            self.cfg, load_error = Config(), str(e)

        self.root = r = tk.Tk()
        r.title(f"Tap Quest Multi {__version__}" + ("  (DEMO - simulated accounts)" if demo else ""))
        r.configure(bg=BG)
        r.geometry("1120x650")
        r.minsize(1080, 620)
        self._style()
        self._build()
        self._fill_from_cfg()
        r.protocol("WM_DELETE_WINDOW", self.close)
        r.after(200, self._poll)
        if load_error:
            self._log("Settings file had a problem, using defaults: " + load_error)
        self._log("Ready. Open your Roblox windows, then press Start.")

    # ---- layout ------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Dim.TLabel", foreground=DIM)
        s.configure("Panel.TLabel", background=PANEL)
        s.configure("PanelDim.TLabel", background=PANEL, foreground=DIM)
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("TButton", background="#2b3140", foreground=FG, padding=(12, 7), borderwidth=0)
        s.map("TButton", background=[("active", "#394156"), ("disabled", "#20242d")],
              foreground=[("disabled", "#59607a")])
        s.configure("Go.TButton", background="#1f8f55")
        s.map("Go.TButton", background=[("active", "#27a866"), ("disabled", "#20242d")])
        s.configure("Stop.TButton", background="#a83838")
        s.map("Stop.TButton", background=[("active", "#c44545"), ("disabled", "#20242d")])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=26, borderwidth=0, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        s.configure("Treeview.Heading", background="#262b36", foreground=DIM, borderwidth=0)
        s.map("Treeview", background=[("selected", "#2f3646")])
        s.configure("TEntry", insertcolor=FG)
        s.configure("Vertical.TScrollbar", background="#2b3140", troughcolor=PANEL, borderwidth=0,
                    arrowcolor=DIM)

    def _build(self):
        r = self.root
        top = ttk.Frame(r, padding=(16, 14, 16, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Tap Quest Multi", font=("Segoe UI", 17, "bold")).pack(side="left")
        self.status = tk.Label(top, text="STOPPED", bg="#2b3140", fg=FG, padx=12, pady=4,
                               font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left", padx=14)
        self.b_stop = ttk.Button(top, text="Stop  (F8)", style="Stop.TButton", command=self.stop)
        self.b_stop.pack(side="right")
        self.b_pause = ttk.Button(top, text="Pause tapping  (F6)", command=self.toggle_pause)
        self.b_pause.pack(side="right", padx=8)
        self.b_start = ttk.Button(top, text="Start", style="Go.TButton", command=self.start)
        self.b_start.pack(side="right")

        self.summary = ttk.Label(r, text="", style="Dim.TLabel", padding=(18, 0, 16, 6))
        self.summary.pack(fill="x")

        mid = ttk.Frame(r, padding=(16, 0, 16, 8))
        mid.pack(fill="both", expand=True)
        side = ttk.Frame(mid, style="Panel.TFrame", padding=12)
        side.pack(side="right", fill="y", padx=(12, 0))
        self.v = {
            "tps": tk.StringVar(), "dwell": tk.StringVar(), "round": tk.StringVar(), "tx": tk.StringVar(), "ty": tk.StringVar(),
            "tap": tk.BooleanVar(), "user": tk.BooleanVar(), "rec": tk.BooleanVar(),
            "weak": tk.BooleanVar(), "egg": tk.BooleanVar(), "hook": tk.StringVar(),
        }
        ttk.Label(side, text="SETTINGS", style="PanelDim.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self._row(side, 1, "Taps per second", "tps")
        self._row(side, 2, "Seconds per account", "dwell")
        self._row(side, 13, "Round every (sec, 0 = nonstop)", "round")
        ttk.Label(side, text="Tap spot (x, y)", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(side, textvariable=self.v["tx"], width=6).grid(row=3, column=1, padx=(8, 2))
        ttk.Entry(side, textvariable=self.v["ty"], width=6).grid(row=3, column=2)
        ttk.Button(side, text="Pick tap spot (F7)", command=self.pick_tap).grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        for i, (key, text) in enumerate((
            ("tap", "Auto-tap"),
            ("egg", "Auto egg (presses R)"),
            ("user", "Wait while I use the mouse"),
            ("rec", "Press Reconnect on disconnect"),
            ("weak", "Weak PC mode (20+ accounts)"),
        )):
            ttk.Checkbutton(side, text=text, variable=self.v[key]).grid(
                row=5 + i, column=0, columnspan=3, sticky="w")
        ttk.Label(side, text="EXTRA STEPS (per account)", style="PanelDim.TLabel").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(12, 2))
        self.steps = tk.Listbox(side, height=3, bg=BG, fg=FG, highlightthickness=0, borderwidth=0,
                                selectbackground="#2f3646", activestyle="none", width=30)
        self.steps.grid(row=11, column=0, columnspan=3, sticky="ew")
        bar = ttk.Frame(side, style="Panel.TFrame")
        bar.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="+ Click", command=lambda: self.add_step("click")).pack(side="left")
        ttk.Button(bar, text="+ Key", command=lambda: self.add_step("key")).pack(side="left", padx=4)
        ttk.Button(bar, text="Remove", command=self.remove_step).pack(side="left")

        cols = ("name", "state", "idle", "left", "visits", "taps", "eggs", "rec")
        heads = ("Account", "Status", "Last input", "Kick timer left", "Visits", "Taps", "Egg keys", "Reconnects")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=7)
        for c, h, w in zip(cols, heads, (92, 108, 82, 100, 44, 62, 64, 78)):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "state") else "center")
        for tag, col in (("ok", GREEN), ("warn", AMBER), ("bad", RED), ("info", BLUE)):
            self.tree.tag_configure(tag, foreground=col)
        scroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        tools = ttk.Frame(r, padding=(16, 0, 16, 8))
        tools.pack(fill="x")
        ttk.Button(tools, text="Skip / unskip selected account", command=self.toggle_skip).pack(side="left")
        ttk.Button(tools, text="Set up Reconnect (F7)", command=self.setup_reconnect).pack(side="left", padx=8)
        ttk.Label(tools, text="Discord alert webhook", style="Dim.TLabel").pack(side="left", padx=(8, 6))
        ttk.Entry(tools, textvariable=self.v["hook"]).pack(side="left", fill="x", expand=True)
        ttk.Button(tools, text="Test", command=self.test_alert).pack(side="left", padx=(8, 0))

        self.logbox = tk.Text(r, height=5, bg=PANEL, fg=DIM, borderwidth=0, highlightthickness=0,
                              font=("Consolas", 9), padx=10, pady=8, state="disabled", wrap="word")
        self.logbox.pack(fill="x", padx=16, pady=(0, 14))
        self.logbox.tag_configure("alert", foreground=RED)

    def _row(self, parent, row, text, key):
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self.v[key], width=6).grid(row=row, column=1, columnspan=2,
                                                                 sticky="e", padx=(8, 0))

    # ---- settings <-> widgets ----------------------------------------------
    def _fill_from_cfg(self):
        c, v = self.cfg, self.v
        v["tps"].set(f"{c.taps_per_second:g}")
        v["dwell"].set(f"{c.dwell_s:g}")
        v["round"].set(f"{c.round_every_s:g}")
        v["tx"].set(f"{c.tap_x:g}")
        v["ty"].set(f"{c.tap_y:g}")
        v["tap"].set(c.tap_enabled)
        v["user"].set(c.pause_on_user_input)
        v["rec"].set(c.reconnect_enabled)
        v["weak"].set(c.weak_pc)
        v["egg"].set(c.egg_enabled)
        v["hook"].set(c.alert_webhook)
        self._fill_steps()

    def _fill_steps(self):
        self.steps.delete(0, "end")
        for s in self.cfg.steps:
            what = f"click {s.x:.2f},{s.y:.2f}" if s.kind == "click" else f"key {s.key.upper()}"
            times = f" x{s.count}" if s.count > 1 else ""
            self.steps.insert("end", f"{s.name}: {what}{times} every {s.every_s:g}s")

    def _read_cfg(self) -> Config:
        """Build settings from the widgets; raises ConfigError with a readable message."""
        c, v = self.cfg, self.v
        try:
            data = dict(c.to_dict(), taps_per_second=float(v["tps"].get()), dwell_s=float(v["dwell"].get()), round_every_s=float(v["round"].get()),
                        tap_x=float(v["tx"].get()), tap_y=float(v["ty"].get()),
                        tap_enabled=v["tap"].get(), pause_on_user_input=v["user"].get(),
                        reconnect_enabled=v["rec"].get(), weak_pc=v["weak"].get(), egg_enabled=v["egg"].get(),
                        alert_webhook=v["hook"].get().strip())
        except ValueError:
            raise ConfigError("Settings boxes must contain numbers") from None
        return Config.from_dict(data)

    # ---- buttons -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return
        try:
            self.cfg = self._read_cfg()
            cfgmod.save(self.cfg, self.path)
        except (ConfigError, OSError) as e:
            messagebox.showerror("Check your settings", str(e))
            return
        hook = self.cfg.alert_webhook
        self.engine = Engine(self.cfg, self.io, log=self.logq.put,
                             notify=Notifier(hook).send if hook else None)
        if hasattr(self.io, "keep_awake"):
            self.io.keep_awake(True)
        self.thread = threading.Thread(target=self._run_engine, args=(self.engine,), daemon=True)
        self.thread.start()
        self._log("Started")

    def _run_engine(self, engine: Engine):
        try:
            engine.run()
        finally:
            self.logq.put("Stopped")

    def stop(self):
        if self.engine:
            self.engine.stop()
        if self.thread:
            self.thread.join(timeout=5)
        if hasattr(self.io, "keep_awake"):
            self.io.keep_awake(False)

    def toggle_pause(self):
        if self.running:
            self.engine.set_mode("keepalive" if self.engine.mode == "run" else "run")

    def close(self):
        if self.running and not messagebox.askokcancel(
            "Quit?", "The macro is running. If you quit, your accounts will idle out in 20 minutes."):
            return
        self.stop()
        self.root.destroy()

    def pick_tap(self):
        def got(fx, fy):
            self.v["tx"].set(f"{fx:g}")
            self.v["ty"].set(f"{fy:g}")
        self._capture(got)

    def toggle_skip(self):
        sel = self.tree.selection()
        if not self.running or not sel:
            self._log("Start the macro and click an account in the table first")
            return
        self.engine.toggle_skip(self.tree.index(sel[0]))

    def setup_reconnect(self):
        """Learn the real pop-up: its colour, and where its Reconnect button is."""
        def got(hwnd, dx, dy):
            color = popup_color(self.io.sample(hwnd, DC_OFFSETS))
            if color is None:
                self._log("No disconnect pop-up found in that window - do this while it is showing")
                return
            self.cfg.reconnect_dx, self.cfg.reconnect_dy, self.cfg.reconnect_color = dx, dy, color
            self._save_quietly()
            self._log(f"Reconnect learned: button at {dx},{dy}, pop-up colour {color}")
        self._capture(got, "offset")
        if self.capture:
            self._log("When an account shows the Disconnected pop-up: hover its Reconnect button, press F7")

    def test_alert(self):
        url = self.v["hook"].get().strip()
        if not url.startswith("https://"):
            self._log("Paste your Discord webhook link (starts with https://) first")
            return
        n = Notifier(url, threaded=False)
        n.send("Tap Quest Multi: test alert - this is where problems will be reported")
        self._log("Test alert failed - check the link and your internet" if n.errors else "Test alert sent")

    def _capture(self, callback, kind="frac"):
        if not hasattr(self.io, "point_fraction"):
            messagebox.showinfo("Demo mode", "Picking a spot works on your PC with Roblox open.")
            return
        if self.running:
            messagebox.showinfo("Stop first", "Stop the macro before picking a spot.")
            return
        self.capture, self.capture_kind = callback, kind
        self.io.pressed("capture")  # forget any earlier press
        if kind == "frac":
            self._log("Hover the mouse over the spot inside a Roblox window, then press F7")

    def add_step(self, kind: str):
        StepDialog(self, kind)

    def remove_step(self):
        sel = self.steps.curselection()
        if sel:
            del self.cfg.steps[sel[0]]
            self._fill_steps()
            self._save_quietly()

    def _save_quietly(self):
        try:
            cfgmod.save(self.cfg, self.path)
        except (ConfigError, OSError) as e:
            self._log(f"Could not save settings: {e}")

    # ---- refresh -----------------------------------------------------------
    def _log(self, msg: str):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n",
                           "alert" if msg.startswith("ALERT") else "")
        if int(self.logbox.index("end").split(".")[0]) > 400:
            self.logbox.delete("1.0", "100.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                self._log(self.logq.get_nowait())
        except queue.Empty:
            pass
        if self.capture and self.io.pressed("capture"):
            frac = self.io.point_offset() if self.capture_kind == "offset" else self.io.point_fraction()
            if frac is None:
                self._log("That spot isn't inside a Roblox window - try again (F7)")
            else:
                cb, self.capture = self.capture, None
                cb(*frac)
                if self.capture_kind == "frac":
                    self._log(f"Spot saved: {frac[0]:.3f}, {frac[1]:.3f}")
        # Weak PC mode redraws the table less often to leave CPU for the games.
        self._tick = getattr(self, "_tick", 0) + 1
        if not self.cfg.weak_pc or self._tick % 4 == 0:
            self._refresh()
        self.root.after(250, self._poll)

    def _refresh(self):
        running = self.running
        self.b_start.state(["disabled" if running else "!disabled"])
        self.b_stop.state(["!disabled" if running else "disabled"])
        self.b_pause.state(["!disabled" if running else "disabled"])
        if not running or not self.engine:
            self.status.configure(text="STOPPED", bg="#2b3140", fg=FG)
            self.b_pause.configure(text="Pause tapping  (F6)")
            self.summary.configure(text="Accounts are NOT being kept connected while stopped.")
            return
        snap = self.engine.snapshot()
        paused = snap["mode"] == "keepalive"
        self.b_pause.configure(text="Resume tapping  (F6)" if paused else "Pause tapping  (F6)")
        if paused:
            self.status.configure(text="KEEP-ALIVE ONLY", bg=AMBER, fg="#1a1a1a")
        elif snap["user_active"]:
            self.status.configure(text="WAITING FOR YOU", bg=BLUE, fg="#10131a")
        else:
            self.status.configure(text="RUNNING", bg=GREEN, fg="#0d1a12")
        accs = snap["accounts"]
        live = [a for a in accs if a["state"] != "closed"]
        eggs = sum(a["eggs"] for a in accs)
        hours = max(snap["uptime"], 1.0) / 3600
        self.summary.configure(
            text=f"{len(live)} open   |   up {_mmss(snap['uptime'] / 60)} h   |   "
                 f"{sum(a['taps'] for a in accs):,} taps   |   {eggs:,} egg keys ({eggs / hours:,.0f}/h)   |   "
                 f"{snap['dwell']:.1f}s per account, lap {_mmss(snap['lap'])}   |   input at least every "
                 f"{_mmss(self.cfg.safe_idle_s)}")
        rows = self.tree.get_children()
        for extra in rows[len(accs):]:
            self.tree.delete(extra)
        labels = {"ok": "Connected", "reconnecting": "Reconnecting...", "blocked": "Window stuck",
                  "closed": "Window closed", "skipped": "Skipped (yours)"}
        for i, a in enumerate(accs):
            idle = a["idle"]
            left = None if idle is None else ROBLOX_IDLE_KICK_S - idle
            tag = "ok"
            if a["state"] == "closed":
                tag, left = "bad", None
            elif a["state"] in ("reconnecting", "skipped"):
                tag = "info"
            elif a["state"] == "blocked" or (idle is not None and idle >= self.cfg.warn_idle_s):
                tag = "bad"
            elif idle is None or idle > self.cfg.safe_idle_s * 1.25:
                tag = "warn"
            values = (
                a["name"], labels[a["state"]] if idle is not None or a["state"] != "ok" else "Waiting...",
                "-" if idle is None else _mmss(idle) + " ago", _mmss(left),
                a["visits"], f"{a['taps']:,}", f"{a['eggs']:,}", a["reconnects"])
            if i < len(rows):  # update in place so the list keeps its scroll position
                self.tree.item(rows[i], values=values, tags=(tag,))
            else:
                self.tree.insert("", "end", values=values, tags=(tag,))

    def run(self):
        self.root.mainloop()


class StepDialog:
    def __init__(self, app: App, kind: str):
        self.app, self.kind = app, kind
        self.win = w = tk.Toplevel(app.root)
        w.title("Add click step" if kind == "click" else "Add key step")
        w.configure(bg=PANEL, padx=16, pady=14)
        w.transient(app.root)
        self.name = tk.StringVar(value="Claim quest" if kind == "click" else "Press key")
        self.key = tk.StringVar(value="e")
        self.every = tk.StringVar(value="60")
        self.count = tk.StringVar(value="1")
        rows = [("Name", self.name)]
        if kind == "key":
            rows.append(("Key (a-z, 0-9, space, enter...)", self.key))
        rows += [("Every (seconds)", self.every), ("Times in a row", self.count)]
        for i, (text, var) in enumerate(rows):
            ttk.Label(w, text=text, style="Panel.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(w, textvariable=var, width=18).grid(row=i, column=1, padx=(12, 0))
        text = "Next: pick the spot (F7)" if kind == "click" else "Add"
        ttk.Button(w, text=text, style="Go.TButton", command=self.ok).grid(
            row=len(rows), column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def ok(self):
        try:
            step = Step(name=self.name.get().strip() or "Step", kind=self.kind,
                        key=self.key.get().strip().lower(), every_s=float(self.every.get()),
                        count=int(self.count.get()))
            Config(steps=self.app.cfg.steps + [step]).validate()
        except (ValueError, ConfigError) as e:
            messagebox.showerror("Check the step", str(e), parent=self.win)
            return
        self.win.destroy()
        if self.kind == "key":
            self._add(step)
        else:
            def got(fx, fy):
                step.x, step.y = fx, fy
                self._add(step)
            self.app._capture(got)

    def _add(self, step: Step):
        self.app.cfg.steps.append(step)
        self.app._fill_steps()
        self.app._save_quietly()
