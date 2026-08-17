"""
Analytics module for the AI filter.

This module computes the full set of metrics, plots, and
diagnostics used by the ML Stats page. It is intentionally
self-contained — every function takes a DataFrame and returns
a value or a matplotlib figure, so the page code stays simple.

The metrics we report cover four angles:

  1. **Discrimination** — does the model separate winners from
     losers? (Accuracy, Precision, Recall, F1, ROC-AUC, PR-AUC)

  2. **Calibration** — when the model says "60% likely", is the
     trade actually profitable ~60% of the time? (Brier score,
     calibration plot)

  3. **Robustness** — does the model hold up on data it hasn't
     seen? (Cross-validated metrics, learning curves)

  4. **Economics** — does using the model actually make money?
     (Backtest P&L, per-symbol breakdown, baseline comparison)

For a screener that uses an AI filter to decide whether to take
a signal, the ECONOMICS are what matter most. A model with
0.55 accuracy that filters out the worst 20% of signals can
double your win rate — which is the whole point.
"""

import os
import numpy as np
import pandas as pd
from typing import Any, Optional, Tuple, Dict

# Matplotlib is used for all charts so the page can embed
# them in FigureCanvasTkAgg widgets.
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import (
    train_test_split, StratifiedKFold, cross_val_score, learning_curve,
)
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, average_precision_score, brier_score_loss,
    confusion_matrix,
    precision_recall_curve, roc_curve,
)
from sklearn.calibration import calibration_curve

from trade_tracker import TRADE_LOG_PATH, FEATURE_KEYS


# -----------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------

def load_trades() -> pd.DataFrame:
    """Read trade_log.csv into a DataFrame. Returns an empty
    DataFrame with the expected columns if the file doesn't
    exist or is empty."""
    if not os.path.exists(TRADE_LOG_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(TRADE_LOG_PATH)
    except Exception:
        return pd.DataFrame()
    return df


def _prepare_xy(df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
    """Extract features X and label y from the trade log.

    Drops rows with missing values and returns (None, None) if
    there isn't enough data to train on (need >= 20 rows with
    at least 2 unique labels).
    """
    if df.empty or len(df) < 20:
        return None, None
    # Ensure the columns we need exist.
    missing = [c for c in FEATURE_KEYS + ["profitable"] if c not in df.columns]
    if missing:
        return None, None
    # Drop rows with any NaN in the feature columns.
    df = df.dropna(subset=FEATURE_KEYS + ["profitable"]).copy()
    if len(df) < 20 or df["profitable"].nunique() < 2:
        return None, None
    X = df[FEATURE_KEYS]
    y = df["profitable"].astype(int)
    return X, y


# -----------------------------------------------------------------
# Model training
# -----------------------------------------------------------------

# A dictionary of "algorithm name" -> (model class, constructor kwargs).
# We use a small grid of complementary algorithms so the user can
# see how different approaches compare on their data:
#
#  * LogisticRegression — linear, interpretable, the original
#  * RandomForest        — non-linear, handles interactions, robust
#
# Gradient Boosting was previously included as a third option but
# it was the slowest of the three and produced nearly identical
# results to Random Forest on this 6-feature classification
# problem, so it was removed. The page now compares only two
# algorithms, which is plenty for a 100-row trade log.
#
# Hyperparameters are intentionally LIGHTER than the sklearn defaults
# so the page refreshes in well under a second on a 200-row trade log
# (and remains usable up to a few thousand rows). The previous values
# (n_estimators=200) made the page freeze for 15+ seconds, which
# blocked the UI thread and made the whole app "Not Responding".
ALGORITHMS = {
    "Logistic Regression": (
        LogisticRegression, {"max_iter": 500, "class_weight": "balanced"}
    ),
    "Random Forest": (
        RandomForestClassifier, {
            "n_estimators": 60, "max_depth": 5,
            "min_samples_leaf": 3, "class_weight": "balanced",
            "random_state": 42,
        }
    ),
}


def _train_single(
    name: str, X: pd.DataFrame, y: pd.Series
) -> Tuple[Any, pd.DataFrame, pd.Series, np.ndarray, np.ndarray]:
    """Train one algorithm and return ``(model, X_test, y_test, y_pred, y_prob)``.

    Uses a stratified 75/25 split so both algorithms see the same
    test set and the comparison is fair. Falls back to a
    non-stratified split when the data is too small to support
    stratification (less than 2 samples of the minority class
    in the test set).
    """
    Cls, kwargs = ALGORITHMS[name]
    # Decide whether we can stratify. Stratification needs at
    # least 2 samples per class in the test set (i.e. 8 in the
    # full set when test_size=0.25 and there are 2 classes).
    min_class_count = int(y.value_counts().min()) if len(y.value_counts()) > 1 else 0
    can_stratify = min_class_count >= 4  # need >=2 per side in test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42,
        stratify=y if can_stratify else None,
    )
    model = Cls(**kwargs)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    # Some classifiers (e.g. some LinearSVC variants) don't have
    # predict_proba. We guard against that.
    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X_test)[:, 1]
    else:
        # Use decision_function as a proxy.
        y_prob = model.decision_function(X_test)
    return model, X_test, y_test, y_pred, y_prob


