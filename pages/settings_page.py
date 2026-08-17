"""
Page 7 — Settings / Filters. Lets the user tune every runtime
screener parameter. Each control is bound to a Tk Variable in
shared.settings, so the change is live — the dashboard, AI page, and
alerts all see the new value on their next tick without a restart.
"""

import tkinter as tk
from tkinter import ttk

from shared import settings
from pages.background import run_in_background


class SettingsPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)

        ttk.Label(self, text="Settings & Filters", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(self)
        form.pack(fill="x")

        # Each row: label + entry/spinbox bound to a Settings var.
        # Order matters only for visual grouping; the backend ignores it.
        self._rows = []

        def add_int_row(label, key, lo, hi):
            row = ttk.Frame(form)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=32).pack(side="left")
            sp = ttk.Spinbox(row, from_=lo, to=hi, textvariable=settings.vars[key], width=10)
            sp.pack(side="left")
            self._rows.append((label, key, sp))

        def add_float_row(label, key, lo, hi, step=0.5):
            row = ttk.Frame(form)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=32).pack(side="left")
            sp = ttk.Spinbox(row, from_=lo, to=hi, increment=step, textvariable=settings.vars[key], width=10)
            sp.pack(side="left")
            self._rows.append((label, key, sp))

        def add_bool_row(label, key):
            row = ttk.Frame(form)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=32).pack(side="left")
            cb = ttk.Checkbutton(row, variable=settings.vars[key])
            cb.pack(side="left")
            self._rows.append((label, key, cb))

        # --- Screening filters --------------------------------------------
        ttk.Label(form, text="— Screening filters —", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 4))
        # Wide LTP range so the spinbox can hold high-priced names
        # like MRF (~₹1L+), BAJFINANCE (~₹7K-8K), etc. Default is
        # 5 to 50,000 in shared.settings.
        add_float_row("LTP min (₹)",        "ltp_min",            0, 200000)
        add_float_row("LTP max (₹)",        "ltp_max",            0, 200000)
        add_int_row(  "Bid/Ask Qty min",    "liquidity_min_qty",  0, 10_000_000)

        # --- Timing --------------------------------------------------------
        ttk.Label(form, text="— Timing —", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 4))
        add_int_row("Refresh interval (ms)", "refresh_interval_ms", 100, 10000, )
        # The Spinbox's `to` arg is fixed at construction time; we still
        # pass a wide range and rely on the value the user types in.
        # Patch the last row's _to attribute so 10000 is allowed.
        self._rows[-1][2].configure(to=10000)

        # --- Indicators ----------------------------------------------------
        ttk.Label(form, text="— Indicators —", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 4))
        add_int_row("SMMA fast period",          "smma_fast",            2, 200)
        add_int_row("SMMA slow period",          "smma_slow",            5, 500)
        add_int_row("LTQ window: short (min)",   "ltq_window_short_min", 1, 60)
        add_int_row("LTQ window: long (min)",    "ltq_window_long_min",  1, 240)

        # --- Notifications / behaviour -------------------------------------
        ttk.Label(form, text="— Behaviour —", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 4))
        add_bool_row("Alert sounds",  "alert_sound")
        add_bool_row("Auto-trade (stub)", "auto_trade")
        add_bool_row("Dark mode",         "dark_mode")

        # Footer
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=12)
        btns = ttk.Frame(self)
        btns.pack(fill="x")
        ttk.Button(btns, text="Reset to Defaults", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Restart Mock Feed", command=self._restart_feed).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="gray").pack(anchor="w", pady=(8, 0))

    def _reset(self):
        for k, v in settings.DEFAULTS.items():
            settings.vars[k].set(v)
        self.status_var.set("Reset to defaults.")

    def _save(self):
        # Values are already live-bound to the Tk Variables; the only
        # thing "Save" does is give the user feedback and a place to
        # hook in persistence (write a settings.json) later.
        self.status_var.set("Saved. All pages are using the new values live.")

    def _restart_feed(self):
        """Stop the current mock feed (if any), wipe all symbol
        state, and start a fresh mock feed with the new realistic
        seed prices. Useful when the user wants to "reset" the
        screener without restarting the app.

        If the live Angel One feed is connected, this button has no
        effect — restarting the live feed requires going through the
        Login page. The status line tells the user what's happening.
        """
        import threading
        import websocket_client as wsc
        from shared import alerts
        if wsc.LIVE_FEED_AVAILABLE:
            self.status_var.set(
                "Live feed is active — restart the app and reconnect to change feed."
            )
            return
        wsc.stop_mock_feed()
        # Give the previous mock loop a moment to exit on its next
        # iteration, then wipe state and start a fresh thread.
        wsc.reset_states()
        # Pre-populate synchronously so the dashboard has data
        # immediately when the user navigates back.
        wsc.mock_pre_populate()
        if not any(t.name == "mock" for t in threading.enumerate()):
            run_in_background(wsc.mock_steady_state, name="mock")
        alerts.push("—", "FEED", "Mock feed restarted with fresh seed prices.")
        # Broadcast so the dashboard (if it's currently visible)
        # refreshes immediately instead of waiting for its
        # auto-refresh tick.
        try:
            from shared import feed_ready
            feed_ready.broadcast()
        except Exception:
            pass
        self.status_var.set(
            "Mock feed restarted. Dashboard repopulated with realistic prices."
        )
