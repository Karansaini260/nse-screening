"""
Non-GUI smoke test: exercises the data layer end-to-end without
needing a display. Run with: `python -m pytest tests/test_smoke.py`
or directly with `python tests/test_smoke.py`.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import joblib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_indicators_smma_and_features():
    from datetime import datetime, timedelta
    import indicators

    s = indicators.SymbolState("TEST")
    base_time = datetime.now()
    # Feed 200 rising ticks so SMMA(20) crosses SMMA(120) cleanly.
    for i in range(200):
        ts = base_time + timedelta(seconds=i)
        s.ticks.append((ts, 100 + i * 0.5, 100))
    s.update_tick(200.0, 100, 199.95, 50_000, 200.05, 50_000)
    assert s.ltp == 200.0
    assert s.smma20 is not None and s.smma120 is not None
    feats = s.get_features()
    for k in (
        "ltq_ratio_2m_5m", "etq_momentum_5_20", "bid_ask_imbalance",
        "spread", "smma_gap_pct", "volatility_20m",
    ):
        assert k in feats, f"missing feature: {k}"


def test_trade_tracker_roundtrip(tmp_path):
    from trade_tracker import TradeTracker, FEATURE_KEYS
    tmp_path.mkdir(parents=True, exist_ok=True)
    log = str(tmp_path / "trades.csv")
    t = TradeTracker(log_path=log)
    feats = {k: 0.5 for k in FEATURE_KEYS}
    # Every crossover is both a close (if there's an opposite trade
    # open) and an open (in the new direction). So:
    #   BUY 100  -> opens a BUY at 100
    #   SELL 110  -> closes the BUY (pnl +10), opens a SELL at 110
    #   BUY 105   -> closes the SELL (pnl +5), opens a BUY at 105
    t.on_signal("ABC", "BUY", 100.0, feats)
    t.on_signal("ABC", "SELL", 110.0, feats)
    t.on_signal("ABC", "BUY", 105.0, feats)
    # After the third signal, ABC is open as a BUY at 105.
    assert "ABC" in t.open_symbols()
    assert t.open_symbols()["ABC"]["direction"] == "BUY"
    # CSV has the two closed round-trips.
    df = pd.read_csv(log)
    assert len(df) == 2
    first = df.iloc[0]
    assert first["symbol"] == "ABC"
    assert first["direction"] == "BUY"
    assert float(first["pnl"]) == 10.0      # BUY: exit(110) - entry(100)
    assert int(first["profitable"]) == 1
    second = df.iloc[1]
    assert second["direction"] == "SELL"
    assert float(second["pnl"]) == 5.0      # SELL: entry(110) - exit(105)
    assert int(second["profitable"]) == 1


def test_ai_model_heuristic():
    from indicators import SymbolState
    from ai_model import predict_signal
    s = SymbolState("XYZ")
    s.update_tick(100, 500, 99.95, 200_000, 100.05, 200_000)
    p, d, r = predict_signal(s, "BUY")
    assert 0.0 <= p <= 1.0
    assert d in ("ACCEPT", "AVOID")
    assert isinstance(r, str)


def test_train_model_pipeline(tmp_path):
    """End-to-end: log 30 trades, fit a model, save, reload, predict."""
    from sklearn.linear_model import LogisticRegression
    from trade_tracker import TradeTracker, FEATURE_KEYS
    import ai_model as aim

    tmp_path.mkdir(parents=True, exist_ok=True)
    log = str(tmp_path / "trades.csv")
    model_path = str(tmp_path / "signal_model.pkl")
    aim.MODEL_PATH = model_path
    t = TradeTracker(log_path=log)

    # 30 separate symbols, each going BUY -> SELL (one closed round-trip).
    # The SELL closes the BUY AND opens a new SELL; we then send a final
    # BUY at the same exit price so the trade is fully flat and counted
    # as two closed round-trips per symbol.
    for i in range(30):
        feats = {k: (i % 6) * 0.1 for k in FEATURE_KEYS}
        t.on_signal(f"SYM{i}", "BUY", 100.0, feats)
        exit_price = 105.0 if i % 2 == 0 else 95.0
        t.on_signal(f"SYM{i}", "SELL", exit_price, feats)
        # Close the just-opened SELL at the same price so the symbol
        # is flat. The SELL row's pnl is exit(==entry) so it's 0; the
        # BUY row's pnl is +5 or -5 depending on parity.
        t.on_signal(f"SYM{i}", "BUY", exit_price, feats)

    df = pd.read_csv(log)
    # 30 symbols * 2 closed rows (BUY + SELL) = 60 rows.
    assert len(df) == 60
    # Of those, the 30 BUY rows alternate +5 / -5 (because exit_price
    # alternates 105 / 95), and the 30 SELL rows are all 0 (because we
    # close them at the same price we opened them). So 15 winners and
    # 15 losers among the BUY rows, all SELL rows are losers.
    buy_rows = df[df["direction"] == "BUY"]
    sell_rows = df[df["direction"] == "SELL"]
    assert (buy_rows["pnl"] != 0).all()        # each BUY has a real P&L
    assert (sell_rows["pnl"] == 0).all()       # SELLs are flat closes
    assert buy_rows["profitable"].sum() == 15  # 15 of 30 BUYs are +5
    assert sell_rows["profitable"].sum() == 0  # no SELL has a real profit
    # Both classes present so the model has something to learn.
    assert df["profitable"].nunique() == 2

    X = df[FEATURE_KEYS]
    y = df["profitable"]
    m = LogisticRegression(max_iter=1000, class_weight="balanced")
    m.fit(X, y)
    joblib.dump(m, model_path)
    assert os.path.exists(model_path)

    aim._model = None
    aim._model_loaded = False
    loaded = aim._load_model()
    assert loaded is not None
    probs = loaded.predict_proba(X[:3])
    assert probs.shape == (3, 2)


def test_shared_settings_defaults():
    import shared
    # Sanity: the key defaults exist and are positive.
    assert "ltp_min" in shared.Settings.DEFAULTS
    assert shared.Settings.DEFAULTS["ltp_min"] > 0
    assert shared.Settings.DEFAULTS["ltp_min"] < shared.Settings.DEFAULTS["ltp_max"]
    assert shared.Settings.DEFAULTS["ltp_max"] >= 1000, \
        "LTP max must be wide enough for high-priced Nifty names like MRF / BAJFINANCE"
    assert shared.Settings.DEFAULTS["liquidity_min_qty"] <= 10_000, \
        "Default liquidity threshold should be modest; the user can raise it"


if __name__ == "__main__":
    import tempfile, shutil
    base = Path(tempfile.mkdtemp())
    try:
        test_indicators_smma_and_features()
        test_trade_tracker_roundtrip(base / "roundtrip")
        test_ai_model_heuristic()
        test_train_model_pipeline(base / "train")
        test_shared_settings_defaults()
        print("ALL SMOKE TESTS PASSED")
    finally:
        shutil.rmtree(base, ignore_errors=True)