def train_all(X: pd.DataFrame, y: pd.Series) -> Dict[str, dict]:
    """Train every algorithm in ALGORITHMS and return a dict
    mapping algorithm name -> {model, X_test, y_test, y_pred,
    y_prob, metrics}.

    The metrics dict has accuracy, precision, recall, f1,
    roc_auc, pr_auc, brier, specificity.
    """
    results = {}
    for name in ALGORITHMS:
        try:
            model, X_test, y_test, y_pred, y_prob = _train_single(name, X, y)
            results[name] = {
                "model": model,
                "X_test": X_test,
                "y_test": y_test,
                "y_pred": y_pred,
                "y_prob": y_prob,
                "metrics": compute_metrics(y_test, y_pred, y_prob),
            }
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


# -----------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------

def compute_metrics(y_true, y_pred, y_prob) -> Dict[str, float]:
    """Return a flat dict of every metric we report on the page.

    All values are floats in [0, 1] except log_loss which is
    unbounded (lower is better). Specificity = true negative
    rate = TN / (TN + FP).
    """
    out = {}
    out["accuracy"] = accuracy_score(y_true, y_pred)
    out["precision"] = precision_score(y_true, y_pred, zero_division=0)
    out["recall"] = recall_score(y_true, y_pred, zero_division=0)
    out["f1"] = f1_score(y_true, y_pred, zero_division=0)
    # ROC-AUC needs both classes in y_true.
    try:
        out["roc_auc"] = roc_auc_score(y_true, y_prob)
    except Exception:
        out["roc_auc"] = float("nan")
    try:
        out["pr_auc"] = average_precision_score(y_true, y_prob)
    except Exception:
        out["pr_auc"] = float("nan")
    try:
        out["brier"] = brier_score_loss(y_true, y_prob)
    except Exception:
        out["brier"] = float("nan")
    # Specificity (true negative rate).
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    out["specificity"] = tn / max(1, tn + fp)
    out["tp"] = int(tp)
    out["tn"] = int(tn)
    out["fp"] = int(fp)
    out["fn"] = int(fn)
    out["n"] = int(len(y_true))
    return out


# -----------------------------------------------------------------
# Economic metrics (does the model make money?)
# -----------------------------------------------------------------

