"""
Round-trip trade logger. Every SMMA crossover is recorded as a trade
entry; a crossover in the opposite direction closes it and writes one
row to trade_log.csv with the entry-time feature snapshot attached.
"""

import csv
import os
from datetime import datetime

TRADE_LOG_PATH = "trade_log.csv"

# Must match the keys returned by SymbolState.get_features() in indicators.py
# AND the columns read by train_model.py / ai_model.py. Adding a feature
# here means adding it in both other files too.
FEATURE_KEYS = [
    "ltq_ratio_2m_5m",
    "etq_momentum_5_20",
    "bid_ask_imbalance",
    "spread",
    "smma_gap_pct",
    "volatility_20m",
]


class TradeTracker:
    """
    One open trade per symbol. A same-direction signal just replaces the
    entry (rare — crossovers are one-time events by construction); an
    opposite-direction signal closes the open trade and immediately
    opens a new one in the other direction.
    """

    def __init__(self, log_path=TRADE_LOG_PATH):
        self.log_path = log_path
        self.open_trades = {}  # symbol -> {direction, entry_price, entry_time, features}
        self._ensure_log_header()

    def _ensure_log_header(self):
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        "symbol", "direction", "entry_time", "entry_price",
                        "exit_time", "exit_price", "pnl", "profitable",
                    ]
                    + FEATURE_KEYS
                )

    def on_signal(self, symbol, direction, ltp, features, when=None):
        """
        Called every time a fresh SMMA crossover fires for `symbol`.
        `direction` is 'BUY' or 'SELL'.
        """
        when = when or datetime.now()
        prev = self.open_trades.get(symbol)

        # Opposite crossover = exit signal for the currently open trade.
        if prev and prev["direction"] != direction:
            self._close_trade(symbol, prev, ltp, when)

        # Open (or re-open in the new direction) the trade at the
        # current LTP. If the same direction fires twice we keep the
        # original entry — averaging into a winning position is out of
        # scope for this screener.
        cur = self.open_trades.get(symbol)
        if not cur or cur["direction"] != direction:
            self.open_trades[symbol] = {
                "direction": direction,
                "entry_price": ltp,
                "entry_time": when,
                "features": features,
            }

    def _close_trade(self, symbol, trade, exit_price, exit_time):
        entry_price = trade["entry_price"]
        direction = trade["direction"]
        # Long profit = exit above entry; short profit = exit below entry.
        pnl = (exit_price - entry_price) if direction == "BUY" else (entry_price - exit_price)
        profitable = int(pnl > 0)

        with open(self.log_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    symbol, direction, trade["entry_time"].isoformat(), entry_price,
                    exit_time.isoformat(), exit_price, pnl, profitable,
                ]
                + [trade["features"].get(k, 0) for k in FEATURE_KEYS]
            )

        # The position is now closed; the caller will open the new one
        # in the opposite direction.
        self.open_trades.pop(symbol, None)

    def open_symbols(self):
        """Snapshot of currently-open trades — used by the Trade Log page."""
        return {
            s: {
                "direction": t["direction"],
                "entry_price": t["entry_price"],
                "entry_time": t["entry_time"],
            }
            for s, t in self.open_trades.items()
        }
