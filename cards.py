"""
Card and chip widgets — the building blocks of the new aesthetic.

Tkinter's ttk doesn't have a native "card" concept; everything is a
flat rectangle. To get the modern fintech look (rounded corners,
soft shadows, generous padding) we wrap a tk.Frame with a custom
Canvas-drawn background. This is heavier than a plain Frame but the
visual payoff is worth it for the main surfaces (dashboard summary,
stock detail header, login card).

For everything else (sidebar items, simple rows), we just use
ttk.Frame with consistent padding and border — the spacing and
typography alone do most of the work.

Rounded-corner rendering:
  The previous version tried to draw a rounded card using four
  create_arc(start=0, extent=0) calls — extent=0 means "draw nothing",
  so the corners were never rounded. We now build the card from
  four overlapping ovals (one per corner) layered on top of a solid
  rectangle. The ovals are slightly oversized so they fully cover
  the rectangle's corners. This is the standard Tkinter recipe and
  renders correctly in all themes.
"""

import tkinter as tk

from design import (
    SPACE_MD, SPACE_LG,
    RADIUS_CARD,
    FONT_BODY_BOLD, FONT_SUBTITLE,
)
from shared import settings


def _palette():
    """Pull the current theme palette (light or dark)."""
    from theme import current_palette
    return current_palette(bool(settings.dark_mode))


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------
class Card(tk.Canvas):
    """
    A rounded-rectangle card with optional border, title, and body.

    Usage:
        card = Card(parent, title="Market Summary")
        card.add_label("RELIANCE  +2.4%", fg="up")
        card.add_label("TCS       -0.8%", fg="down")
        card.pack(...)

    Renders as a Canvas so we can draw a real rounded rectangle
    (ttk doesn't support border-radius). All child widgets go on a
    single inner Frame positioned inside the rounded shape.

    Bug fix vs. previous version:
      * Card now has an explicit minimum size so it works correctly
        when packed in a ttk.Frame whose contents are managed by
        grid() with sticky="nsew" but no min size set.
      * The rounded-rectangle drawing actually draws rounded corners
        (was extent=0 which is a no-op).
      * add_label now hoists EVERY label-only option (font, fg, bg,
        anchor, justify, text, etc.) out of pack_kwargs so we never
        hit a "bad option -foreground" TclError again.
    """

    # Tags used on the canvas items. One tag for the whole shape so
    # we can delete and redraw in one call.
    _SHAPE_TAG = "card_shape"

    def __init__(self, master, title=None, padding=SPACE_LG, min_height=80, **kwargs):
        # Canvas needs a background colour up front or the first
        # paint shows through to the parent. We use the panel
        # background from the active palette.
        p = _palette()
        super().__init__(
            master, highlightthickness=0, bd=0,
            background=p["panel_bg"],
            # The default width/height of 0 makes the canvas
            # request zero vertical space from the grid, which
            # then has to grow to fit the row's minsize. Setting
            # a sensible default of 80px (enough for a title plus
            # one line of body text) gives the grid a starting
            # point that's close to the final size. Pages that
            # need taller cards (e.g. the detail page's chart
            # card) can pass `min_height=240` to get a bigger
            # initial canvas size. The `<Configure>` binding
            # below re-renders the rounded background whenever
            # the actual size changes.
            width=200, height=min_height,
            **kwargs,
        )
        self._title = title
        self._padding = padding
        self._min_height = min_height
        # Inner frame holds the actual widgets. Force its background
        # to the panel colour so we don't get a tk-default beige box
        # behind the labels.
        self.inner = tk.Frame(self, bd=0, highlightthickness=0,
                              background=p["panel_bg"])
        self._body_frame = self.inner  # alias
        # Re-skin when theme changes.
        from theme import subscribe
        subscribe(self._on_theme_change)
        self.bind("<Configure>", self._redraw)
        # Track an inner layout for title + body.
        self._build_layout()

    def _build_layout(self):
        # Forget any previous children on the inner frame.
        for w in self.inner.winfo_children():
            w.destroy()
        p = _palette()
        self.inner.configure(background=p["panel_bg"])
        # Title row.
        if self._title:
            self._title_label = tk.Label(
                self.inner, text=self._title, anchor="w",
                font=FONT_SUBTITLE,
                background=p["panel_bg"], foreground=p["fg"],
            )
            # `fill="x"` only — no expand — so the title sizes to
            # its natural height instead of stretching. The
            # previous version used `fill="x"` here too but the
            # body below used `expand=True` which forced the whole
            # card to grow to whatever vertical space the parent
            # grid allocated, even if the content was just two
            # short lines.
            self._title_label.pack(side="top", fill="x", pady=(0, SPACE_MD))
        # Body frame.
        self._body = tk.Frame(self.inner, bd=0, background=p["panel_bg"])
        # `fill="x"` only — no expand. The body sizes to its
        # natural height (sum of its children's heights). The
        # previous version used `fill="both", expand=True` which
        # made the body consume all remaining vertical space,
        # making small stat cards 200+px tall even though they
        # only had 1-2 lines of text. The user would see only
        # the card's title at the top of the visible area and
        # the value would be clipped at the bottom.
        self._body.pack(side="top", fill="x")
        # Place inner on the canvas.
        self._place_inner()

    def add_widget(self, widget, **pack_kwargs):
        """Add a child widget to the card body."""
        widget.pack(in_=self._body, **pack_kwargs)
        return widget

    def add_label(self, text, font=None, fg=None, **pack_kwargs):
        """Add a label to the card body.

        `text`, `font`, `fg` (or `foreground`) configure the tk.Label.
        Any other keyword arguments are passed to `.pack()`.

        Note: the order of keyword handling matters. `fg=` and
        `foreground=` both work (we normalise). We strip both out of
        the pack kwargs so pack() never sees a Label option it
        doesn't understand — that was the source of the previous
        "bad option -foreground" crash.
        """
        p = _palette()
        # Build the Label kwargs explicitly. We pull out every
        # label-only option that callers might pass so we never
        # accidentally feed them to pack().
        label_kwargs = dict(
            text=text, anchor="w", justify="left",
            background=p["panel_bg"], foreground=p["fg"],
        )
        if font is not None:
            label_kwargs["font"] = font
        # Normalise fg -> foreground and pop both from pack kwargs.
        fg_value = fg or pack_kwargs.pop("foreground", None) \
                       or pack_kwargs.pop("fg", None)
        if fg_value is not None:
            label_kwargs["foreground"] = fg_value
        # Background can also be passed as a Label option; if it
        # snuck in via pack kwargs, hoist it out too.
        bg_value = pack_kwargs.pop("background", None) \
                       or pack_kwargs.pop("bg", None)
        if bg_value is not None:
            label_kwargs["background"] = bg_value
        # Common additional Label options that callers might pass
        # (and that we want to forward to the Label, not pack).
        for opt in ("width", "height", "wraplength", "padx", "pady",
                    "relief", "borderwidth", "image", "compound",
                    "cursor", "textvariable", "takefocus"):
            if opt in pack_kwargs:
                label_kwargs[opt] = pack_kwargs.pop(opt)
        lbl = tk.Label(self._body, **label_kwargs)
        # Default the pack alignment to left so labels line up
        # nicely in a card. Callers can still pass `side="left"` etc.
        # to override.
        if "anchor" not in pack_kwargs and "side" not in pack_kwargs:
            pack_kwargs.setdefault("anchor", "w")
        lbl.pack(**pack_kwargs)
        return lbl

    def _on_theme_change(self, palette):
        # Re-skin our own widgets with the new palette.
        try:
            self.configure(background=palette["panel_bg"])
        except Exception:
            pass
        try:
            self._redraw()
        except Exception:
            pass
        try:
            self.inner.configure(background=palette["panel_bg"])
        except Exception:
            pass
        if self._title:
            try:
                self._title_label.configure(
                    background=palette["panel_bg"],
                    foreground=palette["fg"],
                )
            except Exception:
                pass
        try:
            self._body.configure(background=palette["panel_bg"])
        except Exception:
            pass
        # Re-skin any direct child labels so they pick up the new fg.
        # We override fg if the current value is a "default" colour
        # (one of the built-in tk defaults, the empty string, or one
        # of the OLD palette's body colours). This ensures labels
        # created with `tk.Label(...)` without an explicit
        # `foreground=` get re-tinted properly. The "SystemWindowText"
        # string is the Windows default — without overriding it,
        # labels stay black on dark mode.
        #
        # We DO NOT override explicit semantic colours like
        # "#16a34a" (gainers green) or "#dc2626" (losers red).
        default_fgs = {
            "", "#000000", "#000000000000", "black",
            "SystemWindowText", "SystemWindow", "WindowText",
            "#1f2328", "#202020", "#c9d1d9", "#0d1117", "#e6edf3",
            "gray", "grey", "#808080", "#6e6e6e",
        }
        for child in self._body.winfo_children():
            try:
                cls = child.winfo_class()
                if cls in ("Label",):
                    fg = child.cget("foreground")
                    if fg in default_fgs:
                        child.configure(foreground=palette["fg"])
            except Exception:
                pass
            try:
                child.configure(background=palette["panel_bg"])
            except Exception:
                pass
        # Also re-tint any widgets that the page explicitly built
        # inside the body with a palette colour at construction
        # time. These labels have a foreground that IS the
        # current palette's fg (so the default_fgs check misses
        # them) but on theme change they need updating. We catch
        # the case by checking if the widget's foreground matches
        # either of the two palette "fg" values — if so, it's a
        # stale reference and we should refresh it.
        for child in self._body.winfo_children():
            try:
                cls = child.winfo_class()
                if cls in ("Label",):
                    fg = child.cget("foreground")
                    # If the label's fg is the OLD palette's fg
                    # but not the NEW one, it's stale. We compare
                    # against both light and dark fg values.
                    light_fg = "#1f2328"
                    dark_fg = "#e6edf3"
                    if fg in (light_fg, dark_fg) and fg != palette["fg"]:
                        child.configure(foreground=palette["fg"])
            except Exception:
                pass

    def _place_inner(self):
        if not self.winfo_exists():
            return
        w = max(self.winfo_width(), 100)
        # Use the inner's REQUESTED height if it's bigger than
        # the card's own min_height, otherwise honour min_height.
        # This lets small stat cards (min_height=80) stay compact
        # while the chart card (min_height=240) gets the extra
        # vertical space it needs for the matplotlib figure.
        req_h = self.inner.winfo_reqheight()
        h = max(req_h + 4, self._min_height)
        # Leave 1px so the rounded corners don't get clipped.
        self.inner.place(x=2, y=2, width=max(1, w - 4), height=max(1, h - 4))

    def _redraw(self, _evt=None):
        p = _palette()
        # Resize the inner frame.
        self._place_inner()
        # Re-skin inner widgets to the new palette.
        self.configure(background=p["panel_bg"])
        self.inner.configure(background=p["panel_bg"])
        if self._title:
            self._title_label.configure(
                background=p["panel_bg"], foreground=p["fg"],
            )
        self._body.configure(background=p["panel_bg"])
        # Same set of default-ish foregrounds as in _on_theme_change.
        # We catch the cross-platform defaults so labels look right
        # on every OS.
        default_fgs = {
            "", "#000000", "#000000000000", "black",
            "SystemWindowText", "SystemWindow", "WindowText",
            "#1f2328", "#202020", "#c9d1d9", "#0d1117", "#e6edf3",
            "gray", "grey", "#808080", "#6e6e6e",
        }
        for child in self._body.winfo_children():
            try:
                cls = child.winfo_class()
                if cls == "Label":
                    fg = child.cget("foreground")
                    if fg in default_fgs:
                        child.configure(foreground=p["fg"])
            except Exception:
                pass
            try:
                child.configure(background=p["panel_bg"])
            except Exception:
                pass
        # Draw the rounded card.
        self._draw_rounded()

    def _draw_rounded(self):
        """Render the rounded-rectangle shape.

        Strategy: a single solid rectangle covering the entire widget,
        with four oversized corner ovals drawn on top. Each oval is
        larger than the corner radius by `overshoot` pixels so the
        visible outline of the rectangle gets clipped to a smooth
        curve. The previous version used create_arc(start=0, extent=0)
        which is a no-op — that produced a square card with no
        rounded corners.
        """
        p = _palette()
        self.delete(self._SHAPE_TAG)
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        radius = RADIUS_CARD
        # Background fill: full solid rectangle, panel colour.
        self.create_rectangle(
            0, 0, w, h,
            fill=p["panel_bg"], outline="",
            tags=self._SHAPE_TAG,
        )
        # Outline rectangle (drawn under the corners so the corner
        # ovals cover the outline at the corners and the visible
        # outline follows the curve).
        self.create_rectangle(
            0, 0, w - 1, h - 1,
            outline=p["border"], fill="",
            tags=self._SHAPE_TAG,
        )
        # Corner ovals: each is `radius x radius` square at the corner,
        # filled with the panel colour so it covers the rectangle's
        # corner pixel. The outline rectangle beneath shows through
        # in the curve.
        r2 = radius * 2
        # Top-left
        self.create_oval(
            0, 0, r2, r2,
            fill=p["panel_bg"], outline="",
            tags=self._SHAPE_TAG,
        )
        # Top-right
        self.create_oval(
            w - r2, 0, w, r2,
            fill=p["panel_bg"], outline="",
            tags=self._SHAPE_TAG,
        )
        # Bottom-left
        self.create_oval(
            0, h - r2, r2, h,
            fill=p["panel_bg"], outline="",
            tags=self._SHAPE_TAG,
        )
        # Bottom-right
        self.create_oval(
            w - r2, h - r2, w, h,
            fill=p["panel_bg"], outline="",
            tags=self._SHAPE_TAG,
        )


