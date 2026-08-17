"""
Page 10 — Debug Log. Read-only view of the most recent lines from
the [websocket_client] logger, plus a live counter of how many ticks
have arrived since the last reconnect.

Useful for diagnosing live-feed issues without opening a separate
terminal. The underlying buffer (LOG_BUFFER in websocket_client.py)
holds the last 500 lines; this page shows them in a scrollable text
view and refreshes every second.
"""

import time
import tkinter as tk
from tkinter import ttk


class DebugLogPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=4)

        # Top: tick counter and last-tick age, plus a clear button.
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        self.summary_var = tk.StringVar(value="—")
        ttk.Label(top, textvariable=self.summary_var,
                  font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(top, text="Clear Display", command=self._clear).pack(side="right")
        ttk.Button(top, text="Copy to Clipboard", command=self._copy).pack(side="right", padx=(0, 4))

        # The actual log view — read-only, monospaced, with vertical
        # scrollbar. `state="disabled"` prevents the user from editing
        # the buffer; we flip it temporarily when inserting.
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            frame, wrap="none", font=("Consolas", 9), state="disabled",
            background="#0d1117", foreground="#c9d1d9", insertbackground="#c9d1d9",
        )
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.after(1000, self._refresh)

    def _refresh(self):
        try:
            from websocket_client import LOG_BUFFER, TICK_COUNT, LAST_TICK_AT, SYMBOL_LAST_TICK
            # Summary line.
            if LAST_TICK_AT:
                age = time.time() - LAST_TICK_AT
                summary = f"Ticks: {TICK_COUNT}   Last tick: {age:.1f}s ago   Symbols with ticks: {len(SYMBOL_LAST_TICK)}/100"
            else:
                summary = f"Ticks: {TICK_COUNT}   No ticks yet"
            self.summary_var.set(summary)

            # Render the buffer. Disable editing, replace contents, re-enable.
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            for line in LOG_BUFFER:
                self.text.insert("end", line + "\n")
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass
        self.after(1000, self._refresh)

    def _clear(self):
        # Clear the display only — don't touch the underlying buffer
        # so the user can re-show it by scrolling the buffer later.
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _copy(self):
        try:
            from websocket_client import LOG_BUFFER
            text = "\n".join(LOG_BUFFER)
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass
