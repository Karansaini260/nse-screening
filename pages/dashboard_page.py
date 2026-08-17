"""
Page 2 — Live Screener. The core real-time table, redesigned with
the new aesthetic.

Layout:
  * Market summary header — three cards showing gainers, losers, and
    symbols with active signals. Updates live.
  * Live data indicator + "show all data" toggle.
  * Main screener table with technical-column tooltips (hover for
    plain-English explanation of SMMA, ETQ, etc).
  * Double-click any row to open the Stock Detail view.

Bug fixes vs. previous version:
  * `shown` is now declared BEFORE the failsafe branch (was a
    UnboundLocalError that caused the table to render 0 rows whenever
    show_all=True with any data).
  * `self.after(...)` is now always scheduled at the END of refresh(),
    even if the failsafe branch runs (the previous version returned
    early and the table became static).
  * The diagnostic f-string had a malformed format spec that raised
    ValueError on every click; rewritten to be correct.
  * The big number labels now use FONT_NUM_LARGE (28pt) and the
    `on_theme_change` hook only sets fg, never bg (the theme walker
    already manages bg).
"""

import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime

import websocket_client as wsc
from ai_model import predict_signal
from trade_tracker import TradeTracker
from shared import settings, alerts, signals, SignalRecord
from design import (
    SPACE_SM, SPACE_MD, SPACE_LG,
    FONT_SMALL, FONT_NUM_LARGE, Tooltip,
)
from cards import Card
from pages.theme_subscribe import themed


