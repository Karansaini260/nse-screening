"""
Page 9 — Help / Documentation. In-app glossary and quick-start guide.
Pure read-only text — no live data, no settings.
"""

import tkinter as tk
from tkinter import ttk


HELP_TEXT = """\
NSE SCREENING — QUICK START
==========================

1. Start the app and go to the Login page.
2. Either fill in your Angel One credentials and click "Connect (Live)",
   or click "Use Mock Feed" to try the UI with random data.
3. The Dashboard fills with live quotes for all 100 Nifty symbols.
4. Double-click any row to open the Stock Detail view (chart, depth, LTQ feed).
5. Use the sidebar to switch between Dashboard, AI Signals, Trade Log, ML Stats,
   Settings, and Alerts.

HOW SIGNALS WORK
================

The app watches two Smoothed Moving Averages on every symbol:
  * SMMA(20)  — fast, reacts to recent price action
  * SMMA(120) — slow, the longer-term trend

A BUY CROSS fires when SMMA(20) crosses above SMMA(120) — short-term momentum
turning bullish. A SELL CROSS fires on the opposite crossover. Each fresh
crossover is logged as a trade entry; the next opposite crossover closes it.

HOW AI SCORING WORKS
====================

On every crossover, the AI filter takes a snapshot of six features (see
Glossary below) and asks: "given what the market looked like at entry,
is this trade likely to be profitable?" The answer is a probability
between 0 and 1; trades >= 0.5 are marked ACCEPT, below are AVOID.

The model is a LogisticRegression that learns from your own closed
trades (trade_log.csv). The first time you run the app the model is a
cold-start heuristic; after ~20-50 closed trades, click "Retrain Now"
on the ML Stats page to fit a real model on your data.

GLOSSARY
========

LTP        Last Traded Price
LTQ        Last Traded Quantity — size of the most recent print
ETQ        Equal-Traded Quantity — total shares traded over a window
           (5/20/60 minutes in this app)
SMMA       Smoothed Moving Average — EMA with a long warm-up; smoother
           than SMA, faster than a long SMA
Bid/Ask    Best buy and sell quotes in the order book
Spread     Ask price minus bid price
Imbalance  (bid_qty - ask_qty) / (bid_qty + ask_qty); positive = more
           buyers queued, negative = more sellers
Volatility Standard deviation of recent LTP prints

CONTACT
=======

This is a personal-use screener. For broker/API issues, contact Angel
One support. For app issues, edit the code — every page is in pages/.
"""


class HelpPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        ttk.Label(self, text="Help & Documentation", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        text = tk.Text(self, wrap="word", font=("Consolas", 10))
        text.insert("1.0", HELP_TEXT)
        text.configure(state="disabled")
        ysb = ttk.Scrollbar(self, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=ysb.set)
        text.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
