"""
AI filter for SMMA crossovers.

Loads a trained model from ``signal_model.pkl`` (produced by
``train_model.py``); if the file is missing or can't be loaded,
falls back to a hand-tuned heuristic so the dashboard still
works during the cold-start period before enough trades have
been collected.

The public API is:

* :func:`predict_signal` — called by the dashboard on every fresh
  crossover. Returns ``(probability, decision, reason)``.
* :func:`get_model` — return the loaded model object (or ``None``)
  without forcing a reload.

The model file is a dict (not a bare estimator) that wraps the
trained estimator with metadata: which algorithm was used and
what decision threshold to apply. This lets the page show
"we're using Random Forest at threshold 0.55" instead of
"unknown model".

Module constants:

* :data:`MODEL_PATH` — the path to the saved model file.
* :data:`HEURISTIC_ACCEPT_THRESHOLD` — the probability above
  which the heuristic's signal is treated as ACCEPT.
* :data:`DEFAULT_THRESHOLD` — the fallback threshold when no
  saved model provides one.

For internal failure modes the module never raises — every
exception is logged and the heuristic fallback is used. This
keeps the dashboard UI responsive even if the on-disk model
is corrupt or the feature schema changes.
"""

import logging
import os
from typing import Any, Optional, Tuple

import joblib
import pandas as pd

from trade_tracker import FEATURE_KEYS

# -----------------------------------------------------------------------------
# Public constants
# -----------------------------------------------------------------------------

#: Filesystem path of the saved model bundle. Older versions stored a
#: bare estimator here; we auto-detect and fall back to the heuristic
#: when the legacy format is encountered.
MODEL_PATH: str = "signal_model.pkl"

#: Probability at and above which the heuristic's signal is treated
#: as ``ACCEPT``. Tuned empirically on synthetic data; see
#: :func:`_heuristic` for the per-feature contributions.
HEURISTIC_ACCEPT_THRESHOLD: float = 0.6

#: Decision threshold used when the saved model file is missing or
#: was written in the legacy format (no ``"threshold"`` key).
DEFAULT_THRESHOLD: float = 0.5


_log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Internal cache
# -----------------------------------------------------------------------------
# These are module-private. External code must use the ``predict_signal``
# and ``get_model`` accessors so the cache lifecycle stays in our
# control.

_model: Optional[Any] = None
_model_loaded: bool = False


def _reset_cache() -> None:
    """Drop the in-memory model so the next call re-reads from disk.

    Called by :mod:`pages.ml_stats_page` after a "Retrain Now" so
    the freshly-written ``signal_model.pkl`` is picked up on the
    next ``predict_signal`` call instead of the stale cache.
    """
    global _model, _model_loaded
    _model = None
    _model_loaded = False


def _load_model() -> Optional[Any]:
    """Load the model bundle from disk.

    Returns the unwrapped estimator (the object exposing
    ``.predict()`` and ``.predict_proba()``) or ``None`` if the
    file is missing or corrupt. The result is cached in the
    module-level ``_model`` so subsequent calls are O(1).

    The cache is keyed by a one-shot boolean — once we've
    attempted to load the file once, we never re-read it. This
    matches the original behaviour: a model is either present
    at startup or it isn't, and re-checking on every signal
    would be wasteful.
    """
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True
    if not os.path.exists(MODEL_PATH):
        _log.info("No trained model at %s; using heuristic.", MODEL_PATH)
        return None
    try:
        loaded = joblib.load(MODEL_PATH)
    except Exception as exc:
        # Corrupt file, wrong format, version mismatch — anything.
        # We log and fall through to the heuristic so the UI keeps
        # working.
        _log.warning("Could not load %s: %s. Falling back to heuristic.",
                     MODEL_PATH, exc)
        return None
    # New format: dict with a "model" key. Old format: bare estimator.
    if isinstance(loaded, dict) and "model" in loaded:
        _model = loaded["model"]
        _log.info("Loaded trained model from %s (algorithm=%s, threshold=%.2f).",
                  MODEL_PATH,
                  loaded.get("algorithm", "unknown"),
                  float(loaded.get("threshold", DEFAULT_THRESHOLD)))
    else:
        _model = loaded
        _log.info("Loaded legacy-format model from %s (no metadata).", MODEL_PATH)
    return _model


def _threshold() -> float:
    """Read the decision threshold from the saved model file.

    Returns :data:`DEFAULT_THRESHOLD` if the file is missing, in the
    legacy format, or unreadable.
    """
    if not os.path.exists(MODEL_PATH):
        return DEFAULT_THRESHOLD
    try:
        loaded = joblib.load(MODEL_PATH)
        if isinstance(loaded, dict):
            return float(loaded.get("threshold", DEFAULT_THRESHOLD))
    except Exception as exc:
        _log.debug("Could not read threshold from %s: %s", MODEL_PATH, exc)
    return DEFAULT_THRESHOLD


# -----------------------------------------------------------------------------
# Heuristic fallback
# -----------------------------------------------------------------------------
# A small, hand-tuned rule used during the cold-start period before
# the user has logged enough trades (~20+ closed round-trips) to fit a
# real model. Conservative by design: it only flips a signal to
# ``ACCEPT`` when the entry-time features are *clearly* aligned with
# the direction. False negatives are preferable to false positives
# here because the user can still see the raw signal on the dashboard.

