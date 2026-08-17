"""
Shared theme-subscription helper for the page modules.

Three pages used to each have their own version of the same pattern:
  * `_palette()` method returning `current_palette(bool(settings.dark_mode))`
  * `_on_theme_change(palette)` method called by the theme bus
  * The 2-line "from theme import subscribe; subscribe(self._on_theme_change)"
    boilerplate at the end of __init__.

This module centralises all of that into one decorator so the
same thing is one line per page.

Typical use:

    from pages.theme_subscribe import themed

    @themed
    class DetailPage(ttk.Frame):
        def _on_theme_change(self, palette):
            # re-skin my own widgets
            ...

After decoration:
  * `self.palette()` is available and returns the current palette.
  * `self._on_theme_change(palette)` is wired to the global theme
    bus automatically.
  * The class receives an initial palette() call right after
    construction so widgets render with the right colours from
    the very first paint.

This was extracted from the duplicate _palette / _on_theme_change
methods in dashboard_page, detail_page, and chatbot_window.

Why a decorator instead of a base class?
  Pages already inherit from ttk.Frame / ttk.Toplevel. A
  decorator works regardless of the base class and is also
  easier to read in the class definition.
"""
from functools import wraps


def themed(cls):
    """Class decorator: wires the class up to the global theme bus.

    After decoration, the class has:
      * `self.palette()` -> dict of colour tokens for the current
        dark/light mode.
      * `self._on_theme_change(palette)` -> the user's re-skin
        callback. **Must** be defined on the class — the
        decorator checks for its presence and raises a clear
        error if it's missing.
      * An initial `self._on_theme_change(self.palette())` call
        is queued via `after(0, ...)` so it runs after
        `__init__` returns. This lets the user's callback assume
        all the widgets it touches already exist.
    """
    original_init = cls.__init__

    @wraps(original_init)
    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Wire to the global theme bus. Imported here so this
        # module stays cheap to import (the theme module pulls
        # in tk, which would slow down every page import).
        from theme import subscribe
        # Late-bind `self.palette` and `self._on_theme_change`
        # so subclasses can override them if they want.
        subscribe(lambda p, _self=self: _self._on_theme_change(p))
        # Schedule the initial palette pass after __init__ returns
        # so the user's callback can assume every widget exists.
        try:
            self.after(0, lambda: self._on_theme_change(self.palette()))
        except Exception:
            # Toplevel widgets don't have after() — fall back to
            # an immediate call. The widgets have already been
            # built by the time we get here.
            self._on_theme_change(self.palette())

    def palette(self):
        """Return the current theme palette (light or dark).

        Imported lazily so importing this module doesn't pull in
        theme.py (and therefore tk) at module load time.
        """
        from shared import settings
        from theme import current_palette
        return current_palette(bool(settings.dark_mode))

    # Check the class actually defines _on_theme_change. We do
    # this here at decoration time so the user gets a clear
    # error if they forget to implement the callback.
    if not hasattr(cls, "_on_theme_change"):
        raise TypeError(
            f"@themed class {cls.__name__} must define "
            f"_on_theme_change(self, palette)"
        )

    cls.__init__ = __init__
    cls.palette = palette
    return cls
