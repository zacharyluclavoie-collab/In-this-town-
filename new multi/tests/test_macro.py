"""Run with:  python -m unittest discover -s tests   (from the "new multi" folder)"""

import ctypes
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tapquest import config as cfgmod
from tapquest.config import Config, ConfigError, Step
from tapquest.engine import Engine
from tapquest.sim import USER_WINDOW, SimIO

HOUR = 3600


def run(io, cfg=None, hours=24, mode="run", seed=1):
    eng = Engine(cfg or Config(), io, seed=seed, strict=True)
    eng.set_mode(mode)
    eng.run(until=hours * HOUR)
    return eng


class StayConnected(unittest.TestCase):
    def test_24h_clean_run_many_account_counts(self):
        for n in (1, 2, 5, 10, 25, 60):
            with self.subTest(accounts=n):
                io = SimIO(accounts=n, seed=n)
                eng = run(io, hours=24 if n <= 10 else 8)
                self.assertEqual(io.idle_kicks, 0)
                self.assertEqual(io.stray_inputs, 0)
                self.assertLess(io.max_idle, Config().safe_idle_s)
                self.assertEqual(eng.alarms, 0)
                for w in io.windows.values():
                    self.assertGreater(w.clicks, 100)

    def test_taps_are_shared_evenly(self):
        io = SimIO(accounts=6, seed=3)
        run(io, hours=4)
        clicks = [w.clicks for w in io.windows.values()]
        self.assertLess(max(clicks) - min(clicks), 0.05 * max(clicks))

    def test_24h_chaos(self):
        """Flaky focus, network drops, stuck windows, and (half the runs) a person on the PC."""
        for seed in range(6):
            user = seed % 2 == 1
            with self.subTest(seed=seed, user=user):
                io = SimIO(
                    accounts=8,
                    seed=seed,
                    focus_fail=0.25,
                    user_per_hour=6 if user else 0,
                    netdrop_per_hour=0.5,
                    block_per_hour=2,
                )
                eng = run(io, hours=24, seed=seed)
                self.assertEqual(io.idle_kicks, 0)
                self.assertEqual(io.stray_inputs, 0)
                self.assertLess(io.max_idle, 900)
                self.assertGreater(io.net_drops, 20)
                # Every network drop was noticed and reconnected. While a person is
                # on the PC the macro only checks in every safe_idle_s, so it's slower.
                self.assertLess(io.max_dc_time, 700 if user else 240)
                self.assertGreaterEqual(sum(a.reconnects for a in eng.accounts.values()), io.net_drops - 8)

    def test_paused_keeps_accounts_alive_without_tapping(self):
        io = SimIO(accounts=5, seed=2)
        eng = run(io, hours=24, mode="keepalive")
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)
        self.assertEqual(sum(w.clicks for w in io.windows.values()), 0)
        self.assertEqual(sum(a.taps for a in eng.accounts.values()), 0)
        self.assertLess(io.max_idle, 600)

    def test_person_on_pc_nonstop_for_12h(self):
        io = SimIO(accounts=6, seed=5)
        io.always_user = True
        eng = run(io, hours=12)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)
        self.assertLess(io.max_idle, 600)
        # it stayed out of the way: only keep-alive visits, a handful per hour each
        for a in eng.accounts.values():
            self.assertLess(a.visits, 12 * 10)

    def test_keepalive_visit_hands_window_and_mouse_back(self):
        io = SimIO(accounts=2, seed=1)
        eng = Engine(Config(), io, seed=1, strict=True)
        eng.set_mode("keepalive")
        eng._cursor = io.cursor()
        io.fg, io.cur = USER_WINDOW, (321, 123)
        eng.tick()  # first visit (accounts have never been touched)
        self.assertEqual(io.fg, USER_WINDOW)
        self.assertEqual(io.cur, (321, 123))
        self.assertEqual(sum(w.keys for w in io.windows.values()), 2)

    def test_input_never_sent_when_focus_is_stolen(self):
        io = SimIO(accounts=3, seed=9, focus_fail=1.0)  # focus never works
        run(io, hours=1)
        self.assertEqual(io.stray_inputs, 0)
        self.assertEqual(sum(w.clicks + w.keys for w in io.windows.values()), 0)

    def test_alarm_before_a_stuck_account_gets_kicked(self):
        io = SimIO(accounts=3, seed=4)
        io.windows[101].blocked_until = 10**9  # one window can never be focused
        eng = Engine(Config(), io, seed=4, strict=True)
        eng.run(until=1000)
        self.assertEqual(io.idle_kicks, 0)
        self.assertGreaterEqual(eng.alarms, 1)
        self.assertEqual(eng.accounts[101].state, "blocked")
        # the other accounts were not starved by the stuck one
        self.assertGreater(io.windows[100].clicks, 1000)
        self.assertGreater(io.windows[102].clicks, 1000)

    def test_crashed_window_is_reported_and_new_one_picked_up(self):
        io = SimIO(accounts=3, seed=6)
        eng = Engine(Config(), io, seed=6, strict=True)
        eng.run(until=60)
        del io.windows[101]
        eng.run(until=120)
        self.assertEqual(eng.accounts[101].state, "closed")
        self.assertEqual(eng.alarms, 1)
        from tapquest.sim import SimWindow

        io.windows[777] = SimWindow(777, last_input=io.t)
        eng.run(until=4 * HOUR)
        self.assertIn(777, eng.accounts)
        self.assertGreater(io.windows[777].clicks, 100)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_crashes_during_long_run(self):
        io = SimIO(accounts=10, seed=8, crash_per_hour=0.1, focus_fail=0.1)
        run(io, hours=24)
        self.assertGreater(io.crashes, 3)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_no_accounts_open_just_waits(self):
        io = SimIO(accounts=0)
        run(io, hours=1)
        self.assertEqual(io.stray_inputs, 0)


