# 08 — Project Structure

A guided tour of every file in the project, what it does,
and how the modules fit together.

> **Audience:** developers who need to modify the code.
> **Time:** ~10 minutes.

---

## High-level architecture

```
nse-screening/
├── app.py                  ← main entry, sets up sidebar + content
├── pages/                  ← each tab in the sidebar is a Frame
├── ai_model.py             ← ML model (logistic regression / random forest)
├── analytics.py            ← training, metrics, figures
├── websocket_client.py     ← live feed + mock feed
├── indicators.py           ← SMMA, ETQ, volatility
├── trade_tracker.py        ← trade lifecycle, CSV persistence
├── cards.py                ← custom rounded card widget
├── chatbot.py              ← chat assistant
├── theme.py                ← light/dark palettes
├── design.py               ← spacing / fonts / radii constants
├── shared.py               ← settings, alerts, signals, credentials
├── check_requirements.py   ← CLI diagnostic
├── build.bat               ← Windows build script
├── nse_screener.spec       ← PyInstaller spec
├── requirements.txt        ← dependency list
└── docs/                   ← you are reading this
```

---

## Module-by-module reference

### Entry points

| File | Purpose |
|------|---------|
| `app.py` | Main entry. Sets up the sidebar + content area, instantiates pages lazily, routes navigation. Run with `python app.py`. |
| `check_requirements.py` | CLI diagnostic that checks every dependency. Run with `python check_requirements.py`. |
| `build.bat` | Windows build script. Run with `build.bat`. |
| `nse_screener.spec` | PyInstaller spec. Read by `pyinstaller nse_screener.spec`. |

### UI layer

| File | Purpose |
|------|---------|
| `cards.py` | `Card` and `Chip` widgets — the rounded "card" and "chip" primitives used throughout the app. |
| `theme.py` | `current_palette()`, `subscribe(callback)` for theme-change notifications. Defines light and dark palettes. |
| `design.py` | Spacing constants (`SPACE_XS` … `SPACE_2XL`), radii, font tuples. The single source of truth for design tokens. |
| `pages/` | One Python file per page. Every page is a `ttk.Frame` subclass. |
| `pages/theme_subscribe.py` | `@themed` decorator — wires a class up to the theme bus. |
| `pages/background.py` | `run_in_background()` and `WorkerTracker` — daemon-thread helpers. |
| `pages/figures.py` | `create_figure_in_frame()` — matplotlib setup that works inside a Tk frame. |

### Pages (one file per sidebar entry)

| File | Page | Key methods |
|------|------|-------------|
| `pages/login_page.py` | 1. Login | `connect_live()`, `connect_mock()` |
| `pages/dashboard_page.py` | 2. Dashboard | `_tick()`, `_on_feed_ready()` |
| `pages/detail_page.py` | 3. Stock Detail | `set_symbol()`, `_tick()`, `_on_theme_change()` |
| `pages/ai_signals_page.py` | 4. AI Signals | `refresh()` |
| `pages/trade_log_page.py` | 5. Trade Log | `refresh()`, `_compute_results()` |
| `pages/ml_stats_page.py` | 6. ML Stats | `refresh()`, `_retrain()`, `_populate_*_tab()` |
| `pages/settings_page.py` | 7. Settings | `_reset()`, `_save()`, `_restart_feed()` |
| `pages/alerts_page.py` | 8. Alerts | `refresh()`, `_ack_selected()` |
| `pages/debug_log_page.py` | 9. Debug Log | `_refresh()`, `_clear()`, `_copy()` |
| `pages/help_page.py` | 10. Help | (static) |
| `pages/chatbot_window.py` | (floating) | `show()`, `toggle()`, `_send()` |

### Data layer

| File | Purpose |
|------|---------|
| `websocket_client.py` | Angel One SmartAPI feed + mock fallback. Exports `start_live_feed()`, `stop_mock_feed()`, `mock_pre_populate()`, `mock_steady_state()`, `states`, `LIVE_FEED_AVAILABLE`, `LOG_BUFFER`, etc. |
| `indicators.py` | `SymbolState` class — per-symbol rolling buffers + SMMA / ETQ / volatility. Updated on every tick. |
| `trade_tracker.py` | `TradeTracker` class — opens / closes trades, writes to `trade_log.csv`. Exports `TRADE_LOG_PATH`, `FEATURE_KEYS`. |
| `ai_model.py` | Loads the trained model from `signal_model.pkl`, exposes `get_model()` and `predict_signal(features)`. |
| `analytics.py` | `train_all()`, `cross_validate()`, `fig_*` figure functions. Heavy ML code, lazy-imported by `ml_stats_page.py`. |

### Shared state

| File | Purpose |
|------|---------|
| `shared.py` | `settings` (live-bound Tk Variables), `alerts` (the Alerts bus), `signals` (the AI Signals bus), `feed_ready` (the "data is flowing" bus), `credentials` (in-memory only, never written to disk). |

### Build artefacts

| File | Purpose |
|------|---------|
| `requirements.txt` | Pinned runtime dependencies. |
| `nse_screener.spec` | PyInstaller spec. Defines `hiddenimports`, `excludes`, output mode. |
| `build.bat` | Windows build script. One-click build. |
| `BUILD.md` | Build guide. |
| `CLEANUP_ROUND*.md` | Round-by-round changelogs. |

