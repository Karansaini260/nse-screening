# NSE Screening — SMMA + ETQ + AI Filter

A multi-page Tkinter app for screening the Nifty 100 with SMMA
crossovers, ETQ, and a learned AI filter.

## Run

```bash
# Core dependencies (data layer, ML, charts)
pip install pandas scikit-learn joblib matplotlib

# Required ONLY for the live Angel One feed. The mock feed works
# without these. Install in the SAME virtualenv you use for the app.
pip install smartapi-python websocket-client

# Optional: lets the SDK generate TOTP codes for you. Without it the
# app falls back to a pure-stdlib implementation.
pip install pyotp

python app.py
```

The app opens on the **Login** page. If the Angel One SDK isn't
installed you'll see a red warning at the top of the Login page with
the exact pip commands to run. Either fill in Angel One credentials
and click **Connect (Live)**, or click **Use Mock Feed** to try the
UI with random data.

### Troubleshooting the live feed

The Login page shows the actual SDK error (and the Alerts page
records it). Common fixes:

- **`No module named 'SmartConnect'`** — run `pip install smartapi-python`
- **`No module named 'websocket'`** — run `pip install websocket-client`
- **`Login failed: Invalid Token`** — your TOTP secret is wrong, or
  the base32 secret was copied with stray spaces. Re-copy from your
  authenticator app.
- **`SmartWebSocketV2 class not found`** — `pip install --upgrade smartapi-python`
- **My `python -c "from smartapi import SmartConnect"` fails** —
  make sure no local file is named `smartapi.py` (it shadows the
  installed package).

## Pages

| # | Page          | What it does                                              |
|---|---------------|-----------------------------------------------------------|
| 1 | Login         | Broker credentials, live vs mock feed                     |
| 2 | Dashboard     | Live screener table (SMMA crossovers, AI verdict)         |
| 3 | Stock Detail  | Single-symbol chart, depth, ETQ, LTQ feed (matplotlib)    |
| 4 | AI Signals    | Recent crossover log with AI Accept/Avoid verdict         |
| 5 | Trade Log     | Open + closed round-trips with P&L and AI-correct verdict |
| 6 | ML Stats      | Accuracy/Precision/Recall/AUC, confusion matrix, retrain  |
| 7 | Settings      | Live-bound runtime tunables (LTP band, qty, intervals)   |
| 8 | Alerts        | Live log of all alerts; subscribe-based live updates      |
| 9 | Help          | In-app glossary and quick-start                           |

## Train the model

After ~20-50 closed trades are logged to `trade_log.csv`:

- click **Retrain Now** on the **ML Stats** page, or
- run `python train_model.py` from the command line.

Either path writes `signal_model.pkl`; `ai_model.py` loads it
automatically on the next crossover, replacing the cold-start heuristic.

## File map

```
app.py                    Main shell (sidebar + content)
config.py                 API credentials (filled in by the user)
indicators.py             SymbolState — SMMA, ETQ, feature snapshot
websocket_client.py       Angel One feed + mock fallback
trade_tracker.py          Round-trip logger -> trade_log.csv
ai_model.py               Loads signal_model.pkl, scores crossovers
train_model.py            CLI: fits LogisticRegression on trade_log.csv
shared.py                 Settings singleton, Alerts bus, Signals bus
pages/                    One module per Tk Frame
tests/test_smoke.py       Non-GUI data-layer tests
```

## Tests

```bash
python tests/test_smoke.py
```

Exercises indicators, trade tracker, AI heuristic, and the full
train-then-predict loop. No display required.
