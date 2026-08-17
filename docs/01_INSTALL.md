# 01 — Install Python and Required Tools

This document walks you through installing everything needed
to run or build the NSE Screening app.

> **Time:** ~10 minutes.

---

## 1. Install Python 3.9 or newer

The app needs **Python 3.9+**. Python 3.11 is recommended
(best balance of speed and library compatibility).

### Windows

1. Go to **[python.org/downloads](https://www.python.org/downloads/)**.
2. Download **Python 3.11.x** (or 3.9+ if 3.11 isn't available).
3. Run the installer.
4. **Important:** on the first screen, tick **"Add Python to PATH"**.
5. Click **"Install Now"**.
6. When the install finishes, click **"Disable path length limit"** if prompted.

Verify in a **new** Command Prompt window:

```bat
python --version
pip --version
```

You should see something like `Python 3.11.9` and `pip 24.0`.

### macOS

Easiest is via [Homebrew](https://brew.sh):

```bash
brew install python@3.11
```

Or download the universal installer from
[python.org](https://www.python.org/downloads/macos/).

Verify:

```bash
python3 --version
pip3 --version
```

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev python3-tk
```

`python3-tk` is required for the GUI. Verify:

```bash
python3 --version
python3 -c "import tkinter; print('tk OK')"
```

---

## 2. Install Git (optional, but recommended)

Git lets you clone the project and pull updates.

* **Windows / macOS:** [git-scm.com/downloads](https://git-scm.com/downloads)
* **Linux:** `sudo apt install git`

Verify:

```bash
git --version
```

---

## 3. Install a code editor (optional, for developers)

If you plan to modify the code, install a code editor:

* **[VS Code](https://code.visualstudio.com/)** (free, recommended)
* **[PyCharm Community](https://www.jetbrains.com/pycharm/)** (free)
* Any text editor

VS Code + the official Python extension gives you syntax
highlighting, debugging, and auto-complete for free.

---

## 4. About virtual environments

A **virtual environment** is an isolated Python install for one
project. It keeps the app's dependencies separate from your
system Python, so:

* You can use different package versions for different projects.
* `pip install` doesn't require admin rights.
* You can delete the project folder and start fresh without
  affecting anything else.

The NSE Screening app uses a virtual environment called `.venv/`
in the project root. The next document creates it.

---

## 5. Sanity check

Open a terminal and run:

```bash
python --version
pip --version
```

Both must print a version number. If you see
`'python' is not recognized as an internal or external command`
on Windows, Python wasn't added to PATH — re-run the installer
and tick the box.

---

## Next step

Continue to **[02_SETUP.md](02_SETUP.md)** to clone the project
and install the dependencies.
