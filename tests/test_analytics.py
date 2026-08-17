"""
Tests for the analytics module.

Run with: python tests/test_analytics.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import analytics


def _make_synthetic_trades(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic trade log with a learnable signal.

    The features have a clear relationship with profitability:
    high LTQ ratio + positive ETQ momentum + tight spread = profit.

    We use a feature weighting that produces roughly 40-60% winners
    (which matches the real NSE Screener win rate) so the train/test
    split has enough of each class to stratify.
    """
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "ltq_ratio_2m_5m": rng.normal(1.0, 0.3, n),
        "etq_momentum_5_20": rng.normal(1.0, 0.2, n),
        "bid_ask_imbalance": rng.normal(0.0, 0.5, n),
        "spread": np.abs(rng.normal(0.2, 0.1, n)),
        "smma_gap_pct": rng.normal(0.0, 0.02, n),
        "volatility_20m": rng.normal(2.0, 0.5, n),
    })
    # Make P&L depend on the features (with noise) so the model
    # has something to learn. We balance the noise so we get
    # ~50% winners.
    signal = (df["ltq_ratio_2m_5m"] * 50
              + df["etq_momentum_5_20"] * 80
              + df["bid_ask_imbalance"] * 30
              - df["spread"] * 100
              - df["volatility_20m"] * 10)
    noise = rng.normal(0, 60, n)  # wider noise for balanced classes
    pnl = signal + noise
    df["pnl"] = pnl
    df["profitable"] = (pnl > 0).astype(int)
    df["symbol"] = [f"SYM{i % 20}" for i in range(n)]
    df["direction"] = ["BUY" if i % 2 == 0 else "SELL" for i in range(n)]
    return df


def test_compute_metrics_basic():
    """compute_metrics should return accuracy, precision, recall
    etc. in [0, 1] for binary classification."""
    y_true = np.array([0, 1, 1, 0, 1, 0, 1, 1])
    y_pred = np.array([0, 1, 1, 0, 0, 0, 1, 1])
    y_prob = np.array([0.1, 0.9, 0.8, 0.2, 0.4, 0.3, 0.7, 0.85])
    m = analytics.compute_metrics(y_true, y_pred, y_prob)
    assert 0 <= m["accuracy"] <= 1
    assert 0 <= m["precision"] <= 1
    assert 0 <= m["recall"] <= 1
    assert 0 <= m["f1"] <= 1
    assert 0 <= m["roc_auc"] <= 1
    assert 0 <= m["specificity"] <= 1
    assert m["n"] == 8
    # Perfect classification should give all metrics = 1
    y_pred_perfect = y_true.copy()
    m_perfect = analytics.compute_metrics(y_true, y_pred_perfect, y_prob)
    assert m_perfect["accuracy"] == 1.0
    assert m_perfect["precision"] == 1.0
    assert m_perfect["recall"] == 1.0
    print("PASS: compute_metrics basic")


def test_train_all_algorithms():
    """train_all should fit every algorithm and return metrics."""
    df = _make_synthetic_trades(n=100)
    X, y = analytics._prepare_xy(df)
    assert X is not None and y is not None
    results = analytics.train_all(X, y)
    assert len(results) == 3  # 3 algorithms
    for name in ("Logistic Regression", "Random Forest", "Gradient Boosting"):
        assert name in results
        assert "error" not in results[name]
        m = results[name]["metrics"]
        # Synthetic data has a real signal, so accuracy should be
        # well above random (0.5).
        assert m["accuracy"] > 0.55, f"{name} accuracy too low: {m['accuracy']}"
    print("PASS: train_all_algorithms")


def test_cross_validate():
    """cross_validate should return mean and std for each metric."""
    df = _make_synthetic_trades(n=80)
    X, y = analytics._prepare_xy(df)
    cv = analytics.cross_validate("Logistic Regression", X, y, n_splits=3)
    for metric in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        assert metric in cv
        assert "mean" in cv[metric] and "std" in cv[metric]
        assert 0 <= cv[metric]["mean"] <= 1
    print("PASS: cross_validate")


