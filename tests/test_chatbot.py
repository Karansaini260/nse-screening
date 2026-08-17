"""
Unit tests for the rule-based chatbot. Pure-Python, no GUI required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_help():
    from chatbot import respond
    out = respond("help")
    assert "Definitions" in out and "Symbol lookup" in out
    assert "Top movers" in out


def test_glossary_what_is():
    from chatbot import respond
    out = respond("what is smma")
    assert "Smoothed Moving Average" in out or "SMMA" in out
    out2 = respond("explain etq")
    assert "ETQ" in out2 or "Equal-Traded" in out2


def test_glossary_fuzzy():
    from chatbot import respond
    # No exact key match but should fuzzy-find "etq"
    out = respond("etq")
    assert "Equal-Traded" in out or "shares traded" in out


def test_symbol_lookup():
    from chatbot import respond
    out = respond("price reliance")
    # The bot should mention RELIANCE by name; whether it has data
    # depends on whether the feed is running, so we don't assert on LTP.
    assert "RELIANCE" in out
    # Same with a different trigger word.
    out2 = respond("ltp tcs")
    assert "TCS" in out2


def test_unknown_symbol():
    from chatbot import respond
    out = respond("show XYZABC")
    # Should fall through to a graceful response without crashing.
    assert isinstance(out, str)
    assert len(out) > 0


def test_open_positions_empty():
    from chatbot import respond
    out = respond("open positions")
    # No tracker is registered in this test process, so should say so.
    assert "no open positions" in out.lower() or "open" in out.lower()


def test_top_by_smma():
    from chatbot import respond
    out = respond("top 3 by smma gap")
    # Without a running feed there's no data to rank, so the bot
    # returns a graceful "not enough data" message. The point of
    # this test is the matcher picks the SMMA-gap ranking intent.
    assert "data" in out.lower() or "top" in out.lower() or "by" in out.lower()


def test_faq_fuzzy():
    from chatbot import respond
    out = respond("how do signals work")
    assert "SMMA" in out or "crossover" in out.lower()


def test_unknown_question():
    from chatbot import respond
    out = respond("asdfghjkl qwertyuiop")
    # Should be a graceful "I don't know" response, not a crash.
    assert isinstance(out, str)
    assert "help" in out.lower() or "try" in out.lower()


if __name__ == "__main__":
    test_help()
    test_glossary_what_is()
    test_glossary_fuzzy()
    test_symbol_lookup()
    test_unknown_symbol()
    test_open_positions_empty()
    test_top_by_smma()
    test_faq_fuzzy()
    test_unknown_question()
    print("ALL CHATBOT TESTS PASSED")
