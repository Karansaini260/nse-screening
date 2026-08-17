"""
Page 6 — ML Model Training & Stats. A problem-and-solution oriented
analytics dashboard for the AI filter.

The "problem" this page addresses:
  The screener fires dozens of SMMA crossovers every day, but most
  are noise. We want a model that says "this crossover is likely a
  winner, take it" vs "this is a loser, skip it" — and we want to
  KNOW how well the model actually works.

The "solution":
  1. Train multiple algorithms (Logistic Regression, Random Forest)
     on the user's closed trades.
  2. Report the algorithm's metrics honestly (cross-validated, not
     just a single train/test split).
  3. Show the user the ECONOMIC impact: how much P&L would they
     have made if they'd followed the model's recommendations vs.
     taken every signal?

This page provides, in order:

  * Headline metrics (Accuracy, Precision, Recall, F1, ROC-AUC, etc.)
  * Algorithm comparison (which model is best on the user's data)
  * Confusion matrix heatmap
  * ROC curve and Precision-Recall curve
  * Calibration plot (is the model's probability trustworthy?)
  * Feature importance (with positive/negative direction for linear
    models)
  * Learning curve (does the model need more data?)
  * P&L distribution and prediction distribution
  * Economic backtest (does using the filter actually make money?)
  * Per-symbol accuracy breakdown
  * Cross-validated metrics with mean ± std
  * Historical trade log (most recent 50 closed trades)

Actions:
  * "Retrain Now" — fits every algorithm, picks the best by ROC-AUC,
    saves it as the active model with the best threshold.
  * "Refresh Metrics" — recompute everything from the current
    trade_log.csv without retraining.

PERFORMANCE NOTES
-----------------
This page used to block the UI thread for 15+ seconds on a 200-row
trade log because it trained 2 algorithms × 5 CV folds × 5 train
sizes in series. That made the whole app "Not Responding" while the
page was being instantiated. The fix is:

  1. The page no longer trains anything in __init__. The UI is built
     immediately and shows a "Click Refresh Metrics" hint. The user
     sees the page in well under 100ms.

  2. The actual training runs in a daemon background thread. The UI
     stays responsive; a spinner label shows "Training..." while it's
     running and the results appear when done.

  3. Heavy operations (cross-validation, learning curve) are NOT
     run unless the user actually visits the Algorithms and Features
     tabs. The Overview, Economics, and Data tabs only need one
     train_all() call.

  4. Results are cached in self._cache keyed by (n_rows, last_modified).
     Repeated Refresh clicks with no new data are essentially free.

  5. The algorithms themselves are lighter (n_estimators=60 instead
     of 200, 3-fold CV instead of 5-fold) so each individual call
     is also faster. See analytics.py.
"""

import os
import csv
import threading
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
# pandas is NOT imported here — it's only used by analytics.py
# (which is itself lazy-imported below). Importing pandas takes
# 237ms, and we don't need it directly on this page.

# LAZY matplotlib import: importing matplotlib.figure + backend_tkagg
# takes ~270ms. We only need them once the user actually clicks
# "Refresh Metrics" on this page. Until then, the page shows
# placeholder labels and the user can see it instantly.
# matplotlib.pyplot and pyplot.figure are imported lazily inside
# _ensure_matplotlib().

# LAZY analytics import: importing analytics pulls in sklearn (664ms)
# and pandas (237ms). We only need it for training + figures, which
# happens on Refresh. Until then, the user just sees "Click Refresh".
# The actual `import analytics` happens inside the refresh worker
# so it doesn't block the UI thread.

from trade_tracker import TRADE_LOG_PATH
from ai_model import MODEL_PATH
from pages.background import run_in_background, WorkerTracker
from pages.figures import create_figure_in_frame


# Module-level stub for `analytics` so the rest of the file's
# `analytics.fig_*` and `analytics._prepare_xy` references work
# even before the real analytics module is imported. The actual
# import is triggered on first use of the module (e.g. when the
# user clicks Refresh Metrics or Retrain Now).
import types
analytics = types.ModuleType("analytics")
analytics.ALGORITHMS = {}


class _FigureSlot:
    """A placeholder for a matplotlib figure that may or may not
    be created yet. Used by MLStatsPage to defer the 30ms-per-
    figure cost until the user actually wants to see charts.

    `is_real` is True once `_ensure_real_figure()` has created
    the underlying Figure and canvas. Before that, `fig`, `ax`,
    and `canvas` are all None and the slot shows a placeholder
    Label in its parent frame.

    Defined here (before MLStatsPage) so the page can reference
    it during __init__.
    """
    __slots__ = ("parent", "placeholder", "fig", "ax", "canvas", "is_real")

    def __init__(self, parent, placeholder):
        self.parent = parent
        self.placeholder = placeholder
        self.fig = None
        self.ax = None
        self.canvas = None
        self.is_real = False


def _ensure_analytics():
    """Lazily import the analytics module. Returns the module.
    Called the first time the user clicks Refresh Metrics or
    Retrain Now. After this, the module is cached in the global
    `analytics` symbol so subsequent calls are O(1).
    """
    global analytics
    if not hasattr(analytics, "load_trades") or not hasattr(analytics, "ALGORITHMS") or not analytics.ALGORITHMS:
        import analytics as _real_analytics
        analytics = _real_analytics
    return analytics


# Pretty human-readable descriptions of each metric. We show
# these as tooltips so the user can learn what the numbers mean.
METRIC_DESCRIPTIONS = {
    "Accuracy":  "Fraction of all predictions that are correct.\n"
                 "Useful but misleading on imbalanced data: a model "
                 "that always predicts 'loser' on a 30%-winner dataset\n"
                 "is 70% accurate but useless.",
    "Precision": "Of the trades the model says 'take', what fraction\n"
                 "are actually winners. High precision = few false "
                 "alarms.",
    "Recall":    "Of the trades that were actually winners, what "
                 "fraction did the model flag.\nHigh recall = few "
                 "missed opportunities.",
    "F1":        "Harmonic mean of precision and recall. The single\n"
                 "best number to compare models on imbalanced data.",
    "ROC-AUC":   "Area under the ROC curve. 0.5 = random, 1.0 = perfect.\n"
                 "Measures how well the model RANK-ORDERS winners "
                 "above losers.",
    "PR-AUC":    "Area under the Precision-Recall curve. Better than\n"
                 "ROC-AUC when the positive class is rare (e.g. "
                 "only 30% winners).",
    "Brier":     "Mean squared error of predicted probabilities.\n"
                 "Lower = better calibrated. 0.25 = random.",
    "Specificity": "Of the trades that were actually losers, what\n"
                   "fraction did the model correctly reject. "
                   "The other side of the recall coin.",
}


