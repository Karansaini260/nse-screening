"""
Page 4 — AI/ML Signal Analysis. A tabular log of the most recent
SMMA crossovers with the AI verdict attached. Backed by SignalsBus,
which the dashboard pushes to on every fresh crossover.
"""

import tkinter as tk
from tkinter import ttk

from shared import signals, feed_ready


class AISignalsPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=4)

        # Header bar with a counter so the user can see at a glance
        # whether the bus is empty or has crossovers.
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text="Recent AI-Scored Crossovers",
                  font=("Segoe UI", 11, "bold")).pack(side="left")
        self.count_var = tk.StringVar(value="(0 signals so far)")
        ttk.Label(header, textvariable=self.count_var,
                  font=("Segoe UI", 9), foreground="gray").pack(side="left", padx=(8, 0))
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side="right")

        cols = ("Time", "Symbol", "Type", "Prob", "Decision", "LTQ Spike", "Reason", "Status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=25)
        widths = {"Time": 90, "Symbol": 80, "Type": 60, "Prob": 60, "Decision": 80,
                  "LTQ Spike": 80, "Reason": 360, "Status": 70}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths.get(c, 90), anchor="center")
        self.tree.tag_configure("accept", background="#e6ffe6")
        self.tree.tag_configure("avoid", background="#ffe6e6")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Subscribe to feed-ready so we refresh immediately when
        # the user clicks "Use Mock Feed" or "Connect to Angel One",
        # rather than waiting 1.5s for the auto-refresh tick.
        feed_ready.subscribe(self._on_feed_ready)

        self.refresh()
        self.after(1000, self._auto_refresh)

    def _on_feed_ready(self):
        try:
            self.refresh()
        except Exception:
            pass

    def _auto_refresh(self):
        self.refresh()
        self.after(1000, self._auto_refresh)

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        # Render newest at top.
        all_signals = signals.all()
        self.count_var.set(f"({len(all_signals)} signal{'s' if len(all_signals) != 1 else ''} so far)")
        for rec in reversed(all_signals):
            tag = ()
            if rec.decision == "ACCEPT":
                tag = ("accept",)
            elif rec.decision == "AVOID":
                tag = ("avoid",)
            # "LTQ Spike" is a quick heuristic: any reason mentioning LTQ
            # acceleration counts; this matches the heuristic rule the
            # model will eventually replace.
            ltq_spike = "Yes" if "LTQ" in rec.reason else "—"
            status = "Closed" if rec.closed else "Live"
            self.tree.insert(
                "", "end",
                values=(
                    rec.when.strftime("%H:%M:%S"), rec.symbol, rec.direction,
                    f"{rec.probability:.2f}", rec.decision, ltq_spike, rec.reason, status,
                ),
                tags=tag,
            )