---

## Data flow

```
                     ┌────────────────┐
                     │  websocket_    │ ticks
                     │  client.py     │──────────┐
                     └────────────────┘          ▼
                                          ┌──────────────┐
                                          │ indicators.py│
                                          │ SymbolState  │
                                          └──────┬───────┘
                                                 │ read
                ┌────────────────────────────────┼──────────────────────────────┐
                │                                │                              │
                ▼                                ▼                              ▼
        ┌──────────────┐               ┌──────────────────┐         ┌────────────────────┐
        │ dashboard_   │               │ detail_page.py   │         │ ai_model.py        │
        │ page.py      │               │ (single-symbol   │         │ predict_signal()   │
        │              │               │  chart)          │         │                    │
        └──────┬───────┘               └──────────────────┘         └─────────┬──────────┘
               │ SMMA crossover detected                                     │
               ▼                                                            │
        ┌────────────────┐                                                  │
        │ trade_         │                                                  │
        │ tracker.py     │ open / close                                     │
        │                │──────────────┐                                   │
        └────┬───────────┘              │                                   │
             │ writes                   ▼                                   │
             │                   ┌──────────────┐                          │
             │                   │ trade_log.csv│                          │
             │                   └──────┬───────┘                          │
             │                          │ read on Refresh                  │
             │                          ▼                                  │
             │                   ┌──────────────┐                          │
             │                   │ analytics.py │                          │
             │                   │ train_all()  │                          │
             │                   │ cross_valid()│                          │
             │                   └──────┬───────┘                          │
             │                          │ saves                            │
             │                          ▼                                  │
             │                   ┌──────────────┐                          │
             │                   │ signal_      │◀─────────────────────────┘
             │                   │ model.pkl    │  loaded on app start
             │                   └──────────────┘
             │
             │ "new crossover + AI verdict"
             ▼
      ┌──────────────┐
      │ shared.py    │
      │ signals bus  │──▶ ai_signals_page.py
      │              │──▶ trade_log_page.py
      └──────────────┘
```

---

## Threading model

| Thread | Owned by | Purpose |
|--------|----------|---------|
| Main (UI) | Tk | All widget updates |
| Mock feed | `websocket_client` (daemon) | Emits a tick per symbol per second |
| Live feed (websocket) | `websocket_client` (daemon) | Receives ticks from Angel One |
| ML refresh | `ml_stats_page` (daemon) | Trains the model in the background |
| ML lazy tab populate | `ml_stats_page` (daemon) | CV + learning curve on first tab visit |

All background work goes through `pages.background.run_in_background`
which registers the thread with a `WorkerTracker` and ensures
exceptions are logged (not silently swallowed).

The ML page uses a **queue** for cross-thread UI updates because
`self.after()` isn't thread-safe. The main thread drains the
queue every 50 ms via `_poll_ui_queue`.

---

## Module dependency graph (high-level)

```
                    app.py
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  pages/*        shared.py      websocket_client
        │              │              │
        ▼              ▼              ▼
    cards.py      theme.py       indicators.py
   theme_subscribe design.py
        │
        ▼
   pages/background  pages/figures
```

Top-level modules (`app.py`, `pages/`, `shared.py`,
`websocket_client.py`) are imported eagerly at startup. Heavy
modules (`analytics.py`, `ai_model.py`, `matplotlib`) are
lazy-imported on first use so the app starts in <100 ms.

---

## Where to add new features

| If you want to... | Edit |
|-------------------|------|
| Add a new sidebar page | Create `pages/new_page.py`, register it in `PAGES` tuple in `app.py` |
| Add a new metric | Add to `analytics.py:_train_single`, surface in `ml_stats_page.py` |
| Add a new chart | Use `pages.figures.create_figure_in_frame()` |
| Add a new screening filter | Add to `shared.settings.DEFAULTS` + a Spinbox row in `settings_page.py` |
| Change colour scheme | Edit `theme.py` light/dark palettes |
| Change spacing / fonts | Edit `design.py` constants |
| Add a new TOTP / auth flow | Edit `websocket_client._import_smartapi` or `_generate_totp_code` |
| Change training algorithm | Edit `analytics.ALGORITHMS` (must be a sklearn-compatible classifier) |

---

## Coding conventions

Established during the cleanup rounds:

* **Type hints** on all public functions in non-test code.
* **Formal docstrings** with `Parameters` / `Returns` sections
  on every public function.
* **Logging** instead of `print()` for any non-user-facing
  output.
* **Constants** extracted at the top of each module with
  uppercase names (`_AUTO_REFRESH_MS`, `_BG_PROFIT`, etc.).
* **Lazy imports** for heavy modules to keep startup time low.
* **Background work** in daemon threads via
  `pages.background.run_in_background`.
* **No global mutable state** except the shared state in
  `shared.py` (settings, alerts, signals, feed_ready, credentials)
  and the per-symbol state in `websocket_client.py:states`.

---

## Next step

You have the lay of the land. To run the app, go back to
**[03_RUN.md](03_RUN.md)**.
