# NSE Screening App — Complete Instructions

**Welcome.** This is the master entry point for everyone who needs
to install, run, or distribute the NSE Screening app.

Read the documents in order if this is your first time. Jump to
the section you need if you've done this before.

---

## Who this is for

This documentation set supports three audiences:

1. **End users** — want to run the app on their own machine.
2. **Developers** — want to modify the code or train new models.
3. **Distributors** — want to package the app as a `.exe` and
   ship it to clients.

---

## Table of contents (read in order)

| # | Document | Who needs it | Time |
|---|----------|--------------|------|
| 1 | [Install](docs/01_INSTALL.md) | Everyone | 10 min |
| 2 | [Setup](docs/02_SETUP.md) | Everyone | 5 min |
| 3 | [Run](docs/03_RUN.md) | End users + developers | 5 min |
| 4 | [Live Feed](docs/04_LIVE_FEED.md) | Live-feed users only | 15 min |
| 5 | [Build EXE](docs/05_BUILD_EXE.md) | Distributors | 15 min |
| 6 | [Deploy](docs/06_DEPLOY.md) | Distributors | 5 min |
| 7 | [Troubleshooting](docs/07_TROUBLESHOOTING.md) | As needed | — |
| 8 | [Project Structure](docs/08_PROJECT_STRUCTURE.md) | Developers | 10 min |

---

## TL;DR — three commands

If you've done this before, here's the whole thing:

```bash
# 1. Install Python 3.9+ from https://www.python.org/downloads/

# 2. Set up the project
git clone <repo-url> nse-screening
cd nse-screening
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 3. Run
python app.py
```

For the Windows `.exe`:

```bat
build.bat                       REM one-folder build (recommended)
set ONE_FILE=1 && build.bat     REM single-file build
set BUILD_VERSION=1.0.0 && build.bat   REM version-stamped build
```

That's it. See the linked documents for details.

---

## What the app does

The NSE Screening app is a desktop tool for Indian stock market
traders. It:

* Streams live quotes for all **Nifty 100** symbols via the
  Angel One SmartAPI feed (or a built-in mock feed).
* Computes **SMMA crossovers** (fast vs slow smoothed moving
  averages) and surfaces every fresh crossover as a candidate
  trade entry.
* Trains an **ML filter** (Logistic Regression + Random Forest)
  on the user's own closed trades to ACCEPT or AVOID each
  signal.
* Visualises the model with **confusion matrices, ROC curves,
  calibration plots, and an economic backtest** — so the user
  knows whether the AI actually adds value.
* Logs every decision in `trade_log.csv` for the model to learn
  from over time.

---

## System requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | Windows 10, macOS 11, or Ubuntu 20.04 | Windows 11 / macOS 13 |
| Python | 3.9 | 3.11 |
| RAM | 4 GB | 8 GB |
| Disk | 500 MB | 2 GB (for the build artefacts) |
| Internet | Required for live feed | Required |
| Display | 1024×640 minimum | 1920×1080 |

---

## Next step

Continue to **[01_INSTALL.md](docs/01_INSTALL.md)** to set up
Python and the development environment.
