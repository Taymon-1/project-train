###############################################
# corrade.py - the connection to Corrade
#
# Sending commands, authentication, subscribing,
# speaking, typing, reading profiles, knowing
# where she is, and unpicking Corrade's replies.
###############################################
import re
import csv
import json
import time
import random
import urllib.parse
from collections import deque

import requests

import config

name_cache = {}        # uuid -> name
uuid_by_name = {}      # lowercase name -> uuid

recent_said = deque(maxlen=20)

PROFILE_FIELDS = ["AboutText", "FirstLifeText", "LanguagesText",
                  "SkillsText", "WantToText", "ProfileURL"]

PROFILE_LABELS = [("AboutText", "About"),
                  ("FirstLifeText", "Real life"),
                  ("LanguagesText", "Languages"),
                  ("SkillsText", "Skills"),
                  ("WantToText", "Looking to"),
                  ("ProfileURL", "Web")]

PROFILE_MAX_AGE = 86400        # a profile she has read is good for a day
PROFILE_RETRY_AFTER = 300      # a read that failed is tried again after this
PROFILE_MAX_CHARS = 1200

profile_cache = {}
region_cache = {"name": "", "when": 0.0, "moved": False}


def send(params, quiet=False, timeout=45):
    """Send one command to Corrade. Returns the raw response text."""
    try:
        response = requests.post(
            config.CORRADE_URL,
            json=params,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        if not quiet:
            print(f"  Corrade status: {response.status_code}")
            print(f"  Corrade response: {response.text[:300]}")
        return response.text
    except Exception as e:
        print(f"  ERROR talking to Corrade: {e}")
        return None


def _auth(extra):
    """Add the group and password every command needs."""
    params = {"group": config.GROUP, "password": config.PASSWORD}
    params.update(extra)
    return params


def subscribe(notification_type, path):
    print(f"Subscribing to {notification_type}...")
    result = send(_auth({
        "command": "notify",
        "action": "set",
        "type": notification_type,
        "URL": f"http://127.0.0.1:{config.LISTEN_PORT}{path}"
    }))
    if result and "true" in result.lower():
        print(f"SUCCESS - listening for {notification_type}!")
    else:
        print(f"Subscribe result for {notification_type} - check above.")


# ---------------------------------------------
# WHO IS WHO
# ---------------------------------------------
# Hypergrid visitors arrive as "First Last @grid.com:8002", and some
# grids render the same person as "First.Last @grid.com:8002". Keeping
# their UUID and using that sidesteps the whole problem - a key is a
# key, wherever the person came from.

def plain_name(name):
    """A name with the grid, dots and extra spacing taken off."""
    text = str(name or "").strip()
    if "@" in text:
        text = text.split("@", 1)[0]
    text = text.replace(".", " ")
    return " ".join(text.split())


def same_person(one, two):
    """Do these two names refer to the same person?"""
    return plain_name(one).lower() == plain_name(two).lower()


def is_her(name):
    """Is this her own name, in any grid's spelling of it?"""
    return same_person(name, config.BOT_NAME)


def is_owner(uuid):
    """Is this Taymon? Judged by key, never by name - a name can be
    typed by anyone on any grid, a key cannot."""
    return bool(uuid) and str(uuid).strip().lower() == config.OWNER_UUID.lower()


def remember_agent(name, uuid):
    """File away a name and its UUID as they come past."""
    name = str(name or "").strip()
    uuid = str(uuid or "").strip()
    if not name or not uuid:
        return
    uuid_by_name[name.lower()] = uuid
    name_cache[uuid] = name


def key_for(name):
    """The UUID for a name, if we have seen it. None otherwise."""
    return uuid_by_name.get(str(name or "").strip().lower())


def _target(name, uuid=None):
    """How to address someone: by key if we have one, else by name."""
    uuid = str(uuid or "").strip() or key_for(name)
    if uuid:
        return {"agent": uuid}

    text = str(name or "").strip()
    if "@" in text or ":" in text:
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    return {"firstname": parts[0], "lastname": " ".join(parts[1:])}


def _tidy(text):
    """A message boiled down for comparing one to another."""
    return " ".join(str(text or "").lower().split())


def was_recently_said(text):
    """Did she say this herself in the last few messages?"""
    return _tidy(text) in recent_said


# ---------------------------------------------
# TYPING AND PACING
# ---------------------------------------------

def typing(on):
    """Show or clear the typing indicator. Local chat only."""
    if not config.TYPING_INDICATOR:
        return
    send(_auth({
        "command": "typing",
        "action": "enable" if on else "disable"
    }), quiet=True, timeout=6)


def pace(started, channel, text="", speaker=""):
    """
    Wait until enough time has passed for this to look typed rather
    than generated. Time already spent waiting on Aion counts, so a
    slow answer is never delayed twice. Taymon knows exactly what she
    is and would rather have her quick, so he is exempt.
    """
    if not config.HUMAN_TIMING:
        return
    if (not config.PACE_FOR_OWNER and speaker
            and same_person(speaker, config.OWNER_NAME)):
        return

    if channel == "im":
        think = random.uniform(config.IM_PAUSE_MIN, config.IM_PAUSE_MAX)
    else:
        think = random.uniform(config.LOCAL_PAUSE_MIN, config.LOCAL_PAUSE_MAX)

    typed = len(str(text or "")) / max(1.0, config.TYPING_SPEED)
    target = min(think + typed, config.MAX_PAUSE)
    left = target - (time.time() - started)
    if left > 0:
        print(f"  pacing: waiting {left:.1f}s before speaking")
        time.sleep(left)


def say(message):
    """Speak in local chat."""
    print(f"  Train says: {message}")
    recent_said.append(_tidy(message))
    send(_auth({
        "command": "tell",
        "entity": "local",
        "type": "Normal",
        "message": message
    }), quiet=True)


def say_to(name, message, uuid=None):
    """Send an instant message to one person."""
    target = _target(name, uuid)
    if not target:
        print(f"  IM: no way to address '{name}' - no key and no usable name.")
        return False

    print(f"  Train IMs {name}: {message}")
    recent_said.append(_tidy(message))
    raw = send(_auth(dict({
        "command": "tell",
        "entity": "avatar",
        "message": message
    }, **target)), quiet=True)

    if _succeeded(raw):
        return True

    print(f"  IM: failed - {str(raw)[:200]}")
    return False


# ---------------------------------------------
# WHERE SHE IS
# ---------------------------------------------
# Corrade puts a region into most notifications, but it is not always
# HERS. An instant message carries the sender's region, and an arrival
# carries the arriving avatar's. Two things are hers: local chat, which
# she heard with her own ears, and the teleport notification, which
# says where she just landed.
#
# The moment she teleports the old region is forgotten, so she is never
# standing on someone else's land believing she is home.

def note_region(name):
    """Remember the region she is standing on."""
    name = str(name or "").strip()
    if not name:
        return
    if name != region_cache["name"]:
        print(f"  REGION: she is on {name}")
    region_cache["name"] = name
    region_cache["when"] = time.time()


def assume_home():
    """At startup, before anything has told her where she is. She
    always logs in at home, and the first thing she hears will
    correct this if it is wrong."""
    if not region_cache["name"] and not region_cache["moved"]:
        region_cache["name"] = config.HOME_REGION
        print(f"  REGION: assuming home ({config.HOME_REGION}) until told otherwise")


def forget_region():
    """She is about to teleport. Returns the old state, in case the
    teleport fails and it has to be put back."""
    before = dict(region_cache)
    region_cache["name"] = ""
    region_cache["moved"] = True
    print("  REGION: teleporting - waiting to hear where she lands")
    return before


def restore_region(before):
    """The teleport did not happen - she is still where she was."""
    region_cache.update(before)


def where_am_i():
    """The region she is on, as last heard. Empty if never seen."""
    return region_cache["name"]


def is_home():
    """True when she is standing on her own home region.

    Unknown counts as home only before she has ever teleported - she
    logs in at home. After a teleport, unknown means away."""
    here = where_am_i()
    if not here:
        return not region_cache["moved"]
    return same_person(here, config.HOME_REGION)


def parse_notification(body):
    """Corrade sends either JSON or form-encoded. Handle both."""
    try:
        params = json.loads(body)
    except Exception:
        raw = dict(urllib.parse.parse_qs(urllib.parse.unquote(body)))
        params = {k: v[0] if isinstance(v, list) else v
                  for k, v in raw.items()}
    if not isinstance(params, dict):
        return params

    kind = str(params.get("type") or params.get("notification") or "").lower()
    if kind == "local":
        note_region(params.get("region"))
    elif kind == "crossing":
        # Fires on every region change, teleports included, and names
        # the place she left and the place she reached.
        note_region(params.get("new"))
    return params


def agent_from(params):
    """Pull the sender's UUID out of a notification, whatever it's called."""
    for key in ("agent", "id", "uuid", "key", "owner"):
        value = str(params.get(key) or "").strip()
        if re.fullmatch(r"[0-9a-fA-F-]{36}", value):
            return value
    return ""


# ---------------------------------------------
# READING WHAT COMES BACK
# ---------------------------------------------

def _succeeded(raw):
    """Did Corrade say the command worked?"""
    if not raw:
        return False
    return '"success":"True"' in raw.replace(" ", "")


def _merge_vectors(cells):
    """A position like <128, 129, 25> can arrive split across three cells."""
    merged = []
    buffer = None
    for cell in cells:
        cell = str(cell).strip()
        if buffer is not None:
            buffer += ", " + cell
            if ">" in cell:
                merged.append(buffer)
                buffer = None
            continue
        if cell.startswith("<") and ">" not in cell:
            buffer = cell
        else:
            merged.append(cell)
    if buffer is not None:
        merged.append(buffer)
    return merged


def _parsed(raw):
    """Corrade's reply as a dict, whichever format it arrived in."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = dict(urllib.parse.parse_qs(urllib.parse.unquote(raw)))
        parsed = {k: v[0] if isinstance(v, list) else v for k, v in parsed.items()}
    return parsed if isinstance(parsed, dict) else {}


def _data_cells(raw):
    """The 'data' field as plain cells, with no vector merging."""
    data = _parsed(raw).get("data")
    if data is None:
        return []
    if isinstance(data, str):
        try:
            return next(csv.reader([data]))
        except Exception:
            return data.split(",")
    if isinstance(data, list):
        return [str(d) for d in data]
    return []


def _corrade_data(raw):
    """The 'data' field as a flat list of strings, vectors rejoined."""
    return _merge_vectors(_data_cells(raw))


def _records(flat):
    """Corrade returns key,value,key,value... per item. Split into dicts."""
    records = []
    current = {}
    for i in range(0, len(flat) - 1, 2):
        key = str(flat[i]).strip()
        value = str(flat[i + 1]).strip()
        if key in current:
            records.append(current)
            current = {}
        current[key] = value
    if current:
        records.append(current)
    return records


def _numbers(text):
    """Pull the three numbers out of a vector string."""
    found = re.findall(r"-?\d+(?:\.\d+)?", str(text))
    if len(found) < 3:
        return None
    return [float(n) for n in found[:3]]


def _clean_vector(text):
    """Return a tidy <x, y, z> string."""
    nums = _numbers(text)
    if not nums:
        return None
    return f"<{nums[0]}, {nums[1]}, {nums[2]}>"


def resolve_name(uuid):
    """Turn an avatar UUID into a name. Cached."""
    if not uuid:
        return None
    if uuid in name_cache:
        return name_cache[uuid]
    raw = send(_auth({
        "command": "batchavatarkeytoname",
        "avatars": uuid
    }), quiet=True)
    if not raw:
        return None
    name = None
    try:
        parsed = json.loads(raw)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, str):
            data = [p.strip() for p in data.split(",")]
        if isinstance(data, list):
            flat = [str(d).strip() for d in data]
            for i, item in enumerate(flat):
                if item.lower() == uuid.lower() and i + 1 < len(flat):
                    name = flat[i + 1]
                    break
            if not name:
                for item in flat:
                    if re.fullmatch(r"[A-Za-z][\w'-]* [A-Za-z][\w'-]*", item):
                        name = item
                        break
    except Exception:
        pass
    if not name:
        text = urllib.parse.unquote(raw)
        match = re.search(r"\b([A-Z][\w'-]+ [A-Z][\w'-]+)\b", text)
        if match:
            name = match.group(1)
    if name:
        remember_agent(name, uuid)
        print(f"  resolved {uuid[:8]}... -> {name}")
    else:
        print(f"  COULD NOT RESOLVE {uuid} from: {raw[:200]}")
    return name


# ---------------------------------------------
# PROFILES
# ---------------------------------------------

def get_profile(name, force=False, uuid=None):
    """
    Read someone's profile. Returns tidy text, or None when the
    profile is empty or could not be read. Cached for a day.
    """
    target = _target(name, uuid)
    if not target:
        print(f"  PROFILE: no way to look up '{name}'.")
        return None

    key = target.get("agent") or str(name).strip().lower()
    cached = profile_cache.get(key)
    if cached and not force:
        age = time.time() - cached[0]
        keep_for = PROFILE_MAX_AGE if cached[1] else PROFILE_RETRY_AFTER
        if age < keep_for:
            return cached[1]

    print(f"  PROFILE: reading {name}...")
    raw = send(_auth(dict({
        "command": "getprofiledata",
        "data": ",".join(PROFILE_FIELDS)
    }, **target)), quiet=True)

    if not _succeeded(raw):
        print(f"  PROFILE: failed - {str(raw)[:200]}")
        profile_cache[key] = (time.time(), None)
        return None

    cells = [str(c).strip() for c in _data_cells(raw)]
    fields = {}
    for i in range(0, len(cells) - 1, 2):
        field, value = cells[i], cells[i + 1]
        if value:
            fields[field] = value

    lines = []
    for field, label in PROFILE_LABELS:
        value = fields.get(field)
        if value:
            lines.append(f"{label}: {value}")

    if not lines:
        print(f"  PROFILE: {name} has an empty profile.")
        profile_cache[key] = (time.time(), None)
        return None

    text = f"Profile of {name}:\n" + "\n".join(lines)
    text = text[:PROFILE_MAX_CHARS]
    print(f"  PROFILE: got {len(text)} characters for {name}")
    profile_cache[key] = (time.time(), text)
    return text