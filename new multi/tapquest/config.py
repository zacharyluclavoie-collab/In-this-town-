"""Settings: defaults, loading, saving and validation."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

# Roblox disconnects a client after 20 minutes without input.
ROBLOX_IDLE_KICK_S = 1200

KEYS = (
    [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [str(d) for d in range(10)]
    + ["space", "enter", "tab", "left", "right", "up", "down"]
    + [f"f{n}" for n in range(1, 13)]
)


class ConfigError(ValueError):
    pass


@dataclass
class Step:
    """Something extra to do on every account on a timer (claim a quest, buy an upgrade...)."""

    name: str = "Step"
    kind: str = "click"  # "click" or "key"
    x: float = 0.5  # click position as a fraction of the game window (0-1)
    y: float = 0.5
    key: str = "e"
    every_s: float = 60.0
    count: int = 1
    gap_ms: int = 150
    enabled: bool = True


@dataclass
class Config:
    # Main tapping
    tap_enabled: bool = True
    tap_x: float = 0.5
    tap_y: float = 0.55
    taps_per_second: float = 12.0
    dwell_s: float = 8.0  # how long to tap on one account before moving to the next

    # Staying connected
    safe_idle_s: float = 480.0  # every account gets input at least this often
    warn_idle_s: float = 900.0  # sound the alarm if an account goes this long
    nudge_key: str = "right"  # harmless key used when no tap is sent
    nudge_back_key: str = "left"  # pressed after, to undo the nudge ("" for none)

    # Sharing the PC with you
    pause_on_user_input: bool = True
    user_grace_s: float = 4.0

    # Disconnect pop-up handling
    reconnect_enabled: bool = True
    reconnect_color: list = field(default_factory=lambda: [57, 59, 61])
    reconnect_tolerance: int = 14
    reconnect_dx: int = 82  # "Reconnect" button, pixels right of the window centre
    reconnect_dy: int = 86  # ...and below it
    reconnect_wait_s: float = 20.0

    # Which windows count as accounts
    process_names: list = field(
        default_factory=lambda: ["RobloxPlayerBeta.exe", "Windows10Universal.exe"]
    )
    settle_s: float = 0.15  # pause after switching windows before sending input
    steps: list = field(default_factory=list)

    def validate(self) -> None:
        def rng(name, lo, hi):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise ConfigError(f"{name} must be between {lo} and {hi} (got {v!r})")

        rng("tap_x", 0, 1)
        rng("tap_y", 0, 1)
        rng("taps_per_second", 0.5, 30)
        rng("dwell_s", 0.5, 300)
        # Half the Roblox limit at most: a missed visit still leaves a full retry window.
        rng("safe_idle_s", 30, ROBLOX_IDLE_KICK_S / 2)
        rng("warn_idle_s", self.safe_idle_s, ROBLOX_IDLE_KICK_S - 60)
        rng("user_grace_s", 0, 120)
        rng("reconnect_tolerance", 0, 60)
        rng("reconnect_wait_s", 5, 300)
        rng("settle_s", 0.02, 2)
        for name in ("nudge_key", "nudge_back_key"):
            k = getattr(self, name)
            if k and k not in KEYS:
                raise ConfigError(f"{name}: unknown key {k!r}")
        if not self.nudge_key:
            raise ConfigError("nudge_key is required (it keeps accounts connected)")
        if len(self.reconnect_color) != 3 or not all(
            isinstance(c, int) and 0 <= c <= 255 for c in self.reconnect_color
        ):
            raise ConfigError("reconnect_color must be [r, g, b] with values 0-255")
        if not self.process_names:
            raise ConfigError("process_names cannot be empty")
        seen = set()
        for s in self.steps:
            if s.kind not in ("click", "key"):
                raise ConfigError(f"step {s.name!r}: kind must be 'click' or 'key'")
            if not (0 <= s.x <= 1 and 0 <= s.y <= 1):
                raise ConfigError(f"step {s.name!r}: x and y must be between 0 and 1")
            if s.kind == "key" and s.key not in KEYS:
                raise ConfigError(f"step {s.name!r}: unknown key {s.key!r}")
            if not 1 <= s.every_s <= 86400:
                raise ConfigError(f"step {s.name!r}: every_s must be 1-86400")
            if not 1 <= s.count <= 50:
                raise ConfigError(f"step {s.name!r}: count must be 1-50")
            if not 20 <= s.gap_ms <= 5000:
                raise ConfigError(f"step {s.name!r}: gap_ms must be 20-5000")
            if s.name in seen:
                raise ConfigError(f"two steps are both named {s.name!r}")
            seen.add(s.name)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("settings file must contain a JSON object")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
        data = dict(data)
        steps = []
        for raw in data.pop("steps", []):
            try:
                steps.append(Step(**raw))
            except TypeError as e:
                raise ConfigError(f"bad step {raw!r}: {e}") from None
        cfg = cls(**data, steps=steps)
        cfg.validate()
        return cfg


def load(path: str) -> Config:
    """Load settings; a missing file gives the defaults."""
    if not os.path.exists(path):
        return Config()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from None
    return Config.from_dict(data)


def save(cfg: Config, path: str) -> None:
    cfg.validate()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2)
    os.replace(tmp, path)  # never leaves a half-written settings file
