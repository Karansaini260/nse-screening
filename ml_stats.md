# ML Stats — Analytics & Training

The **ML Stats** page is the analytics-rich companion to the AI filter that runs
on the dashboard. Its job is to tell the user, with full evidence, **how well
the model actually works on their data** — not just a single accuracy number
but the whole picture: precision, recall, F1, ROC, calibration, learning
behaviour, economic impact, and a per-symbol breakdown.

The page is built around the **problem → solution** frame so a non-technical
user can read it top-to-bottom without prior ML knowledge.

## Where it lives

* **Page module:** `pages/ml_stats_page.py`
* **Analytics library:** `analytics.py` (11 functions, 9 figure helpers)
* **Tests:** `tests/test_analytics.py` (8 tests) and
  `tests/test_ml_stats_page.py` (4 tests)
* **Active model on disk:** `ai_model.py` saves the best estimator together
  with its algorithm name and chosen threshold as a dict:
  `{"model": estimator, "algorithm": name, "threshold": float, "trained_on": n}`

## The problem & the solution

| | |
|--|--|
| **Problem** | SMMA crossovers fire constantly. Most are noise. We need a way to say "this one is a winner, take it" vs. "this is junk, skip it." |
| **Solution** | Train a classifier on the user's own closed trades, learn which combination of LTQ ratio, ETQ momentum, bid-ask imbalance, spread, SMMA gap, and volatility predicts a winner, and report honestly how well the model performs. |

## The 6 tabs

### 1. Overview
The entry point. Shows:
- **Problem / solution statement** at the top so users know what they're looking at
- **Headline metrics** in a single row: Accuracy, Precision, Recall, F1, ROC-AUC, PR-AUC, Specificity, Brier — each with a tooltip that explains what it means in plain English
- **Confusion matrix heatmap** with cell percentages
- **Prediction distribution histogram** showing how well the model's probabilities separate winners from losers

### 2. Algorithms
Compares the three classifiers head-to-head:
- **Logistic Regression** — interpretable, fast baseline
- **Random Forest** — handles non-linearities, gives feature importance
- **Gradient Boosting** — usually the strongest, but slower to train
- **Bar chart** comparing all three on Accuracy, Precision, Recall, F1, ROC-AUC
- **Cross-validated metrics table** with mean ± std across 5 folds (more honest than a single train/test split)

### 3. Curves
Three diagnostic charts for the best algorithm:
- **ROC curve** — area under = ROC-AUC; 0.5 = random, 1.0 = perfect
- **Precision-Recall curve** — better than ROC when the positive class is rare
- **Calibration plot** — checks whether "60% probability" really means 60%

### 4. Economics
The most important tab for a trader:
- **Backtest summary**: "What if you'd followed the AI filter on your last N trades?"
  - Trades taken (with the chosen threshold)
  - Net P&L (filtered)
  - P&L improvement vs. taking every signal
  - Win rate (filtered vs. baseline)
  - Average P&L per trade (filtered vs. baseline)
- **P&L distribution histogram** of all closed trades
- **Per-symbol breakdown** showing where the model adds value, sorted by lift

### 5. Features
Tells the user which signals actually matter:
- **Feature importance** bar chart (impurity-based for tree models, coefficient-based for linear models)
- **Learning curve** — does adding more data help? If training ROC-AUC is 1.0 but validation is stuck at 0.5, the model has memorised the training set and won't improve with more data

### 6. Data
The raw, unfiltered historical trade log (most recent 100 closed trades):
- Time, Symbol, Direction, P&L, Profitable (Yes/No), Exit reason (win/loss)
- Useful for spot-checking whether the model is being trained on realistic data

## Two buttons at the top

| Button | What it does |
|--|--|
| **Refresh Metrics** | Re-reads `trade_log.csv` and recomputes every chart, table, and number. Doesn't retrain the model. |
| **Retrain Now** | Fits every algorithm, picks the best one by ROC-AUC, finds the optimal decision threshold by scanning 0.1–0.9, and saves the result as the new active model. |

## Optimal threshold — why we don't just use 0.5

By default a classifier says "winner" if the predicted probability is above
0.5. But for imbalanced data (say 30% winners) 0.5 is rarely optimal.

`MLStatsPage._find_optimal_threshold` scans `np.arange(0.1, 1.0, 0.05)` and
picks the threshold that **maximises the user's expected P&L on the test
set**. A higher threshold means fewer trades but each trade is more likely
to be a winner; a lower threshold means more trades but the model is less
selective. The right balance is the one that makes the most money.

## How the active model file is structured

```python
joblib.dump({
    "model":         <sklearn estimator>,
    "algorithm":     "Random Forest",   # or Logistic Regression / Gradient Boosting
    "threshold":     0.45,              # the optimal P&L threshold
    "trained_on":    1234,              # how many trades it was trained on
}, MODEL_PATH)
```

`ai_model.get_model()` reads this dict and returns just the estimator for
backward compatibility, but `ai_model` also exposes `get_threshold()` and
`get_algorithm_name()` so the dashboard can show "Model: Gradient Boosting
(threshold 0.45)" in the live AI panel.

## Tests

| Test file | What it covers |
|--|--|
| `tests/test_analytics.py` | 8 tests — metrics, training, cross-validation, backtest, per-symbol breakdown, figure rendering, edge cases |
| `tests/test_ml_stats_page.py` | 4 tests — page renders with all 6 tabs, handles insufficient data, handles no data, optimal threshold search |

**Total: 12 new tests added this round, all passing.**
