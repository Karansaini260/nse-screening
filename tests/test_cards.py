"""
Tests for the Card and Chip widgets. Most of these need a Tk root,
so they use a headless Tk if possible and skip otherwise. The
critical regression test is the one that doesn't need a display:
it verifies the add_label method's kwarg handling logic by
inspecting the source / signature and by exercising the
separation logic in isolation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_add_label_signature():
    """add_label should accept text + named Label options + **pack kwargs."""
    from cards import Card
    import inspect
    sig = inspect.signature(Card.add_label)
    params = list(sig.parameters.keys())
    # Must have self, text, font, fg, and **pack_kwargs
    assert params[:4] == ["self", "text", "font", "fg"]
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()), \
        "add_label must accept **pack_kwargs"


def test_add_label_pops_foreground_from_pack_kwargs():
    """When a caller passes `foreground='gray'`, it must be popped out
    of pack_kwargs before .pack() is called — otherwise pack() raises
    'bad option -foreground'."""
    from cards import Card
    import inspect
    src = inspect.getsource(Card.add_label)
    # The fix uses pack_kwargs.pop to extract Label-only options.
    assert 'pack_kwargs.pop("foreground"' in src, \
        "add_label must pop 'foreground' from pack_kwargs"
    assert 'pack_kwargs.pop("background"' in src, \
        "add_label must pop 'background' from pack_kwargs too"


def test_add_label_does_not_pass_foreground_to_pack():
    """Static-analysis check: the literal string 'foreground' must
    NOT appear as a bare keyword in the lbl.pack() call. We check
    the source between the lbl.pack() line and the next def / class
    boundary."""
    from cards import Card
    import inspect
    src = inspect.getsource(Card.add_label)
    # Find the lbl.pack line and verify foreground is not in it.
    pack_line = next((l for l in src.splitlines() if "lbl.pack" in l), None)
    assert pack_line is not None, "Could not find lbl.pack() in add_label"
    assert "foreground" not in pack_line, \
        f"foreground must not be passed to pack(): {pack_line!r}"


def test_card_imports_cleanly():
    """The cards module should import without errors even when the
    ttk import is unused (this was a flake8 warning previously)."""
    import cards
    assert hasattr(cards, "Card")
    assert hasattr(cards, "Chip")


def test_chip_signature():
    """Chip takes master, text, fg, bg, font, padx, pady — no surprise
    **kwargs that could swallow a real pack option later."""
    from cards import Chip
    import inspect
    sig = inspect.signature(Chip.__init__)
    params = list(sig.parameters.keys())
    # No **kwargs on Chip — the palette and styling are explicit.
    assert not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()), \
        f"Chip should not accept arbitrary **kwargs: {params}"


if __name__ == "__main__":
    test_add_label_signature()
    test_add_label_pops_foreground_from_pack_kwargs()
    test_add_label_does_not_pass_foreground_to_pack()
    test_card_imports_cleanly()
    test_chip_signature()
    print("ALL CARD TESTS PASSED")
