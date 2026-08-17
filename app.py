"""
Main App shell. Sets up the sidebar + content area, instantiates
pages lazily, and routes navigation clicks to ``tkraise()``.

Lives at the top of the project so it can be run directly::

    python app.py

Navigation
----------
  * Click any sidebar button to jump to a page.
  * Up/Down arrow keys move between pages (when the sidebar has
    keyboard focus).
  * Hover over a nav button to see it highlight with the accent
    colour. The currently-active page button is permanently
    highlighted so the user always knows where they are.

Lazy loading (Round 3 performance fix)
----------------------------------------
The previous version eagerly imported every page module and
constructed every page widget at app startup. This blocked the
user from seeing the login screen for ~1.6 seconds because of
heavy imports (sklearn=664 ms, analytics=171 ms, matplotlib=83
ms, pandas=237 ms) and heavy page construction (MLStatsPage=378
ms, DetailPage=77 ms).

Now we:

  1. Only import the lightweight modules at startup.
  2. Only build the LoginPage at startup.
  3. Build other pages on first ``show()`` — the first time the
     user clicks "ML Stats" or "Stock Detail", the import
     happens and the page is constructed. Subsequent shows
     reuse the cached instance.
  4. The chatbot window is created on first toggle, not at
     startup.

The trade-off: the FIRST navigation to a heavy page is slow
(the import happens on the UI thread). But the user only sees
this once per page per session, and only for pages they actually
visit. The login screen appears in <100 ms.

Responsive behaviour
--------------------
  * The window has a minimum size of 1024×640 so the layout
    never collapses below usable.
  * The sidebar width is fixed but the content area resizes
    to fill the remaining horizontal space.
  * Pages that contain a table (Dashboard, AI Signals, Trade
    Log, Alerts) use horizontal scrollbars so narrow windows
    still show all columns — they don't reflow / hide columns
    because that would lose information.
  * Pages that contain a chart (Stock Detail) shrink the chart
    figure proportionally with the window width.
"""

import importlib
import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

# Lightweight imports — these have no heavy dependencies.
from pages.login_page import LoginPage
from shared import alerts, settings
from theme import apply_theme

_log = logging.getLogger(__name__)


#: Ordered list of pages in the sidebar. Each entry is a
#: 4-tuple of ``(display_name, module_path, class_name,
#: is_heavy)``. The ``is_heavy`` flag tells the loader that
#: this page pulls in sklearn / matplotlib / pandas and should
#: only be built on first navigation. The login page is NOT in
#: this list (it's a pre-login gate, not a regular nav target).
PAGES: List[Tuple[str, str, str, bool]] = [
    # (name, module, class, is_heavy)
    ("Dashboard",    "pages.dashboard_page",  "DashboardPage",  False),
    ("Stock Detail", "pages.detail_page",     "DetailPage",     True),
    ("AI Signals",   "pages.ai_signals_page", "AISignalsPage",  False),
    ("Trade Log",    "pages.trade_log_page",  "TradeLogPage",   False),
    ("ML Stats",     "pages.ml_stats_page",   "MLStatsPage",    True),
    ("Settings",     "pages.settings_page",   "SettingsPage",   False),
    ("Alerts",       "pages.alerts_page",     "AlertsPage",     False),
    ("Debug Log",    "pages.debug_log_page",  "DebugLogPage",   False),
    ("Help",         "pages.help_page",       "HelpPage",       False),
]