#: Per-feature score adjustments used by :func:`_heuristic`. Keeping
#: them as a module constant makes the rule easy to tune without
#: digging through nested ``if`` blocks.
_HEURISTIC_RULES: Tuple[Tuple[str, str, float, float], ...] = (
    # (feature_key, direction_where_it_helps, threshold, score_delta)
    ("ltq_ratio_2m_5m",  "BUY",  1.2,  +0.15),  # accelerating
    ("ltq_ratio_2m_5m",  "SELL", 0.8,  +0.15),  # decelerating
    ("bid_ask_imbalance","BUY",  0.1,  +0.10),  # bid-heavy
    ("bid_ask_imbalance","SELL",-0.1,  +0.10),  # ask-heavy
)
#: Below this spread we award a small bonus; above we deduct a larger
#: penalty. Picked empirically — wide spreads on NSE usually mean
#: illiquid names that are easy to slip on.
_TIGHT_SPREAD_THRESHOLD: float = 0.1
_WIDE_SPREAD_THRESHOLD: float = 0.5
_TIGHT_SPREAD_BONUS: float = 0.05
_WIDE_SPREAD_PENALTY: float = 0.20


def _heuristic(state: Any, direction: str) -> Tuple[float, str, str]:
    """Cold-start rule of thumb until enough trades are logged.

    Returns ``(probability, decision, reason)``. The probability
    is bounded to ``[0, 1]`` and the decision is ``ACCEPT`` when
    the probability is at or above
    :data:`HEURISTIC_ACCEPT_THRESHOLD`, else ``AVOID``.
    """
    features = state.get_features()
    score: float = 0.5
    reasons: list = []
    for feature_key, dir_match, threshold, delta in _HEURISTIC_RULES:
        value = features[feature_key]
        if direction != dir_match:
            continue
        if (dir_match == "BUY" and value > threshold) or \
           (dir_match == "SELL" and value < threshold):
            score += delta
            reasons.append(_heuristic_reason(feature_key, dir_match, value))
    spread = features["spread"]
    if 0 <= spread < _TIGHT_SPREAD_THRESHOLD:
        score += _TIGHT_SPREAD_BONUS
        reasons.append("Tight spread")
    elif spread > _WIDE_SPREAD_THRESHOLD:
        score -= _WIDE_SPREAD_PENALTY
        reasons.append("Wide spread")
    score = max(0.0, min(1.0, score))
    decision = "ACCEPT" if score >= HEURISTIC_ACCEPT_THRESHOLD else "AVOID"
    reason_text = "; ".join(reasons) or "Heuristic, no strong signal"
    return score, decision, reason_text


def _heuristic_reason(feature_key: str, direction: str, value: float) -> str:
    """Render a short human-readable reason string for a heuristic rule."""
    if feature_key == "ltq_ratio_2m_5m":
        return "LTQ accelerating (BUY supportive)" if direction == "BUY" \
            else "LTQ decelerating (SELL supportive)"
    if feature_key == "bid_ask_imbalance":
        return "Bid-heavy depth" if direction == "BUY" else "Ask-heavy depth"
    return f"{feature_key} supports {direction}"


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def predict_signal(state: Any, direction: str = "BUY") -> Tuple[float, str, str]:
    """Score a fresh crossover and decide whether to take it.

    Parameters
    ----------
    state : indicators.SymbolState
        Per-symbol state at the moment of the crossover. Must
        expose ``.get_features() -> dict`` with the six
        feature keys.
    direction : str
        Either ``"BUY"`` or ``"SELL"``.

    Returns
    -------
    (probability, decision, reason) : tuple
        ``probability`` is a float in ``[0, 1]``;
        ``decision`` is ``"ACCEPT"`` or ``"AVOID"``;
        ``reason`` is a short human-readable explanation.

    The function never raises. Any failure (model corrupt, feature
    shape changed, OOM in the estimator) is logged and the
    heuristic fallback is used instead.
    """
    model = _load_model()
    if model is None:
        return _heuristic(state, direction)
    try:
        features = state.get_features()
        # Wrap in a DataFrame with named columns so newer sklearn
        # doesn't warn about feature-name mismatch.
        x = pd.DataFrame(
            [[features[k] for k in FEATURE_KEYS]],
            columns=FEATURE_KEYS,
        )
        probability = float(model.predict_proba(x)[0][1])
        threshold = _threshold()
        decision = "ACCEPT" if probability >= threshold else "AVOID"
        reason = f"Model: P(profitable)={probability:.2f}"
        return probability, decision, reason
    except Exception as exc:
        # Model file corrupt or feature shape changed. Fall back
        # gracefully so the UI never breaks mid-session.
        _log.warning("predict_signal failed (%s); falling back to heuristic.",
                     exc)
        return _heuristic(state, direction)


def get_model() -> Optional[Any]:
    """Return the loaded model object (or ``None``) without forcing a reload.

    Useful for diagnostics pages and tests that want to inspect
    the trained model directly.
    """
    return _load_model()