class Features(unittest.TestCase):
    def test_steps_fire_on_schedule_for_every_account(self):
        cfg = Config(steps=[
            Step(name="Claim quest", x=0.9, y=0.2, every_s=300, count=2),
            Step(name="Rebirth", kind="key", key="r", every_s=1800),
            Step(name="Off", x=0.1, y=0.1, every_s=10, enabled=False),
        ])
        io = SimIO(accounts=4, seed=2)
        run(io, cfg, hours=5)
        for w in io.windows.values():
            # 5h / 300s = 60 rounds of 2 clicks; allow for lap timing
            self.assertTrue(110 <= w.step_clicks <= 122, w.step_clicks)
            self.assertTrue(9 <= w.keys <= 11, w.keys)

    def test_auto_egg_presses_key_on_every_account(self):
        for tap in (True, False):
            with self.subTest(tap=tap):
                io = SimIO(accounts=4, seed=2)
                eng = run(io, Config(egg_enabled=True, tap_enabled=tap), hours=2)
                for w in io.windows.values():
                    # 2h shared by 4 accounts, one press a second
                    self.assertTrue(1400 <= w.keys <= 1900, w.keys)
                    self.assertEqual(w.clicks > 0, tap)
                self.assertEqual(sum(a.eggs for a in eng.accounts.values()),
                                 sum(w.keys for w in io.windows.values()))
                self.assertEqual(io.idle_kicks, 0)
                self.assertEqual(io.stray_inputs, 0)
        with self.assertRaises(ConfigError):
            Config(egg_key="banana").validate()

    def test_round_mode_visits_each_account_once_per_round(self):
        cfg = Config(round_every_s=60, dwell_s=1, egg_enabled=True)
        io = SimIO(accounts=4, seed=2)
        eng = run(io, cfg, hours=1)
        for a in eng.accounts.values():
            self.assertTrue(56 <= a.visits <= 61, a.visits)
            self.assertTrue(a.visits <= a.eggs <= 2 * a.visits, a.eggs)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_long_gap_between_rounds_still_stays_connected(self):
        io = SimIO(accounts=5, seed=2)
        eng = run(io, Config(round_every_s=3600, dwell_s=1, egg_enabled=True), hours=12)
        self.assertEqual(io.idle_kicks, 0)
        self.assertLess(io.max_idle, 600)
        for a in eng.accounts.values():
            self.assertTrue(12 <= a.eggs <= 26, a.eggs)
        with self.assertRaises(ConfigError):
            Config(round_every_s=2).validate()

    def test_dwell_shrinks_so_a_lap_fits_the_safe_window(self):
        cfg = Config(dwell_s=120)
        io = SimIO(accounts=20, seed=1)
        eng = run(io, cfg, hours=6)
        self.assertLess(eng.dwell(), 20)
        self.assertEqual(io.idle_kicks, 0)
        self.assertLess(io.max_idle, cfg.safe_idle_s)

    def test_tapping_off_still_stays_connected(self):
        io = SimIO(accounts=4, seed=1)
        run(io, Config(tap_enabled=False), hours=6)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(sum(w.clicks for w in io.windows.values()), 0)

    def test_pause_hotkey_toggles_and_stop_hotkey_stops(self):
        io = SimIO(accounts=2, seed=1)
        eng = Engine(Config(), io, seed=1, strict=True)
        eng.run(until=30)
        io.pending_hotkey = "pause"
        eng.run(until=40)
        self.assertEqual(eng.mode, "keepalive")
        taps = sum(a.taps for a in eng.accounts.values())
        eng.run(until=300)
        self.assertEqual(sum(a.taps for a in eng.accounts.values()), taps)
        io.pending_hotkey = "pause"
        eng.run(until=330)
        self.assertEqual(eng.mode, "run")
        self.assertGreater(sum(a.taps for a in eng.accounts.values()), taps)
        io.pending_hotkey = "stop"
        eng.run(until=10**6)
        self.assertTrue(eng.stopped)
        self.assertLess(io.t, 340)

    def test_reconnect_can_be_switched_off(self):
        io = SimIO(accounts=2, seed=1, netdrop_per_hour=2)
        eng = run(io, Config(reconnect_enabled=False), hours=3)
        self.assertEqual(sum(a.reconnects for a in eng.accounts.values()), 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_reconnect_that_never_works_raises_alarm(self):
        io = SimIO(accounts=2, seed=1, reconnect_offset=(1, 1))  # button isn't where we click
        io.windows[100].disconnected = True
        eng = Engine(Config(), io, seed=1, strict=True)
        eng.run(until=300)
        self.assertGreaterEqual(eng.alarms, 1)
        self.assertGreater(io.windows[101].clicks, 500)

    def test_survives_io_errors_when_not_strict(self):
        io = SimIO(accounts=2, seed=1)
        real, calls = io.click, [0]

        def flaky(*a):
            calls[0] += 1
            if calls[0] % 50 == 0:
                raise OSError("glitch")
            real(*a)

        io.click = flaky
        eng = Engine(Config(), io, seed=1)
        eng.run(until=2 * HOUR)
        self.assertFalse(eng.stopped)
        self.assertEqual(io.idle_kicks, 0)
        self.assertGreaterEqual(eng.alarms, 1)
        self.assertGreater(calls[0], 10000)


class WeakPC(unittest.TestCase):
    """A simulated bad PC: windows take seconds to appear, input gets swallowed, it freezes."""

    def slow(self, n, **kw):
        return SimIO(accounts=n, seed=n, slow_pc=True, focus_fail=0.15, netdrop_per_hour=0.2,
                     block_per_hour=1, **kw)

    def test_24h_with_20_to_60_accounts(self):
        for n in (20, 30, 45, 60):
            with self.subTest(accounts=n):
                io = self.slow(n)
                eng = run(io, Config(weak_pc=True), hours=24)
                self.assertEqual(io.idle_kicks, 0)
                self.assertEqual(io.stray_inputs, 0)
                self.assertLess(io.max_idle, 900)
                self.assertGreater(io.freezes, 300)
                self.assertGreater(io.dropped, 1000)
                for a in eng.accounts.values():
                    self.assertGreater(a.taps, 2000)
                # only the account being worked on is ever on screen
                self.assertLessEqual(io.visible(), 2)
                self.assertLessEqual(io.max_visible, 4)
                self.assertEqual(io.tuned, set(io.windows))
                self.assertEqual(io.sizes, {h: (480, 360) for h in io.windows})
                # waiting accounts are throttled; at most the active one or two run free
                # (the macro frees them all when it stops, so only look before that)
                self.assertLessEqual(max(n for t, n in io.free_log if t < 24 * HOUR), 3)
                self.assertEqual(io.throttled_inputs, 0)
                # ...and nothing is left throttled when the macro stops
                self.assertTrue(all(v == (0, False) for v in io.capped.values()))
                self.assertGreater(io.trims, 1000)

    def test_24h_many_accounts_while_person_uses_pc(self):
        for n in (25, 40):
            with self.subTest(accounts=n):
                io = self.slow(n, user_per_hour=6)
                run(io, Config(weak_pc=True), hours=24)
                self.assertEqual(io.idle_kicks, 0)
                self.assertEqual(io.stray_inputs, 0)
                self.assertLess(io.max_idle, 900)

    def test_person_on_slow_pc_nonstop_12h(self):
        io = self.slow(25)
        io.always_user = True
        run(io, Config(weak_pc=True), hours=12)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_slow_pc_is_safe_even_with_weak_mode_off(self):
        io = self.slow(20)
        run(io, Config(), hours=24)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)
        self.assertEqual(io.trims, 0)
        self.assertEqual(io.visible(), 20)

    def test_warns_when_pc_cannot_keep_up(self):
        io = self.slow(40)
        eng = Engine(Config(weak_pc=True, safe_idle_s=60), io, seed=1, strict=True)
        eng.run(until=1800)
        self.assertTrue(any("too slow" in m for _, m in eng.events))

    def test_failed_pc_tweak_never_stops_the_macro(self):
        io = self.slow(20)

        def boom(hwnd):
            raise OSError("access denied")

        io.tune = io.trim = io.minimize = boom
        io.resize = lambda hwnd, w, h: boom(hwnd)
        io.throttle = lambda hwnd, cap, eco: boom(hwnd)
        eng = run(io, Config(weak_pc=True), hours=6)
        self.assertEqual(io.idle_kicks, 0)
        self.assertGreater(sum(a.taps for a in eng.accounts.values()), 10000)

    def test_trim_setting_limits(self):
        Config(weak_trim_s=0, weak_window=[0, 0]).validate()
        Config(weak_cpu_cap_pct=0, weak_eco=False).validate()
        with self.assertRaises(ConfigError):
            Config(weak_cpu_cap_pct=0.1).validate()
        with self.assertRaises(ConfigError):
            Config(weak_window=[50, 50]).validate()
        with self.assertRaises(ConfigError):
            Config(weak_trim_s=5).validate()
        with self.assertRaises(ConfigError):
            Config(focus_timeout_s=0).validate()


