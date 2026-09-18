###############################################
# bio.py - writing her own profile
#
# Two things only: the "About" box on her 2nd
# Life tab, and her Picks. Nothing here can
# reach any other tab. The 1st Life tab in
# particular stays exactly as Taymon left it.
###############################################
import os
import csv
import io
import time

import config
import corrade

ABOUT_LIMIT = 500      # characters the About box will hold


def _csv(pairs):
    """Corrade wants key,value,key,value as one CSV line."""
    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="").writerow(pairs)
    return out.getvalue()


def _tidy(text):
    """Trim each line and squeeze spaces, but keep paragraph breaks."""
    lines = [" ".join(l.split()) for l in str(text or "").replace("\r", "").split("\n")]
    out = "\n".join(lines).strip()
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out


def _backup_about():
    """Keep a copy of the About box as it is, so a bad write can be undone.
    Lives in her private memory folder, never in the repo."""
    try:
        current = read_about()
        if not current.strip():
            return
        folder = os.path.join(config.MEMORY_DIR, "profile_backups")
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        with open(os.path.join(folder, f"about_{stamp}.txt"), "w", encoding="utf-8") as f:
            f.write(current)
    except Exception as e:
        print(f"  bio: could not back up the About box: {e}")


def write_about(text):
    """Put this text in her About box. Returns (ok, message)."""
    text = _tidy(text)
    if not text:
        return False, "There's nothing to write."
    _backup_about()
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


def read_about():
    """Her About box as it is now. Empty string if unreadable."""
    target = corrade._target(config.BOT_NAME)
    if not target:
        return ""
    raw = corrade.send(corrade._auth(dict({
        "command": "getprofiledata",
        "data": "AboutText"
    }, **target)), quiet=True, timeout=30)
    cells = [str(c).strip() for c in corrade._data_cells(raw)]
    for i in range(0, len(cells) - 1, 2):
        if cells[i] == "AboutText":
            return cells[i + 1]
    return ""


def append_about(text):
    """Add text below what is already in her About box."""
    text = _tidy(text)
    if not text:
        return False, "There's nothing to add."
    current = _tidy(read_about())
    combined = (current + "\n\n" + text) if current else text
    if len(combined) > ABOUT_LIMIT:
        return False, (f"That would make my profile too long - it holds about "
                       f"{ABOUT_LIMIT} characters and this would be {len(combined)}. "
                       f"Trim it, or use !setprofile to replace the whole thing.")
    ok, msg = write_about(combined)
    return ok, ("Done, it's in my profile below what was there." if ok else msg)


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
