###############################################
# bio.py - writing her own profile
#
# Two things only: the "About" box on her 2nd
# Life tab, and her Picks. Nothing here can
# reach any other tab. The 1st Life tab in
# particular stays exactly as Taymon left it.
###############################################
import csv
import io

import corrade

ABOUT_LIMIT = 500      # characters the About box will hold


def _csv(pairs):
    """Corrade wants key,value,key,value as one CSV line."""
    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="").writerow(pairs)
    return out.getvalue()


def write_about(text):
    """Put this text in her About box. Returns (ok, message)."""
    text = " ".join(str(text or "").split())
    if not text:
        return False, "There's nothing to write."
    clipped = len(text) > ABOUT_LIMIT
    text = text[:ABOUT_LIMIT]

    raw = corrade.send(corrade._auth({
        "command": "setprofiledata",
        "data": _csv(["AboutText", text])       # the only field, ever
    }), quiet=True, timeout=30)

    if corrade._succeeded(raw):
        corrade.profile_cache.clear()           # so a re-read sees the new text
        note = " (It ran long, so I trimmed it to fit.)" if clipped else ""
        return True, "Done, it's in my profile now." + note
    print(f"  bio: about failed - {str(raw)[:200]}")
    return False, "That didn't take - the console has the reason."


def add_pick(name, description=""):
    """Add a Pick for the spot she is standing on. Returns (ok, message)."""
    name = " ".join(str(name or "").split())[:60]
    description = " ".join(str(description or "").split())[:ABOUT_LIMIT]
    if not name:
        return False, "A pick needs a name."

    params = {"command": "addpick", "name": name}
    if description:
        params["description"] = description
    raw = corrade.send(corrade._auth(params), quiet=True, timeout=30)

    if corrade._succeeded(raw):
        return True, f"Added '{name}' to my picks."
    print(f"  bio: addpick failed - {str(raw)[:200]}")
    return False, "That pick didn't take - the console has the reason."


def delete_pick(name):
    """Remove a Pick by name. Returns (ok, message)."""
    name = " ".join(str(name or "").split())
    if not name:
        return False, "Which pick?"
    raw = corrade.send(corrade._auth({
        "command": "deletepick",
        "name": name
    }), quiet=True, timeout=30)
    if corrade._succeeded(raw):
        return True, f"Removed '{name}' from my picks."
    print(f"  bio: deletepick failed - {str(raw)[:200]}")
    return False, "I couldn't remove that one - the console has the reason."