def test_backtest_pnl():
    """backtest_pnl should compute baseline and filtered P&L."""
    df = _make_synthetic_trades(n=50)
    # Pretend the model accepts everything (threshold 0).
    y_prob = np.ones(len(df)) * 0.9
    bt = analytics.backtest_pnl(df, y_prob, threshold=0.5)
    # Accepting all trades should equal the baseline.
    assert bt["n_taken"] == 50
    assert abs(bt["filtered_pnl"] - bt["baseline_pnl"]) < 1e-6
    # Pretend the model rejects everything.
    y_prob_zero = np.zeros(len(df))
    bt2 = analytics.backtest_pnl(df, y_prob_zero, threshold=0.5)
    assert bt2["n_taken"] == 0
    assert bt2["filtered_pnl"] == 0
    print("PASS: backtest_pnl")


def test_per_symbol_breakdown():
    """per_symbol_breakdown should return per-symbol stats."""
    df = _make_synthetic_trades(n=100)
    y_prob = np.random.uniform(0, 1, len(df))
    bd = analytics.per_symbol_breakdown(df, y_prob, threshold=0.5)
    assert "win_rate" in bd.columns
    assert "model_accuracy" in bd.columns
    assert "model_lift" in bd.columns
    assert len(bd) > 0  # at least some symbols had trades
    print("PASS: per_symbol_breakdown")


def test_figures_render():
    """Every figure function should return a non-empty Figure."""
    df = _make_synthetic_trades(n=100)
    X, y = analytics._prepare_xy(df)
    results = analytics.train_all(X, y)
    lr = results["Logistic Regression"]
    # All the figure functions.
    fig = analytics.fig_confusion_matrix(
        analytics.confusion_matrix(lr["y_test"], lr["y_pred"], labels=[0, 1]),
        "Logistic Regression"
    )
    assert fig is not None
    fig = analytics.fig_roc_curve(lr["y_test"], lr["y_prob"],
                                 lr["metrics"]["roc_auc"], "Logistic Regression")
    assert fig is not None
    fig = analytics.fig_pr_curve(lr["y_test"], lr["y_prob"],
                                lr["metrics"]["pr_auc"], "Logistic Regression")
    assert fig is not None
    fig = analytics.fig_calibration(lr["y_test"], lr["y_prob"], "Logistic Regression")
    assert fig is not None
    fig = analytics.fig_feature_importance(lr["model"], X, "Logistic Regression")
    assert fig is not None
    fig = analytics.fig_learning_curve("Logistic Regression", X, y)
    assert fig is not None
    fig = analytics.fig_pnl_distribution(df)
    assert fig is not None
    fig = analytics.fig_proba_distribution(lr["y_test"], lr["y_prob"],
                                         "Logistic Regression")
    assert fig is not None
    fig = analytics.fig_algorithm_comparison(results)
    assert fig is not None
    print("PASS: figures_render")


def test_algorithm_comparison_random_data():
    """On random data, all algorithms should perform near chance."""
    rng = np.random.default_rng(123)
    n = 200
    X = pd.DataFrame(rng.normal(0, 1, (n, 6)),
                     columns=analytics.FEATURE_KEYS)
    y = pd.Series(rng.integers(0, 2, n))
    results = analytics.train_all(X, y)
    for name, r in results.items():
        if "error" not in r:
            # Accuracy should be near 0.5 on random data.
            acc = r["metrics"]["accuracy"]
            assert 0.3 < acc < 0.7, f"{name} accuracy on random: {acc}"
    print("PASS: algorithm_comparison_random_data")


def test_prepare_xy_handles_missing():
    """_prepare_xy should return (None, None) for bad input."""
    X, y = analytics._prepare_xy(pd.DataFrame())
    assert X is None and y is None
    # Only 5 rows.
    df = _make_synthetic_trades(n=5)
    X, y = analytics._prepare_xy(df)
    assert X is None and y is None
    print("PASS: prepare_xy_handles_missing")


if __name__ == "__main__":
    test_compute_metrics_basic()
    test_train_all_algorithms()
    test_cross_validate()
    test_backtest_pnl()
    test_per_symbol_breakdown()
    test_figures_render()
    test_algorithm_comparison_random_data()
    test_prepare_xy_handles_missing()
    print("\nALL ANALYTICS TESTS PASSED")
