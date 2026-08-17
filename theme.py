"""
Centralised theming. All colour and font choices live here so dark
mode is a single setting that re-skins the whole app.

Two palettes:
  * LIGHT — clean, off-white, indigo accent. Inspired by Linear /
            Notion / Robinhood's light mode.
  * DARK  — high-contrast GitHub-Dark-inspired with a sky-blue
            accent. Easy on the eyes during long sessions.

`apply_theme(root, dark=False)` reconfigures the ttk styles in place.
It's safe to call at any time — the next render of every widget will
use the new colours. For widgets that don't pick up ttk styles
(notably tk.Listbox, tk.Text, and matplotlib canvases), the theme
also walks the widget tree and reconfigures them via .configure().
"""

import tkinter as tk
from tkinter import ttk

# --- Light palette ---
# Off-white background (warmer than pure #fff), white cards, indigo
# accent. Text is near-black with a softer "muted" variant for
# secondary copy. Greens and reds are tuned for the BUY/SELL signals.
LIGHT = {
    "name":          "light",
    "bg":            "#f7f8fa",   # page background (very light grey)
    "fg":            "#1f2328",   # primary text (near-black)
    "text_muted":    "#656d76",   # secondary text
    "text_inverse":  "#ffffff",   # text on accent background
    "sidebar_bg":    "#ffffff",   # sidebar (white card)
    "panel_bg":      "#ffffff",   # card / panel background
    "accent":        "#4f46e5",   # indigo (buttons, links, focus)
    "accent_soft":   "#eef2ff",   # tinted accent (chip backgrounds)
    "muted":         "#656d76",
    "border":        "#d0d7de",   # subtle borders
    "buy":           "#dcfce7",   # BUY / gain row background
    "sell":          "#fee2e2",   # SELL / loss row background
    "up":            "#16a34a",   # text colour for positive numbers
    "down":          "#dc2626",   # text colour for negative numbers
    "warn":          "#d97706",   # warning amber
    "neutral":       "#6b7280",   # NO / HOLD
    "tree_row_alt":  "#f7f8fa",
    "shadow":        "#00000018", # 9% black for subtle card shadows
}

# --- Dark palette ---
# GitHub-Dark-inspired. Sky-blue accent instead of the GitHub
# purple — feels more "fintech", less "developer tool".
DARK = {
    "name":          "dark",
    "bg":            "#0d1117",   # page background
    "fg":            "#e6edf3",   # primary text
    "text_muted":    "#8b949e",   # secondary text
    "text_inverse":  "#0d1117",   # text on accent background
    "sidebar_bg":    "#161b22",   # sidebar (slightly elevated)
    "panel_bg":      "#161b22",   # cards
    "accent":        "#58a6ff",   # sky blue
    "accent_soft":   "#1f2937",   # tinted accent
    "muted":         "#8b949e",
    "border":        "#30363d",
    "buy":           "#103a1f",
    "sell":          "#3a1010",
    "up":            "#3fb950",   # green
    "down":          "#f85149",   # red
    "warn":          "#d29922",
    "neutral":       "#8b949e",
    "tree_row_alt":  "#0d1117",
    "shadow":        "#00000066", # 40% black for darker shadows
}


def current_palette(dark: bool):
    return DARK if dark else LIGHT


def _style_names():
    """Every ttk style we configure. Keeping the list here means
    `apply_theme` doesn't have to know which pages exist."""
    return [
        "TFrame", "TLabel", "TButton", "TCheckbutton",
        "TEntry", "TCombobox", "TNotebook", "TNotebook.Tab",
        "Treeview", "Treeview.Heading",
        "TLabelframe", "TLabelframe.Label",
        "TSpinbox", "T_SEPARATOR", "Horizontal.TSeparator",
    ]


