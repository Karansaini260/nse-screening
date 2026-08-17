"""
Tests for the ML Stats page.

The page is a Tk widget, so we instantiate it inside Xvfb and
verify the tabs, the metric labels, the figure canvases, and
the data table all populate correctly. We use a synthetic
trade_log.csv so the test is reproducible.

PERFORMANCE: The page used to block the UI thread for 15+ seconds
on every refresh (training 3 algorithms × 5-fold CV × 5 train
sizes). It now runs heavy work in a background thread, so the
tests must wait for the thread to finish before checking the
results. We use _wait_for_refresh() to do that.

Run with: python tests/test_ml_stats_page.py
"""
import sys
import os
import csv
import time
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# We need a display for tkinter.
from pyvirtualdisplay import Display
display = Display(visible=0, size=(1500, 900))
display.start()

import tkinter as tk
from tkinter import ttk


# SINGLE ROOT: Tcl/Tk only supports ONE root window per process.
# After the first test's root is destroyed, creating a second root
# silently fails and the second test hangs. The fix is to use ONE
# root for the entire test module and just destroy+recreate the
# page widget on top of it. The root outlives every test.
_root = None
_root_theme = None

def _get_root():
    global _root, _root_theme
    if _root is None or not _root.winfo_exists():
        _root = tk.Tk()
        from theme import apply_theme
        apply_theme(_root, dark=False)
        _root_theme = True
        _root.geometry("1500x900")
    return _root


