# Tap Quest Multi (v5.0)

Multi-account macro for Tap Quest Sim on a Windows PC. It cycles through every open
Roblox window, taps, runs your extra steps (claim quest, rebirth...), and makes sure
no account sits idle long enough for Roblox's 20-minute kick.

![Running](screenshots/2-running.png)

## Use it

1. Install Python 3.10+ from python.org (tick "Add python.exe to PATH"). Nothing else to install.
2. Open all your Roblox accounts and join the game on each.
3. Double-click **Start Macro.bat**.
4. Click **Pick tap spot (F7)**, hover the mouse where the macro should tap inside any
   Roblox window, and press **F7**. Spots are saved as a fraction of the window, so they
   work on every account as long as the windows show the same layout.
5. Optional: **+ Click** / **+ Key** add timed steps that run on every account.
6. Press **Start**.

| Key | Does |
| --- | --- |
| F6 | Pause/resume tapping. Paused accounts are still kept connected. |
| F8 | Stop everything. Accounts are no longer kept connected. |
| F7 | Save a spot (only while picking one). |

## How it keeps accounts connected

- The account that has gone longest without input is always visited next.
- Every account gets input at least every 8 minutes. Time per account shrinks automatically
  when you open more accounts so a full lap always fits.
- When you move the mouse, tapping waits. If an account reaches 8 minutes meanwhile, the
  macro switches to it for about a second, sends one harmless key press, and hands your
  window and mouse position back.
- Input is only sent after confirming the right Roblox window is in front, so it never
  types or clicks into your other apps.
- If a window can't be brought to the front it is retried with a back-off and the other
  accounts carry on. You get a sound alert at 15 minutes idle, before the kick.
- If the grey "Disconnected" pop-up is showing, it presses Reconnect.
- Windows is stopped from sleeping or locking the screen while the macro runs.
- A closed/crashed Roblox window raises an alert; newly opened windows are picked up
  automatically.

## What was tested, and what wasn't

Tested here (25 automated tests, `Run Tests.bat` runs them on your PC):

- 24-hour simulated sessions with 1 to 60 accounts: zero idle kicks.
- 24-hour sessions with everything going wrong at once (focus failing 25% of the time,
  network drops, stuck windows, a person using the PC): zero idle kicks, zero input sent
  to the wrong window, every network drop reconnected.
- 72-hour run with 12 accounts: 0 kicks, longest gap without input 9.4 min.
- Paused mode, tapping switched off, crashes, stop/pause keys, bad settings, the app window.

Not tested (this was built without access to a Windows PC or Roblox):

- The Windows layer in `tapquest/win.py` (finding windows, focusing them, sending clicks).
  Do a short supervised run first.
- The disconnect pop-up detector. Its colour and Reconnect button position
  (`reconnect_color`, `reconnect_dx`, `reconnect_dy` in `settings.json`) are best guesses
  and may need adjusting. If it misbehaves, untick "Press Reconnect on disconnect".

Limits to know about:

- Roblox only accepts input in the focused window, so the macro takes the mouse while it
  taps. Use F6 when you want the PC to yourself.
- It can't relaunch a Roblox window that closed, or log back in.
- Macros can be against a game's rules; use it on your own accounts at your own risk.

## Files

- `tapquest/engine.py` - scheduling and safety rules
- `tapquest/win.py` - Windows input and window handling
- `tapquest/sim.py` - simulated PC used by the tests and `--demo`
- `tapquest/gui.py` - the app window
- `settings.json` - all settings (the app saves it when you press Start)

`python -m tapquest --demo` shows the app with simulated accounts.
`python -m tapquest --soak 24 --accounts 10` runs a simulated endurance test.
