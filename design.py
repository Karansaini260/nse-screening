"""
Design tokens — the single source of truth for spacing, colours,
typography, and radii used across the app. Every page imports
constants from here so a colour/spacing change is one line, not
fifty.

Visual style is "modern fintech consumer app": inspired by Robinhood,
Linear, Notion. Soft shadows, rounded corners, generous whitespace,
clear typographic hierarchy, and a single accent colour per theme
that carries the brand.

This module complements theme.py (which handles the live re-skin
machinery for ttk widgets). The palette tables here are the same
ones; we expose them as module-level constants for use by widgets
that draw their own visuals (matplotlib charts, custom canvases).
"""

import tkinter as tk


# --- Spacing scale (pixels) ---
# Multiples of 4 so the rhythm is consistent across the app. Stick
# to these — no random padding="13".
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32

# --- Corner radii ---
# 0 = sharp, 999 = pill. Cards 8, buttons 6, chips 999.
RADIUS_CARD = 8
RADIUS_BUTTON = 6
RADIUS_CHIP = 999

# --- Font stacks ---
# Segoe UI is the Windows default and looks great; if not available
# Tkinter falls back to the platform default. We use it for body text
# and headers. The "mono" stack is for numbers and code-like things
# (the dashboard LTP column, the debug log) so digits line up.
FONT_BODY      = ("Segoe UI", 10)
FONT_BODY_BOLD = ("Segoe UI", 10, "bold")
FONT_SUBTITLE  = ("Segoe UI", 11)
FONT_TITLE     = ("Segoe UI", 14, "bold")
FONT_DISPLAY   = ("Segoe UI", 24, "bold")
FONT_NUM_LARGE = ("Segoe UI", 28, "bold")
FONT_NUM_MED   = ("Segoe UI", 14, "bold")
FONT_SMALL     = ("Segoe UI", 9)
FONT_MONO      = ("Consolas", 10)

# --- Semantic colour names ---
# These are the "what" — the theme module decides the actual RGB
# values. Pages reference them by name so a theme change auto-propagates.
COL_TEXT         = "text"
COL_TEXT_MUTED   = "text_muted"
COL_TEXT_INVERSE = "text_inverse"
COL_BG           = "bg"
COL_PANEL        = "panel"
COL_SIDEBAR      = "sidebar"
COL_ACCENT       = "accent"
COL_ACCENT_SOFT  = "accent_soft"
COL_BORDER       = "border"
COL_UP           = "up"
COL_DOWN         = "down"
COL_WARN         = "warn"
COL_NEUTRAL      = "neutral"


def color_for(palette, name):
    """Look up a semantic colour name in a palette dict. Falls back
    to a sensible default so a missing key never crashes the app."""
    return palette.get(name, palette.get("fg", "#000000"))


# ---------------------------------------------------------------------------
# Plain-English tooltips for the technical terms used in the UI.
# Pages call Tooltip.attach(widget, term) to wire up hover help.
# ---------------------------------------------------------------------------
TOOLTIPS = {
    "SMMA20":  "Smoothed Moving Average over 20 ticks — a fast trend line. "
               "When it crosses above SMMA120, momentum is turning up (BUY signal).",
    "SMMA120": "Smoothed Moving Average over 120 ticks — a slow trend line. "
               "Represents the medium-term trend.",
    "ETQ":     "Equal-Traded Quantity — total shares traded over a window. "
               "Spikes often precede big moves.",
    "LTQ":     "Last Traded Quantity — size of the most recent print. "
               "Unusually large LTQ can signal a block deal.",
    "LTP":     "Last Traded Price — the most recent price the stock changed hands at.",
    "Bid/Ask": "Best buy and sell price currently quoted. "
               "A wide spread means lower liquidity.",
    "Cross":   "A 'crossover' is when the fast SMMA line crosses the slow one. "
               "Up cross = BUY signal, down cross = SELL signal.",
    "Prob":    "AI confidence that the trade will be profitable, from 0 to 1. "
               "Computed by a model trained on your own trade history.",
    "Signal":  "The most recent SMMA crossover. NO means no fresh crossover yet.",
    "AI":      "Logistic Regression model — learns from your own past trades "
               "to predict which new ones are likely to be profitable.",
}


class Tooltip:
    """
    Lightweight hover tooltip for any Tk widget. Usage:

        Tooltip.attach(my_label, "SMMA20")

    On hover, a small Toplevel window appears with the plain-English
    explanation. No external dependencies.
    """

    _DELAY_MS = 400

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _evt):
        self._after_id = self.widget.after(self._DELAY_MS, self._show)

    def _show(self):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify="left",
            background="#fffbe6", foreground="#3a3a3a",
            relief="solid", borderwidth=1, padx=8, pady=6,
            font=("Segoe UI", 9), wraplength=320,
        )
        label.pack()

    def _hide(self, _evt=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    @classmethod
    def attach(cls, widget, term):
        """Look up the term in TOOLTIPS and attach a tooltip if a
        definition exists. Silent no-op otherwise."""
        text = TOOLTIPS.get(term)
        if text:
            cls(widget, text)
