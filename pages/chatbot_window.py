"""
Floating chatbot window. Always-on-top Toplevel that the user can
open from the sidebar (or close and forget). Internally just renders
a chat log + entry box, and calls chatbot.respond() for each
message.

The window remembers its position between opens in the same session
but doesn't persist across restarts (we don't write to a file).
"""

import tkinter as tk
from tkinter import ttk

from chatbot import respond, HELP_TEXT
from pages.theme_subscribe import themed


@themed
class ChatbotWindow:
    def __init__(self, master):
        self.master = master
        self.win: tk.Toplevel = None
        self._last_geom = "420x520+120+120"
        # Theme subscription is wired up by the @themed decorator.

    # ------------------------------------------------------------------ public

    def toggle(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
            self.win = None
            return
        self.show()

    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return
        self.win = tk.Toplevel(self.master)
        self.win.title("Assistant")
        self.win.geometry(self._last_geom)
        self.win.minsize(360, 400)
        # Stays above the main window without stealing focus when not
        # being typed into. Users can still click through to the app.
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._on_theme_change(self.palette())
        self._post_bot(HELP_TEXT)

    def _on_close(self):
        if self.win is not None:
            self._last_geom = self.win.geometry()
            self.win.destroy()
            self.win = None

    # ------------------------------------------------------------------ build

    def _build(self):
        wrap = ttk.Frame(self.win, padding=8)
        wrap.pack(fill="both", expand=True)

        # Header
        ttk.Label(wrap, text="Assistant", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        # Chat log
        log_frame = ttk.Frame(wrap)
        log_frame.pack(fill="both", expand=True, pady=(6, 6))
        self.log = tk.Text(
            log_frame, wrap="word", height=18,
            font=("Segoe UI", 10), state="disabled", relief="flat",
        )
        ysb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=ysb.set)
        self.log.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        # Input row
        entry_row = ttk.Frame(wrap)
        entry_row.pack(fill="x")
        self.entry = ttk.Entry(entry_row, font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self._send())
        ttk.Button(entry_row, text="Send", command=self._send).pack(side="left")

        # Quick-action chips
        chips = ttk.Frame(wrap)
        chips.pack(fill="x", pady=(6, 0))
        for label, question in [
            ("Help",          "help"),
            ("Open trades",   "open positions"),
            ("Recent",        "recent signals"),
            ("Top by SMMA",   "top 5 by smma gap"),
        ]:
            ttk.Button(chips, text=label,
                       command=lambda q=question: self._ask(q)).pack(side="left", padx=(0, 4))

    # ------------------------------------------------------------------ chat

    def _post(self, sender, text):
        """Append a message to the chat log. Sender: 'You' or 'Bot'."""
        self.log.configure(state="normal")
        self.log.insert("end", f"{sender}: {text}\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _post_bot(self, text):
        self._post("Bot", text)

    def _post_user(self, text):
        self._post("You", text)

    def _ask(self, question):
        """Pre-fill the entry box and send (used by quick chips)."""
        self.entry.delete(0, "end")
        self.entry.insert(0, question)
        self._send()

    def _send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._post_user(text)
        try:
            answer = respond(text)
        except Exception as e:
            answer = f"Sorry, I hit an error: {e}"
        self._post_bot(answer)

    # ------------------------------------------------------------------ theme

    def _on_theme_change(self, palette):
        if self.win is None or not self.win.winfo_exists():
            return
        self.win.configure(background=palette["bg"])
        # ttk styles propagate via theme.apply_theme(); the bare tk.Text
        # widget needs explicit recolouring.
        try:
            self.log.configure(
                background=palette["panel_bg"],
                foreground=palette["fg"],
                insertbackground=palette["fg"],
                selectbackground=palette["accent"],
                selectforeground="#ffffff",
            )
        except Exception:
            pass
        try:
            self.entry.configure(foreground=palette["fg"])
        except Exception:
            pass