def apply_theme(root: tk.Tk, dark: bool = False):
    """
    Re-skin the entire app. Walks every child widget and updates
    both ttk styles (which propagate to ttk widgets) and the
    classic-Tk options (bg/fg) used by tk.Listbox, tk.Text, and
    any Frame we created with tk.Frame instead of ttk.Frame.
    """
    p = current_palette(dark)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # clam respects our colours; default themes don't
    except tk.TclError:
        pass

    # TButton / Nav.TButton: regular buttons get a subtle hover
    # effect. The "Nav.TButton" style is used for sidebar nav
    # buttons — it has a clearly visible hover state so the user
    # always knows which page they're about to click.
    style.configure("TButton",         background=p["sidebar_bg"], foreground=p["fg"],
                     bordercolor=p["border"], lightcolor=p["sidebar_bg"], darkcolor=p["sidebar_bg"],
                     padding=(14, 6), relief="flat")
    style.map("TButton",
              background=[("active", p["accent_soft"]),
                          ("pressed", p["accent_soft"]),
                          ("selected", p["accent"])],
              foreground=[("active", p["fg"]),
                          ("pressed", p["fg"]),
                          ("selected", p["text_inverse"])])
    # Nav.TButton: same as TButton but with a stronger hover
    # state (accent background + inverse text) so the hover is
    # obvious. The "active" state (when the page is current) is
    # permanent — the user always sees which page they're on.
    style.configure("Nav.TButton",
                     background=p["sidebar_bg"], foreground=p["fg"],
                     bordercolor=p["border"],
                     lightcolor=p["sidebar_bg"], darkcolor=p["sidebar_bg"],
                     padding=(14, 8), relief="flat",
                     font=("Segoe UI", 10))
    style.map("Nav.TButton",
              background=[("active", p["accent"]),
                          ("pressed", p["accent"]),
                          ("hover", p["accent_soft"]),
                          ("selected", p["accent"])],
              foreground=[("active", p["text_inverse"]),
                          ("pressed", p["text_inverse"]),
                          ("hover", p["fg"]),
                          ("selected", p["text_inverse"])])
    # Accent button: a separate style for primary CTAs. Use as
    # style="Accent.TButton" when you want the bold action button.
    style.configure("Accent.TButton",
                     background=p["accent"], foreground=p["text_inverse"],
                     bordercolor=p["accent"], lightcolor=p["accent"],
                     darkcolor=p["accent"], padding=(16, 8), relief="flat")
    style.map("Accent.TButton",
              background=[("active", p["accent"]), ("pressed", p["accent"])],
              foreground=[("active", p["text_inverse"])])
    style.configure("TCheckbutton",    background=p["bg"], foreground=p["fg"])
    style.configure("TEntry",          fieldbackground=p["panel_bg"],
                     foreground=p["fg"], bordercolor=p["border"],
                     padding=(8, 6), relief="flat")
    style.configure("TCombobox",       fieldbackground=p["panel_bg"],
                     foreground=p["fg"], bordercolor=p["border"],
                     padding=(8, 4))
    style.configure("TNotebook",       background=p["bg"], bordercolor=p["border"])
    style.configure("TNotebook.Tab",   background=p["sidebar_bg"],
                     foreground=p["fg"], padding=(14, 6))
    style.map("TNotebook.Tab",
              background=[("selected", p["accent"])],
              foreground=[("selected", p["text_inverse"])])
    style.configure("Treeview",
                     background=p["panel_bg"],
                     fieldbackground=p["panel_bg"],
                     foreground=p["fg"],
                     bordercolor=p["border"],
                     rowheight=28)
    style.configure("Treeview.Heading",
                     background=p["sidebar_bg"],
                     foreground=p["text_muted"],
                     relief="flat",
                     font=("Segoe UI", 9, "bold"))
    style.map("Treeview.Heading",
              background=[("active", p["accent"])])
    style.configure("TLabelframe",     background=p["bg"],
                     foreground=p["fg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["accent"])
    style.configure("TSpinbox",        fieldbackground=p["panel_bg"],
                     foreground=p["fg"], bordercolor=p["border"],
                     padding=(8, 4))
    style.configure("Horizontal.TSeparator", background=p["border"])

    # Walk the entire widget tree and re-skin non-ttk children too.
    _rewalk(root, p)

    # Re-tint Treeview row tags (buy/sell/profit/loss) to match palette.
    _retint_treeview_tags(root, p)

    # Matplotlib figures everywhere should match the new background.
    _retint_matplotlib(root, p)

    # Tell any registered "I want to know about theme changes" callback
    # (the chatbot floating window, etc.) so they can refresh their own
    # tk widgets.
    for cb in _subscribers:
        try:
            cb(p)
        except Exception:
            pass


def _retint_treeview_tags(root, palette):
    """Reconfigure the per-row tag colours on every ttk.Treeview so
    highlight rows (buy/sell/profit/loss) stay legible in both themes.
    Each call to tag_configure re-binds the colour."""
    for tree in _find_trees(root):
        try:
            # Row backgrounds (subtle tint of the buy/sell colour).
            tree.tag_configure("buy",    background=palette["buy"],
                               foreground=palette["up"])
            tree.tag_configure("sell",   background=palette["sell"],
                               foreground=palette["down"])
            tree.tag_configure("profit", background=palette["buy"],
                               foreground=palette["up"])
            tree.tag_configure("loss",   background=palette["sell"],
                               foreground=palette["down"])
            tree.tag_configure("accept", background=palette["buy"],
                               foreground=palette["up"])
            tree.tag_configure("avoid",  background=palette["sell"],
                               foreground=palette["down"])
            tree.tag_configure("unack",  foreground=palette["accent"])
        except Exception:
            pass


def _find_trees(root):
    """Yield every ttk.Treeview in the widget tree."""
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            if w.winfo_class() == "Treeview":
                yield w
        except Exception:
            pass
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass


def _rewalk(widget, palette):
    """Recursively reconfigure bg/fg on every widget in the tree.

    Important: we do NOT override an explicit semantic foreground
    (e.g. "#16a34a" for gainers, "#4f46e5" for the brand colour, or
    palette names like "up" / "down" / "accent"). The previous
    version unconditionally set foreground=palette["fg"] on every
    Label, which destroyed brand colours and made the dashboard's
    "25" gainers number render in plain body-text colour.
    """
    try:
        cls = widget.winfo_class()
    except Exception:
        return
    if cls in ("TFrame", "Frame", "Label", "Button", "Checkbutton",
               "TLabel", "TButton", "TCheckbutton", "TLabelframe",
               "Labelframe"):
        try:
            widget.configure(background=palette["bg"])
        except Exception:
            pass
    # TLabel / Label: re-tint the foreground if the current value
    # is a default (empty, black, "SystemWindowText" on Windows, the
    # other-platform defaults, or a greyed-out placeholder). We leave
    # explicit semantic colours alone so the user's brand/up/down/
    # accent choices survive a theme toggle.
    if cls in ("TLabel", "Label"):
        try:
            current = widget.cget("foreground")
            # Default-ish colours that should follow the theme.
            default_fgs = {
                "", "black", "#000000",
                "SystemWindowText", "SystemWindow", "WindowText",
                "gray", "grey", "#808080", "#6e6e6e",
            }
            if current in default_fgs:
                widget.configure(foreground=palette["fg"])
            # else: explicit semantic colour (brand, up, down, accent)
            # — leave it alone.
        except Exception:
            pass
    if cls == "Listbox":
        try:
            widget.configure(background=palette["panel_bg"],
                             foreground=palette["fg"],
                             selectbackground=palette["accent"],
                             selectforeground="#ffffff")
        except Exception:
            pass
    if cls == "Text":
        try:
            widget.configure(background=palette["panel_bg"],
                             foreground=palette["fg"],
                             insertbackground=palette["fg"],
                             selectbackground=palette["accent"],
                             selectforeground="#ffffff")
        except Exception:
            pass
    if cls == "TEntry":
        try:
            widget.configure(foreground=palette["fg"])
        except Exception:
            pass

    for child in widget.winfo_children():
        _rewalk(child, palette)


def _retint_matplotlib(root, palette):
    """Find every FigureCanvasTkAgg in the tree and re-tint its figure.

    Note: pages that own a matplotlib chart also subscribe to
    `subscribe()` so they can re-tint their own chart. The
    double-tinting is intentional — theme.py handles the background
    and structural elements (face colour, spines, tick colours,
    legend text), and the page's _on_theme_change handles the
    data-line colours and chart-specific styling. We use draw()
    (synchronous) here so this repaint completes before any
    subscriber runs, avoiding visible flicker.
    """
    def visit(widget):
        for child in widget.winfo_children():
            try:
                fig = getattr(child, "_figure_ref", None)
                if fig is not None:
                    fig.patch.set_facecolor(palette["panel_bg"])
                    for ax in fig.axes:
                        ax.set_facecolor(palette["panel_bg"])
                        ax.tick_params(colors=palette["fg"])
                        for spine in ax.spines.values():
                            spine.set_color(palette["border"])
                        ax.title.set_color(palette["fg"])
                        ax.xaxis.label.set_color(palette["fg"])
                        ax.yaxis.label.set_color(palette["fg"])
                        legend = ax.get_legend()
                        if legend is not None:
                            for txt in legend.get_texts():
                                txt.set_color(palette["fg"])
                            try:
                                legend.get_frame().set_facecolor(
                                    palette["panel_bg"])
                                legend.get_frame().set_edgecolor(
                                    palette["border"])
                            except Exception:
                                pass
                    try:
                        # Synchronous redraw so this completes
                        # before subscribers run.
                        child.draw()
                    except Exception:
                        pass
            except Exception:
                pass
            visit(child)

    visit(root)


# Subscribers are called on every apply_theme(). Used by the chatbot
# window so it can re-tint its own non-ttk widgets.
_subscribers = []

def subscribe(callback):
    _subscribers.append(callback)
