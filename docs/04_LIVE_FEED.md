# 04 — Live Feed Setup (Angel One SmartAPI)

This document explains how to connect the app to your
**Angel One** trading account and stream real-time quotes
for all 100 Nifty symbols.

> **Time:** ~15 minutes (most of it is paperwork on
> the Angel One side).
> **Prerequisites:** completed [01_INSTALL.md](01_INSTALL.md) and
> [02_SETUP.md](02_SETUP.md).

---

## When you need this

Skip this document entirely if you'll only ever use the
**Mock Feed** (the app's built-in random-data generator for
testing the UI). The mock feed works without any external
service.

You need the live feed if:

* You want to screen **real** Nifty 100 prices.
* You want the model to train on **real** closed trades, not
  mock data.

---

## 1. Angel One account requirements

You need:

1. **An active Angel One trading account** with market data
   API access. Some account plans need explicit activation —
   check Angel One support if you're unsure.
2. **A TOTP authenticator** (Google Authenticator, Aegis,
   Authy, etc.) already configured for your Angel One login.
3. **A registered API key** from the Angel One developer
   dashboard.

### Register for an API key

1. Go to [smartapi.angelbroking.com](https://smartapi.angelbroking.com)
   and log in with your Angel One credentials.
2. Click **"Create App"** (or the equivalent button — the
   dashboard changes occasionally).
3. Fill in:
   * **App name** — anything, e.g. "NSE Screener"
   * **Redirect URL** — leave blank or use `http://localhost`
   * **Postback URL** — leave blank
4. Click **Create**.
5. The dashboard shows your new **API key**. Copy it — you'll
   need it in step 3 below.

> **Note:** the API key is per-app, not per-user. You only
> need to do this once.

---

## 2. Get your TOTP secret

The Angel One SDK needs your **TOTP secret** (the base32
string, not the 6-digit code). It's the long random string
behind the QR code you originally scanned when setting up
TOTP.

### If you still have access to the original QR

Open your authenticator app and find the entry for Angel One.
Most apps have a "Show secret" or "Export" option that
reveals the base32 string.

### If you lost the original QR

1. Log in to Angel One's web portal.
2. Go to **Settings → Security → Two-Factor Authentication**.
3. Click **"Reset 2FA"** and re-scan the new QR with your
   authenticator app.
4. **Crucially: copy the new TOTP secret** before scanning.
   Some apps reveal it in the manual-entry option — when you
   tap "Enter setup key" instead of "Scan QR code", the
   secret field is shown.

The secret looks like:

```
JBSWY3DPEHPK3PXP ABCDEFGH IJKLMNOP QRSTUVWX
```

(Without the spaces — those are just for readability.)

---

## 3. Install the live-feed packages

In your project folder, with the virtual environment active:

```bash
pip install smartapi-python websocket-client
```

(Optional but recommended for cleaner TOTP handling:)

```bash
pip install pyotp
```

The app falls back to a pure-stdlib TOTP implementation if
`pyotp` isn't installed, but `pyotp` is more reliable.

If you're building an `.exe` for clients, also uncomment the
three SDK lines in `requirements.txt` and re-install:

```bash
pip install -r requirements.txt
```

---

## 4. Connect in the app

1. Start the app: `python app.py`
2. On the Login page, click **"Show technical details ▾"**
   to expand the credential form.
3. Fill in:
   * **API Key** — from step 1 above
   * **Client Code** — your Angel One login ID (e.g.
     `A12345678`)
   * **Password** — your Angel One login password
   * **TOTP Secret** — the base32 string from step 2
4. Click **"Connect to Angel One"** (the big purple button
   at the top of the page).

The status line shows progress:

```
Connecting to Angel One…
```

Then one of:

* **`✓ Connected to live feed.`** — success. The sidebar
  unlocks.
* **`Live feed unavailable — see Alerts page for details.`**
  — an error occurred. Open the **Alerts** page for the full
  message.

---

## 5. Market hours

The live feed only emits ticks during NSE market hours:

| Session | Time (IST) |
|---------|-----------|
| Pre-open | 09:00 – 09:15 |
| Normal | 09:15 – 15:30 |
| Closing auction | 15:40 – 16:00 |

Outside these hours, the websocket connects but no ticks
arrive. The Debug Log page will show "WebSocket closed" or
"Ticks: 0".

> **Tip:** use `python check_requirements.py` to see the
> current IST time and whether the market is open.

---

## 6. Common live-feed errors and fixes

### `No module named 'SmartConnect'`

You haven't installed the SDK in the right environment.

```bash
# Make sure the venv is active
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install smartapi-python
```

### `Login failed: Invalid Token`

Either the TOTP secret is wrong, or it was copied with stray
spaces. Re-copy from your authenticator app — make sure
there are **no leading or trailing spaces**.

### `Login failed: Invalid credentials`

The client code or password is wrong. The client code is
case-sensitive and matches your Angel One login ID exactly.

### `TOTP secret is not valid base32`

The secret has non-base32 characters (only `A-Z` and `2-7` are
valid). Re-copy from your authenticator app.

### `SmartWebSocketV2 class not found in this SDK version`

The SDK version is too old.

```bash
pip install --upgrade smartapi-python
```

### `Could not download scrip master`

The Angel One scrip master file is unreachable. Check:

* Your internet connection
* Whether a corporate firewall is blocking
  `margincalculator.angelone.in`

### `WebSocket connect() failed`

Common causes:

* Market is closed (see market hours above)
* Your IP isn't allowlisted (rare)
* Angel One servers are temporarily down — try again in 5
  minutes

### Subscribed but no ticks arriving

The Debug Log page will show `Ticks: 0` and the `Last tick`
age will grow. Check:

* **Market is open** (see above)
* The subscription message went through — look for
  `Subscribed batch 0 (50 tokens) via attempt 1` in the
  Debug Log
* Angel One hasn't throttled you — if you've opened multiple
  feeds from the same API key, only the first one gets data

---

## 7. Where to find the TOTP secret in popular apps

### Google Authenticator

1. Open the app, find your Angel One entry.
2. Tap the entry → tap the **pencil icon** (or three dots
   → "Edit").
3. Some versions show "Show secret". If not, the secret is
   not recoverable from Google Authenticator — you need to
   reset 2FA on Angel One's website.

### Aegis (Android, open-source)

1. Open the app, find your Angel One entry.
2. Tap the entry → tap the **pencil icon**.
3. The secret is shown as a base32 string under "Secret".

### Authy

1. Open the app, find your Angel One entry.
2. Tap the entry.
3. The secret is shown as a base32 string under "Secret
   key" or similar.

### 1Password / Bitwarden

Both store TOTP secrets internally for auto-fill. The secret
is usually under the entry's "OTP" or "Two-factor" section.

---

## 8. Disconnecting

There's no "disconnect" button — to switch back to mock:

1. Close the app.
2. Reopen it.
3. Click **"Use Mock Feed"** instead of "Connect to Angel
   One".

The live feed thread is a daemon — it stops when the window
closes.

---

## Next step

For building the Windows `.exe`, continue to
**[05_BUILD_EXE.md](05_BUILD_EXE.md)**.