def _make_synthetic_trades(n: int = 100, seed: int = 7):
    """Create a trade log with realistic NSE-style features and
    a learnable signal. Returns the rows as a list of dicts.

    We use a wider noise (std=120) and a stronger signal so the
    classes end up balanced (~50/50), which keeps the train/test
    split's stratification happy.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        f1 = rng.normal(1.0, 0.3)
        f2 = rng.normal(1.0, 0.2)
        f3 = rng.normal(0.0, 0.5)
        f4 = abs(rng.normal(0.2, 0.1))
        f5 = rng.normal(0.0, 0.02)
        f6 = rng.normal(2.0, 0.5)
        signal = (f1 * 50 + f2 * 80 + f3 * 30 - f4 * 100 - f6 * 10)
        # Wider noise (std=120) to get a balanced 50/50 class split.
        noise = rng.normal(0, 120)
        pnl = signal + noise
        rows.append({
            "symbol": f"SYM{i % 15}",
            "direction": "BUY" if i % 2 == 0 else "SELL",
            "entry_time": f"2026-01-01T0{i//10 % 24}:00:00",
            "entry_price": 100.0 + i,
            "exit_time": f"2026-01-01T0{i//10 % 24}:30:00",
            "exit_price": 100.0 + i + pnl,
            "pnl": pnl,
            "profitable": int(pnl > 0),
            "ltq_ratio_2m_5m": f1,
            "etq_momentum_5_20": f2,
            "bid_ask_imbalance": f3,
            "spread": f4,
            "smma_gap_pct": f5,
            "volatility_20m": f6,
        })
    return rows


def _write_trade_log(rows, path):
    """Write a list of row dicts to a CSV file with the schema
    the trade_tracker writes."""
    fieldnames = ["symbol", "direction", "entry_time", "entry_price",
                  "exit_time", "exit_price", "pnl", "profitable",
                  "ltq_ratio_2m_5m", "etq_momentum_5_20",
                  "bid_ask_imbalance", "spread", "smma_gap_pct",
                  "volatility_20m"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _make_app_with_trades(rows):
    """Build a minimal Tk app, patch the trade log path so the
    page reads our synthetic data, and return (root, page, backup).

    Uses a SINGLE root for the entire test module (Tkinter only
    supports one root per process). The container is destroyed
    between tests so the page can be replaced with a fresh one.
    """
    from trade_tracker import TRADE_LOG_PATH
    backup = None
    if os.path.exists(TRADE_LOG_PATH):
        backup = TRADE_LOG_PATH + ".bak"
        shutil.copy(TRADE_LOG_PATH, backup)
    _write_trade_log(rows, TRADE_LOG_PATH)
    root = _get_root()
    # If a previous test left a container, destroy it.
    for child in root.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass
    # Pump the event loop several times so any pending
    # after() callbacks from the destroyed page fire (and
    # become no-ops via our winfo_exists() guard).
    for _ in range(5):
        root.update_idletasks()
        root.update()
    # Also force a GC pass to clean up Tk Variables from the
    # previous page. Without this, they linger in the heap and
    # can be GC'd later from a worker thread, which calls
    # Tk from the wrong thread and slows down subsequent tests.
    import gc
    gc.collect()
    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    from pages.ml_stats_page import MLStatsPage
    page = MLStatsPage(container)
    page.grid(row=0, column=0, sticky="nsew")
    root.update_idletasks()
    root.update()
    return root, page, backup


def _wait_for_refresh(page, root, timeout=10.0):
    """Block until the page's background training thread finishes
    AND the UI queue is fully drained (or until timeout). We use
    Tk's update() to pump the event loop and check the thread's
    is_alive() between pumps.

    This is the key helper for the new threaded design — without
    it, the tests would race against the worker thread and see
    empty results.

    Note on robustness: between tests, leaked after() callbacks
    from destroyed pages can be sitting in Tk's event queue. Those
    callbacks do nothing useful (the widget is gone) but they
    consume CPU time, slowing the next test's worker. The
    MLStatsPage.destroy() override cancels its own pending
    callbacks to prevent this, but we also retry the loop a few
    extra times in case of stragglers.
    """
    start = time.time()
    while time.time() - start < timeout:
        # Pump the Tk event loop several times so the UI poller
        # drains the queue.
        for _ in range(5):
            root.update_idletasks()
            root.update()
        # If no workers are alive AND the UI queue is empty, done.
        workers_alive = page._active_worker_count()
        queue_empty = page._ui_queue.empty()
        if workers_alive == 0 and queue_empty:
            # Drain a few more times to let pending after() fire.
            for _ in range(20):
                root.update_idletasks()
                root.update()
                if page._ui_queue.empty():
                    time.sleep(0.05)
            return True
        time.sleep(0.05)
    return False


def _wait_for_algorithm_tab(page, root, timeout=30.0):
    """Switch to the Algorithms tab and wait for the lazy cross-
    validation worker thread to finish rendering. This is
    different from _wait_for_refresh because the lazy populate
    starts its own thread (not stored in _train_thread), so we
    wait for the UI queue to drain instead.

    Timeout was 20s, but cold-start lazy imports (sklearn=664ms,
    analytics module init) can make the first call exceed 20s.
    Bumped to 30s to give margin on slow CI machines.
    """
    page.nb.select(1)  # Algorithms is the 2nd tab (0-indexed 1)
    page._on_tab_changed()  # Trigger lazy populate
    return _wait_for_queue_drain(page, root, timeout=timeout)


def _wait_for_features_tab(page, root, timeout=30.0):
    """Switch to the Features tab and wait for the lazy learning
    curve worker thread to finish rendering."""
    page.nb.select(4)  # Features is the 5th tab (0-indexed 4)
    page._on_tab_changed()  # Trigger lazy populate
    return _wait_for_queue_drain(page, root, timeout=timeout)


def _wait_for_queue_drain(page, root, timeout=15.0):
    """Wait until all worker threads are done AND the UI queue
    is empty. Used for lazy tab populate threads.
    """
    return _wait_for_refresh(page, root, timeout=timeout)


def test_ml_stats_page_renders():
    """Build the page with synthetic trades and verify all the
    tabs, metric labels, and figure canvases are populated.

    With the new threaded design:
      1. The page is built instantly (no training in __init__).
      2. The metrics start as '—' until the user clicks Refresh.
      3. refresh() kicks off a background thread; we wait for it.
      4. The headline metrics, data table, and per-symbol table
         all populate from the cache.
    """
    root, page, backup = _make_app_with_trades(_make_synthetic_trades(n=100))
    try:
        # The page should have 6 tabs.
        assert len(page.nb.tabs()) == 6, f"Expected 6 tabs, got {len(page.nb.tabs())}"
        tab_texts = [page.nb.tab(t, "text") for t in page.nb.tabs()]
        assert "Overview" in tab_texts
        assert "Algorithms" in tab_texts
        assert "Curves" in tab_texts
        assert "Economics" in tab_texts
        assert "Features" in tab_texts
        assert "Data" in tab_texts

        # Before refresh, metrics should be "—" (page is lazy now).
        for label, var in page._metric_vars.items():
            assert var.get() == "—", \
                f"Metric {label} should be '—' before refresh, got {var.get()}"

        # Now click Refresh. This kicks off a background thread.
        page.refresh()
        # Wait for the training thread to finish. The first call
        # also triggers the lazy import of analytics (and through
        # it, sklearn), so it can take ~5s on a cold start.
        ok = _wait_for_refresh(page, root, timeout=30.0)
        assert ok, "Background refresh thread did not finish within 30s"

        # Now the headline metric labels should be populated.
        for label, var in page._metric_vars.items():
            v = var.get()
            assert v != "—", f"Metric {label} is still '—' after refresh"
            # All headline metrics should be 0..1
            try:
                f = float(v)
                assert 0 <= f <= 1, f"Metric {label} out of range: {f}"
            except ValueError:
                pass

        # Active model should be set
        algo = page.active_algo_var.get()
        assert "(click" not in algo and "—" not in algo, \
            f"Active model not set: {algo}"

        # Per-symbol table should have rows
        assert len(page.sym_tree.get_children()) > 0
        # Data table should have rows
        assert len(page.ds_tree.get_children()) > 0
        # Algorithm comparison table should be EMPTY until user
        # visits the Algorithms tab (lazy).
        # We don't assert on cmp_tree here — see test_lazy_algorithm_tab.
        print("PASS: ml_stats_page_renders")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


def test_ml_stats_page_insufficient_data():
    """With fewer than 20 trades, the page should show a friendly
    message instead of crashing."""
    root, page, backup = _make_app_with_trades(_make_synthetic_trades(n=10))
    try:
        page.refresh()
        # Wait for the (very fast) empty-state path to finish.
        _wait_for_refresh(page, root, timeout=5.0)
        # The status should mention the data problem.
        status = page.status_var.get()
        assert "20" in status or "data" in status.lower(), \
            f"Expected data-problem message, got: {status}"
        # Metrics should all be "—"
        for label, var in page._metric_vars.items():
            assert var.get() == "—", f"{label} should be '—' when no data"
        print("PASS: ml_stats_page_insufficient_data")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


def test_ml_stats_page_no_data():
    """With an empty trade log, the page should still render without
    crashing."""
    root, page, backup = _make_app_with_trades([])
    try:
        page.refresh()
        _wait_for_refresh(page, root, timeout=5.0)
        # Should not crash; metrics should be "—"
        for var in page._metric_vars.values():
            assert var.get() == "—"
        print("PASS: ml_stats_page_no_data")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


def test_ml_stats_page_optimal_threshold():
    """Verify the optimal-threshold search returns a sensible value
    (between 0.1 and 0.9) on synthetic data."""
    rows = _make_synthetic_trades(n=100)
    from trade_tracker import TRADE_LOG_PATH
    _write_trade_log(rows, TRADE_LOG_PATH)
    try:
        import pandas as pd
        df = pd.read_csv(TRADE_LOG_PATH)
        from sklearn.model_selection import train_test_split
        from sklearn.linear_model import LogisticRegression
        from trade_tracker import FEATURE_KEYS
        X = df[FEATURE_KEYS]
        y = df["profitable"].astype(int)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y)
        model = LogisticRegression(max_iter=1000)
        model.fit(X_train, y_train)
        y_prob = model.predict_proba(X_test)[:, 1]
        test_df = df.iloc[-len(y_test):]
        from pages.ml_stats_page import MLStatsPage
        thr = MLStatsPage._find_optimal_threshold(
            MLStatsPage, test_df, y_prob, y_test.values)
        assert 0.1 <= thr <= 0.9, f"Threshold out of range: {thr}"
        print(f"PASS: ml_stats_page_optimal_threshold (found {thr})")
    finally:
        try:
            os.remove(TRADE_LOG_PATH)
        except Exception:
            pass


def test_ml_stats_page_lazy_algorithm_tab():
    """The Algorithms tab uses cross-validation which is the
    heaviest part of the page. Verify that:
      1. The tab is NOT populated on construction.
      2. After visiting the tab, the cross-validated table fills in.
    """
    root, page, backup = _make_app_with_trades(_make_synthetic_trades(n=100))
    try:
        # First refresh to populate the cache. The first refresh
        # also triggers the lazy import of analytics + sklearn, so
        # it's slower than subsequent ones.
        page.refresh()
        _wait_for_refresh(page, root, timeout=30.0)
        # Before visiting the Algorithms tab, the cmp_tree should
        # be empty (lazy).
        assert len(page.cmp_tree.get_children()) == 0, \
            "Algorithm table should be empty before visiting the tab"
        # Now visit it and wait.
        ok = _wait_for_algorithm_tab(page, root, timeout=20.0)
        assert ok, "Algorithm tab worker thread did not finish within 20s"
        # Now the table should have 2 rows (one per algorithm).
        assert len(page.cmp_tree.get_children()) == 2, \
            f"Expected 2 algorithm rows, got {len(page.cmp_tree.get_children())}"
        print("PASS: ml_stats_page_lazy_algorithm_tab")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


def test_ml_stats_page_lazy_features_tab():
    """The Features tab uses a learning curve. Verify that:
      1. The tab is NOT populated on construction.
      2. After visiting the tab, the feature importance and
         learning curve render.
    """
    root, page, backup = _make_app_with_trades(_make_synthetic_trades(n=100))
    try:
        page.refresh()
        _wait_for_refresh(page, root, timeout=30.0)
        # Visit the Features tab and wait.
        ok = _wait_for_features_tab(page, root, timeout=20.0)
        assert ok, "Features tab worker thread did not finish within 20s"
        # After _replace_figure, the slot's `fig` is the new
        # one. Check that it has axes with content.
        new_fig = page._imp_canvas.fig
        assert new_fig is not None
        assert len(new_fig.axes) > 0, "Feature importance has no axes"
        # There should be at least one Axes with at least one patch
        # (the bar rectangles).
        has_patches = False
        for ax in new_fig.axes:
            if len(ax.patches) > 0:
                has_patches = True
                break
        assert has_patches, "Feature importance figure has no bars after render"
        # Same for the learning curve.
        lc_fig = page._lc_canvas.fig
        assert lc_fig is not None
        assert len(lc_fig.axes) > 0, "Learning curve has no axes"
        print("PASS: ml_stats_page_lazy_features_tab")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


def test_ml_stats_page_cache_reuse():
    """A second Refresh call with unchanged data should reuse the
    cache and be essentially instant (no background thread)."""
    root, page, backup = _make_app_with_trades(_make_synthetic_trades(n=100))
    try:
        # First refresh: kicks off a thread, populates cache.
        page.refresh()
        _wait_for_refresh(page, root, timeout=30.0)
        first_status = page.status_var.get()
        # Second refresh: should detect no change and skip the thread.
        page.refresh()
        # Wait a beat to let any after() callbacks fire.
        for _ in range(10):
            root.update_idletasks()
            root.update()
            time.sleep(0.02)
        second_status = page.status_var.get()
        # The second status should mention caching / reusing.
        assert "cached" in second_status.lower() or "unchanged" in second_status.lower(), \
            f"Expected cache-reuse message, got: {second_status}"
        # No thread should be running after a cache hit.
        with page._train_lock:
            thread = page._train_thread
        assert thread is None or not thread.is_alive(), \
            "Background thread should not be running after cache hit"
        print("PASS: ml_stats_page_cache_reuse")
    finally:
        from trade_tracker import TRADE_LOG_PATH
        if backup:
            shutil.move(backup, TRADE_LOG_PATH)
        else:
            try:
                os.remove(TRADE_LOG_PATH)
            except Exception:
                pass
        try:
            page.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    test_ml_stats_page_renders()
    test_ml_stats_page_insufficient_data()
    test_ml_stats_page_no_data()
    test_ml_stats_page_optimal_threshold()
    test_ml_stats_page_lazy_algorithm_tab()
    test_ml_stats_page_lazy_features_tab()
    test_ml_stats_page_cache_reuse()
    print("\nALL ML STATS PAGE TESTS PASSED")
    display.stop()