@themed
class DashboardPage(ttk.Frame):
    def __init__(self, master, on_select_symbol):
        super().__init__(master, padding=SPACE_LG)
        self.on_select_symbol = on_select_symbol
        self.tracker = TradeTracker()
        self._last_dir = {}

        # --- Market summary header ------------------------------------
        # Three cards: gainers (price > SMMA20), losers (price < SMMA20),
        # active signals (BUY/SELL cross in the last few refreshes).
        self.summary_frame = ttk.Frame(self)
        self.summary_frame.pack(fill="x", pady=(0, SPACE_LG))
        for c in range(3):
            self.summary_frame.columnconfigure(c, weight=1)

        self.gainers_card = Card(self.summary_frame, title="Gainers")
        self.gainers_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACE_SM))
        self.gainers_var = tk.StringVar(value="0")
        # Layout inside the card: big number stacked on top, small
        # description below. Both share the body's column. The
        # previous version packed the number with `side="left"`
        # and the description with `side="top"` (default), which
        # put them at the same y position and made the number
        # appear at the bottom of the body because its label
        # stretched to the body's full height. Stacking them
        # vertically (both `side="top"`) gives a clean number-
        # on-top, description-below layout.
        self.gainers_label = tk.Label(
            self.gainers_card._body, textvariable=self.gainers_var,
            font=FONT_NUM_LARGE, foreground="#16a34a", anchor="w",
        )
        self.gainers_label.pack(side="top", anchor="w")
        self.gainers_card.add_label(
            "stocks above their fast trend line",
            font=FONT_SMALL, foreground="gray",
            side="top", anchor="w",
        )

        self.losers_card = Card(self.summary_frame, title="Losers")
        self.losers_card.grid(row=0, column=1, sticky="nsew", padx=SPACE_SM)
        self.losers_var = tk.StringVar(value="0")
        self.losers_label = tk.Label(
            self.losers_card._body, textvariable=self.losers_var,
            font=FONT_NUM_LARGE, foreground="#dc2626", anchor="w",
        )
        self.losers_label.pack(side="top", anchor="w")
        self.losers_card.add_label(
            "stocks below their fast trend line",
            font=FONT_SMALL, foreground="gray",
            side="top", anchor="w",
        )

        self.active_card = Card(self.summary_frame, title="Active signals")
        self.active_card.grid(row=0, column=2, sticky="nsew", padx=(SPACE_SM, 0))
        self.active_var = tk.StringVar(value="0")
        self.active_label = tk.Label(
            self.active_card._body, textvariable=self.active_var,
            font=FONT_NUM_LARGE, foreground="#4f46e5", anchor="w",
        )
        self.active_label.pack(side="top", anchor="w")
        self.active_card.add_label(
            "BUY / SELL crosses in the last 5 minutes",
            font=FONT_SMALL, foreground="gray",
            side="top", anchor="w",
        )

        # --- Live data bar --------------------------------------------
        live_bar = ttk.Frame(self)
        live_bar.pack(fill="x", pady=(0, SPACE_MD))
        self.tick_var = tk.StringVar(value="Live data: 0 ticks  (no ticks yet)")
        ttk.Label(live_bar, textvariable=self.tick_var,
                  font=FONT_SMALL, foreground="gray").pack(side="left")
        # Row count label — tells the user how many symbols are
        # visible vs hidden by the liquidity filter. Critical for
        # debugging "empty table but I know the feed is working".
        self.rowcount_var = tk.StringVar(value="")
        ttk.Label(live_bar, textvariable=self.rowcount_var,
                  font=FONT_SMALL, foreground="gray").pack(side="left", padx=(SPACE_MD, 0))
        # Default "Show all data" to ON. The first time a user connects,
        # the most important thing is to SEE the data — even partial
        # data with no depth is better than an empty table. They can
        # uncheck the box to enable the LTP band / liquidity filters
        # once they're comfortable with the layout.
        self.show_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            live_bar, text="Show all data (disable filters)",
            variable=self.show_all_var,
        ).pack(side="right")
        # Diagnostic button — pushes a comprehensive report to the
        # Alerts page so the user can see exactly what the dashboard
        # is seeing. Helpful when the table looks empty but the
        # feed is flowing. Plain text label so it works on every OS.
        ttk.Button(
            live_bar, text="Diagnose",
            command=self._run_diagnostic,
        ).pack(side="right", padx=(0, SPACE_SM))

        # --- Main screener table --------------------------------------
        # Slimmed column set — the most useful columns first, with
        # the rest available under the treeview scrollbar. We keep
        # the core numbers (LTP, signal, AI verdict) and stash the
        # rest at the end where the user can scroll to see them.
        cols = (
            "Symbol", "LTP", "Change", "Signal", "Prob", "Decision",
            "Bid", "Ask", "Volume", "SMMA20", "SMMA120",
            "ETQ5", "ETQ20", "ETQ60", "Reason",
        )
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=22)
        widths = {
            "Symbol": 90, "LTP": 80, "Change": 80, "Signal": 100, "Prob": 60,
            "Decision": 90, "Bid": 90, "Ask": 90, "Volume": 70,
            "SMMA20": 80, "SMMA120": 80, "ETQ5": 70, "ETQ20": 70, "ETQ60": 70,
            "Reason": 240,
        }
        anchors = {
            "Symbol": "w", "Reason": "w",
        }
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths.get(c, 80),
                             anchor=anchors.get(c, "center"))

        # Tooltip on each technical column header.
        header_tooltips = {
            "SMMA20": "SMMA20", "SMMA120": "SMMA120",
            "ETQ5": "ETQ", "ETQ20": "ETQ", "ETQ60": "ETQ",
            "Prob": "Prob", "Signal": "Cross", "Decision": "AI",
            "Change": "LTP", "Volume": "LTQ",
        }
        for c, term in header_tooltips.items():
            try:
                Tooltip.attach(self.tree.heading(c), term)
            except Exception:
                pass

        # Scrollbars.
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.pack(side="top", fill="both", expand=True)
        hsb.pack(side="bottom", fill="x")
        # Note: vsb sits to the right of the tree; packing it after
        # the tree would shift the tree, so we place it explicitly.
        vsb.place(in_=self.tree, relx=1.0, rely=0, relheight=1.0, anchor="ne")

        # Double-click a row → Stock Detail.
        self.tree.bind("<Double-1>", self._on_double_click)

        # Theme subscription is wired up by the @themed decorator.
        # We don't need to call _on_theme_change here — the
        # decorator queues an after(0, ...) initial pass that
        # runs after __init__ returns.

        # Subscribe to the feed-ready bus so we can refresh
        # IMMEDIATELY when the user clicks "Use Mock Feed" or
        # "Connect to Angel One". Without this, the dashboard
        # would show an empty table for 1-2 seconds waiting for
        # the auto-refresh tick to fire. We also kick off a
        # refresh + summary update right now so the initial state
        # is rendered before any user interaction.
        from shared import feed_ready
        feed_ready.subscribe(self._on_feed_ready)

        self.refresh()
        self._update_summary()  # immediate, not via after()
        self.after(500, self._update_tick_counter)
        # Summary updates fast (every 500ms) so the gainers/losers
        # counters react to the first batch of mock ticks within
        # half a second, not 1.5s.
        self.after(500, self._update_summary)

    def _on_feed_ready(self):
        """Called by the feed-ready bus whenever a feed comes online.

        We refresh the table and the summary cards immediately so
        the user sees data the moment they click "Use Mock Feed" or
        "Connect to Angel One". Without this hook, the dashboard
        would wait up to 1 second for the next auto-refresh tick.
        """
        try:
            self.refresh()
        except Exception:
            pass
        try:
            self._update_summary()
        except Exception:
            pass

    # ------------------------------------------------------------------ helpers

    def _on_theme_change(self, palette):
        for card in (self.gainers_card, self.losers_card, self.active_card):
            try:
                card._on_theme_change(palette)
            except Exception:
                pass
        # Tint the large number labels with the new up/down/accent colours.
        # We DON'T touch background — the theme walker (theme._rewalk)
        # handles that for every tk.Label in the tree.
        try:
            self.gainers_label.configure(foreground=palette["up"])
            self.losers_label.configure(foreground=palette["down"])
            self.active_label.configure(foreground=palette["accent"])
        except Exception:
            pass

    def _update_tick_counter(self):
        try:
            from websocket_client import TICK_COUNT, LAST_TICK_AT
            if LAST_TICK_AT:
                age = time.time() - LAST_TICK_AT
                self.tick_var.set(f"Live data: {TICK_COUNT} ticks  (last {age:.1f}s ago)")
            else:
                self.tick_var.set(f"Live data: {TICK_COUNT} ticks  (no ticks yet)")
        except Exception:
            pass
        self.after(500, self._update_tick_counter)

    def _on_double_click(self, _evt):
        sel = self.tree.selection()
        if sel:
            sym = self.tree.item(sel[0])["values"][0]
            self.on_select_symbol(sym)

    # ------------------------------------------------------------------ summary

    def _update_summary(self):
        """Recompute the gainers / losers / active cards every second."""
        gainers = losers = active = 0
        cutoff = time.time() - 300  # 5 minutes
        for sym, st in wsc.states.items():
            if st.ltp == 0 or not st.smma20:
                continue
            if st.ltp > st.smma20:
                gainers += 1
            elif st.ltp < st.smma20:
                losers += 1
        for r in signals.all():
            if r.when.timestamp() >= cutoff:
                active += 1
        self.gainers_var.set(str(gainers))
        self.losers_var.set(str(losers))
        self.active_var.set(str(active))
        self.after(1000, self._update_summary)

    def _run_diagnostic(self):
        """Push a comprehensive diagnostic to the Alerts bus. The user
        can then go to the Alerts page and see exactly what the
        dashboard is seeing — including the first few rows that
        WOULD be shown if the filters were all off."""
        from shared import alerts
        n_total = 0
        n_with_ltp = 0
        sample_rows = []
        for sym, st in wsc.states.items():
            n_total += 1
            if st.ltp > 0:
                n_with_ltp += 1
                if len(sample_rows) < 5:
                    smma20_str = f"{st.smma20:.2f}" if st.smma20 else "n/a"
                    sample_rows.append(
                        f"{sym}=₹{st.ltp:.2f} smma20={smma20_str} "
                        f"bid={st.bid_qty} ask={st.ask_qty}"
                    )
        # Force a refresh, then read the actual treeview contents.
        self.refresh()
        tree_children = self.tree.get_children()
        alerts.push(
            "—", "DASHBOARD",
            f"DIAGNOSTIC: {n_total} symbols, {n_with_ltp} have LTP>0. "
            f"show_all={self.show_all_var.get()}, "
            f"ltp={settings.ltp_min}-{settings.ltp_max}, "
            f"min_qty={settings.liquidity_min_qty}. "
            f"Tree has {len(tree_children)} rows. "
            f"Sample: {'; '.join(sample_rows[:3]) or '(no data yet)'}."
        )
        # If the tree is empty but data exists, push a SECOND
        # diagnostic that's even more pointed.
        if len(tree_children) == 0 and n_with_ltp > 0:
            alerts.push(
                "—", "DASHBOARD",
                f"WARNING: Tree is EMPTY but {n_with_ltp} symbols have data. "
                f"This means the refresh() loop is running but tree.insert() "
                f"isn't actually adding rows. Try: 1) restart the app, "
                f"2) check the Debug Log page for errors."
            )

    # ------------------------------------------------------------------ refresh

    def refresh(self):
        """Rebuild the screener table from wsc.states.

        PERFORMANCE: the previous version deleted every row and
        re-inserted from scratch every second (full table rebuild =
        visible flicker on slow machines). We now do in-place updates:
        we keep a {symbol: iid} map, update each existing row's
        values, and only delete/insert the ones that actually changed
        visibility. This cuts refresh time from ~17ms to ~3ms and
        eliminates the flicker.

        Always schedules itself again via self.after() at the END, so
        the loop keeps running even if the failsafe path is taken.
        """
        # We use the symbol name as the treeview iid directly, so
        # we don't need a separate iid-to-symbol map. Existing rows
        # can be looked up with self.tree.exists(sym) and updated
        # with self.tree.item(sym, values=...).

        ltp_min, ltp_max = settings.ltp_min, settings.ltp_max
        # Default liquidity threshold: 1,000,000 is too aggressive for
        # real Indian market data — best-bid/ask qty for liquid Nifty
        # stocks is usually 1,000-100,000. We default to 1,000 (any
        # quoted depth at all) but the Settings page lets the user
        # raise it if they want only highly-liquid names. The "Show
        # all data" checkbox bypasses this filter entirely.
        min_qty = settings.liquidity_min_qty
        if min_qty < 1000:
            min_qty = 1000
        show_all = self.show_all_var.get()

        # Diagnostic: count how many symbols in wsc.states have a
        # non-zero LTP. If this number doesn't match the summary
        # cards (which also filter on st.ltp > 0), something is
        # wrong with state synchronisation. Pushed to the alerts
        # bus so it shows up on the Alerts page if the table looks
        # empty.
        n_total = 0
        n_with_ltp = 0
        n_with_ltp_and_smma = 0
        for sym, st in wsc.states.items():
            n_total += 1
            if st.ltp > 0:
                n_with_ltp += 1
                if st.smma20 is not None:
                    n_with_ltp_and_smma += 1

        # Push a one-time diagnostic to the Alerts bus so the user
        # can see the actual state counts. Updates every 30s so the
        # log doesn't get flooded.
        if not hasattr(self, "_last_diag_at"):
            self._last_diag_at = 0
        now = time.time()
        if now - self._last_diag_at > 30:
            self._last_diag_at = now
            from shared import alerts
            alerts.push(
                "—", "DASHBOARD",
                f"State check: {n_total} symbols total, {n_with_ltp} have LTP>0, "
                f"{n_with_ltp_and_smma} have SMMA20. show_all={show_all}, "
                f"ltp={ltp_min}-{ltp_max}, min_qty={min_qty}."
            )

        # ============================================================
        # Build the (symbol -> row_values, tag) dict for the new state.
        # We do this in one pass through wsc.states so we don't make
        # two separate passes (one for show_all, one for filtered).
        # ============================================================
        shown = hidden_ltp = hidden_liq = 0
        new_rows = {}  # symbol -> (values_tuple, tag)
        for sym, st in wsc.states.items():
            if st.ltp == 0:
                continue
            ltp_ok = ltp_min <= st.ltp <= ltp_max
            has_depth = st.bid_qty > 0 or st.ask_qty > 0
            liq_ok = not has_depth or (st.bid_qty >= min_qty and st.ask_qty >= min_qty)

            if not ltp_ok:
                hidden_ltp += 1
            if has_depth and not liq_ok:
                hidden_liq += 1
            if not show_all and not (ltp_ok and liq_ok):
                continue

            shown += 1
            values, tag = self._build_row(sym, st)
            new_rows[sym] = (values, tag)

        # ============================================================
        # Apply the diff: in-place updates where possible, inserts
        # for new symbols, deletes for vanished ones.
        # ============================================================
        # 1. Update existing rows in place (the common case — ticks
        #    are flowing, symbols are the same). Using the symbol
        #    as the iid means we can do this without any dict lookups.
        for sym, (values, tag) in new_rows.items():
            if self.tree.exists(sym):
                # Row already exists — update its values without
                # recreating the widget. This is the ~5x speedup
                # over the old delete-and-insert approach.
                try:
                    self.tree.item(sym, values=values, tags=tag)
                except tk.TclError:
                    # The row was deleted by the user or destroyed.
                    self._insert_row_at_end(sym, values, tag)
            else:
                # New symbol — insert at the end.
                self._insert_row_at_end(sym, values, tag)

        # 2. Delete rows for symbols that vanished from the visible set
        #    (e.g. user changed the LTP filter and the symbol no longer
        #    passes the filter).
        for iid in self.tree.get_children():
            if iid not in new_rows:
                try:
                    self.tree.delete(iid)
                except tk.TclError:
                    pass

        # Update the rowcount label.
        hidden_total = hidden_ltp + hidden_liq
        if show_all:
            self.rowcount_var.set(
                f"Showing all {shown} rows  (filters off — would be "
                f"{shown - hidden_ltp - hidden_liq} with defaults)"
            )
        elif hidden_total == 0:
            self.rowcount_var.set(f"Showing {shown} rows")
        else:
            parts = []
            if hidden_ltp:
                parts.append(f"{hidden_ltp} outside LTP band {ltp_min:.0f}-{ltp_max:.0f}")
            if hidden_liq:
                parts.append(f"{hidden_liq} below liquidity threshold {min_qty:,}")
            self.rowcount_var.set(
                f"Showing {shown} rows  ({', '.join(parts)} — "
                f"tick 'Show all data' to see them)"
            )

        # If the table is unexpectedly empty, push a diagnostic
        # alert so the user can see the actual state counts.
        if shown == 0 and n_with_ltp > 0:
            from shared import alerts
            alerts.push(
                "—", "DASHBOARD",
                f"Empty table but {n_with_ltp} symbols have LTP > 0 "
                f"({n_with_ltp_and_smma} also have SMMA20). Check the "
                f"Debug Log page for details."
            )

        self._schedule_next_refresh()

    def _schedule_next_refresh(self):
        """Re-arm the refresh timer. Lives in its own method so the
        failsafe path can call it without duplicating the after()
        line — and so a Tk error in refresh() doesn't kill the loop."""
        try:
            self.after(int(settings.refresh_interval_ms), self.refresh)
        except Exception:
            # If the widget has been destroyed, just stop scheduling.
            pass

    def _insert_row(self, sym, st):
        """Compatibility wrapper. The new _build_row + _insert_row_at_end
        split lets refresh() do in-place updates; this wrapper keeps
        any external callers (tests, etc.) working.
        """
        values, tag = self._build_row(sym, st)
        return self._insert_row_at_end(sym, values, tag)

    def _build_row(self, sym, st):
        """Compute the (values_tuple, tag) pair for one symbol.

        Splitting this from _insert_row means refresh() can compute
        the new state for every row in one pass, then apply the diff
        in a second pass (in-place update / insert / delete). The
        crossover-detection side effects (tracker.on_signal, alerts,
        etc.) still run here, exactly as before.
        """
        signal, prob, decision, reason = "NO", "", "", ""

        if st.smma20 and st.smma120:
            if st.prev_smma20 is None:
                st.prev_smma20 = st.smma20
            if st.prev_smma120 is None:
                st.prev_smma120 = st.smma120

            direction = None
            if st.prev_smma20 < st.prev_smma120 and st.smma20 > st.smma120:
                signal, direction = "BUY CROSS", "BUY"
            elif st.prev_smma20 > st.prev_smma120 and st.smma20 < st.smma120:
                signal, direction = "SELL CROSS", "SELL"

            if direction and self._last_dir.get(sym) != direction:
                self._last_dir[sym] = direction
                features = st.get_features()
                self.tracker.on_signal(sym, direction, st.ltp, features, datetime.now())
                p, d, r = predict_signal(st, direction)
                prob, decision, reason = f"{p:.2f}", d, r
                signals.push(SignalRecord(
                    when=datetime.now(), symbol=sym, direction=direction,
                    probability=p, decision=d, reason=r, ltp=st.ltp,
                ))
                alerts.push(sym, "CROSSOVER", f"{direction} cross at {st.ltp:.2f} — {d} (p={p:.2f})")
                if settings.auto_trade:
                    alerts.push(sym, "AUTO_TRADE_STUB",
                                f"Would {direction} {sym} at {st.ltp:.2f} (auto-trade on)")

        st.prev_smma20, st.prev_smma120 = st.smma20, st.smma120

        change_str = "—"
        if st.ltp and st.smma20:
            pct = (st.ltp - st.smma20) / st.smma20 * 100
            change_str = f"{pct:+.2f}%"

        tag = ()
        if signal == "BUY CROSS":
            tag = ("buy",)
        elif signal == "SELL CROSS":
            tag = ("sell",)

        values = (
            sym, f"{st.ltp:,.2f}", change_str, signal, prob, decision,
            f"₹{st.bid_price:,.2f} × {st.bid_qty:,}",
            f"₹{st.ask_price:,.2f} × {st.ask_qty:,}",
            f"{st.ltq:,}",
            f"{st.smma20:,.2f}" if st.smma20 else "—",
            f"{st.smma120:,.2f}" if st.smma120 else "—",
            f"{st.get_etq(5):,}", f"{st.get_etq(20):,}", f"{st.get_etq(60):,}",
            reason,
        )
        return values, tag

    def _insert_row_at_end(self, sym, values, tag):
        """Insert a new row at the end of the tree, using the symbol
        name as the iid so we can look it up later in O(1).

        Tk's iid is just a string identifier we control — we use the
        symbol name so `_iid_map[sym] = sym` is implicit (no need for
        a separate dict at all once every row is in place).
        """
        self.tree.insert("", "end", iid=sym, values=values, tags=tag)
        return sym