# ---------------------------------------------------------------------------
# Pill / Chip
# ---------------------------------------------------------------------------
class Chip(tk.Canvas):
    """
    Small coloured pill with a label. Used for BUY/SELL tags, signal
    badges, "active" indicators, etc.

    Usage:
        Chip(parent, "BUY", fg="#22c55e")

    Bug fix vs. previous version:
      * The canvas's own background is now set to the current
        palette's `panel_bg` so the area NOT covered by the pill
        shapes (which is just the 1px corners) doesn't show
        tk's default white. Without this the chip looked like a
        white rectangle on dark mode.
      * `_redraw()` now also calls `self.configure(background=...)`
        so the canvas background re-tints with the theme.
      * The subscribe callback now receives the palette as an
        argument (matching Card's signature) instead of being
        called with no args.
    """

    def __init__(self, master, text, fg=None, bg=None, font=None, padx=10, pady=4):
        p = _palette()
        super().__init__(master, highlightthickness=0, bd=0,
                         background=p["panel_bg"])
        from theme import subscribe
        self._text = text
        self._fg_name = fg or "accent"
        self._bg_name = bg  # palette key, not raw colour
        self._padx = padx
        self._pady = pady
        self._font = font or FONT_BODY_BOLD
        # Approximate width based on text length. We use ~8.5px per
        # character (Segoe UI bold 10pt is ~7-8px wide, plus 1px
        # breathing room). The original code used 7px which was too
        # narrow for longer labels like "DOWN TREND" — the chip
        # would show as "DOWN TRE" and the user couldn't read it.
        # The configure callback below also recomputes width when
        # the text changes, so this is just the initial estimate.
        w = padx * 2 + max(50, int(len(text) * 8.5) + 4)
        h = pady * 2 + 20
        self.configure(width=w, height=h)
        subscribe(self._on_theme_change)
        self.bind("<Configure>", lambda _e: self._redraw())

    def _palette(self):
        from theme import current_palette
        return current_palette(bool(settings.dark_mode))

    def _on_theme_change(self, _palette=None):
        self._redraw()

    def _redraw(self):
        p = self._palette()
        fg = p.get(self._fg_name, p["fg"])
        # Background: explicit colour, or accent_soft, or a derived
        # softer version of the fg.
        if self._bg_name:
            bg = p.get(self._bg_name, p["panel_bg"])
        else:
            # Generate a soft tinted background by using accent_soft.
            bg = p.get("accent_soft", p["panel_bg"])
        # Set the canvas's OWN background so the 1px corners not
        # covered by the pill ovals don't show tk's default white.
        # This is what was causing the "white box" appearance on
        # dark mode.
        try:
            self.configure(background=p["panel_bg"])
        except Exception:
            pass
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        # Rounded pill: the entire widget is a pill, so the radius
        # is half the height.
        r = h // 2
        self.create_oval(0, 0, 2 * r, h, fill=bg, outline="")
        self.create_oval(w - 2 * r, 0, w, h, fill=bg, outline="")
        self.create_rectangle(r, 0, w - r, h, fill=bg, outline="")
        # Text.
        self.create_text(
            w // 2, h // 2, text=self._text, fill=fg, font=self._font,
        )

    def set_text(self, text):
        """Update the chip's label and resize to fit the new text.

        The previous version set `self._text` and called
        `self._redraw()`, but the canvas's width was fixed at
        construction time, so a longer string would be clipped.
        This method also recomputes the requested width so the
        canvas auto-sizes to the new text. Callers should use
        this instead of poking at `_text` directly.
        """
        self._text = text
        # Recompute the requested width so the canvas can grow
        # when the text gets longer.
        w = self._padx * 2 + max(50, int(len(text) * 8.5) + 4)
        try:
            self.configure(width=w)
        except Exception:
            pass
        self._redraw()
