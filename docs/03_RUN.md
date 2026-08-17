# 03 — Run the App

This document covers the everyday use of the app: starting it,
navigating between pages, and using the core features.

> **Time:** ~5 minutes.
> **Prerequisites:** completed [01_INSTALL.md](01_INSTALL.md) and
> [02_SETUP.md](02_SETUP.md).

---

## 1. Start the app

Open a terminal in the project folder and activate the
virtual environment if it isn't already:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
```

Then run:

```bash
python app.py
```

The app window opens on the **Login** page.

> **Tip:** on Windows, you can also double-click
> `run_app.bat` (create it once with the contents of
> `build.bat` minus the PyInstaller block). Or make a
> shortcut on the desktop that runs `python app.py`.

---

## 2. The Login page

The Login page is the entry point. You have two choices:

### Option A — Mock Feed (recommended for first run)

Click **"Use Mock Feed"**. The app:

1. Generates ~150 random ticks per symbol to warm up the
   indicators.
2. Starts a background thread that emits a fresh tick per
   symbol every second.
3. Unlocks the sidebar so you can navigate to every page.

The mock feed uses **realistic seed prices** (RELIANCE ~₹2,450,
TCS ~₹3,500, etc.) so the data looks like a real feed.

### Option B — Connect to Angel One (live feed)

This requires Angel One credentials. See
**[04_LIVE_FEED.md](04_LIVE_FEED.md)** for the full step-by-step.

The Login page also has a **"Show technical details ▾"**
disclosure that exposes the four credential fields. You don't
need to fill these in for the mock feed.

---

## 3. The sidebar

After login, the sidebar on the left shows every page:

| # | Page | Purpose |
|---|------|---------|
| 1 | Dashboard | Live screener table — every Nifty 100 symbol + AI verdict |
| 2 | Stock Detail | Single-symbol chart, depth, ETQ, LTQ feed |
| 3 | AI Signals | Tabular log of every SMMA crossover + AI verdict |
| 4 | Trade Log | Open + closed trades, win rate, AI accuracy |
| 5 | ML Stats | Train the AI, see accuracy / confusion matrix / backtest |
| 6 | Settings | Tune screening filters, refresh interval, dark mode |
| 7 | Alerts | In-app error log |
| 8 | Debug Log | Tick counter + websocket log buffer |
| 9 | Help | Quick-start guide + glossary |

Click any item to switch pages. Up/Down arrow keys also work
when the sidebar has keyboard focus.

---

## 4. The Dashboard

The Dashboard is the main screener view. Each row is one
Nifty 100 symbol and shows:

* **Symbol** — trading symbol (clickable to open Stock Detail)
* **LTP** — last traded price
* **Change** — % change vs previous close
* **SMMA(20)** and **SMMA(120)** — fast and slow smoothed MAs
* **Bias** — UP / DOWN (fast vs slow)
* **LTQ** — last traded quantity
* **ETQ** — equal-traded quantity over a 5-min window
* **AI** — model probability + ACCEPT/AVOID verdict

Rows highlighted in **green** are the most recent AI ACCEPT
signals. The screener auto-refreshes every 1-2 seconds.

**Double-click a row** to open the **Stock Detail** page for
that symbol.

---

## 5. Stock Detail

Shows one symbol in depth:

* Header — symbol, LTP, % change vs SMMA(20), UP/DOWN chip
* Chart — LTP + SMMA(20) + SMMA(120) line chart (matplotlib)
* 6 stat cards — Bid, Ask, Spread, Volume, 5m ETQ, 60m ETQ
* Market depth — best bid and best ask with quantities
* Recent trades (LTQ feed) — last 8 prints

Click **← Back to Dashboard** to return.

---

## 6. AI Signals

A scrollable log of every SMMA crossover the screener has
detected, with the AI verdict attached. Newest at top.
Auto-refreshes every 1 second.

Color coding:

* **Green rows** — AI verdict was ACCEPT
* **Red rows** — AI verdict was AVOID

---

## 7. Trade Log

Two tabs:

* **Open** — trades currently in flight. Updates as the LTP
  moves; unrealized P&L in real time.
* **Closed** — every completed round-trip. P&L, win rate, and
  the AI's verdict (Correct / Wrong) for each.

A summary line at the bottom shows aggregate stats:
"Trades: 87   Wins: 51   Win rate: 58.6%   Net P&L:
₹+12,340.00   AI accuracy: 62.1% (87 evaluated)".

---

## 8. ML Stats

Six tabs:

* **Overview** — headline metrics, confusion matrix, prediction
  distribution
* **Algorithms** — comparison chart + cross-validated metrics
* **Curves** — ROC curve, PR curve, calibration plot
* **Economics** — backtest (did the filter make money?), P&L
  distribution, per-symbol breakdown
* **Features** — feature importance, learning curve
* **Data** — raw closed-trade log (last 100)

**First time?** Click **"Refresh Metrics"** in the top right.
This trains 2 algorithms on your closed trades and populates
every chart. Takes 1-2 seconds for 100 rows.

**Once you have 20+ closed trades**, click **"Retrain Now"**
to fit a new model and save it as the active model. The next
crossover will use the freshly-trained model.

---

## 9. Settings

Tweak every runtime screener parameter:

* LTP min / max — filter out illiquid prices
* Bid/Ask Qty min — minimum liquidity
* Refresh interval (ms) — dashboard refresh rate
* SMMA fast / slow periods
* LTQ window sizes
* Alert sounds, dark mode, auto-trade stub

**Restart Mock Feed** wipes state and starts a fresh run —
useful when the screener has been running for a while and you
want a clean slate.

---

## 10. Alerts

Live log of every error and warning the app emits. Useful for
diagnosing live-feed issues without opening a separate
terminal.

---

## 11. Debug Log

The `websocket_client` logger's tail. Shows tick counter, last
tick age, and the last 500 log lines.

---

## 12. Help

Quick-start guide + glossary of every term (LTP, LTQ, ETQ,
SMMA, etc.).

---

## 13. Stopping the app

Close the window (X button) or press `Ctrl+C` in the terminal.

The mock-feed thread stops automatically when the window
closes (it's a daemon thread).

---

## Next step

For live-feed setup, continue to
**[04_LIVE_FEED.md](04_LIVE_FEED.md)**.