def backtest_pnl(df: pd.DataFrame, y_prob: np.ndarray, threshold: float = 0.5) -> dict:
    """Simulate trading only when the model predicts P(profitable)
    > threshold. Returns a dict with the result.

    The trade log has one row per CLOSED trade. We replay the
    model's prediction (y_prob must align with df row order) and
    only "take" the trade if the predicted probability exceeds
    the threshold. Then we sum the P&L of the taken trades and
    compare to the baseline of taking every trade.
    """
    if df.empty or len(y_prob) != len(df):
        return {}
    # y_prob may be on a subset of df (the test set). If the
    # caller is passing test-set predictions, df should already
    # be the test-set subset.
    take = y_prob >= threshold
    pnl = df["pnl"].values
    baseline_pnl = float(pnl.sum())
    filtered_pnl = float(pnl[take].sum()) if take.any() else 0.0
    n_taken = int(take.sum())
    n_total = int(len(pnl))
    win_rate_filtered = float((pnl[take] > 0).mean()) if n_taken else 0.0
    win_rate_baseline = float((pnl > 0).mean()) if n_total else 0.0
    avg_pnl_filtered = float(pnl[take].mean()) if n_taken else 0.0
    avg_pnl_baseline = float(pnl.mean()) if n_total else 0.0
    return {
        "n_taken": n_taken,
        "n_total": n_total,
        "baseline_pnl": baseline_pnl,
        "filtered_pnl": filtered_pnl,
        "win_rate_baseline": win_rate_baseline,
        "win_rate_filtered": win_rate_filtered,
        "avg_pnl_baseline": avg_pnl_baseline,
        "avg_pnl_filtered": avg_pnl_filtered,
        "improvement_pnl": filtered_pnl - baseline_pnl,
    }


def per_symbol_breakdown(df: pd.DataFrame, y_prob: np.ndarray, threshold: float = 0.5) -> pd.DataFrame:
    """Per-symbol accuracy and P&L: which symbols does the model
    handle well, which does it get wrong?

    Returns a DataFrame indexed by symbol with columns:
      n_trades, win_rate, avg_pnl, model_accuracy, accepted_n,
      accepted_pnl, rejected_n, rejected_pnl, model_lift.
    """
    if df.empty or len(y_prob) != len(df):
        return pd.DataFrame()
    work = df.copy()
    work["pred"] = (y_prob >= threshold).astype(int)
    work["correct"] = (work["pred"] == work["profitable"]).astype(int)
    grp = work.groupby("symbol")
    out = pd.DataFrame({
        "n_trades":    grp.size(),
        "win_rate":    grp["profitable"].mean(),
        "avg_pnl":     grp["pnl"].mean(),
        "model_accuracy": grp["correct"].mean(),
    })
    accepted = work[work["pred"] == 1].groupby("symbol")
    if len(accepted) > 0:
        # reindex to the same symbol list so every symbol has a row
        # (NaN if it had no accepted trades).
        a = accepted.agg({"pnl": "sum", "symbol": "size",
                          "profitable": "mean"}).rename(
            columns={"symbol": "accepted_n", "pnl": "accepted_pnl",
                     "profitable": "accepted_win"})
        a = a.reindex(out.index)
        out["accepted_n"] = a["accepted_n"].fillna(0).astype(int)
        out["accepted_pnl"] = a["accepted_pnl"].fillna(0.0)
        out["accepted_win"] = a["accepted_win"].fillna(0.0)
    else:
        out["accepted_n"] = 0
        out["accepted_pnl"] = 0.0
        out["accepted_win"] = 0.0
    rejected = work[work["pred"] == 0].groupby("symbol")
    if len(rejected) > 0:
        # reindex to the same symbol list so every symbol has a row
        # (NaN if it had no rejected trades).
        r = rejected.agg({"pnl": "sum", "symbol": "size"}).rename(
            columns={"symbol": "rejected_n", "pnl": "rejected_pnl"})
        r = r.reindex(out.index)
        out["rejected_n"] = r["rejected_n"].fillna(0).astype(int)
        out["rejected_pnl"] = r["rejected_pnl"].fillna(0.0)
    else:
        out["rejected_n"] = 0
        out["rejected_pnl"] = 0.0
    # Model lift = avg P&L when accepting - avg P&L when rejecting.
    # If a symbol has no rejected trades, the lift is just the avg
    # P&L of accepted trades (i.e. assume rejecting would have
    # zero P&L, which is the best-case scenario).
    out["model_lift"] = out["accepted_pnl"] / out["accepted_n"].clip(lower=1) - \
                       out["rejected_pnl"] / out["rejected_n"].clip(lower=1)
    out["model_lift"] = out["model_lift"].fillna(0.0)
    out = out.sort_values("model_lift", ascending=False)
    return out


# -----------------------------------------------------------------
# Cross-validated metrics
# -----------------------------------------------------------------

