"""Legends in the game itself: a journal posted as a note that another player can read, and an epithet worn as a
title."""

from xania_sim.chronicle import post_note
from xania_sim.session import Profile


async def test_journal_note_and_title(new_bot):
    writer = await new_bot(Profile(cls="mage"))
    reader = await new_bot(Profile(cls="knight"))
    entry = ["Monday 9 November. Mostly Midgaard.", "My first kill: a gutter rat. " * 6, "More tomorrow."]
    assert await post_note(writer, reader.name, f"{writer.name}'s journal", entry)
    listing = await reader.do("note list", expect=r"journal|no unread")
    assert f"{writer.name}'s journal" in listing.text
    note = await reader.do("note read", expect=r"More tomorrow|No such note|no unread")
    assert "My first kill: a gutter rat." in note.text and "More tomorrow." in note.text
    r = await writer.do("title the Ratcatcher", expect=r"^Ok\.")
    assert r.complete
    who = await reader.do("who", expect=writer.name)  # "who <x>" filters by race/class/clan, not name
    assert "the Ratcatcher" in who.text
