"""Start the macro:  python -m tapquest   (or double-click "Start Macro.bat")."""

from __future__ import annotations

import argparse
import os
import sys

from . import config as cfgmod
from .engine import Engine
from .sim import SimIO

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def soak(hours: float, accounts: int, cfg, slow: bool = False) -> int:
    """Simulate a long rough session and report whether any account would have been kicked."""
    io = SimIO(accounts=accounts, seed=7, focus_fail=0.2, user_per_hour=4, netdrop_per_hour=0.3,
               block_per_hour=1, slow_pc=slow)
    eng = Engine(cfg, io, seed=7, strict=True)
    eng.run(until=hours * 3600)
    taps = sum(a.taps for a in eng.accounts.values())
    pc = "a slow, freezing PC" if slow else "a normal PC"
    print(f"Simulated {hours:g} h with {accounts} accounts on {pc} "
          f"(flaky focus, network drops, you using the PC)")
    print(f"  taps sent ............... {taps:,}")
    print(f"  idle kicks .............. {io.idle_kicks}")
    print(f"  longest gap w/o input ... {io.max_idle / 60:.1f} min (Roblox kicks at 20.0)")
    print(f"  network drops / fixed ... {io.net_drops} / {sum(a.reconnects for a in eng.accounts.values())}")
    print(f"  input sent to wrong app . {io.stray_inputs}")
    ok = io.idle_kicks == 0 and io.stray_inputs == 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tapquest", description="Tap Quest Sim multi-account macro")
    ap.add_argument("--settings", default=os.path.join(HERE, "settings.json"))
    ap.add_argument("--demo", action="store_true", help="run against simulated accounts")
    ap.add_argument("--demo-speed", type=float, default=1.0)
    ap.add_argument("--soak", type=float, metavar="HOURS", help="simulated endurance test, no window")
    ap.add_argument("--accounts", type=int, default=6, help="accounts for --demo / --soak")
    ap.add_argument("--slow-pc", action="store_true", help="simulate a bad PC in --demo / --soak")
    args = ap.parse_args(argv)

    if args.soak:
        return soak(args.soak, args.accounts, cfgmod.load(args.settings), args.slow_pc)

    demo = args.demo or sys.platform != "win32"
    if demo:
        io = SimIO(accounts=args.accounts, seed=3, netdrop_per_hour=1.0, user_per_hour=3,
                   realtime_speed=args.demo_speed, slow_pc=args.slow_pc)
    else:
        from .win import WinIO

        try:
            names = cfgmod.load(args.settings).process_names
        except cfgmod.ConfigError:
            names = cfgmod.Config().process_names
        io = WinIO(names)
        try:
            if cfgmod.load(args.settings).multi_instance:
                io.allow_multi_instance()
        except Exception:
            pass
    from .gui import App

    App(io, args.settings, demo=demo).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