def cross_validate(name: str, X: pd.DataFrame, y: pd.Series, n_splits: int = 3) -> dict:
    """Stratified cross-validation. Returns the mean and
    std of accuracy, precision, recall, f1, roc_auc across folds.

    This is a more honest measure of model performance than a
    single train/test split because every sample is in the
    test set exactly once.

    The default is 3 folds (not 5) to keep the page snappy.
    3 folds still gives a meaningful mean ± std on trade logs
    of 100+ rows, and the page can refresh in well under a
    second. If you want 5-fold, pass n_splits=5.
    """
    Cls, kwargs = ALGORITHMS[name]
    model = Cls(**kwargs)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    out = {}
    for metric in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        try:
            if metric == "roc_auc":
                scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
            else:
                scores = cross_val_score(model, X, y, cv=cv, scoring=metric)
            out[metric] = {"mean": float(scores.mean()), "std": float(scores.std())}
        except Exception:
            out[metric] = {"mean": float("nan"), "std": float("nan")}
    return out


# -----------------------------------------------------------------
# Plots — each function returns a matplotlib Figure
# -----------------------------------------------------------------

def fig_confusion_matrix(cm, model_name: str = "") -> Figure:
    """Draw the confusion matrix as a heatmap with cell counts
    and percentages. The colour scale is fixed across plots so
    light and dark mode look the same."""
    fig = Figure(figsize=(4, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    cm_arr = np.array(cm)
    # Normalise to fractions for the cell colour.
    row_sums = cm_arr.sum(axis=1, keepdims=True)
    fractions = np.where(row_sums > 0, cm_arr / row_sums, 0)
    # Heatmap with a blue colormap (works in both light and dark).
    ax.imshow(fractions, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(["Predicted\nLoss", "Predicted\nProfit"], fontsize=9)
    ax.set_yticklabels(["Actual\nLoss", "Actual\nProfit"], fontsize=9)
    # Annotate each cell with count and percentage.
    for i in range(2):
        for j in range(2):
            count = int(cm_arr[i, j])
            pct = fractions[i, j] * 100
            # Pick text colour: white on dark cells, black on light.
            colour = "white" if fractions[i, j] > 0.5 else "black"
            ax.text(j, i, f"{count}\n({pct:.0f}%)",
                    ha="center", va="center", fontsize=10,
                    color=colour, fontweight="bold")
    title = "Confusion Matrix"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    fig.tight_layout()
    return fig


def fig_roc_curve(y_true, y_prob, auc: float, model_name: str = "") -> Figure:
    """Receiver-operating-characteristic curve. The diagonal line
    is a random classifier; the further the curve bows toward the
    top-left, the better the model."""
    fig = Figure(figsize=(4, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    ax.plot(fpr, tpr, color="#4f46e5", linewidth=2,
            label=f"Model (AUC = {auc:.2f})")
    ax.plot([0, 1], [0, 1], "--", color="gray", linewidth=1,
            label="Random (AUC = 0.50)")
    ax.fill_between(fpr, tpr, alpha=0.15, color="#4f46e5")
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1.02])
    ax.set_xlabel("False Positive Rate", fontsize=9)
    ax.set_ylabel("True Positive Rate (Recall)", fontsize=9)
    title = "ROC Curve"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def fig_pr_curve(y_true, y_prob, pr_auc: float, model_name: str = "") -> Figure:
    """Precision-Recall curve. Especially useful when the
    positive class is rare (which is the case for "profitable
    trades" — typically 30-50% of trades)."""
    fig = Figure(figsize=(4, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    precision, recall, _ = precision_recall_curve(y_true, y_prob)
    ax.plot(recall, precision, color="#16a34a", linewidth=2,
            label=f"Model (AP = {pr_auc:.2f})")
    # Baseline = positive class rate.
    baseline = float(np.mean(y_true))
    ax.axhline(baseline, linestyle="--", color="gray", linewidth=1,
               label=f"Baseline ({baseline:.0%})")
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1.02])
    ax.set_xlabel("Recall (catches profitable)", fontsize=9)
    ax.set_ylabel("Precision (precision when it does)", fontsize=9)
    title = "Precision-Recall Curve"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def fig_calibration(y_true, y_prob, model_name: str = "") -> Figure:
    """Calibration plot. If the model is perfectly calibrated,
    the curve is on the diagonal. A curve above the diagonal
    means the model is OVER-confident (predicts higher prob
    than actual); below means UNDER-confident."""
    fig = Figure(figsize=(4, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    # Calibration curve. We use 5 quantile bins so the curve
    # is reasonably smooth even with small N.
    if len(y_true) >= 5:
        try:
            frac_pos, mean_pred = calibration_curve(
                y_true, y_prob, n_bins=min(5, len(y_true) // 2),
                strategy="quantile",
            )
            ax.plot([0, 1], [0, 1], "--", color="gray", linewidth=1,
                    label="Perfectly calibrated")
            ax.plot(mean_pred, frac_pos, "o-", color="#4f46e5",
                    linewidth=2, markersize=8,
                    label="Model")
        except Exception:
            pass
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1.02])
    ax.set_xlabel("Mean predicted probability", fontsize=9)
    ax.set_ylabel("Fraction actually profitable", fontsize=9)
    title = "Calibration Plot"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def fig_feature_importance(model, X: pd.DataFrame, model_name: str = "") -> Figure:
    """Two-panel feature importance: coefficient magnitudes
    (for linear models) and a generic bar chart of importances
    (for tree models). Falls back to permutation-style for any
    model that doesn't expose either."""
    fig = Figure(figsize=(5, 3.5), dpi=100)
    ax = fig.add_subplot(111)
    if hasattr(model, "coef_"):
        # Linear model.
        coefs = np.abs(model.coef_[0])
        names = list(X.columns)
        order = np.argsort(coefs)
        names = [names[i] for i in order]
        vals = coefs[order]
        colors = ["#16a34a" if v > 0 else "#dc2626" for v in model.coef_[0][order]]
        ax.barh(range(len(names)), vals, color=colors)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("|coefficient|  (green = positive, red = negative)", fontsize=8)
    elif hasattr(model, "feature_importances_"):
        # Tree model.
        imp = model.feature_importances_
        names = list(X.columns)
        order = np.argsort(imp)
        ax.barh(range(len(names)), imp[order], color="#4f46e5")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels([names[i] for i in order], fontsize=8)
        ax.set_xlabel("Feature importance (impurity-based)", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No importance available for this model",
                ha="center", va="center", transform=ax.transAxes)
    title = "Feature Importance"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    fig.tight_layout()
    return fig


def fig_learning_curve(name: str, X: pd.DataFrame, y: pd.Series) -> Figure:
    """Learning curve: how does model performance change as we
    train on more data? If the train and validation curves
    converge, the model is at its data limit and you need
    MORE data to improve. If they diverge, the model is
    overfitting and you need REGULARISATION (more features
    or simpler model).

    We use 3 train sizes and 2-fold CV internally to keep
    this fast. That's 3 × 2 = 6 model fits per call (vs.
    18 with the old 6 sizes × 3 folds), which is plenty for
    showing the rough shape of the learning curve.
    """
    fig = Figure(figsize=(5, 3.5), dpi=100)
    ax = fig.add_subplot(111)
    Cls, kwargs = ALGORITHMS[name]
    try:
        # Use train_sizes appropriate for the dataset size.
        train_sizes = np.linspace(0.3, 0.9, 3).tolist()
        train_sizes_abs, train_scores, val_scores = learning_curve(
            Cls(**kwargs), X, y,
            cv=StratifiedKFold(n_splits=2, shuffle=True, random_state=42),
            train_sizes=train_sizes,
            scoring="roc_auc", random_state=42, n_jobs=1,
        )
        train_mean = train_scores.mean(axis=1)
        train_std = train_scores.std(axis=1)
        val_mean = val_scores.mean(axis=1)
        val_std = val_scores.std(axis=1)
        ax.plot(train_sizes_abs, train_mean, "o-", color="#4f46e5",
                label="Training ROC-AUC")
        ax.fill_between(train_sizes_abs, train_mean - train_std,
                        train_mean + train_std, alpha=0.15, color="#4f46e5")
        ax.plot(train_sizes_abs, val_mean, "s-", color="#16a34a",
                label="Validation ROC-AUC")
        ax.fill_between(train_sizes_abs, val_mean - val_std,
                        val_mean + val_std, alpha=0.15, color="#16a34a")
    except Exception as e:
        ax.text(0.5, 0.5, f"Could not compute learning curve:\n{e}",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
    ax.set_xlabel("Training set size", fontsize=9)
    ax.set_ylabel("ROC-AUC", fontsize=9)
    ax.set_title(f"Learning Curve — {name}", fontsize=10, fontweight="bold", pad=8)
    ax.set_ylim([0, 1.02])
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def fig_pnl_distribution(df: pd.DataFrame) -> Figure:
    """Histogram of P&L for all closed trades. The shaded bars
    show the distribution; a vertical line at 0 separates
    winners (right) from losers (left)."""
    fig = Figure(figsize=(5, 3), dpi=100)
    ax = fig.add_subplot(111)
    pnl = df["pnl"].values
    ax.hist(pnl, bins=20, color="#4f46e5", edgecolor="white", alpha=0.85)
    ax.axvline(0, color="#dc2626", linestyle="--", linewidth=2,
               label=f"Break-even ({(pnl > 0).mean():.0%} win rate)")
    ax.axvline(pnl.mean(), color="#16a34a", linestyle="-", linewidth=2,
               label=f"Mean P&L = ₹{pnl.mean():.2f}")
    ax.set_xlabel("P&L per trade (₹)", fontsize=9)
    ax.set_ylabel("Number of trades", fontsize=9)
    ax.set_title("P&L Distribution", fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return fig


def fig_proba_distribution(y_true, y_prob, model_name: str = "") -> Figure:
    """Two overlaid histograms: predicted probability for trades
    that were actually winners vs losers. If the model is
    discriminative, the two distributions don't overlap much."""
    fig = Figure(figsize=(5, 3), dpi=100)
    ax = fig.add_subplot(111)
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    winners = y_prob[y_true == 1]
    losers = y_prob[y_true == 0]
    bins = np.linspace(0, 1, 21)
    ax.hist(losers, bins=bins, color="#dc2626", alpha=0.6,
            label=f"Actual losers (n={len(losers)})", edgecolor="white")
    ax.hist(winners, bins=bins, color="#16a34a", alpha=0.6,
            label=f"Actual winners (n={len(winners)})", edgecolor="white")
    ax.set_xlabel("Predicted P(profitable)", fontsize=9)
    ax.set_ylabel("Number of trades", fontsize=9)
    title = "Prediction Distribution"
    if model_name:
        title += f" — {model_name}"
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="upper center", fontsize=8)
    ax.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return fig


def fig_algorithm_comparison(results: dict) -> Figure:
    """Bar chart comparing the algorithms on every metric.

    The user can see at a glance which algorithm wins on
    which metric. With our small feature set (six columns)
    the two remaining algorithms tend to be very close on
    accuracy but disagree on ROC-AUC.
    """
    fig = Figure(figsize=(7, 3.5), dpi=100)
    ax = fig.add_subplot(111)
    names = [n for n, r in results.items() if "error" not in r]
    metrics_to_plot = ["accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"]
    metric_labels = ["Accuracy", "Precision", "Recall", "F1", "ROC-AUC", "PR-AUC"]
    n_metrics = len(metrics_to_plot)
    n_algos = len(names)
    if n_algos == 0:
        return fig
    x = np.arange(n_metrics)
    width = 0.8 / n_algos
    colors = ["#4f46e5", "#16a34a", "#dc2626", "#d97706"]
    for i, name in enumerate(names):
        vals = [results[name]["metrics"].get(m, 0) for m in metrics_to_plot]
        ax.bar(x + i * width - 0.4 + width / 2, vals, width,
               label=name, color=colors[i % len(colors)], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels, fontsize=9)
    ax.set_ylim([0, 1.05])
    ax.set_ylabel("Score", fontsize=9)
    ax.set_title("Algorithm Comparison", fontsize=10, fontweight="bold", pad=8)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return fig
