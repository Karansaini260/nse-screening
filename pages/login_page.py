"""
Page 1 — Login / Configuration. Polished, friendly entry screen.

Design:
  * Branded splash header — app name, tagline, accent bar
  * Big "Connect to Angel One" button as the primary CTA
  * A collapsible "Technical details" disclosure for the four
    credential fields (API key, client code, password, TOTP secret)
    so non-technical users see a single friendly button first
  * "Use mock feed" as a secondary action for trying the UI

All credentials are still kept in memory only — nothing is written
to disk.
"""

import threading
import tkinter as tk
from tkinter import ttk

import websocket_client as wsc
from design import (
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL,
    FONT_BODY, FONT_SUBTITLE, FONT_SMALL,
)
from shared import alerts, settings, credentials


# Hardcoded for now — extend if you wire up multiple brokers later.
BROKERS = ["Angel One"]


class LoginPage(ttk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, padding=SPACE_2XL)
        self.on_success = on_success

        # --- Branded header -------------------------------------------
        # Two-tone header: app name in the brand accent + tagline.
        # Visually signals "this is a product, not a config screen".
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, SPACE_2XL))
        ttk.Label(
            header, text="NSE Screener",
            font=("Segoe UI", 28, "bold"),
            foreground="#4f46e5",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Real-time Nifty 100 screening with SMMA crossovers and an AI filter",
            font=FONT_SUBTITLE, foreground="gray",
        ).pack(anchor="w", pady=(SPACE_XS, 0))

        # --- Pre-flight check -----------------------------------------
        # Friendly notice if the Angel One SDK isn't installed yet.
        self.sdk_warning = self._check_sdk_installed()
        if self.sdk_warning:
            warn = ttk.Frame(self, padding=(SPACE_MD, SPACE_MD))
            ttk.Label(
                warn, text=self.sdk_warning, foreground="#d97706",
                font=FONT_BODY, wraplength=520, justify="left",
            ).pack(anchor="w")
            warn.pack(fill="x", pady=(0, SPACE_LG))

        # --- Big primary CTA ------------------------------------------
        cta = ttk.Frame(self)
        cta.pack(fill="x", pady=(0, SPACE_MD))
        ttk.Button(
            cta, text="Connect to Angel One",
            style="Accent.TButton",
            command=self._on_connect_clicked,
        ).pack(side="left", ipadx=SPACE_LG, ipady=SPACE_SM)
        ttk.Button(
            cta, text="Use Mock Feed",
            command=self.connect_mock,
        ).pack(side="left", padx=(SPACE_MD, 0), ipady=SPACE_SM)

        ttk.Label(
            self,
            text="Mock feed generates random ticks for all 100 symbols — no broker required.",
            font=FONT_SMALL, foreground="gray",
        ).pack(anchor="w", pady=(0, SPACE_LG))

        # --- Status line ----------------------------------------------
        self.status_var = tk.StringVar(value="")
        self.status_lbl = ttk.Label(
            self, textvariable=self.status_var, font=FONT_BODY,
        )
        self.status_lbl.pack(anchor="w", pady=(0, SPACE_MD))

        # --- Technical details disclosure -----------------------------
        # A collapsible section that holds the four credential
        # inputs. Hidden by default so non-technical users see a
        # friendly "Connect" button first.
        self.tech_visible = tk.BooleanVar(value=False)
        self._tech_toggle_btn = ttk.Button(
            self, text="Show technical details ▾",
            command=self._toggle_tech,
        )
        self._tech_toggle_btn.pack(anchor="w", pady=(SPACE_LG, 0))

        self._tech_frame = ttk.Frame(self)
        # Built lazily so it doesn't take up vertical space when hidden.
        self._tech_built = False

        # --- Privacy notice -------------------------------------------
        ttk.Label(
            self,
            text="🔒 Credentials are kept in memory only — they are not saved to disk "
                 "and disappear when the app closes.",
            font=FONT_SMALL, foreground="gray", wraplength=560, justify="left",
        ).pack(anchor="w", pady=(SPACE_XL, 0))

    # ------------------------------------------------------------------ tech panel

    def _toggle_tech(self):
        if self.tech_visible.get():
            self.tech_visible.set(False)
            self._tech_frame.pack_forget()
            self._tech_toggle_btn.configure(text="Show technical details ▾")
        else:
            self.tech_visible.set(True)
            if not self._tech_built:
                self._build_tech_form()
            self._tech_frame.pack(fill="x", pady=(SPACE_SM, SPACE_LG), anchor="w")
            self._tech_toggle_btn.configure(text="Hide technical details ▴")

    def _build_tech_form(self):
        """Build the four credential input fields + Broker dropdown.
        Lazy — only created if the user clicks 'Show technical details'."""
        self._tech_built = True
        form = self._tech_frame

        # Broker + 4 credential rows in a tight grid.
        self.var_broker = tk.StringVar(value=BROKERS[0])
        self.var_api    = tk.StringVar()
        self.var_secret = tk.StringVar()  # client code
        self.var_pwd    = tk.StringVar()
        self.var_totp   = tk.StringVar()

        rows = [
            ("Broker",       self.var_broker,  "combobox"),
            ("API Key",      self.var_api,     "entry"),
            ("Client Code",  self.var_secret,  "entry"),
            ("Password",     self.var_pwd,     "password"),
            ("TOTP Secret",  self.var_totp,    "entry"),
        ]
        for i, (label, var, kind) in enumerate(rows):
            ttk.Label(form, text=label, width=14, anchor="e"
                      ).grid(row=i, column=0, padx=(0, SPACE_MD), pady=3, sticky="e")
            if kind == "combobox":
                w = ttk.Combobox(form, textvariable=var, values=BROKERS,
                                 state="readonly", width=40)
            else:
                show = "*" if kind == "password" else None
                w = ttk.Entry(form, textvariable=var, width=44, show=show)
            w.grid(row=i, column=1, pady=3, sticky="w")
            # Help text under each field.
            helps = {
                "Broker":       "Your broker. Only Angel One supported today.",
                "API Key":      "From the Angel One developer dashboard.",
                "Client Code":  "Your Angel One client / user ID.",
                "Password":     "Your Angel One login password.",
                "TOTP Secret":  "The base32 string from your authenticator app QR code.",
            }
            ttk.Label(form, text=helps.get(label, ""), font=FONT_SMALL,
                      foreground="gray"
                      ).grid(row=i, column=2, padx=(SPACE_MD, 0), sticky="w")

        # Hint about clicking "Connect to Angel One" at the top.
        ttk.Label(form,
                  text="After filling these in, click 'Connect to Angel One' at the top.",
                  font=FONT_SMALL, foreground="gray"
                  ).grid(row=len(rows), column=0, columnspan=3,
                         sticky="w", pady=(SPACE_MD, 0))

    # ------------------------------------------------------------------ helpers

    def _check_sdk_installed(self):
        """Return a user-friendly warning string if the SDK isn't
        importable, or None if everything's good. This catches the
        'pip install smartapi-python' case before the user wastes
        time filling in credentials."""
        for path in ("SmartApi", "SmartApi.SmartConnect", "SmartConnect"):
            try:
                __import__(path)
                return None
            except ImportError:
                continue
        return (
            "⚠ To use the live feed, install these once in your terminal:\n"
            "      pip install smartapi-python websocket-client logzero\n"
            "Then restart the app. The mock feed works without them."
        )

    def _gather_credentials(self):
        return {
            "api_key":     self.var_api.get().strip(),
            "client_code": self.var_secret.get().strip(),
            "password":    self.var_pwd.get().strip(),
            "totp_secret": self.var_totp.get().strip(),
        }

    def _validate(self, creds):
        missing = []
        if not creds["api_key"]:     missing.append("API Key")
        if not creds["client_code"]: missing.append("Client Code")
        if not creds["password"]:    missing.append("Password")
        if not creds["totp_secret"]: missing.append("TOTP Secret")
        return missing

    def _set_status(self, text, color=None):
        """Set the status line. Color is a palette key; we resolve
        it to a real RGB so the message stays readable in both
        themes."""
        from theme import current_palette
        palette = current_palette(bool(settings.dark_mode))
        if color is None:
            color = "fg"
        self.status_var.set(text)
        try:
            self.status_lbl.configure(foreground=palette.get(color, palette["fg"]))
        except Exception:
            pass

    def _on_connect_clicked(self):
        """Big primary button handler. If the tech form is visible
        and filled, use those values; otherwise prompt the user to
        expand the disclosure first."""
        # If the tech form hasn't been built or any field is empty,
        # open the disclosure so the user sees what to fill in.
        if not self._tech_built:
            self._toggle_tech()
            self._set_status("Fill in your Angel One credentials below, then click Connect again.",
                             "warn")
            return
        creds = self._gather_credentials()
        missing = self._validate(creds)
        if missing:
            self._set_status(f"Missing: {', '.join(missing)}", "warn")
            return
        self.connect_live(creds)

    def _latest_feed_error(self):
        for a in reversed(alerts.all()):
            if a.kind == "FEED":
                return a.message
        return None

    # ------------------------------------------------------------------ actions

    def connect_live(self, creds=None):
        if creds is None:
            creds = self._gather_credentials()
            missing = self._validate(creds)
            if missing:
                self._set_status(f"Missing: {', '.join(missing)}", "warn")
                return

        credentials.update(creds)
        self._set_status("Connecting to Angel One…", "muted")
        self.update_idletasks()

        wsc.start_live_feed(
            api_key=creds["api_key"],
            client_code=creds["client_code"],
            password=creds["password"],
            totp_secret=creds["totp_secret"],
        )

        if wsc.LIVE_FEED_AVAILABLE:
            self._set_status("✓ Connected to live feed.", "up")
            alerts.push("—", "LOGIN", "Connected to Angel One live feed.")
            self.on_success()
        else:
            err = self._latest_feed_error() or "Live feed unavailable — see Alerts page for details."
            self._set_status(err, "down")

    def connect_mock(self):
        """Start (or restart) the mock feed and unlock the app.

        Side effect: any running mock thread is stopped and the
        per-symbol state is reset before the new thread starts. This
        means every click of "Use Mock Feed" gives a clean run —
        no carry-over values from a previous session.

        We synchronously run the pre-population phase so the
        dashboard shows realistic data the instant the page appears
        (otherwise the user sees 100 rows of ₹0 for ~0.5s while the
        background thread warms up).
        """
        # Stop any old mock thread and clear state.
        wsc.stop_mock_feed()
        wsc.reset_states()
        self._set_status("Starting mock feed…", "muted")
        self.update_idletasks()

        # Run the pre-population phase IN-LINE so the dashboard has
        # data the moment we navigate to it. Then start the steady-
        # state loop on a background thread. This is the same logic
        # as mock_data_thread() but split across two calls so we can
        # do the first half synchronously.
        wsc.mock_pre_populate()

        if not any(t.name == "mock" for t in threading.enumerate()):
            t = threading.Thread(target=wsc.mock_steady_state, name="mock", daemon=True)
            t.start()
        self._set_status("✓ Mock feed running with realistic prices.", "up")
        alerts.push("—", "FEED", "Mock feed started (realistic seed prices).")
        # Broadcast a 'feed ready' signal so any page that's already
        # been constructed (e.g. the dashboard) can refresh
        # IMMEDIATELY instead of waiting for the next 1-second tick.
        # The previous version showed an empty table for ~1-2s
        # because the auto-refresh had to fire first.
        try:
            from shared import feed_ready
            feed_ready.broadcast()
        except Exception:
            pass
        self.on_success()