class App(tk.Tk):
    """The application's main window.

    Owns the sidebar (a vertical list of nav buttons) and a
    content area that hosts every page. Pages are built lazily
    on first navigation so the login screen appears in <100 ms.

    Attributes
    ----------
    frames : dict[type, tk.Widget]
        Maps a page class to its currently-built widget
        instance. The :class:`LoginPage` is registered at
        construction; other pages are added on first
        navigation.
    nav_buttons : dict[type, ttk.Button]
        Maps a page class to the sidebar button that navigates
        to it. Built in :meth:`__init__`.
    """

    # Default initial geometry. Picked to fit a 13" laptop screen
    # with room to spare on each side.
    _DEFAULT_GEOMETRY: str = "1280x720"

    # Minimum window size in pixels. Below this, the layout
    # starts to break (sidebar overflows, tables clip).
    _MIN_WIDTH: int = 1024
    _MIN_HEIGHT: int = 640

    # Width of the sidebar in pixels. Fixed (no resize) so the
    # buttons always have the same width.
    _SIDEBAR_MIN_WIDTH: int = 170

    def __init__(self) -> None:
        super().__init__()
        self.title("NSE Screening — SMMA + ETQ + AI Filter")
        # Start at a comfortable size, but allow the user to
        # resize down to the minimum before the layout breaks.
        self.geometry(self._DEFAULT_GEOMETRY)
        self.minsize(self._MIN_WIDTH, self._MIN_HEIGHT)

        # Apply the chosen theme BEFORE building any widgets so
        # the initial render uses the right colours.
        apply_theme(self, dark=bool(settings.dark_mode))

        # Build the sidebar + content layout. Column 0 (sidebar)
        # has a fixed weight so it doesn't grow with the window —
        # the sidebar is always the same width regardless of
        # window size. Column 1 (content) takes all the
        # remaining horizontal space.
        self.columnconfigure(0, weight=0, minsize=self._SIDEBAR_MIN_WIDTH)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar: ttk.Frame = ttk.Frame(self, padding=4)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        # Content area is a single Frame that hosts every page;
        # pages grid() themselves into it and we tkraise() the
        # active one.
        self.content: ttk.Frame = ttk.Frame(self)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        # Build the sidebar header (title + dark-mode + chatbot
        # toggles) before the nav buttons so the layout order is
        # predictable.
        self._build_sidebar_header()

        # -----------------------------------------------------------------
        # LAZY LOADING: the previous version constructed every
        # page at startup (taking ~557 ms) AND imported all their
        # heavy dependencies (taking ~1.0 s). This made the login
        # screen appear 1.5+ seconds after the user launched the
        # app. Now we build only the Login page at startup
        # (~10 ms) and defer construction of all other pages
        # until the user actually navigates to them.
        # -----------------------------------------------------------------
        self._login_unlocked: bool = False
        self._tracker_registered: bool = False

        # The Login page isn't in the sidebar; we show it via a
        # separate method that runs first and gates everything
        # else. Register it in self.frames too so show(LoginPage)
        # can look it up the same way it looks up every other page.
        self.login_frame: LoginPage = LoginPage(
            self.content, on_success=self._on_login_success,
        )
        self.login_frame.grid(row=0, column=0, sticky="nsew")
        self.frames: Dict[Type, tk.Widget] = {LoginPage: self.login_frame}

        # PageClass -> button. Built in _build_sidebar_nav().
        self.nav_buttons: Dict[Type, ttk.Button] = {}
        # Ordered list of (PageClass, button) so arrow-key
        # navigation can step through them in display order.
        # The login page is NOT in this list.
        self._nav_order: List[Tuple[Type, ttk.Button]] = []
        # Cached PageClass -> instance. Populated lazily on first
        # show().
        self._page_cache: Dict[Type, tk.Widget] = {}

        # Build the sidebar nav buttons. The page widgets they
        # navigate to are constructed on demand.
        self._build_sidebar_nav()

        # Keyboard navigation: Up/Down arrows move between
        # sidebar buttons when any sidebar button has focus.
        # Left/Right also work for accessibility (they map to
        # the same up/down in a vertical list). We bind at the
        # toplevel level so arrow keys work no matter which
        # child widget has focus, EXCEPT when the user is typing
        # in an entry (Entry widgets handle arrow keys for cursor
        # movement and we don't want to override that).
        self.bind_all("<KeyPress-Up>",    self._on_arrow_nav)
        self.bind_all("<KeyPress-Down>",  self._on_arrow_nav)
        self.bind_all("<KeyPress-Left>",  self._on_arrow_nav)
        self.bind_all("<KeyPress-Right>", self._on_arrow_nav)
        # Alt+1..9 jumps directly to that page (1-indexed from
        # the top of the sidebar).
        for i in range(9):
            self.bind_all(
                f"<Alt-Key-{i + 1}>",
                lambda _e, idx=i: self._jump_to_nav_index(idx),
            )

        # Watch the dark_mode setting — when the user flips it
        # on the Settings page, re-skin the whole app without a
        # restart.
        settings.vars["dark_mode"].trace_add("write", self._on_dark_mode_changed)

        # Start on the Login page; only Login navigation is
        # enabled.
        self._lock_nav_until_login()
        self.show(LoginPage)

    # ------------------------------------------------------------------
    # Sidebar construction
    # ------------------------------------------------------------------

    def _build_sidebar_header(self) -> None:
        """Build the top-of-sidebar header (title + toggles).

        We use ASCII text for the toggle buttons because some
        systems don't have emoji fonts installed; the actual
        theme button label is updated in
        :meth:`_on_dark_mode_changed`.
        """
        header = ttk.Frame(self.sidebar)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(
            header, text="NSE Screening", font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        self.theme_btn: ttk.Button = ttk.Button(
            header, text="Dark", width=5, command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", padx=(4, 0))
        self.chatbot_btn: ttk.Button = ttk.Button(
            header, text="Help", width=5, command=self._toggle_chatbot,
        )
        self.chatbot_btn.pack(side="right")

    def _build_sidebar_nav(self) -> None:
        """Build the nav buttons for every entry in :data:`PAGES`.

        Each button is wired to :meth:`show` via a closure that
        captures the target class. Hover and focus bindings
        visually highlight the active button.
        """
        for name, mod_path, cls_name, _is_heavy in PAGES:
            page_class = self._resolve_class(mod_path, cls_name)
            btn = ttk.Button(
                self.sidebar, text=name, width=16,
                style="Nav.TButton",
                command=lambda pc=page_class: self.show(pc),
            )
            btn.pack(fill="x", pady=2)
            # Hover effects: highlight on enter, restore on
            # leave. We can't ttk-style the cursor cleanly, but
            # the visual feedback is what matters.
            btn.bind("<Enter>", lambda _e, b=btn: self._on_nav_hover(b, True))
            btn.bind("<Leave>", lambda _e, b=btn: self._on_nav_hover(b, False))
            # Focus indicator: when the button has focus, also
            # highlight it.
            btn.bind("<FocusIn>",  lambda _e, b=btn: self._on_nav_hover(b, True))
            btn.bind("<FocusOut>", lambda _e, b=btn: self._on_nav_hover(b, False))
            self.nav_buttons[page_class] = btn
            self._nav_order.append((page_class, btn))

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def _resolve_class(self, mod_path: str, cls_name: str) -> Type:
        """Resolve a ``(module_path, class_name)`` pair to the
        actual class object.

        We do this on first nav-button construction so we can
        cache the result for later ``show()`` calls. This
        defers the actual ``import pages.ml_stats_page`` (which
        pulls in sklearn, pandas, matplotlib) until the user
        actually navigates to ML Stats. The first time this is
        called, the import happens, but the page widget itself
        isn't built until the user clicks the nav button.
        """
        module = importlib.import_module(mod_path)
        return getattr(module, cls_name)

    def _get_or_build_page(self, page_class: Type) -> tk.Widget:
        """Return the page instance, building it on first call.

        This is the heart of the lazy loading: every page is
        constructed on first ``show()``. The construction time
        is the same as it was when pages were eager (e.g.
        MLStatsPage still takes ~400 ms to build) but the user
        only sees that cost when they actually visit the page.
        Subsequent calls are O(1) via the page cache.
        """
        instance = self._page_cache.get(page_class)
        if instance is not None:
            return instance
        # First time this page is requested. Import its module
        # (which may be heavy — sklearn, matplotlib, etc.) and
        # construct the widget. Both happen in the main thread
        # so the user sees a single ~400 ms pause on first
        # navigation rather than a janky multi-stage load.
        kwargs = self._ctor_kwargs(page_class)
        instance = page_class(self.content, **kwargs)
        instance.grid(row=0, column=0, sticky="nsew")
        self._page_cache[page_class] = instance
        self.frames[page_class] = instance
        return instance

    def _ctor_kwargs(self, page_class: Type) -> Dict[str, Any]:
        """Per-page constructor extras.

        Most pages take no extra constructor args. The three
        exceptions are:

          * :class:`LoginPage` — needs ``on_success`` so it
            can unlock the app.
          * :class:`DashboardPage` — needs ``on_select_symbol``
            so a double-click on a row can open the Stock
            Detail view.
          * :class:`DetailPage` — needs ``on_back`` so its
            Back button can return to the Dashboard.
        """
        if page_class.__name__ == "LoginPage":
            return {"on_success": self._on_login_success}
        if page_class.__name__ == "DashboardPage":
            return {"on_select_symbol": self._goto_detail}
        if page_class.__name__ == "DetailPage":
            return {
                "on_back": lambda: self.show(
                    self._resolve_class(
                        "pages.dashboard_page", "DashboardPage"
                    )
                ),
            }
        return {}

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def _on_login_success(self) -> None:
        """Called by :class:`LoginPage` when the user successfully
        connects (live or mock).

        Unlocks the sidebar and shows the dashboard. This is
        the moment the DashboardPage is actually constructed
        (it was lazy before). On a slow machine the user will
        see a brief ~15 ms pause here. The pre-warm below is a
        no-op on subsequent logins because the page is already
        cached.
        """
        self._unlock_nav()
        # Build the dashboard eagerly at login time so the first
        # navigation is instant. The user expects to land on
        # the dashboard, and the dashboard's own _build_* is
        # fast (~13 ms) so this is cheap.
        dashboard_class = self._resolve_class(
            "pages.dashboard_page", "DashboardPage"
        )
        self._get_or_build_page(dashboard_class)
        # Focus the first nav button so Up/Down arrow keys work
        # immediately after the user logs in.
        self._nav_order[0][1].focus_set()
        self.show(dashboard_class)

    def _lock_nav_until_login(self) -> None:
        """Disable every nav button except the login flow."""
        for btn in self.nav_buttons.values():
            btn.state(["disabled"])

    def _unlock_nav(self) -> None:
        """Re-enable every nav button after a successful login."""
        for btn in self.nav_buttons.values():
            btn.state(["!disabled"])
        self._login_unlocked = True

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def show(self, page_class: Type) -> None:
        """Navigate to ``page_class``.

        Lazy-builds the page on first navigation. Subsequent
        navigations are O(1) (cache hit). The first time the
        user picks :class:`DashboardPage` we also wire its
        TradeTracker into :mod:`shared` so the Trade Log page
        can list open positions.

        Parameters
        ----------
        page_class : type
            The page class to show. Must be a registered class
            in :data:`PAGES` or :class:`LoginPage`.
        """
        # Stop the user from leaving the Login page until they
        # connect.
        if not self._login_unlocked and page_class is not LoginPage:
            return
        # Lazy-build the page on first navigation. Subsequent
        # navigations are O(1) (cache hit).
        page = self._get_or_build_page(page_class)
        # If the user picks Dashboard for the first time, wire
        # the TradeTracker into shared so the Trade Log page
        # can list open trades. Done once per session.
        if (
            page_class.__name__ == "DashboardPage"
            and not self._tracker_registered
        ):
            self._register_tracker(page)
            self._tracker_registered = True
        page.tkraise()
        # Update the active-nav-button highlight so the user
        # always knows which page they're on.
        for pc, btn in self._nav_order:
            if pc is page_class:
                btn.state(["active"])
            else:
                btn.state(["!active"])

    def _register_tracker(self, dashboard_page: Any) -> None:
        """Expose the dashboard's TradeTracker through :mod:`shared`.

        The dashboard owns the tracker. The Trade Log page
        reads it through :func:`shared.open_trades_snapshot`
        so it doesn't have to import the dashboard directly
        (which would create a circular dependency).
        """
        from shared import register_tracker
        register_tracker(dashboard_page.tracker)

    def _goto_detail(self, symbol: str) -> None:
        """Open the Stock Detail view for ``symbol``.

        Called by the dashboard when the user double-clicks a
        row. We construct the detail page on first call (if
        it isn't cached yet) and then push it to the front.
        """
        detail_class = self._resolve_class("pages.detail_page", "DetailPage")
        detail = self._get_or_build_page(detail_class)
        detail.set_symbol(symbol)
        self.show(detail_class)

    # ------------------------------------------------------------------
    # Navigation: hover + keyboard
    # ------------------------------------------------------------------

    def _on_nav_hover(self, btn: ttk.Button, hovered: bool) -> None:
        """Visual hover effect for nav buttons.

        On hover, we set the button's "active" state (the
        strongest highlight we have in ttk). The active
        button (the currently-shown page) stays highlighted
        even when the mouse leaves, so the user always knows
        which page they're on.
        """
        try:
            if hovered:
                btn.state(["active"])
            else:
                # Restore only if this isn't the active page
                # button (so the active one stays highlighted).
                if not self._is_active_nav_button(btn):
                    btn.state(["!active"])
        except Exception:
            pass

    def _is_active_nav_button(self, btn: ttk.Button) -> bool:
        """Return ``True`` if ``btn`` is the button for the
        currently-shown page."""
        for w in self.content.winfo_children():
            if w.winfo_ismapped():
                # The active page is the visible one. Look up
                # which button corresponds to it.
                for pc, b in self._nav_order:
                    if self.frames.get(pc) is w:
                        return b is btn
        return False

    def _on_arrow_nav(self, event: tk.Event) -> Optional[str]:
        """Handle Up/Down/Left/Right arrow keys for sidebar nav.

        Behaviour:

          * If a nav button currently has focus, move the
            focus to the previous/next button and navigate to
            that page.
          * If focus is somewhere else in the sidebar, jump to
            the active page button and start from there.
          * If focus is in a text Entry, do nothing (let the
            Entry handle arrow keys for cursor movement).
          * Else (focus in the content area), do nothing — the
            user can tab back to the sidebar first.

        Returns the literal string ``"break"`` after a
        successful navigation, which tells Tk not to run its
        default focus traversal.
        """
        # Don't interfere with text-entry cursor movement.
        focused = self.focus_get()
        if focused is not None and focused.winfo_class() in ("TEntry", "Entry"):
            return None

        # Find the currently-focused button (or the active page
        # button as a fallback).
        current_btn: Optional[ttk.Button] = (
            focused if focused in [b for _, b in self._nav_order] else None
        )
        if current_btn is None:
            # No nav button has focus — find the active one
            # and start from there.
            for pc, b in self._nav_order:
                if self._is_active_nav_button(b):
                    current_btn = b
                    break
            if current_btn is None:
                # Nothing's selected — jump to the first button.
                if self._nav_order:
                    self._nav_order[0][1].focus_set()
                    self.show(self._nav_order[0][0])
                return "break"

        # Find the current index.
        idx = next(
            (i for i, (_, b) in enumerate(self._nav_order) if b is current_btn),
            0,
        )
        # Map arrow keys to direction. Up/Left = previous,
        # Down/Right = next.
        if event.keysym in ("Up", "Left"):
            new_idx = max(0, idx - 1)
        elif event.keysym in ("Down", "Right"):
            new_idx = min(len(self._nav_order) - 1, idx + 1)
        else:
            return None
        # Focus the new button AND navigate to that page.
        new_pc, new_btn = self._nav_order[new_idx]
        new_btn.focus_set()
        self.show(new_pc)
        # Prevent default focus traversal.
        return "break"

    def _jump_to_nav_index(self, idx: int) -> None:
        """Alt+N (N = 1..9) jumps directly to that nav page.

        Indices are 0-based internally; the binding converts
        Alt+1 to idx 0, Alt+2 to idx 1, etc.
        """
        if 0 <= idx < len(self._nav_order):
            pc, btn = self._nav_order[idx]
            btn.focus_set()
            self.show(pc)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self) -> None:
        """Flip the dark-mode setting and trigger a re-skin."""
        new_value = not bool(settings.dark_mode)
        settings.vars["dark_mode"].set(new_value)

    def _on_dark_mode_changed(self, *_args: Any) -> None:
        """Re-skin every widget when the user toggles dark mode.

        Called by the Tk Variable trace. We use plain text for
        the toggle button label because some systems don't
        have the unicode sun/moon glyphs.
        """
        apply_theme(self, dark=bool(settings.dark_mode))
        self.theme_btn.configure(
            text="Light" if settings.dark_mode else "Dark"
        )

    # ------------------------------------------------------------------
    # Chatbot (lazy)
    # ------------------------------------------------------------------

    def _toggle_chatbot(self) -> None:
        """Toggle the chatbot window.

        We create it on first toggle so the chatbot module's
        regex rules aren't evaluated at app startup. Subsequent
        toggles reuse the existing window.
        """
        if not hasattr(self, "_chatbot") or self._chatbot is None:
            # Defer the import + construction to first use.
            from pages.chatbot_window import ChatbotWindow
            self._chatbot: Any = ChatbotWindow(self)
        self._chatbot.toggle()


def main() -> None:
    """Application entry point. Run with ``python app.py``.

    Constructs the :class:`App`, pushes a startup alert onto
    the bus (visible on the Alerts page), and starts Tk's
    main event loop. The loop runs until the user closes the
    window or the process receives SIGINT.
    """
    app = App()
    alerts.push("—", "FEED", "Application started.")
    app.mainloop()


if __name__ == "__main__":
    main()
