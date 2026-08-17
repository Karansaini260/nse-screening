"""
Per-symbol rolling state: tick history + SMMA(20)/SMMA(120) + derived
features (LTQ ratios, ETQ, bid/ask imbalance, volatility, etc.).

This module is intentionally framework-agnostic — no Tk, no websocket
imports — so it can be tested or driven from a replay harness.
"""

import collections
import numpy as np
from datetime import datetime, timedelta


class SymbolState:
    def __init__(self, symbol):
        self.symbol = symbol
        # (timestamp, ltp, ltq) — bounded so we don't grow without limit
        # 5000 ticks at ~1/sec is ~83 min, more than enough for SMMA120 +
        # 60-min ETQ windows and the 20-min volatility feature.
        self.ticks = collections.deque(maxlen=5000)
        self.smma20 = None
        self.smma120 = None
        self.prev_smma20 = None
        self.prev_smma120 = None
        self.bid_price = 0
        self.bid_qty = 0
        self.ask_price = 0
        self.ask_qty = 0
        self.ltp = 0
        # Last-traded quantity — the size of the most recent print.
        # The dashboard shows it in its own "Volume" column and the
        # detail page lists it in the LTQ feed. We initialise it to 0
        # so the dashboard's f-string never crashes before the first
        # tick arrives.
        self.ltq = 0

    def update_tick(self, ltp, ltq, bid_p, bid_q, ask_p, ask_q):
        """Called by the websocket (or mock feed) on every incoming tick."""
        now = datetime.now()
        self.ticks.append((now, ltp, ltq))
        self.ltp = ltp
        self.ltq = ltq
        self.bid_price, self.bid_qty = bid_p, bid_q
        self.ask_price, self.ask_qty = ask_p, ask_q

        # SMMA (Smoothed Moving Average) — equivalent to EMA with a long
        # warm-up. Recurrence: smma_n = (smma_{n-1} * (n-1) + price) / n.
        closes = [t[1] for t in self.ticks]
        if len(closes) >= 20:
            if self.smma20 is None:
                self.smma20 = float(np.mean(closes[-20:]))
            else:
                self.smma20 = (self.smma20 * 19 + ltp) / 20
        if len(closes) >= 120:
            if self.smma120 is None:
                self.smma120 = float(np.mean(closes[-120:]))
            else:
                self.smma120 = (self.smma120 * 119 + ltp) / 120

    def get_etq(self, minutes):
        """Equal-Traded Quantity over the last `minutes` minutes."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return sum(t[2] for t in self.ticks if t[0] >= cutoff)

    def get_avg_ltp(self, minutes):
        """Average LTP over the last `minutes` minutes."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        vals = [t[1] for t in self.ticks if t[0] >= cutoff]
        return float(np.mean(vals)) if vals else self.ltp

    def get_features(self):
        """
        Feature snapshot taken AT ENTRY and persisted to trade_log.csv.
        train_model.py fits the AI filter on this dict, so the keys here
        must match FEATURE_KEYS in trade_tracker.py and train_model.py.
        """
        now = datetime.now()
        cutoff_2 = now - timedelta(minutes=2)
        cutoff_5 = now - timedelta(minutes=5)
        ltq_2 = [t[2] for t in self.ticks if t[0] >= cutoff_2]
        ltq_5 = [t[2] for t in self.ticks if t[0] >= cutoff_5]

        avg_2 = float(np.mean(ltq_2)) if ltq_2 else 1.0
        avg_5 = float(np.mean(ltq_5)) if ltq_5 else 1.0
        etq_5 = self.get_etq(5)
        etq_20 = self.get_etq(20) or 1

        denom = self.bid_qty + self.ask_qty + 1
        imbalance = (self.bid_qty - self.ask_qty) / denom

        recent_closes = [t[1] for t in self.ticks][-100:]
        volatility_20m = float(np.std(recent_closes)) if len(self.ticks) > 10 else 0.0

        return {
            "ltq_ratio_2m_5m": avg_2 / (avg_5 + 1),
            "etq_momentum_5_20": etq_5 / etq_20,
            "bid_ask_imbalance": imbalance,
            "spread": self.ask_price - self.bid_price,
            "smma_gap_pct": (self.smma20 - self.smma120) / (self.ltp + 1) if self.smma20 else 0.0,
            "volatility_20m": volatility_20m,
        }
