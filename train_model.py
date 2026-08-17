"""
CLI trainer. Reads trade_log.csv (populated automatically by the
dashboard via trade_tracker.py) and fits a LogisticRegression on the
entry-time features. Re-run after every ~50 closed trades to keep
signal_model.pkl current.

    python train_model.py
"""

import os
import pandas as pd
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score

from trade_tracker import TRADE_LOG_PATH, FEATURE_KEYS

MODEL_PATH = "signal_model.pkl"


def main():
    if not os.path.exists(TRADE_LOG_PATH):
        print(f"No {TRADE_LOG_PATH} yet — run the dashboard first to collect trades.")
        return

    df = pd.read_csv(TRADE_LOG_PATH)
    if len(df) < 20:
        print(
            f"Only {len(df)} logged trades so far; the model needs more "
            f"before training is meaningful. Keep the dashboard running, "
            f"then rerun this script."
        )
        return

    X = df[FEATURE_KEYS]
    y = df["profitable"]

    # stratify= requires both classes present; otherwise do a plain split.
    stratify = y if y.nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=stratify
    )

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(f"Test accuracy: {accuracy_score(y_test, preds):.2f}")
    try:
        probs = model.predict_proba(X_test)[:, 1]
        print(f"Test ROC-AUC: {roc_auc_score(y_test, probs):.2f}")
    except Exception:
        # ROC-AUC undefined with only one class in the test split.
        pass

    joblib.dump(model, MODEL_PATH)
    print(f"Saved trained model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