class MLStatsPage(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=SPACE_MD)

        # Top: title + buttons
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="ML Model — Analytics & Training",
                  font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Button(top, text="Retrain Now",
                   command=self._retrain).pack(side="right")
        ttk.Button(top, text="Refresh Metrics",
                   command=self.refresh).pack(side="right", padx=(0, 6))

        # Notebook with tabs for different analytics sections. Using
        # a ttk.Notebook keeps each section focused and avoids
        # overwhelming the user with 12 charts at once.
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, pady=(8, 0))

        # Build all the tabs. Each is a Frame that we'll add to the
        # notebook. We store them in self.tabs for easy access.
        self.tabs = {}
        self._build_overview_tab()
        self._build_algorithm_tab()
        self._build_curves_tab()
        self._build_economics_tab()
        self._build_features_tab()
        self._build_data_tab()

        # When the user switches tabs, lazily compute that tab's
        # heavy content (Algorithms = cross-validation, Features =
        # learning curve). This keeps the cheap tabs (Overview,
        # Economics, Data) snappy.
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # The "active algorithm" displayed in the header — this is
        # the one used by the dashboard for live predictions.
        self.active_algo_var = tk.StringVar(value="(none)")
        active_bar = ttk.Frame(self)
        active_bar.pack(fill="x", pady=(8, 0))
        ttk.Label(active_bar, text="Active model:",
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(active_bar, textvariable=self.active_algo_var,
                  foreground="#4f46e5").pack(side="left", padx=(4, 0))

        # Status line
        self.status_var = tk.StringVar(value="Click 'Refresh Metrics' to compute analytics.")
        ttk.Label(self, textvariable=self.status_var,
                  foreground="gray").pack(fill="x", pady=(2, 0))

        # -----------------------------------------------------------------
        # Performance infrastructure
        # -----------------------------------------------------------------
        # Cache of last results, keyed by (n_rows, file_mtime). Refresh
        # is a no-op if the data hasn't changed.
        self._cache_key = None
        self._cache_df = None           # the last DataFrame
        self._cache_results = None      # train_all() output
        self._cache_best = None         # (name, result) of best algo
        self._cache_tab_computed = set()  # which tabs have been computed
        self._train_thread = None       # current background thread
        self._train_lock = threading.Lock()
        # All background worker threads (refresh + lazy tab populate).
        # The test helper uses this to know when everything has
        # finished. We don't strictly need it for the app itself.
        # The implementation is in pages/background.py.
        self._tracker = WorkerTracker()
        # Queue of UI-update callables produced by background threads.
        # We can't use self.after() from a non-main thread (it raises
        # "main thread is not in main loop"), so worker threads put
        # callables here and the main thread drains the queue via
        # _poll_ui_queue. The poll is started by _start_ui_poll().
        self._ui_queue = queue.Queue()
        self._ui_poll_running = False
        # Show a friendly "click refresh" hint in the headline metrics
        # on first load — no training in __init__ anymore.
        self._show_idle_hint()

        # -----------------------------------------------------------------
        # Figure cache. Each entry maps a "figure role" (cm, pd, roc,
        # pr, cal, pnl) to a cache key derived from the input data.
        # When the input data changes, the cache key changes and we
        # re-render the figure. When the data is the same, we skip
        # the ~30ms cost of creating a new matplotlib figure.
        # This is a big win on the Overview tab: 8 metric labels
        # update in <1ms, but the 2 figures were taking 60ms+.
        # -----------------------------------------------------------------
        self._fig_cache = {}

    def _make_lazy_figure(self, parent_frame):
        """Create a placeholder for a matplotlib figure inside
        `parent_frame`. The placeholder is just a tk.Label saying
        "Click Refresh to compute". On the first call to
        `_ensure_real_figure()` for this slot, the placeholder is
        replaced with a real Figure + FigureCanvasTkAgg.

        Returns (fig, ax, canvas) — all of which are None until
        the first refresh. The page's `__init__` uses this so we
        don't pay the 30ms-per-figure cost of creating 9 figures
        that the user might never look at (if they never click
        Refresh).

        We track the parent_frame so the lazy init can find it
        later. We also track the slot name (cm, pd, roc, etc.) so
        we can call _ensure_real_figure("cm") from a refresh.
        """
        # Placeholder label inside the parent frame. The user sees
        # "Click Refresh to compute" until they actually compute
        # the data.
        placeholder = ttk.Label(
            parent_frame,
            text="Click 'Refresh Metrics' to compute.",
            foreground="gray", justify="center", font=("Segoe UI", 9),
        )
        placeholder.pack(fill="both", expand=True)
        # Stash the parent + placeholder for later use.
        slot = _FigureSlot(parent_frame, placeholder)
        return slot, slot, slot

    def _ensure_real_figure(self, slot, figsize=(4, 3.2)):
        """If the slot is still a placeholder, replace it with a
        real matplotlib Figure + canvas. Idempotent: subsequent
        calls are no-ops. Returns (fig, ax, canvas).

        Lazy: only called when we actually have data to draw.
        The 9 figure creations are deferred until the first
        refresh, which can save ~270ms on page init.

        Implementation: delegates to
        `pages.figures.create_figure_in_frame()` for the actual
        Figure + canvas creation. The placeholder-slot
        bookkeeping stays in this class because the slot object
        owns the placeholder Label.
        """
        if slot.is_real:
            return slot.fig, slot.ax, slot.canvas
        # Remove the placeholder label from the parent frame.
        try:
            slot.placeholder.destroy()
        except Exception:
            pass
        # Delegate the figure + canvas creation to the shared
        # helper. The helper takes care of the matplotlib imports
        # and the canvas packing.
        fig, ax, canvas = create_figure_in_frame(
            slot.parent, figsize=figsize,
        )
        # The theme walker uses _figure_ref to find the
        # FigureCanvasTkAgg when the user toggles dark mode.
        canvas.get_tk_widget()._figure_ref = fig
        slot.fig = fig
        slot.ax = ax
        slot.canvas = canvas
        slot.is_real = True
        return fig, ax, canvas

    # -----------------------------------------------------------------
    # Tab construction
    # -----------------------------------------------------------------

    def _spawn_worker(self, target, name=None):
        """Spawn a daemon worker thread and track it in
        self._worker_threads. Returns the thread.

        Implementation is now a thin wrapper over
        `pages.background.run_in_background()` so the daemon
        flag, error logging, and tracker-update logic live in
        one place.
        """
        return run_in_background(target, name=name, tracker=self._tracker)

    def _active_worker_count(self):
        """Return the number of worker threads still alive.
        Used by the test helper to know when all background work
        is finished."""
        return len(self._tracker.alive)

    def destroy(self):
        """Override destroy to stop the UI poller cleanly. Without
        this, the recurring after() callback fires after the widget
        is gone and prints "invalid command name" warnings to the
        console.

        We flip _ui_poll_running BEFORE calling super().destroy()
        so the in-flight poll can check the flag and bail out
        before trying to re-arm itself on a dead widget.

        We also drop our references to all Tk StringVars and
        matplotlib Figure objects so they're garbage-collected
        BEFORE the parent widget is destroyed. Otherwise the
        StringVar.__del__ can run on a non-main thread (when GC
        is triggered from a worker thread's sklearn work) and
        call into a half-destroyed Tk interpreter.
        """
        self._ui_poll_running = False
        # Also clear the worker tracking so any late-finishing
        # worker threads don't keep the test helper waiting.
        try:
            self._tracker.clear()
        except Exception:
            pass
        try:
            with self._train_lock:
                self._train_thread = None
        except Exception:
            pass
        # Drop our refs to Tk StringVars BEFORE destroy so their
        # __del__ can run on the main thread while the Tk
        # interpreter is still healthy.
        try:
            self._metric_vars.clear()
        except Exception:
            pass
        try:
            self._econ_vars.clear()
        except Exception:
            pass
        # Close any matplotlib figures we created.
        for slot_name in ("_cm_fig", "_pd_fig", "_comp_fig",
                          "_roc_fig", "_pr_fig", "_cal_fig",
                          "_pnl_fig", "_imp_fig", "_lc_fig"):
            try:
                slot = getattr(self, slot_name, None)
                if slot is not None and getattr(slot, "is_real", False):
                    if slot.canvas is not None:
                        slot.canvas.get_tk_widget().destroy()
                    if slot.fig is not None:
                        import matplotlib.pyplot as plt
                        plt.close(slot.fig)
            except Exception:
                pass
        try:
            super().destroy()
        except Exception:
            pass
        # Force a GC pass so any remaining Tk Variables are cleaned
        # up NOW (on the main thread) rather than later from a
        # worker thread.
        import gc
        gc.collect()

    def _build_overview_tab(self):
        """The 'Overview' tab: headline metrics, confusion matrix, and
        problem/solution statement so the user knows what this is
        for."""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Overview")
        self.tabs["overview"] = tab

        # Top: Problem / Solution statement
        ps_frame = ttk.LabelFrame(tab, text="What this page is for")
        ps_frame.pack(fill="x", pady=(8, 4), padx=4)
        problem_text = (
            "PROBLEM: SMMA crossovers fire constantly. Most are noise.\n"
            "We need a model that says 'take this one' vs 'skip this one'.\n"
            "\n"
            "SOLUTION: Train a classifier on the user's own closed trades.\n"
            "It learns which combination of LTQ ratio, ETQ momentum, bid-ask\n"
            "imbalance, spread, SMMA gap, and volatility predicts a winner.\n"
            "\n"
            "Below: how well the model works on YOUR data, with cross-validated\n"
            "metrics, confusion matrix, ROC curve, calibration, and an\n"
            "economic backtest (does using the filter actually make money?).\n"
            "\n"
            "TIPS:\n"
            "  - First time? Click 'Refresh Metrics' to compute everything.\n"
            "  - 'Retrain Now' trains a new model and saves it as the active one.\n"
            "  - The Algorithms and Features tabs run extra cross-validation;\n"
            "    they only compute when you actually visit them."
        )
        ttk.Label(ps_frame, text=problem_text, justify="left",
                  font=("Segoe UI", 9), wraplength=900).pack(
            anchor="w", padx=8, pady=8)

        # Headline metrics row
        metrics_frame = ttk.LabelFrame(tab, text="Headline Metrics (best algorithm)")
        metrics_frame.pack(fill="x", pady=(0, 6), padx=4)
        # Use a grid of label-value pairs, all in one row.
        self._metric_vars = {}
        col = 0
        for label in ("Accuracy", "Precision", "Recall", "F1", "ROC-AUC", "PR-AUC", "Specificity", "Brier"):
            ttk.Label(metrics_frame, text=label, font=("Segoe UI", 9, "bold")
                      ).grid(row=0, column=col, padx=(12, 2), pady=4, sticky="e")
            v = tk.StringVar(value="—")
            lbl = ttk.Label(metrics_frame, textvariable=v, font=("Segoe UI", 10, "bold"))
            lbl.grid(row=0, column=col + 1, padx=(0, 8), pady=4, sticky="w")
            # Tooltip with the metric description.
            from design import Tooltip
            Tooltip.attach(lbl, METRIC_DESCRIPTIONS[label])
            self._metric_vars[label] = v
            col += 2
        # 8 labels * 2 cols = 16 columns.
        for c in range(16):
            metrics_frame.columnconfigure(c, weight=1)

        # Confusion matrix figure on the left, prediction distribution
        # on the right. We use LazyFigure placeholders that don't
        # actually create the matplotlib Figure + canvas until the
        # user clicks Refresh Metrics. This saves ~30ms × 9 figures
        # = 270ms on page init.
        charts = ttk.Frame(tab)
        charts.pack(fill="both", expand=True, padx=4, pady=4)
        charts.columnconfigure(0, weight=1)
        charts.columnconfigure(1, weight=1)
        charts.rowconfigure(0, weight=1)

        # Confusion matrix
        cm_frame = ttk.LabelFrame(charts, text="Confusion Matrix (test set)")
        cm_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        self._cm_fig, self._cm_ax, self._cm_canvas = self._make_lazy_figure(cm_frame)

        # Prediction distribution
        pd_frame = ttk.LabelFrame(charts,
            text="Prediction Distribution — are winners and losers separable?")
        pd_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        self._pd_fig, self._pd_ax, self._pd_canvas = self._make_lazy_figure(pd_frame)

    def _build_algorithm_tab(self):
        """The 'Algorithms' tab: comparison + learning curves."""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Algorithms")
        self.tabs["algorithms"] = tab

        # Lazy placeholder shown until the user visits this tab.
        self._algo_placeholder = ttk.Label(
            tab,
            text="Click here to compute cross-validated metrics for all algorithms.\n"
                 "(Only runs when you visit this tab.)",
            foreground="gray", justify="center", font=("Segoe UI", 10),
        )
        self._algo_placeholder.pack(pady=40)

        # The actual content is built lazily in _populate_algorithm_tab.
        # We keep a container frame that we populate on first visit.
        self._algo_content = ttk.Frame(tab)
        self._algo_populated = False

        # Algorithm comparison bar chart on top.
        comp_frame = ttk.LabelFrame(self._algo_content,
            text="Which algorithm wins on YOUR data? (test set, both algorithms trained on the same split)")
        comp_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._comp_fig, self._comp_ax, self._comp_canvas = self._make_lazy_figure(comp_frame)

        # Algorithm comparison table (mean ± std for each metric).
        cmp_frame = ttk.LabelFrame(self._algo_content,
            text="Cross-validated metrics (3-fold, mean ± std) — more honest than a single train/test split")
        cmp_frame.pack(fill="both", expand=True, padx=4, pady=4)
        cols = ("Algorithm", "Accuracy", "Precision", "Recall", "F1", "ROC-AUC")
        self.cmp_tree = ttk.Treeview(cmp_frame, columns=cols, show="headings", height=5)
        for c in cols:
            self.cmp_tree.heading(c, text=c)
            self.cmp_tree.column(c, width=130 if c == "Algorithm" else 110, anchor="center")
        self.cmp_tree.pack(fill="both", expand=True)

    def _build_curves_tab(self):
        """The 'Curves' tab: ROC + PR + Calibration."""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Curves")
        self.tabs["curves"] = tab

        # Three charts side by side.
        charts = ttk.Frame(tab)
        charts.pack(fill="both", expand=True, padx=4, pady=4)
        for c in range(3):
            charts.columnconfigure(c, weight=1)
        charts.rowconfigure(0, weight=1)

        # ROC
        roc_frame = ttk.LabelFrame(charts,
            text="ROC Curve — area under = ROC-AUC")
        roc_frame.grid(row=0, column=0, sticky="nsew", padx=2)
        self._roc_fig, self._roc_ax, self._roc_canvas = self._make_lazy_figure(roc_frame)

        # PR
        pr_frame = ttk.LabelFrame(charts,
            text="Precision-Recall — area under = PR-AUC")
        pr_frame.grid(row=0, column=1, sticky="nsew", padx=2)
        self._pr_fig, self._pr_ax, self._pr_canvas = self._make_lazy_figure(pr_frame)

        # Calibration
        cal_frame = ttk.LabelFrame(charts,
            text="Calibration — when model says 60%, is it 60%?")
        cal_frame.grid(row=0, column=2, sticky="nsew", padx=2)
        self._cal_fig, self._cal_ax, self._cal_canvas = self._make_lazy_figure(cal_frame)

    def _build_economics_tab(self):
        """The 'Economics' tab: does using the filter make money?"""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Economics")
        self.tabs["economics"] = tab

        # Summary stats
        summary_frame = ttk.LabelFrame(tab,
            text="Backtest: what if you'd followed the AI filter?")
        summary_frame.pack(fill="x", pady=(8, 4), padx=4)
        # Two rows of label-value pairs.
        self._econ_vars = {}
        for r, row in enumerate([
            ("Trades taken", "Total trades"),
            ("Net P&L", "P&L improvement"),
            ("Win rate (filtered)", "Win rate (baseline)"),
            ("Avg P&L/trade (filtered)", "Avg P&L/trade (baseline)"),
        ]):
            ttk.Label(summary_frame, text=row[0], font=("Segoe UI", 9, "bold")
                      ).grid(row=r, column=0, padx=(12, 2), pady=4, sticky="e")
            v1 = tk.StringVar(value="—")
            ttk.Label(summary_frame, textvariable=v1, font=("Segoe UI", 10, "bold")
                      ).grid(row=r, column=1, padx=(0, 24), pady=4, sticky="w")
            self._econ_vars[row[0]] = v1
            ttk.Label(summary_frame, text=row[1], font=("Segoe UI", 9, "bold")
                      ).grid(row=r, column=2, padx=(12, 2), pady=4, sticky="e")
            v2 = tk.StringVar(value="—")
            ttk.Label(summary_frame, textvariable=v2, font=("Segoe UI", 10, "bold")
                      ).grid(row=r, column=3, padx=(0, 12), pady=4, sticky="w")
            self._econ_vars[row[1]] = v2

        # P&L distribution
        pnl_frame = ttk.LabelFrame(tab, text="P&L distribution of closed trades")
        pnl_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._pnl_fig, self._pnl_ax, self._pnl_canvas = self._make_lazy_figure(pnl_frame)

        # Per-symbol breakdown
        per_sym_frame = ttk.LabelFrame(tab,
            text="Per-symbol breakdown: where does the model add value?")
        per_sym_frame.pack(fill="both", expand=True, padx=4, pady=4)
        sym_cols = ("Symbol", "Trades", "Win rate", "Avg P&L", "Model acc",
                    "Accepted n", "Accepted win", "Rejected n", "Model lift")
        self.sym_tree = ttk.Treeview(per_sym_frame, columns=sym_cols,
                                      show="headings", height=10)
        for c in sym_cols:
            self.sym_tree.heading(c, text=c)
            self.sym_tree.column(c, width=90, anchor="center")
        # Vertical scrollbar for the symbol list.
        ysb = ttk.Scrollbar(per_sym_frame, orient="vertical",
                             command=self.sym_tree.yview)
        self.sym_tree.configure(yscrollcommand=ysb.set)
        self.sym_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    def _build_features_tab(self):
        """The 'Features' tab: feature importance + learning curve."""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Features")
        self.tabs["features"] = tab

        # Lazy placeholder shown until the user visits this tab.
        # The learning curve inside this tab is the slowest chart
        # (3 train sizes × 2 folds = 6 model fits), so we only
        # compute it on demand.
        self._feat_placeholder = ttk.Label(
            tab,
            text="Click here to compute feature importance and learning curve.\n"
                 "(Only runs when you visit this tab.)",
            foreground="gray", justify="center", font=("Segoe UI", 10),
        )
        self._feat_placeholder.pack(pady=40)
        self._feat_content = ttk.Frame(tab)
        self._feat_populated = False

        # Feature importance on top
        imp_frame = ttk.LabelFrame(self._feat_content,
            text="Feature importance — which signals matter most?")
        imp_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._imp_fig, self._imp_ax, self._imp_canvas = self._make_lazy_figure(imp_frame)

        # Learning curve
        lc_frame = ttk.LabelFrame(self._feat_content,
            text="Learning curve — does the model need more data? (best algorithm)")
        lc_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._lc_fig, self._lc_ax, self._lc_canvas = self._make_lazy_figure(lc_frame)

    def _build_data_tab(self):
        """The 'Data' tab: raw historical trade log."""
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Data")
        self.tabs["data"] = tab

        ds_frame = ttk.LabelFrame(tab, text="Historical closed trades (most recent 100)")
        ds_frame.pack(fill="both", expand=True, padx=4, pady=4)
        cols = ("Time", "Symbol", "Direction", "P&L", "Profitable", "Exit reason")
        self.ds_tree = ttk.Treeview(ds_frame, columns=cols,
                                     show="headings", height=20)
        for c in cols:
            self.ds_tree.heading(c, text=c)
            self.ds_tree.column(c, width=110 if c != "Symbol" else 80, anchor="center")
        ysb = ttk.Scrollbar(ds_frame, orient="vertical",
                             command=self.ds_tree.yview)
        self.ds_tree.configure(yscrollcommand=ysb.set)
        self.ds_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    # -----------------------------------------------------------------
    # Lazy tab population (heavy work only when visited)
    # -----------------------------------------------------------------

    def _on_tab_changed(self, _event=None):
        """Called when the user switches tabs. If the Algorithms or
        Features tab is now selected and we have cached results,
        populate it on demand."""
        try:
            sel = self.nb.select()
            tab_text = self.nb.tab(sel, "text")
        except Exception:
            return
        if tab_text == "Algorithms" and not self._algo_populated:
            self._populate_algorithm_tab()
        elif tab_text == "Features" and not self._feat_populated:
            self._populate_features_tab()

    def _populate_algorithm_tab(self):
        """Compute and render the cross-validated metrics table
        and the algorithm-comparison bar chart. This is the
        second-heaviest operation (3-fold CV × 2 algorithms =
        6 model fits), so we run it in a thread to keep the UI
        responsive.
        """
        if self._cache_results is None or self._cache_df is None:
            self._algo_placeholder.config(
                text="Click 'Refresh Metrics' first to load the data.")
            return
        self._algo_placeholder.config(text="Computing cross-validated metrics...")
        self._algo_populated = True  # Mark early so double-clicks don't re-trigger.

        def worker():
            analytics = _ensure_analytics()
            X, y = analytics._prepare_xy(self._cache_df)
            cv_results = {}
            for name in analytics.ALGORITHMS:
                if name in self._cache_results and "error" not in self._cache_results[name]:
                    cv_results[name] = analytics.cross_validate(
                        name, X, y, n_splits=3)
            self._schedule_on_ui(lambda: self._render_algorithm_tab(cv_results))

        self._spawn_worker(worker)

    def _render_algorithm_tab(self, cv_results):
        """Render the cross-validated metrics on the UI thread."""
        analytics = _ensure_analytics()
        try:
            self._algo_placeholder.pack_forget()
        except Exception:
            pass
        self._algo_content.pack(fill="both", expand=True)
        # Lazy-create the real figure now that we have data to draw.
        comp_fig, comp_ax, comp_canvas = self._ensure_real_figure(
            self._comp_fig, figsize=(7, 3.5))
        # Algorithm comparison bar chart
        new_fig = analytics.fig_algorithm_comparison(self._cache_results)
        self._replace_figure(comp_fig, comp_canvas, new_fig)
        # Cross-validated metrics table
        for child in self.cmp_tree.get_children():
            self.cmp_tree.delete(child)
        for name in analytics.ALGORITHMS:
            if name not in cv_results:
                self.cmp_tree.insert("", "end", values=(
                    name, "—", "—", "—", "—", "—"))
                continue
            cv = cv_results[name]
            self.cmp_tree.insert("", "end", values=(
                name,
                f"{cv['accuracy']['mean']:.3f} ± {cv['accuracy']['std']:.3f}",
                f"{cv['precision']['mean']:.3f} ± {cv['precision']['std']:.3f}",
                f"{cv['recall']['mean']:.3f} ± {cv['recall']['std']:.3f}",
                f"{cv['f1']['mean']:.3f} ± {cv['f1']['std']:.3f}",
                f"{cv['roc_auc']['mean']:.3f} ± {cv['roc_auc']['std']:.3f}",
            ))

    def _populate_features_tab(self):
        """Compute and render the feature importance + learning
        curve. The learning curve is the slowest single chart
        (3 train sizes × 2 folds = 6 model fits), so we run it
        in a thread.
        """
        if self._cache_best is None or self._cache_df is None:
            self._feat_placeholder.config(
                text="Click 'Refresh Metrics' first to load the data.")
            return
        self._feat_placeholder.config(text="Computing feature importance and learning curve...")
        self._feat_populated = True

        def worker():
            analytics = _ensure_analytics()
            X, y = analytics._prepare_xy(self._cache_df)
            best_name, best_result = self._cache_best
            # Feature importance: cheap (~30ms)
            imp_fig = analytics.fig_feature_importance(
                best_result["model"], X, best_name)
            # Learning curve: heavier (6 model fits)
            lc_fig = analytics.fig_learning_curve(best_name, X, y)
            self._schedule_on_ui(lambda: self._render_features_tab(imp_fig, lc_fig))

        self._spawn_worker(worker)

    def _render_features_tab(self, imp_fig, lc_fig):
        try:
            self._feat_placeholder.pack_forget()
        except Exception:
            pass
        self._feat_content.pack(fill="both", expand=True)
        # Lazy-create the real figures on first render.
        imp_slot_fig, imp_slot_ax, imp_slot_canvas = self._ensure_real_figure(
            self._imp_fig, figsize=(7, 3.5))
        lc_slot_fig, lc_slot_ax, lc_slot_canvas = self._ensure_real_figure(
            self._lc_fig, figsize=(7, 3))
        self._replace_figure(imp_slot_fig, imp_slot_canvas, imp_fig)
        self._replace_figure(lc_slot_fig, lc_slot_canvas, lc_fig)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------

    def _retrain(self):
        """Re-fit every algorithm on trade_log.csv, pick the best
        one by ROC-AUC, save it as the active model. Runs in a
        background thread so the UI stays responsive.

        NOTE: We invalidate the cache so the next refresh uses the
        new model. We don't show the new model in the analytics
        tabs until the user clicks Refresh Metrics (or we can do
        it automatically — we choose to NOT do it automatically
        so the user explicitly sees a fresh result).
        """
        # First, kick off the retrain in a thread.
        def worker():
            analytics = _ensure_analytics()
            df = analytics.load_trades()
            if df.empty or len(df) < 20:
                self._schedule_on_ui(lambda: messagebox.showinfo(
                    "Not enough data",
                    f"Only {len(df)} closed trades — need at least 20 "
                    f"to train. Let the dashboard run for a while to "
                    f"collect more data."
                ))
                return
            X, y = analytics._prepare_xy(df)
            if X is None:
                self._schedule_on_ui(lambda: messagebox.showinfo(
                    "Data problem",
                    "The trade log doesn't have enough variety to train "
                    "on (need at least 20 trades with both winners AND "
                    "losers)."
                ))
                return

            self._schedule_on_ui(lambda: self.status_var.set(
                f"Retraining {len(analytics.ALGORITHMS)} algorithms on {len(df)} trades..."))

            results = analytics.train_all(X, y)
            best_name, best_result, best_auc = self._pick_best(results)
            if best_name is None:
                self._schedule_on_ui(lambda: messagebox.showerror(
                    "Training failed",
                    "All algorithms failed to train. See the status line."))
                return

            threshold = self._find_optimal_threshold(
                df.iloc[-len(best_result["y_test"]):],
                best_result["y_prob"],
                best_result["y_test"])

            import joblib
            joblib.dump({
                "model": best_result["model"],
                "algorithm": best_name,
                "threshold": threshold,
                "trained_on": len(df),
            }, MODEL_PATH)

            import ai_model
            ai_model._model = None
            ai_model._model_loaded = False

            self._schedule_on_ui(lambda: self.status_var.set(
                f"Retrained on {len(df)} trades. Best: {best_name} "
                f"(ROC-AUC {best_auc:.3f}), threshold {threshold:.2f}. "
                f"Click 'Refresh Metrics' to see the new analytics."
            ))

        run_in_background(worker, name="retrain")
        # Don't track this in the worker tracker — the test
        # helper doesn't need to wait for retrain (it's a user
        # action, not a refresh).

    def _pick_best(self, results):
        """Return (best_name, best_result, best_auc). best_name is
        None if every algorithm failed."""
        best_name, best_result, best_auc = None, None, -1
        for name, r in results.items():
            if "error" in r:
                continue
            auc = r["metrics"]["roc_auc"]
            if not np.isnan(auc) and auc > best_auc:
                best_auc = auc
                best_name = name
                best_result = r
        return best_name, best_result, best_auc

    def _find_optimal_threshold(self, test_df, y_prob, y_true) -> float:
        """Find the decision threshold that maximises the user's
        expected P&L.

        For each candidate threshold (0.1, 0.2, ..., 0.9), we
        compute the sum of P&L for trades the model would accept
        at that threshold, and pick the threshold that maximises
        it. The trade-off is:
          * Higher threshold = fewer trades taken, but each
            taken trade is more likely to be a winner.
          * Lower threshold = more trades taken, but the model
            is less selective.
        We don't restrict to the 0.5 default because for
        imbalanced data (e.g. 30% winners), 0.5 often isn't
        optimal.
        """
        if "pnl" not in test_df.columns:
            return 0.5
        pnl = test_df["pnl"].values
        best_thr = 0.5
        best_pnl = -float("inf")
        for thr in np.arange(0.1, 1.0, 0.05):
            take = y_prob >= thr
            if not take.any():
                continue
            total = pnl[take].sum()
            if total > best_pnl:
                best_pnl = total
                best_thr = float(thr)
        return round(best_thr, 2)

    # -----------------------------------------------------------------
    # Refresh — recompute everything from disk (in a background thread)
    # -----------------------------------------------------------------

    def refresh(self):
        """Re-read trade_log.csv and recompute every chart, table,
        and number. Runs the heavy training in a background thread
        so the UI never freezes.

        Results are cached by (n_rows, file_mtime), so a second
        Refresh within the same dataset is essentially free.
        """
        # Already running? Don't kick off another thread.
        with self._train_lock:
            if self._train_thread is not None and self._train_thread.is_alive():
                self.status_var.set("Refresh already in progress...")
                return
        # Quick file-stat check for the cache.
        try:
            n_rows, mtime = self._quick_file_stat()
        except Exception:
            n_rows, mtime = -1, -1
        cache_key = (n_rows, mtime)
        if cache_key == self._cache_key and self._cache_results is not None:
            # Data hasn't changed — just re-render from cache.
            self.status_var.set(
                f"Data unchanged ({n_rows} trades). Reusing cached analytics.")
            self._render_from_cache()
            return
        # Kick off a background thread for the heavy work.
        self.status_var.set("Loading trade log and training models...")
        # Start the UI poll on the main thread so the worker can
        # safely put UI updates onto the queue.
        self._start_ui_poll()
        with self._train_lock:
            self._train_thread = self._spawn_worker(self._refresh_worker)

    def _quick_file_stat(self):
        """Return (n_rows, mtime) of trade_log.csv without reading
        the whole thing."""
        if not os.path.exists(TRADE_LOG_PATH):
            return (0, 0)
        try:
            mtime = os.path.getmtime(TRADE_LOG_PATH)
            # Cheap line count.
            with open(TRADE_LOG_PATH, "rb") as f:
                n = sum(1 for _ in f) - 1  # minus header
            return (max(0, n), mtime)
        except Exception:
            return (0, 0)

    def _schedule_on_ui(self, fn):
        """Schedule a callable to run on the Tk main thread. This is
        safe to call from a background thread.

        We can't use self.after() from a worker thread because Tk's
        createcommand isn't thread-safe. Instead we put the callable
        on a Queue. The main thread will drain the queue either via
        the recurring poll (started in refresh()) or via the test
        helper _wait_for_refresh which calls _drain_ui_queue().
        """
        self._ui_queue.put(fn)
        # Note: do NOT call _start_ui_poll() here. It's not thread
        # safe to call self.after() from a worker thread. The poll
        # is started by the main thread (in refresh()).

    def _start_ui_poll(self):
        """Start a recurring poll of the UI queue. Idempotent — only
        schedules one poll timer at a time. The poll itself runs on
        the main thread and drains any pending callables.
        """
        if self._ui_poll_running:
            return
        self._ui_poll_running = True
        self._poll_ui_queue()

    def _poll_ui_queue(self):
        """Drain the UI queue, executing one callable. Then schedule
        the next poll after a short delay. This runs on the main
        thread so it's safe to call Tk widget methods.

        If the widget is being destroyed (winfo_exists() returns 0),
        stop polling and don't re-arm the after() callback. This
        prevents a leaked after() from blocking the test cleanup
        between tests (the next test's UI poll would never get a
        turn because Tk's event loop is busy firing our stale
        callbacks).
        """
        import traceback
        try:
            # If the widget was destroyed between scheduling and
            # execution, stop polling immediately. winfo_exists()
            # returns 0 once destroy() has been called.
            if not self.winfo_exists():
                self._ui_poll_running = False
                return
            for _ in range(20):  # drain up to 20 per tick
                try:
                    fn = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception as e:
                    # Don't let a single failed UI update kill the
                    # whole page — just log it and continue.
                    print(f"UI update failed: {type(e).__name__}: {e}")
                    traceback.print_exc()
        finally:
            # Re-schedule. We use after() (which is main-thread-safe)
            # to come back in 50ms. Skip re-arming if the widget is
            # gone (destroyed page, or shutdown in progress).
            if not self._ui_poll_running:
                return
            try:
                if not self.winfo_exists():
                    # Widget destroyed between scheduling and firing.
                    self._ui_poll_running = False
                    return
                self.after(50, self._poll_ui_queue)
            except Exception as e:
                # If Tk is gone (page destroyed), stop polling.
                self._ui_poll_running = False
                # Don't print this — it's expected on teardown.

    def _refresh_worker(self):
        """Heavy work: load data, train all 2 algorithms, compute
        backtest and P&L distribution. Runs in a background thread.
        Schedules the UI update via the _ui_queue.
        """
        # Lazy import: the previous version imported `analytics` at
        # module load time, which pulled in sklearn (664ms) and
        # pandas (237ms) on every page import. We do it here so
        # the cost is paid only when the user actually clicks
        # Refresh Metrics. This is the largest single source of
        # app startup latency.
        analytics = _ensure_analytics()

        t0 = time.time()
        try:
            df = analytics.load_trades()
            n_trades = 0 if df.empty else len(df)
            if df.empty or len(df) < 20:
                self._schedule_on_ui(lambda: self._show_empty_state(
                    f"Need at least 20 closed trades to train a model. "
                    f"Currently have {n_trades}. Let the dashboard run "
                    f"to collect more data."))
                return
            X, y = analytics._prepare_xy(df)
            if X is None:
                self._schedule_on_ui(lambda: self._show_empty_state(
                    f"Have {n_trades} trades but not enough variety "
                    f"(need at least 20 with both winners AND losers)."))
                return

            # Train all 2 algorithms (~0.5s for 200 rows with new
            # light hyperparameters).
            results = analytics.train_all(X, y)
            best_name, best_result, best_auc = self._pick_best(results)
            if best_result is None:
                self._schedule_on_ui(lambda: self._show_empty_state(
                    "All algorithms failed to train."))
                return

            # Update the cache.
            self._cache_df = df
            self._cache_results = results
            self._cache_best = (best_name, best_result)
            self._cache_key = (n_trades, os.path.getmtime(TRADE_LOG_PATH))
            self._cache_tab_computed = set()  # invalidate lazy tabs
            self._algo_populated = False
            self._feat_populated = False

            # Render the cheap tabs (Overview, Curves, Economics, Data)
            # on the UI thread.
            self._schedule_on_ui(lambda: self._render_from_cache())
            elapsed = time.time() - t0
            self._schedule_on_ui(lambda: self.status_var.set(
                f"Trained {len([r for r in results.values() if 'error' not in r])}/"
                f"{len(results)} algorithms on {n_trades} trades in {elapsed:.1f}s. "
                f"Best: {best_name} (ROC-AUC {best_auc:.3f}). "
                f"Visit Algorithms/Features for cross-validation."
            ))
        except Exception as e:
            self._schedule_on_ui(lambda: self._show_empty_state(
                f"Error during refresh: {e}"))

    def _render_from_cache(self):
        """Re-render all the cheap tabs from the cached results.
        Called whenever the cache is updated OR the user clicks
        Refresh with unchanged data."""
        if self._cache_df is None or self._cache_results is None:
            return
        df = self._cache_df
        results = self._cache_results
        best_name, best_result = self._cache_best
        if best_name is None:
            return

        # Update active-model display.
        algo, threshold = self._read_active_model_info()
        if algo is None:
            algo = best_name
        self.active_algo_var.set(f"{algo}  (threshold = {threshold:.2f})")

        # 1) Overview tab.
        self._update_overview(df, results, best_name, best_result)
        # 2) Curves tab (cheap, uses cached best_result).
        self._update_curves(best_result)
        # 3) Economics tab.
        self._update_economics(df, best_result, threshold)
        # 4) Data tab (cheap, just iterates the last 100 rows).
        self._update_data(df)
        # 5) If the user is currently on the Algorithms or Features
        #    tab, re-trigger the lazy populate.
        try:
            sel = self.nb.select()
            tab_text = self.nb.tab(sel, "text")
        except Exception:
            tab_text = ""
        if tab_text == "Algorithms":
            self._algo_populated = False
            # Re-show placeholder; populate on next event loop turn.
            try:
                self._algo_content.pack_forget()
            except Exception:
                pass
            self._algo_placeholder.pack(pady=40)
            self._algo_placeholder.config(
                text="Data refreshed. Click here to recompute cross-validated metrics.")
        elif tab_text == "Features":
            self._feat_populated = False
            try:
                self._feat_content.pack_forget()
            except Exception:
                pass
            self._feat_placeholder.pack(pady=40)
            self._feat_placeholder.config(
                text="Data refreshed. Click here to recompute feature importance and learning curve.")

    def _read_active_model_info(self):
        """Read the algorithm name and threshold from the saved
        model file, if it exists. Returns (algo, threshold) or
        (None, 0.5) if not available."""
        if not os.path.exists(MODEL_PATH):
            return None, 0.5
        try:
            import joblib
            loaded = joblib.load(MODEL_PATH)
            if isinstance(loaded, dict):
                return loaded.get("algorithm"), float(loaded.get("threshold", 0.5))
        except Exception:
            pass
        return None, 0.5

    def _show_idle_hint(self):
        """Show a friendly 'click refresh' message in the headline
        metrics on first load. Used in __init__ so the page opens
        instantly with no training.

        With lazy figure creation, the figure slots are placeholders
        at this point (no real Figure has been created yet). We
        only need to clear the headline metric labels — the figure
        placeholders are already showing the right hint text.
        """
        for label in self._metric_vars.values():
            label.set("—")
        # The figure slots are placeholders right now (lazy
        # creation), so we don't have real axes to draw into. The
        # placeholder label already says "Click Refresh to compute"
        # so we don't need to do anything else.
        self.active_algo_var.set("(click Refresh Metrics)")

    def _show_empty_state(self, message):
        """Show a friendly 'not enough data' message in the overview
        tab and clear all the charts.

        If we haven't created the real figures yet (lazy creation),
        we don't need to draw into their axes — the placeholder
        labels are still showing. If they have been created (e.g.
        the user clicked Refresh once, then deleted their data),
        we draw the message into each axis.
        """
        for label in self._metric_vars.values():
            label.set("—")
        # Only try to draw into axes that have actually been
        # created. With lazy figures, ax may be None.
        for slot in (self._cm_ax, self._pd_ax, self._comp_ax,
                     self._roc_ax, self._pr_ax, self._cal_ax,
                     self._pnl_ax, self._imp_ax, self._lc_ax):
            if slot is None or not slot.is_real:
                continue
            ax = slot.ax
            ax.clear()
            ax.text(0.5, 0.5, message, ha="center", va="center",
                    wrap=True, transform=ax.transAxes, fontsize=10)
            slot.canvas.draw()
        self.active_algo_var.set("(none — no model trained yet)")
        self.status_var.set(message)

    # -----------------------------------------------------------------
    # Per-tab updaters (all cheap, all run on UI thread)
    # -----------------------------------------------------------------

    def _update_overview(self, df, results, best_name, best_result):
        analytics = _ensure_analytics()
        m = best_result["metrics"]
        self._metric_vars["Accuracy"].set(f"{m['accuracy']:.3f}")
        self._metric_vars["Precision"].set(f"{m['precision']:.3f}")
        self._metric_vars["Recall"].set(f"{m['recall']:.3f}")
        self._metric_vars["F1"].set(f"{m['f1']:.3f}")
        self._metric_vars["ROC-AUC"].set(f"{m['roc_auc']:.3f}")
        self._metric_vars["PR-AUC"].set(f"{m['pr_auc']:.3f}")
        self._metric_vars["Specificity"].set(f"{m['specificity']:.3f}")
        self._metric_vars["Brier"].set(f"{m['brier']:.3f}")

        # Ensure the real matplotlib figures exist (lazy creation).
        # First refresh of this page pays the ~30ms-per-figure
        # cost; subsequent refreshes hit the cache.
        cm_fig, cm_ax, cm_canvas = self._ensure_real_figure(self._cm_fig, figsize=(4, 3.2))
        pd_fig, pd_ax, pd_canvas = self._ensure_real_figure(self._pd_fig, figsize=(4, 3.2))

        # Confusion matrix as heatmap. Use the cache to avoid
        # re-creating the figure when the data hasn't changed.
        cm = [[m["tn"], m["fp"]], [m["fn"], m["tp"]]]
        cache_key = (best_name, m["tn"], m["fp"], m["fn"], m["tp"])
        if self._fig_cache.get("cm") != cache_key:
            new_fig = analytics.fig_confusion_matrix(cm, best_name)
            self._replace_figure(cm_fig, cm_canvas, new_fig)
            self._fig_cache["cm"] = cache_key

        # Prediction distribution. The hash is over the test labels
        # + probabilities + algo name.
        y_test = best_result["y_test"]
        y_prob = best_result["y_prob"]
        cache_key = _figure_cache_key(y_test, y_prob, best_name, m["roc_auc"], m["pr_auc"])
        if self._fig_cache.get("pd") != cache_key:
            new_fig = analytics.fig_proba_distribution(y_test, y_prob, best_name)
            self._replace_figure(pd_fig, pd_canvas, new_fig)
            self._fig_cache["pd"] = cache_key

    def _update_curves(self, best_result):
        analytics = _ensure_analytics()
        y_test = best_result["y_test"]
        y_prob = best_result["y_prob"]
        m = best_result["metrics"]
        algo = best_result.get("algorithm", "")
        # Ensure the real matplotlib figures exist (lazy creation).
        roc_fig, roc_ax, roc_canvas = self._ensure_real_figure(self._roc_fig, figsize=(4, 3.2))
        pr_fig, pr_ax, pr_canvas = self._ensure_real_figure(self._pr_fig, figsize=(4, 3.2))
        cal_fig, cal_ax, cal_canvas = self._ensure_real_figure(self._cal_fig, figsize=(4, 3.2))
        # Cache key includes the y_test/y_prob arrays' hash so we
        # re-render only when the data actually changes. The hash
        # is fast (O(N) over the test set) and avoids the ~30ms
        # cost of creating a new figure.
        cache_key = _figure_cache_key(y_test, y_prob, algo, m["roc_auc"], m["pr_auc"])
        if self._fig_cache.get("roc") != cache_key:
            new_fig = analytics.fig_roc_curve(y_test, y_prob, m["roc_auc"], algo)
            self._replace_figure(roc_fig, roc_canvas, new_fig)
            self._fig_cache["roc"] = cache_key
        if self._fig_cache.get("pr") != cache_key:
            new_fig = analytics.fig_pr_curve(y_test, y_prob, m["pr_auc"], algo)
            self._replace_figure(pr_fig, pr_canvas, new_fig)
            self._fig_cache["pr"] = cache_key
        if self._fig_cache.get("cal") != cache_key:
            new_fig = analytics.fig_calibration(y_test, y_prob, algo)
            self._replace_figure(cal_fig, cal_canvas, new_fig)
            self._fig_cache["cal"] = cache_key

    def _update_economics(self, df, best_result, threshold):
        analytics = _ensure_analytics()
        y_test = best_result["y_test"]
        y_prob = best_result["y_prob"]
        # The test set's PnL is the LAST len(y_test) rows of df.
        test_df = df.iloc[-len(y_test):].copy()
        bt = analytics.backtest_pnl(test_df, y_prob, threshold=threshold)
        if bt:
            self._econ_vars["Trades taken"].set(
                f"{bt['n_taken']} of {bt['n_total']} "
                f"({bt['n_taken']/max(1,bt['n_total']):.0%})")
            self._econ_vars["Total trades"].set(str(bt["n_total"]))
            self._econ_vars["Net P&L"].set(f"₹{bt['filtered_pnl']:,.2f}")
            self._econ_vars["P&L improvement"].set(
                f"₹{bt['improvement_pnl']:+,.2f} vs baseline")
            self._econ_vars["Win rate (filtered)"].set(
                f"{bt['win_rate_filtered']:.1%}")
            self._econ_vars["Win rate (baseline)"].set(
                f"{bt['win_rate_baseline']:.1%}")
            self._econ_vars["Avg P&L/trade (filtered)"].set(
                f"₹{bt['avg_pnl_filtered']:,.2f}")
            self._econ_vars["Avg P&L/trade (baseline)"].set(
                f"₹{bt['avg_pnl_baseline']:,.2f}")
        else:
            for v in self._econ_vars.values():
                v.set("—")

        # P&L distribution. Lazy-create the real figure on first
        # refresh; subsequent refreshes hit the cache.
        pnl_fig, pnl_ax, pnl_canvas = self._ensure_real_figure(self._pnl_fig, figsize=(7, 3))
        new_fig = analytics.fig_pnl_distribution(df)
        self._replace_figure(pnl_fig, pnl_canvas, new_fig)

        # Per-symbol breakdown
        for child in self.sym_tree.get_children():
            self.sym_tree.delete(child)
        bd = analytics.per_symbol_breakdown(test_df, y_prob, threshold=threshold)
        for sym, row in bd.iterrows():
            self.sym_tree.insert("", "end", values=(
                sym,
                int(row["n_trades"]),
                f"{row['win_rate']:.0%}",
                f"₹{row['avg_pnl']:.2f}",
                f"{row['model_accuracy']:.0%}",
                int(row["accepted_n"]),
                f"{row.get('accepted_win', 0):.0%}",
                int(row["rejected_n"]),
                f"₹{row['model_lift']:.2f}",
            ))

    def _update_data(self, df):
        for child in self.ds_tree.get_children():
            self.ds_tree.delete(child)
        # Show the most recent 100 trades.
        for _, r in df.tail(100).iterrows():
            pnl = float(r["pnl"])
            self.ds_tree.insert("", "end", values=(
                r.get("exit_time", "—"),
                r["symbol"],
                r["direction"],
                f"₹{pnl:+.2f}",
                "Yes" if int(r["profitable"]) else "No",
                "win" if pnl > 0 else "loss",
            ))

    def _replace_figure(self, old_fig, canvas, new_fig):
        """Replace the contents of an existing matplotlib figure
        with a new one.

        We use the simplest approach that works: copy the new
        figure's content (lines, patches, imshow, text, ticks,
        title, axis limits) into the OLD figure's axes, then
        redraw. This reuses the Tk widget (no flicker) and
        avoids the bleed-through issue (the old idle-hint text
        is cleared by figure.clear()).

        For matplotlib, artists are tied to specific axes, so
        we have to re-create each artist in the new axes. We
        support line plots, bar/patch rectangles, imshow heatmaps,
        and text annotations — which covers everything the
        analytics module produces.
        """
        try:
            old_fig.clear()
            ax = old_fig.add_subplot(111)
            src_ax = new_fig.axes[0] if new_fig.axes else None
            if src_ax is not None:
                _copy_axes(src_ax, ax)
            old_fig.tight_layout()
            canvas.draw()
            import matplotlib.pyplot as plt
            plt.close(new_fig)
        except Exception as e:
            print(f"_replace_figure fallback: {e}")
            try:
                canvas.figure = new_fig
                canvas.draw()
            except Exception:
                canvas.draw()


def _copy_axes(src, dst):
    """Copy title, labels, lines, patches, and basic styling from
    one matplotlib Axes to another. We support the chart types we
    use in this app: line plots, bar plots, histograms, heatmaps
    (imshow), and text annotations.

    For bars and histograms: each bar's xy is preserved
    (so the bar appears at the right x position with the right
    width), and the figure is set to autoscale so the limits
    match the data instead of matplotlib's (0, 1) default.
    """
    import matplotlib.patches as mpatches
    # Title and labels
    if src.get_title():
        dst.set_title(src.get_title(), fontsize=10, fontweight="bold", pad=8)
    if src.get_xlabel():
        dst.set_xlabel(src.get_xlabel(), fontsize=9)
    if src.get_ylabel():
        dst.set_ylabel(src.get_ylabel(), fontsize=9)
    # Images (e.g. heatmap from imshow) — copy first since they
    # set their own axis ticks/labels.
    for img in src.get_images():
        try:
            # The aspect is set on the parent axes, not the image.
            dst.imshow(img.get_array(), cmap=img.get_cmap(),
                       vmin=img.get_clim()[0], vmax=img.get_clim()[1],
                       aspect=src.get_aspect())
            # imshow sets the axis limits to (0, n-1), so we should
            # NOT autoscale after this.
        except Exception as e:
            print(f"imshow copy failed: {e}")
    # If src has an imshow, copy its tick labels (which are the
    # confusion matrix categories).
    if src.get_images():
        xticklabels = [t.get_text() for t in src.get_xticklabels()]
        yticklabels = [t.get_text() for t in src.get_yticklabels()]
        if any(xticklabels):
            n = len(xticklabels)
            dst.set_xticks(range(n))
            dst.set_xticklabels(xticklabels, fontsize=9)
        if any(yticklabels):
            n = len(yticklabels)
            dst.set_yticks(range(n))
            dst.set_yticklabels(yticklabels, fontsize=9)
    # Lines
    for line in src.get_lines():
        x, y = line.get_xdata(), line.get_ydata()
        if len(x) == 0:
            continue
        dst.plot(x, y,
                 color=line.get_color(),
                 linewidth=line.get_linewidth() or 1.5,
                 linestyle=line.get_linestyle() or "-",
                 marker=line.get_marker() if line.get_marker() != "None" else None,
                 markersize=line.get_markersize() or 6,
                 label=line.get_label(),
                 alpha=line.get_alpha() if line.get_alpha() is not None else 1.0)
    # Patches (rectangles = bars, etc.) — copy with their xy intact.
    # The width comes from the source patch which was drawn with
    # the correct bin width.
    for patch in src.patches:
        try:
            new_patch = mpatches.Rectangle(
                patch.get_xy(), patch.get_width(), patch.get_height(),
                facecolor=patch.get_facecolor(),
                edgecolor=patch.get_edgecolor() or "white",
                linewidth=patch.get_linewidth() or 0.5,
                alpha=patch.get_alpha() if patch.get_alpha() is not None else 1.0,
            )
            dst.add_patch(new_patch)
        except Exception:
            pass
    # Text annotations (confusion matrix cell labels etc.)
    for text in src.texts:
        try:
            x, y = text.get_position()
            dst.text(x, y, text.get_text(),
                     ha=text.get_ha(), va=text.get_va(),
                     fontsize=text.get_fontsize() or 10,
                     color=text.get_color(),
                     fontweight=text.get_fontweight() or "normal",
                     transform=text.get_transform())
        except Exception:
            pass
    # Axis limits: if there's an imshow, it already set the limits
    # to (0, n-1) and inverted the y axis. Don't autoscale or
    # we'll lose those. Otherwise, autoscale to fit the data.
    has_image = bool(src.get_images())
    if not has_image:
        try:
            dst.set_autoscalex_on(True)
            dst.set_autoscaley_on(True)
            dst.autoscale_view(scalex=True, scaley=True)
        except Exception:
            pass
    else:
        # Preserve the source's axis limits (imshow sets them).
        try:
            dst.set_xlim(src.get_xlim())
            dst.set_ylim(src.get_ylim())
        except Exception:
            pass
    # Legend
    handles, labels = src.get_legend_handles_labels()
    if handles and any(labels):
        try:
            src_legend = src.get_legend()
            loc = src_legend._loc if src_legend else "best"
            dst.legend(loc=loc, fontsize=8)
        except Exception:
            try:
                dst.legend(fontsize=8)
            except Exception:
                pass
    # Grid
    try:
        if src.get_axisbelow():
            dst.grid(True, alpha=0.2)
    except Exception:
        pass


# -----------------------------------------------------------------
# Module-level convenience: re-export SPACE_MD so the import
# at the top of the file doesn't fail.
# -----------------------------------------------------------------
from design import SPACE_MD


def _figure_cache_key(*args):
    """Compute a hash key for the figure cache.

    Each figure is a function of (y_test, y_prob, algorithm, and one
    or two metrics). We hash the numpy arrays' bytes plus the
    metrics. This is O(N) over the test set (a few hundred floats
    at most) and avoids creating any new objects.

    We use Python's built-in hash() which is salted per process
    (so it changes between runs) but stable within a process. That's
    exactly what we want for the cache — within one run, equal data
    gives equal keys; across runs we don't care.
    """
    parts = []
    for a in args:
        if a is None:
            parts.append("None")
        elif isinstance(a, np.ndarray):
            # .tobytes() is the fastest way to hash the contents
            parts.append(a.tobytes())
        elif isinstance(a, str):
            parts.append(a.encode("utf-8"))
        else:
            parts.append(str(a).encode("utf-8"))
    return hash(b"|".join(parts))
