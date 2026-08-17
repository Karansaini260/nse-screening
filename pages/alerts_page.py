"""
Page 8 — Alerts & Notifications Center. Live log of every alert
pushed onto the AlertsBus. Subscribes to the bus so new entries
appear immediately without waiting for the next refresh tick.
"""

import tkinter as tk
from tkinter import ttk

from shared import alerts


class AlertsPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=4)

        cols = ("Time", "Symbol", "Type", "Message", "Ack")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=25)
        widths = {"Time": 90, "Symbol": 90, "Type": 110, "Message": 600, "Ack": 50}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths.get(c, 100), anchor="center")
        self.tree.tag_configure("unack", font=("Segoe UI", 9, "bold"))
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Acknowledge Selected", command=self._ack_selected).pack(side="left")
        ttk.Button(bar, text="Clear All", command=self._clear).pack(side="left", padx=6)

        # Live updates: register a callback so new alerts appear
        # without a full table rebuild on each push.
        alerts.subscribe(self._on_new_alert)
        # Also subscribe to feed-ready so we refresh immediately when
        # a feed comes online (the first alerts are usually the
        # "FEED" / "LOGIN" ones that mark the connection event).
        from shared import feed_ready
        feed_ready.subscribe(self._on_feed_ready)
        self.refresh()

    def _on_feed_ready(self):
        try:
            self.refresh()
        except Exception:
            pass

    def _on_new_alert(self, alert):
        # Insert at the top; use `iid=...` to keep the row stable.
        self.tree.insert(
            "", 0,
            iid=str(id(alert)),
            values=(
                alert.when.strftime("%H:%M:%S"), alert.symbol, alert.kind,
                alert.message, "No",
            ),
            tags=("unack",) if not alert.acknowledged else (),
        )

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        # Newest at top.
        for a in reversed(alerts.all()):
            self.tree.insert(
                "", "end",
                iid=str(id(a)),
                values=(
                    a.when.strftime("%H:%M:%S"), a.symbol, a.kind,
                    a.message, "Yes" if a.acknowledged else "No",
                ),
                tags=() if a.acknowledged else ("unack",),
            )

    def _ack_selected(self):
        for iid in self.tree.selection():
            # Reverse the iid -> index lookup: iid is the id() of the
            # Alert, so we walk the bus to find the matching object.
            for a in alerts.all():
                if str(id(a)) == iid:
                    a.acknowledged = True
                    break
        self.refresh()

    def _clear(self):
        # We don't have a `clear()` on the bus; emulate by replacing
        # the deque contents in place. Keeps the same AlertsBus object
        # so subscribers don't have to re-register.
        alerts._buf.clear()
        self.refresh()
