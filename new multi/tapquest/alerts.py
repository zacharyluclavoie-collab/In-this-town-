"""Send macro alerts to a Discord webhook (so you hear about problems on your phone)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request


def _post(url: str, text: str):
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": text}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "TapQuestMulti"},
    )
    urllib.request.urlopen(req, timeout=10).close()


class Notifier:
    """Queues messages and sends them from a background thread, never faster than
    one post per `min_gap_s`, so a burst of alerts can't stall the macro or spam you."""

    def __init__(self, url: str, post=_post, min_gap_s: float = 20.0, threaded: bool = True):
        self.url, self._post, self.min_gap_s, self.threaded = url, post, min_gap_s, threaded
        self._pending: list[str] = []
        self._lock = threading.Lock()
        self._busy = False
        self._last = 0.0
        self.errors = 0

    def send(self, msg: str):
        with self._lock:
            self._pending.append(msg)
            if self._busy:
                return
            self._busy = True
        if self.threaded:
            threading.Thread(target=self._drain, daemon=True).start()
        else:
            self._drain()

    def _drain(self):
        while True:
            wait = self._last + self.min_gap_s - time.monotonic()
            if wait > 0 and self.threaded:
                time.sleep(wait)
            with self._lock:
                batch, self._pending = self._pending, []
                if not batch:
                    self._busy = False
                    return
            try:
                self._post(self.url, "\n".join(batch)[:1800])
            except Exception:
                self.errors += 1  # no internet etc: the macro carries on regardless
            self._last = time.monotonic()
