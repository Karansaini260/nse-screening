"""
Cross-page shared state. Holds three things every page needs:

  * Settings   — runtime tunables (LTP band, qty thresholds, SMMA
                 periods, alert toggles, auto-trade stub flag).
                 Mutating a setting fires a Tk Variable so bound
                 widgets update instantly.

  * AlertsBus  — append-only log of every noteworthy event (crossover,
                 AI decision, login, mock-feed notice, etc.) read by
                 the Alerts page.

  * SignalsBus — most recent SMMA crossovers (with the AI verdict),
                 read by the AI/ML Signal panel.

Pages import `settings`, `alerts`, and `signals` directly. They never
mutate each other's widgets.
"""

import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import datetime


# ---------------------------------------------------------------------------
# Credentials (session-only)
# ---------------------------------------------------------------------------
# The Login page stores the entered Angel One credentials here in
# memory only — never written to disk. The websocket module reads from
# this dict when bringing up the live feed. On startup the dict is
# empty; the user must type their credentials into the Login page
# each session.
#
# Keeping this in shared (rather than writing to a config file on
# disk) means there is no file containing the secrets — nothing to
# accidentally commit, nothing to leak via a screenshot of the repo.
credentials = {
    "api_key":      "",
    "client_code":  "",
    "password":     "",
    "totp_secret":  "",
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    """Single source of truth for runtime-tunable screening parameters.

    Tk Variables need a root window to construct, so we defer the
    `vars` dict until the first access. That lets `import shared` work
    from scripts (train_model.py, etc.) before the GUI exists.
    """

    DEFAULTS = {
        # LTP band: 5 to 50,000 rupees. Covers penny stocks through
        # high-priced names like MRF (~₹1L+), BAJFINANCE (~₹7K-8K),
        # and HDFCBANK (~₹1500-1700). Users can narrow this in
        # Settings if they want a specific band only.
        "ltp_min": 5.0,
        "ltp_max": 50_000.0,
        # Bid/Ask qty must both exceed this to count as "liquid".
        # 1,000,000 was way too aggressive — real Nifty bid/ask qty
        # is usually 1,000-100,000. 1,000 lets through any quoted
        # depth; the Settings page lets the user raise it if they
        # want only highly-liquid names. Note: rows where bid/ask
        # qty is missing entirely (LTP-only feed) are shown
        # regardless of this threshold.
        "liquidity_min_qty": 1_000,
        "refresh_interval_ms": 1000,
        "smma_fast": 20,
        "smma_slow": 120,
        "ltq_window_short_min": 2,
        "ltq_window_long_min": 5,
        "alert_sound": True,
        "auto_trade": False,              # stub — logs intent, places nothing
        "dark_mode": False,               # theme toggle; read by app.apply_theme
    }

    def __init__(self):
        self._vars = None  # built lazily on first access

    def _ensure_vars(self):
        if self._vars is None:
            self._vars = {}
            for k, v in self.DEFAULTS.items():
                if isinstance(v, bool):
                    self._vars[k] = tk.BooleanVar(value=v)
                elif isinstance(v, int):
                    self._vars[k] = tk.IntVar(value=v)
                elif isinstance(v, float):
                    self._vars[k] = tk.DoubleVar(value=v)
                else:
                    self._vars[k] = tk.StringVar(value=str(v))
        return self._vars

    @property
    def vars(self):
        return self._ensure_vars()

    def __getattr__(self, name):
        if name.startswith("_") or name == "vars":
            raise AttributeError(name)
        d = self._ensure_vars()
        if name in d:
            return d[name].get()
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "_vars":
            super().__setattr__(name, value)
            return
        if name in self.DEFAULTS:
            self._ensure_vars()[name].set(value)
            return
        super().__setattr__(name, value)

    def as_dict(self):
        return {k: v.get() for k, v in self._ensure_vars().items()}


# Module-level singleton — imported wherever needed.
settings = Settings()


# ---------------------------------------------------------------------------
# Alerts bus
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    when: datetime
    symbol: str
    kind: str          # "CROSSOVER", "AI_DECISION", "LOGIN", "FEED", "ERROR", ...
    message: str
    acknowledged: bool = False


class AlertsBus:
    """Bounded log of alerts. Capped so memory doesn't grow forever
    during a long session; the Alerts page also persists to CSV on
    demand from the user."""

    def __init__(self, maxlen=2000):
        self._buf = deque(maxlen=maxlen)
        self._subscribers = []

    def push(self, symbol, kind, message):
        a = Alert(datetime.now(), symbol, kind, message)
        self._buf.append(a)
        for cb in list(self._subscribers):
            try:
                cb(a)
            except Exception:
                pass
        return a

    def all(self):
        return list(self._buf)

    def acknowledge(self, idx_from_newest):
        """Mark the Nth most recent alert as read. Used by the Alerts page."""
        if 0 <= idx_from_newest < len(self._buf):
            self._buf[len(self._buf) - 1 - idx_from_newest].acknowledged = True

    def subscribe(self, callback):
        """Register a callback for live updates (used by the Alerts page
        so the row appears without waiting for the next refresh tick)."""
        self._subscribers.append(callback)


alerts = AlertsBus()


# ---------------------------------------------------------------------------
# Signals bus
# ---------------------------------------------------------------------------

@dataclass
class SignalRecord:
    when: datetime
    symbol: str
    direction: str     # "BUY" or "SELL"
    probability: float
    decision: str      # "ACCEPT" / "AVOID"
    reason: str
    ltp: float
    closed: bool = False


class SignalsBus:
    """Bounded ring of the most recent crossovers across all symbols.
    Read by the AI/ML Signal panel."""

    def __init__(self, maxlen=500):
        self._buf = deque(maxlen=maxlen)

    def push(self, record: SignalRecord):
        self._buf.append(record)
        return record

    def all(self):
        return list(self._buf)


signals = SignalsBus()


# ---------------------------------------------------------------------------
# TradeTracker bridge
# ---------------------------------------------------------------------------
# The dashboard owns the single TradeTracker instance. We expose it
# here so the Trade Log page can list "currently open" trades without
# us having to thread the tracker object through the App class.
_tracker_ref = {"current": None}


def register_tracker(tracker):
    _tracker_ref["current"] = tracker


def open_trades_snapshot():
    """Return a {symbol: {direction, entry_price, entry_time}} dict of
    trades that are currently open. Empty dict if no tracker registered
    yet (e.g. user navigated here before the dashboard ever ran)."""
    t = _tracker_ref["current"]
    if t is None:
        return {}
    return t.open_symbols()


# ---------------------------------------------------------------------------
# Feed-ready signal
# ---------------------------------------------------------------------------
# A simple pub/sub bus that fires whenever a feed (mock or live) is
# ready to be consumed. The dashboard subscribes to this and refreshes
# IMMEDIATELY on each fire, instead of waiting for its 1-second
# auto-refresh tick. The previous version showed an empty table for
# 1-2 seconds after the user clicked "Use Mock Feed" or "Connect to
# Angel One" because the auto-refresh was the only thing driving
# table updates.
#
# The bus is intentionally simple — no payload, just a fire-and-forget
# notification. If the user connects, disconnects, and reconnects in
# quick succession the dashboard will just refresh N times, which is
# cheap and harmless.
class FeedReadyBus:
    def __init__(self):
        self._subscribers = []

    def subscribe(self, callback):
        """Register a callback to be called on every feed-ready fire.
        Returns a token you can pass to unsubscribe() later."""
        self._subscribers.append(callback)
        return callback

    def unsubscribe(self, token):
        try:
            self._subscribers.remove(token)
        except ValueError:
            pass

    def broadcast(self):
        for cb in list(self._subscribers):
            try:
                cb()
            except Exception:
                pass  # never let one bad subscriber kill the bus


feed_ready = FeedReadyBus()