class Extras(unittest.TestCase):
    def test_skipped_account_is_left_completely_alone(self):
        io = SimIO(accounts=3, seed=1)
        eng = Engine(Config(weak_pc=True), io, seed=1, strict=True)
        eng.run(until=60)
        eng.toggle_skip(1)
        eng.run(until=70)
        before = io.windows[101].clicks + io.windows[101].keys
        io.windows[101].last_input = 10**9  # the person is playing it
        eng.run(until=2 * HOUR)
        self.assertEqual(io.windows[101].clicks + io.windows[101].keys, before)
        self.assertEqual(io.capped[101], (0, False))  # and it runs at full speed
        self.assertEqual(eng.snapshot()["accounts"][1]["state"], "skipped")
        self.assertEqual(eng.alarms, 0)
        io.windows[101].last_input = io.t
        eng.toggle_skip(1)
        eng.run(until=3 * HOUR)
        self.assertGreater(io.windows[101].clicks, before + 1000)
        self.assertEqual(io.idle_kicks, 0)
        self.assertEqual(io.stray_inputs, 0)

    def test_relaunch_command_runs_when_window_closes_with_hourly_limit(self):
        cfg = Config(relaunch_command="start roblox", relaunch_max_per_hour=2)
        io = SimIO(accounts=3, seed=1)
        eng = Engine(cfg, io, seed=1, strict=True)
        eng.run(until=60)
        del io.windows[101]
        eng.run(until=300)
        self.assertEqual([c for _, c in io.launched], ["start roblox"])
        self.assertEqual(len(eng.live()), 3)  # the relaunched window was picked up
        for _ in range(4):  # it keeps crashing: stop after the hourly limit
            del io.windows[max(io.windows)]
            eng.run(until=io.t + 200)
        self.assertEqual(len(io.launched), 2)
        self.assertEqual(io.idle_kicks, 0)
        io2 = SimIO(accounts=2, seed=1)
        eng2 = Engine(Config(), io2, seed=1, strict=True)
        eng2.run(until=30)
        del io2.windows[101]
        eng2.run(until=200)
        self.assertEqual(io2.launched, [])  # off unless a command is set

    def test_alarms_are_sent_to_the_notifier_and_failures_ignored(self):
        got = []
        io = SimIO(accounts=2, seed=1)
        eng = Engine(Config(), io, seed=1, strict=True, notify=got.append)
        eng.run(until=30)
        del io.windows[101]
        eng.run(until=60)
        self.assertEqual(len(got), 1)
        self.assertIn("window closed", got[0])

        def broken(msg):
            raise OSError("no internet")

        io = SimIO(accounts=2, seed=1)
        eng = Engine(Config(), io, seed=1, strict=True, notify=broken)
        eng.run(until=30)
        del io.windows[101]
        eng.run(until=600)
        self.assertGreater(io.windows[100].clicks, 1000)

    def test_notifier_batches_and_survives_post_errors(self):
        from tapquest.alerts import Notifier

        sent = []
        n = Notifier("https://example.invalid/hook", post=lambda url, text: sent.append((url, text)),
                     threaded=False)
        n.send("one")
        n.send("two")
        self.assertEqual([t for _, t in sent], ["one", "two"])
        self.assertEqual(sent[0][0], "https://example.invalid/hook")

        def bad(url, text):
            raise OSError("down")

        n = Notifier("https://example.invalid/hook", post=bad, threaded=False)
        n.send("x")
        n.send("y")
        self.assertEqual(n.errors, 2)

        # threaded: a burst while a post is in flight goes out as one message
        import threading, time

        gate, sent = threading.Event(), []

        def slow(url, text):
            sent.append(text)
            gate.wait(2)

        n = Notifier("https://example.invalid/hook", post=slow, min_gap_s=0)
        n.send("a")
        time.sleep(0.1)
        n.send("b")
        n.send("c")
        gate.set()
        time.sleep(0.3)
        self.assertEqual(sent, ["a", "b\nc"])

    def test_popup_colour_learning(self):
        from tapquest.engine import popup_color

        grey = (57, 59, 61)
        self.assertEqual(popup_color([grey] * 13 + [(255, 255, 255)] * 2), [57, 59, 61])
        self.assertIsNone(popup_color([(i, i * 2 % 256, 9) for i in range(15)]))
        self.assertIsNone(popup_color([]))

    def test_learned_popup_settings_are_used(self):
        cfg = Config(reconnect_dx=40, reconnect_dy=70, reconnect_color=[57, 59, 61])
        io = SimIO(accounts=2, seed=1, reconnect_offset=(40, 70), netdrop_per_hour=3)
        eng = run(io, cfg, hours=6)
        self.assertGreater(io.net_drops, 10)
        self.assertLess(io.max_dc_time, 240)
        self.assertEqual(eng.alarms, 0)

    def test_new_settings_validation(self):
        Config(alert_webhook="https://discord.com/api/webhooks/1/abc").validate()
        for bad in ({"alert_webhook": "http://x"}, {"alert_webhook": 5},
                    {"relaunch_max_per_hour": 0}, {"relaunch_command": 3}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                Config.from_dict(bad)


class Settings(unittest.TestCase):
    def test_defaults_are_valid_and_round_trip(self):
        cfg = Config(steps=[Step(name="A")])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            cfgmod.save(cfg, p)
            self.assertEqual(cfgmod.load(p).to_dict(), cfg.to_dict())
            self.assertEqual(cfgmod.load(os.path.join(d, "missing.json")).to_dict(), Config().to_dict())

    def test_shipped_settings_file_loads(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")
        cfgmod.load(p)

    def test_unsafe_or_broken_settings_are_rejected(self):
        bad = [
            {"safe_idle_s": 900},  # too close to the 20 min kick
            {"safe_idle_s": 5},
            {"warn_idle_s": 100},
            {"taps_per_second": 0},
            {"taps_per_second": 500},
            {"tap_x": 1.5},
            {"nudge_key": ""},
            {"nudge_key": "banana"},
            {"reconnect_color": [1, 2]},
            {"process_names": []},
            {"dwell_s": "fast"},
            {"typo_setting": 1},
            {"steps": [{"name": "a", "kind": "swipe"}]},
            {"steps": [{"name": "a"}, {"name": "a"}]},
            {"steps": [{"name": "a", "every_s": 0}]},
            {"steps": [{"name": "a", "bogus": 1}]},
        ]
        for data in bad:
            with self.subTest(data=data):
                with self.assertRaises(ConfigError):
                    Config.from_dict(data)

    def test_broken_json_gives_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w") as f:
                f.write("{not json")
            with self.assertRaises(ConfigError):
                cfgmod.load(p)
            with open(p, "w") as f:
                json.dump([1, 2], f)
            with self.assertRaises(ConfigError):
                cfgmod.load(p)


class WindowsLayer(unittest.TestCase):
    """The parts of the Windows code that can be checked without Windows."""

    def test_input_struct_matches_windows_64bit_layout(self):
        from tapquest import win

        self.assertEqual(ctypes.sizeof(win.CPU_RATE), 8)
        self.assertEqual(ctypes.sizeof(win.POWER_THROTTLING), 12)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(win.INPUT), 40)
            self.assertEqual(win.INPUT.u.offset, 8)

    def test_every_allowed_key_has_a_key_code(self):
        from tapquest import win

        for k in cfgmod.KEYS:
            self.assertIn(k, win.VK, k)




class Window(unittest.TestCase):
    def test_app_window_starts_pauses_and_stops(self):
        try:
            import tkinter

            tkinter.Tk().destroy()
        except Exception:
            self.skipTest("no display / tkinter here")
        from tapquest.gui import App

        with tempfile.TemporaryDirectory() as d:
            io = SimIO(accounts=3, seed=1, realtime_speed=200)
            app = App(io, os.path.join(d, "settings.json"), demo=True)
            app.v["tps"].set("abc")
            with self.assertRaises(ConfigError):
                app._read_cfg()
            app.v["tps"].set("10")
            app.start()
            self.assertTrue(app.running)
            end = __import__("time").time() + 2
            while __import__("time").time() < end:
                app.root.update()
                app._refresh()
            self.assertEqual(len(app.tree.get_children()), 3)
            app.toggle_pause()
            self.assertEqual(app.engine.mode, "keepalive")
            app.stop()
            self.assertFalse(app.running)
            self.assertTrue(os.path.exists(os.path.join(d, "settings.json")))
            self.assertEqual(io.stray_inputs, 0)
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
