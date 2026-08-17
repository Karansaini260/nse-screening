"""
Page 3 — Stock Detail. Beautiful single-symbol view.

Layout (top to bottom):
  * Header card — large symbol name, big LTP, % change, action chips
  * Chart card — candlestick/line chart with SMMA overlays
  * Stats grid — 6 small cards: Bid/Ask, Spread, Volume, ETQ, Day range
  * Market depth card — 5-level depth ladder
  * Real-time LTQ feed card

The page is built from `Card` widgets so the layout is consistent
with the rest of the app's design language.
"""

import collections
import tkinter as tk
from tkinter import ttk

import websocket_client as wsc
from design import (
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    FONT_BODY_BOLD, FONT_TITLE,
    FONT_NUM_LARGE, FONT_NUM_MED, FONT_SMALL, FONT_MONO,
    Tooltip,
)
from cards import Card, Chip
from pages.theme_subscribe import themed
from pages.figures import create_figure_in_frame


@themed
class DetailPage(ttk.Frame):
    def __init__(self, master, on_back):
        super().__init__(master, padding=SPACE_LG)
        self.on_back = on_back
        self.symbol = None
        # Ring buffer of (ltp, smma20, smma120) for the chart's
        # x-axis. We store SMMA values per-tick so the chart can
        # show all three lines without re-computing SMMA on every
        # render. Bounded so we don't grow without limit.
        self.series = collections.deque(maxlen=300)
        # Buffer for the most recent LTQ prints shown in the feed.
        self.prints = collections.deque(maxlen=15)

        # --- Scrollable container --------------------------------------
        # Use a Canvas + inner Frame so the page scrolls if the user's
        # window is short. This matters because the new design has
        # more vertical content (header card + stats grid + depth + feed).
        self.canvas_wrap = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canvas_wrap.pack(side="left", fill="both", expand=True)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                  command=self.canvas_wrap.yview)
        self.vsb.pack(side="right", fill="y")
        self.canvas_wrap.configure(yscrollcommand=self.vsb.set)

        self.inner = ttk.Frame(self.canvas_wrap, padding=0)
        self._win_id = self.canvas_wrap.create_window(
            (0, 0), window=self.inner, anchor="nw",
        )
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas_wrap.configure(
                scrollregion=self.canvas_wrap.bbox("all"),
            ),
        )
        self.canvas_wrap.bind(
            "<Configure>",
            lambda e: self.canvas_wrap.itemconfigure(self._win_id, width=e.width),
        )

        # Top bar: back button on the left, symbol title in the middle.
        # The title is a tk.Label (not ttk.Label) so we can set its
        # foreground explicitly to the palette's body colour. The
        # default ttk.Label foreground is theme-dependent and can be
        # grey-on-grey, making the title nearly invisible on dark
        # mode.
        p = self.palette()
        top_bar = ttk.Frame(self.inner)
        top_bar.pack(fill="x", pady=(0, SPACE_LG))
        ttk.Button(top_bar, text="← Back to Dashboard",
                   command=self.on_back).pack(side="left")
        self.title_var = tk.StringVar(value="Select a stock")
        self.title_label = tk.Label(
            top_bar, textvariable=self.title_var,
            font=FONT_TITLE, anchor="w",
            background=p["bg"], foreground=p["fg"],
        )
        self.title_label.pack(side="left", padx=SPACE_LG)

        # --- Header card: symbol + LTP + change + chips ---------------
        self.header_card = Card(self.inner, title="")
        self.header_card.pack(fill="x", pady=(0, SPACE_LG))
        self._build_header()

        # --- Chart card -----------------------------------------------
        # IMPORTANT: the chart card was previously packed with
        # `fill="both", expand=True` which made it consume all
        # remaining vertical space, pushing the stat grid and
        # depth card BELOW the visible window. We now use
        # `fill="x"` so the chart sizes to its preferred height
        # (set by min_height + the figure's figsize) and the
        # rest of the page (stats, depth) stays visible without
        # scrolling. The chart still fills the width of the page.
        self.chart_card = Card(self.inner, title="Price chart",
                               min_height=240)
        self.chart_card.pack(fill="x", pady=(0, SPACE_LG))
        self._build_chart()

        # --- Stats grid: 6 small cards in a 3x2 layout ---------------
        self.stats_grid = ttk.Frame(self.inner)
        self.stats_grid.pack(fill="x", pady=(0, SPACE_LG))
        self.stats_grid.columnconfigure(0, weight=1)
        self.stats_grid.columnconfigure(1, weight=1)
        self.stats_grid.columnconfigure(2, weight=1)
        self._build_stats_grid()

        # --- Depth + LTQ feed side by side ---------------------------
        # Both cards need MORE than the default 80px min_height
        # because the Market depth card shows 2 rows of values
        # (Best Bid/Ask + the values) plus a note, and the Recent
        # trades card shows up to 8 trade rows. The previous
        # default of 80px caused the values to be clipped at the
        # bottom of the card. 120px gives enough room for 2-3
        # value rows.
        bottom = ttk.Frame(self.inner)
        bottom.pack(fill="x", pady=(0, SPACE_LG))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        self.depth_card = Card(bottom, title="Market depth", min_height=120)
        self.depth_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACE_MD))
        self._build_depth()
        self.ltq_card = Card(bottom, title="Recent trades (LTQ)", min_height=120)
        self.ltq_card.grid(row=0, column=1, sticky="nsew", padx=(SPACE_MD, 0))
        self._build_ltq_feed()

        # Theme subscription is wired up by the @themed decorator.
        # We don't need to call _on_theme_change here — the
        # decorator queues an after(0, ...) initial pass that
        # runs after __init__ returns.

        # Kick off the per-tick update loop.
        self.after(500, self._tick)

    # ------------------------------------------------------------------ header

    def _build_header(self):
        """Build the LTP / change / chips header inside the card."""
        body = self.header_card._body
        # We use explicit background colours on every widget we
        # create here, pulled from the current palette. Without
        # this the labels inherit tk's default "SystemWindowText"
        # foreground (which is BLACK on Windows regardless of
        # theme), so they stay black on dark mode even after the
        # theme walker runs.
        p = self.palette()
        body.columnconfigure(0, weight=0)  # symbol column
        body.columnconfigure(1, weight=1)  # spacer
        body.columnconfigure(2, weight=0)  # LTP column

        # Symbol on the left. Use FONT_TITLE (14pt) instead of 28pt
        # so the header card doesn't take 280px of vertical space —
        # the previous 28pt version was visually impressive but
        # pushed the stat grid BELOW the visible window on a 900px
        # screen, hiding the Bid/Ask/Spread values.
        self.symbol_label = tk.Label(
            body, text="—", font=FONT_TITLE, anchor="w",
            background=p["panel_bg"], foreground=p["fg"],
        )
        self.symbol_label.grid(row=0, column=0, sticky="w", padx=(0, SPACE_XL))

        # LTP and % change stacked on the right.
        right = ttk.Frame(body)
        right.grid(row=0, column=2, sticky="e")
        self.ltp_var = tk.StringVar(value="—")
        # LTP in FONT_NUM_MED (14pt) instead of FONT_NUM_LARGE (28pt)
        # for the same reason as above — keeping the header
        # compact so the stat grid stays visible.
        self.ltp_label = tk.Label(
            right, textvariable=self.ltp_var, font=("Segoe UI", 18, "bold"), anchor="e",
            width=14,
            background=p["panel_bg"], foreground=p["fg"],
        )
        self.ltp_label.grid(row=0, column=0, sticky="e")
        self.change_var = tk.StringVar(value="—")
        self.change_label = tk.Label(
            right, textvariable=self.change_var, font=FONT_NUM_MED, anchor="e",
            width=14,
            background=p["panel_bg"], foreground=p["muted"],
        )
        self.change_label.grid(row=1, column=0, sticky="e")

        # Action chips row.
        chips = ttk.Frame(body)
        chips.grid(row=1, column=0, sticky="w", pady=(SPACE_MD, 0))
        self.signal_chip = Chip(chips, "NO SIGNAL", fg="neutral")
        self.signal_chip.pack(side="left", padx=(0, SPACE_SM))
        self.ai_chip = Chip(chips, "AI: —", fg="neutral")
        self.ai_chip.pack(side="left")

    # ------------------------------------------------------------------ chart

    def _build_chart(self):
        body = self.chart_card._body
        # Even smaller figure so the stat grid + depth + LTQ all
        # fit on a 900px-tall screen without scrolling. The chart
        # shows the trend at a glance; for detailed historical
        # analysis the user can switch to a different view.
        self.fig, self.ax, self.canvas = create_figure_in_frame(
            body, figsize=(8, 2.0),
        )
        # Three line series: LTP, SMMA20, SMMA120. We start empty and
        # fill in as ticks arrive. We set the initial colours from
        # the current palette so the very first paint matches the
        # active theme — without this the chart would show matplotlib
        # default colours (blue/orange/green) for a few hundred ms
        # before _on_theme_change() gets called.
        p = self.palette()
        self.line_ltp,  = self.ax.plot([], [], label="LTP",
                                        linewidth=1.6, color=p["accent"])
        self.line_fast, = self.ax.plot([], [], label="SMMA (fast)",
                                        linewidth=1.2, color=p["up"])
        self.line_slow, = self.ax.plot([], [], label="SMMA (slow)",
                                        linewidth=1.2, color=p["down"])
        # Place the legend OUTSIDE the axes (bbox_to_anchor below)
        # so it doesn't overlap the chart lines when data fills
        # the upper portion of the chart. The previous version put
        # it at "upper left" INSIDE the axes, which produced a
        # visible overlap with the SMMA lines.
        self.ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.0, -0.12),
            ncol=3,
            fontsize=8,
            frameon=False,
        )
        self.ax.set_xlabel("")
        self.ax.set_ylabel("Price (₹)")
        self.ax.grid(True, alpha=0.2)
        # Default axis ranges — overridden in _tick() when data arrives.
        self.ax.set_xlim(0, 60)
        self.ax.set_ylim(0, 100)
        # Tint the figure/axes backgrounds to the panel colour so
        # the chart doesn't have a white background on dark mode.
        self.fig.patch.set_facecolor(p["panel_bg"])
        self.ax.set_facecolor(p["panel_bg"])
        self.ax.tick_params(colors=p["text_muted"])
        for spine in self.ax.spines.values():
            spine.set_color(p["border"])
        for gridline in self.ax.get_xgridlines() + self.ax.get_ygridlines():
            gridline.set_color(p["border"])
        # tight_layout doesn't account for the bbox_to_anchor legend,
        # so we leave more room at the bottom. This prevents the
        # legend from being clipped at the bottom of the figure.
        self.fig.subplots_adjust(bottom=0.22)
        # The theme walker uses this attribute to find the
        # FigureCanvasTkAgg when the user toggles dark mode.
        self.canvas.get_tk_widget()._figure_ref = self.fig
        # Tooltip on the chart card title — explains what the lines mean.
        Tooltip.attach(self.chart_card._title_label, "Cross")

    # ------------------------------------------------------------------ stats

    def _build_stats_grid(self):
        """Six stat cards: Bid, Ask, Spread, Volume, 5m ETQ, 60m ETQ."""
        self._stat_vars = {}
        specs = [
            ("Bid",      "bid",  "—"),
            ("Ask",      "ask",  "—"),
            ("Spread",   "spread", "—"),
            ("Volume",   "volume", "—"),
            ("5m ETQ",   "etq5", "—"),
            ("60m ETQ",  "etq60", "—"),
        ]
        for i, (label, key, default) in enumerate(specs):
            r, c = divmod(i, 3)
            card = Card(self.stats_grid, title=label)
            # We DON'T use sticky="nsew" here — that would let the
            # card grow to fill the grid cell, and the cell's
            # height is determined by the largest card in the
            # row (which is the chart card at 250+px). With
            # sticky="n" (only stretch North-South vertically is
            # dropped), the card sizes to its natural content.
            # The cell is still wide enough because the column
            # has weight=1.
            card.grid(row=r, column=c, sticky="nsew", padx=SPACE_SM, pady=SPACE_SM,
                      ipadx=2, ipady=2)
            # Force the row to be just tall enough for the card
            # content (title + value + padding). 80px is enough
            # for two lines of 14pt text plus the title.
            self.stats_grid.rowconfigure(r, minsize=80)
            var = tk.StringVar(value=default)
            self._stat_vars[key] = (var, card)
            # Use a Label with explicit background so the value
            # text stays readable on dark mode. The default
            # tk.Label foreground ("SystemWindowText" on Windows)
            # doesn't get re-tinted by the theme walker, so we
            # also set the foreground explicitly to the palette's
            # body colour.
            p = self.palette()
            val_label = tk.Label(
                card._body, textvariable=var, font=FONT_NUM_MED, anchor="w",
                background=p["panel_bg"], foreground=p["fg"],
                height=2,  # explicit height so the text always has room to render
            )
            # `fill="x"` + `pady=4` gives the label enough height
            # for the 14pt font without expanding the card body.
            # `fill="both"` was the bug — it would stretch the
            # label to 230+px and push the text out of the visible
            # area on dark mode. `height=2` ensures the text has
            # at least two text-line slots so it's never clipped.
            val_label.pack(fill="x", pady=(SPACE_XS, SPACE_XS))
            # Tooltip on the title.
            if key in ("etq5", "etq60"):
                Tooltip.attach(card._title_label, "ETQ")
            elif key in ("bid", "ask", "spread"):
                Tooltip.attach(card._title_label, "Bid/Ask")

    # ------------------------------------------------------------------ depth

    def _build_depth(self):
        body = self.depth_card._body
        # Two columns: bid (green) and ask (red), 5 levels each.
        # We use tk.Label (not ttk.Label) so we can set explicit
        # background colours that survive the theme walker.
        # ttk.Label gets its colors from the TLabel style which
        # works for the default fg/bg but doesn't pick up
        # explicit foregrounds reliably across themes.
        p = self.palette()
        grid = ttk.Frame(body)
        grid.pack(fill="both", expand=True)
        for c in range(2):
            grid.columnconfigure(c, weight=1)
        self.depth_bid_var = tk.StringVar(value="—")
        self.depth_ask_var = tk.StringVar(value="—")
        tk.Label(grid, text="Best Bid", font=FONT_BODY_BOLD, anchor="w",
                 foreground=p["up"], background=p["panel_bg"]
                 ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        tk.Label(grid, text="Best Ask", font=FONT_BODY_BOLD, anchor="w",
                 foreground=p["down"], background=p["panel_bg"]
                 ).grid(row=0, column=1, sticky="w", pady=(0, 4))
        self.depth_bid_label = tk.Label(
            grid, textvariable=self.depth_bid_var, font=FONT_NUM_MED, anchor="w",
            foreground=p["up"], background=p["panel_bg"],
        )
        self.depth_bid_label.grid(row=1, column=0, sticky="w")
        self.depth_ask_label = tk.Label(
            grid, textvariable=self.depth_ask_var, font=FONT_NUM_MED, anchor="w",
            foreground=p["down"], background=p["panel_bg"],
        )
        self.depth_ask_label.grid(row=1, column=1, sticky="w")
        # Note about deeper depth.
        tk.Label(
            grid,
            text=("Live 5-level ladder is shown for top of book; "
                  "deeper depth is not in the current feed."),
            font=FONT_SMALL, anchor="w", wraplength=200,
            foreground=p["muted"], background=p["panel_bg"],
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(SPACE_MD, 0))

    # ------------------------------------------------------------------ ltq feed

    def _build_ltq_feed(self):
        body = self.ltq_card._body
        self.ltq_box = tk.Listbox(
            body, height=8, font=FONT_MONO, relief="flat",
            highlightthickness=0, borderwidth=0,
        )
        self.ltq_box.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ public

    def set_symbol(self, symbol):
        """Called by App when the user picks a row on the dashboard."""
        self.symbol = symbol
        self.title_var.set(f"Stock Detail — {symbol}")
        self.symbol_label.configure(text=symbol)
        self.series.clear()
        self.prints.clear()
        self.ltq_box.delete(0, "end")
        self.ltp_var.set("—")
        self.change_var.set("—")
        # Force a redraw of the chart so the old symbol's line goes away.
        self.line_ltp.set_data([], [])
        self.line_fast.set_data([], [])
        self.line_slow.set_data([], [])
        try:
            self.canvas.draw_idle()
        except Exception:
            pass
        self._on_theme_change(self.palette())
        # Trigger an immediate tick so the user sees the new
        # symbol's data on the very next render, not 500ms later
        # when the next after() callback fires.
        self._tick_now()

    def _tick_now(self):
        """One synchronous tick of the detail view's data update.

        Used by set_symbol() to populate the LTP / change / stats
        fields without waiting for the periodic 500ms after() tick.
        The data shown is the LATEST available from wsc.states —
        even if it was a tick from 0.5s ago, the user sees something
        on screen instead of "—" for half a second.
        """
        if self.symbol and self.symbol in wsc.states:
            st = wsc.states[self.symbol]
            # Append one synthetic sample so the chart shows a dot.
            fast = st.smma20 if st.smma20 else None
            slow = st.smma120 if st.smma120 else None
            self.series.append((st.ltp, fast, slow))
            if st.ltp:
                p = self.palette()
                self.ltp_var.set(f"₹{st.ltp:,.2f}")
                if st.smma20:
                    pct = (st.ltp - st.smma20) / st.smma20 * 100
                    sign = "+" if pct >= 0 else ""
                    self.change_var.set(f"{sign}{pct:.2f}% vs SMMA20")
                    self.change_label.configure(
                        foreground=p["up"] if pct >= 0 else p["down"]
                    )
            # Also seed the stats grid with whatever we have.
            self._stat_vars["bid"][0].set(f"₹{st.bid_price:.2f}  ×  {st.bid_qty:,}")
            self._stat_vars["ask"][0].set(f"₹{st.ask_price:.2f}  ×  {st.ask_qty:,}")
            spread = st.ask_price - st.bid_price
            self._stat_vars["spread"][0].set(f"₹{spread:.2f}")
            self._stat_vars["volume"][0].set(f"{st.ltq:,}")
            self._stat_vars["etq5"][0].set(f"{st.get_etq(5):,}")
            self._stat_vars["etq60"][0].set(f"{st.get_etq(60):,}")
            self.depth_bid_var.set(f"₹{st.bid_price:.2f}  ×  {st.bid_qty:,}")
            self.depth_ask_var.set(f"₹{st.ask_price:.2f}  ×  {st.ask_qty:,}")
            # Update the chart with the new sample.
            xs = list(range(len(self.series)))
            ys = [p[0] for p in self.series]
            fast_ys = [p[1] for p in self.series if p[1] is not None]
            fast_xs = [i for i, p in enumerate(self.series) if p[1] is not None]
            slow_ys = [p[2] for p in self.series if p[2] is not None]
            slow_xs = [i for i, p in enumerate(self.series) if p[2] is not None]
            self.line_ltp.set_data(xs, ys)
            self.line_fast.set_data(fast_xs, fast_ys)
            self.line_slow.set_data(slow_xs, slow_ys)
            p = self.palette()
            self.line_ltp.set_color(p["accent"])
            self.line_fast.set_color(p["up"])
            self.line_slow.set_color(p["down"])
            try:
                self.canvas.draw_idle()
            except Exception:
                pass

    # ------------------------------------------------------------------ tick loop

    def _tick(self):
        if self.symbol and self.symbol in wsc.states:
            st = wsc.states[self.symbol]
            # Capture LTP + SMMA values at the moment of this tick.
            # The chart will show all three lines side by side. We
            # only record an SMMA point if the SMMA is actually
            # populated (None for the first 20/120 ticks).
            fast = st.smma20 if st.smma20 else None
            slow = st.smma120 if st.smma120 else None
            self.series.append((st.ltp, fast, slow))

            # Build x/y arrays for the three lines. SMMA series
            # have None for early ticks where the SMMA isn't
            # populated yet — we filter those out so the SMMA
            # line starts partway through the chart instead of
            # being glued to the bottom.
            xs = list(range(len(self.series)))
            ys = [p[0] for p in self.series]
            fast_ys = [p[1] for p in self.series]
            slow_ys = [p[2] for p in self.series]
            fast_xs = [i for i, v in enumerate(fast_ys) if v is not None]
            fast_ys = [v for v in fast_ys if v is not None]
            slow_xs = [i for i, v in enumerate(slow_ys) if v is not None]
            slow_ys = [v for v in slow_ys if v is not None]

            self.line_ltp.set_data(xs, ys)
            self.line_fast.set_data(fast_xs, fast_ys)
            self.line_slow.set_data(slow_xs, slow_ys)

            if xs:
                self.ax.set_xlim(0, max(xs) + 1)
                # Y-axis: include SMMA values so the lines don't
                # get clipped above/below the LTP band.
                all_vals = list(ys)
                all_vals.extend(fast_ys)
                all_vals.extend(slow_ys)
                vals = [v for v in all_vals if v]
                if vals:
                    lo, hi = min(vals), max(vals)
                    pad = max(0.5, (hi - lo) * 0.1)
                    self.ax.set_ylim(lo - pad, hi + pad)

            # Update the line colours so they re-tint with the theme.
            p = self.palette()
            self.line_ltp.set_color(p["accent"])
            self.line_fast.set_color(p["up"])
            self.line_slow.set_color(p["down"])
            self.canvas.draw_idle()

            # Header LTP and change %.
            if st.ltp:
                self.ltp_var.set(f"₹{st.ltp:,.2f}")
                if st.smma20:
                    change_pct = (st.ltp - st.smma20) / st.smma20 * 100
                    sign = "+" if change_pct >= 0 else ""
                    self.change_var.set(f"{sign}{change_pct:.2f}% vs SMMA20")
                    self.change_label.configure(
                        foreground=p["up"] if change_pct >= 0 else p["down"]
                    )
            # Stats grid values.
            self._stat_vars["bid"][0].set(f"₹{st.bid_price:.2f}  ×  {st.bid_qty:,}")
            self._stat_vars["ask"][0].set(f"₹{st.ask_price:.2f}  ×  {st.ask_qty:,}")
            spread = st.ask_price - st.bid_price
            self._stat_vars["spread"][0].set(f"₹{spread:.2f}")
            self._stat_vars["volume"][0].set(f"{st.ltq:,}")
            self._stat_vars["etq5"][0].set(f"{st.get_etq(5):,}")
            self._stat_vars["etq60"][0].set(f"{st.get_etq(60):,}")

            # Depth card.
            self.depth_bid_var.set(f"₹{st.bid_price:.2f}  ×  {st.bid_qty:,}")
            self.depth_ask_var.set(f"₹{st.ask_price:.2f}  ×  {st.ask_qty:,}")

            # LTQ feed: append only if the latest tick changed.
            if st.ticks:
                last_ts, last_ltp, last_ltq = st.ticks[-1]
                stamp = last_ts.strftime("%H:%M:%S")
                line = f"{stamp}   ₹{last_ltp:>8.2f}   {last_ltq:>6,}"
                if not self.prints or self.prints[-1] != line:
                    self.prints.append(line)
                    self.ltq_box.insert("end", line)
                    self.ltq_box.yview_moveto(1)

            # SMMA crossover status → chip. Use the new
            # set_text() helper so the chip auto-resizes to fit
            # the new label — the previous code set _text and
            # called _redraw() directly, but the canvas's width
            # was fixed at construction so "DOWN TREND" got
            # clipped to "DOWN TRE" on screen.
            if st.smma20 and st.smma120:
                if st.smma20 > st.smma120:
                    self.signal_chip._fg_name = "up"
                    self.signal_chip.set_text("UP TREND")
                else:
                    self.signal_chip._fg_name = "down"
                    self.signal_chip.set_text("DOWN TREND")

        self.after(500, self._tick)

    # ------------------------------------------------------------------ theme

    def _on_theme_change(self, palette):
        """Re-tint our own tk widgets when the theme flips.

        The order matters: we update every tk widget FIRST, then
        re-tint the matplotlib figure. If we did it the other way
        around, the chart would repaint against a stale background
        for a single frame, producing a visible flicker on dark-mode
        toggles. We also use `draw()` (synchronous) instead of
        `draw_idle()` so the chart repaints before this function
        returns — `draw_idle()` schedules a paint for later which
        can race with the rest of the theme application.
        """
        # 0. Re-tint the top-bar title (it's a tk.Label that the
        #    theme walker won't reach because the default foreground
        #    on Windows is "SystemWindowText", not "" or "black").
        try:
            self.title_label.configure(
                background=palette["bg"],
                foreground=palette["fg"],
            )
        except Exception:
            pass
        # Also re-tint the symbol/LTP/change labels in the header
        # card. They have explicit foregrounds set to palette colours
        # at construction time, but theme changes need to re-apply
        # them so they stay in sync.
        try:
            self.symbol_label.configure(
                background=palette["panel_bg"],
                foreground=palette["fg"],
            )
        except Exception:
            pass

        # 1. Re-skin the cards (header, chart, depth, LTQ, stats).
        for card in [self.header_card, self.chart_card,
                     self.depth_card, self.ltq_card]:
            try:
                card._on_theme_change(palette)
            except Exception:
                pass
        for _, card in self._stat_vars.values():
            try:
                card._on_theme_change(palette)
            except Exception:
                pass
        # The stat card value labels were created with an explicit
        # `foreground=palette["fg"]` at construction time, which
        # means the Card's _on_theme_change leaves them alone (it
        # only re-tints labels with "default" foregrounds). We
        # re-tint them explicitly here so they switch with the
        # theme. Without this, switching from dark to light mode
        # leaves the values in the OLD (dark) foreground, which
        # is invisible against the new (light) panel background.
        for var, card in self._stat_vars.values():
            for child in card._body.winfo_children():
                if child.winfo_class() == "Label":
                    try:
                        child.configure(
                            background=palette["panel_bg"],
                            foreground=palette["fg"],
                        )
                    except Exception:
                        pass

        # 2. Re-tint the matplotlib chart BEFORE letting the per-
        #    tick _tick() loop run. We use `draw()` (synchronous)
        #    rather than `draw_idle()` so the repaint completes
        #    before the function returns. Without this the chart
        #    would briefly show old-theme colours before the new
        #    ones land, producing a visible flicker.
        try:
            self.line_ltp.set_color(palette["accent"])
            self.line_fast.set_color(palette["up"])
            self.line_slow.set_color(palette["down"])
            self.ax.set_facecolor(palette["panel_bg"])
            self.fig.patch.set_facecolor(palette["panel_bg"])
            for spine in self.ax.spines.values():
                spine.set_color(palette["border"])
            self.ax.tick_params(colors=palette["text_muted"])
            self.ax.title.set_color(palette["fg"])
            self.ax.yaxis.label.set_color(palette["text_muted"])
            for gridline in self.ax.get_xgridlines() + self.ax.get_ygridlines():
                gridline.set_color(palette["border"])
            legend = self.ax.get_legend()
            if legend is not None:
                for txt in legend.get_texts():
                    txt.set_color(palette["fg"])
                # Also re-tint the legend background and border
                # so it doesn't look like a white box on dark mode.
                try:
                    legend.get_frame().set_facecolor(palette["panel_bg"])
                    legend.get_frame().set_edgecolor(palette["border"])
                except Exception:
                    pass
            self.canvas.draw()
        except Exception:
            pass

        # 3. Re-tint the LTP / change labels and the listbox.
        try:
            self.ltp_label.configure(background=palette["panel_bg"],
                                     foreground=palette["fg"])
            self.change_label.configure(background=palette["panel_bg"],
                                        foreground=palette["muted"])
        except Exception:
            pass
        # Re-tint the depth labels (bid/ask) so they stay legible.
        try:
            self.depth_bid_label.configure(background=palette["panel_bg"],
                                           foreground=palette["up"])
            self.depth_ask_label.configure(background=palette["panel_bg"],
                                           foreground=palette["down"])
        except Exception:
            pass
        try:
            self.ltq_box.configure(background=palette["panel_bg"],
                                   foreground=palette["fg"],
                                   selectbackground=palette["accent"])
        except Exception:
            pass
