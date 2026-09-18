###############################################
# sight.py - a glance at her surroundings
#
# She has no camera. What she has is the grid's
# own knowledge of where everything is, and this
# turns that into the kind of description a
# friend would give over the phone: who is here,
# how far, which way, what is nearby, and what
# she herself is wearing.
###############################################
import re
import math
import time
import threading

import config
import corrade
import body
import vision

PEOPLE_RANGE = 60         # metres - people further than this are "far off"
SETTLE_SECONDS = 6        # after landing, wait for the region to load
FRESH_SECONDS = 600       # how long a landing glance stays in her head

# Words that mean someone is asking her about her surroundings.
LOOK_WORDS = re.compile(
    r"\b(see|look|looking|around|nearby|near you|where (?:is|are|am|'s)|"
    r"where's|what'?s (?:here|there|that|this)|who'?s (?:here|there|around)|"
    r"who is (?:here|there|around)|find|describe|place|view|scenery)\b", re.I)
WEAR_WORDS = re.compile(
    r"\b(wearing|wear|outfit|clothes|dressed|look like|your hair|"
    r"your skin|your eyes|freckles)\b", re.I)

fresh = {"text": "", "when": 0.0}     # the glance she took on landing
NEXT_TO = 2.0             # metres - closer than this is "right next to you"
ABOVE_BELOW = 2.0         # metres of height difference worth mentioning

COMPASS = ["north", "north-east", "east", "south-east",
           "south", "south-west", "west", "north-west"]

RELATIVE = ["straight ahead", "ahead to your right", "to your right",
            "behind you to the right", "behind you",
            "behind you to the left", "to your left", "ahead to your left"]


# ---- WHERE SHE IS AND WHICH WAY SHE FACES ----

def _quaternion(text):
    found = re.findall(r"-?\d+(?:\.\d+)?", str(text or ""))
    if len(found) < 4:
        return None
    return [float(n) for n in found[:4]]


def _yaw(q):
    """Heading in radians from a rotation. 0 = east, counter-clockwise."""
    x, y, z, w = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def whereabouts():
    """Her position and heading. Returns (coords, yaw) - yaw may be None."""
    raw = corrade.send(corrade._auth({
        "command": "getselfdata",
        "data": "SimPosition,SimRotation"
    }), quiet=True, timeout=10)
    cells = corrade._corrade_data(raw)
    rec = corrade._records(cells)
    rec = rec[0] if rec else {}
    here = corrade._numbers(rec.get("SimPosition"))
    q = _quaternion(rec.get("SimRotation"))
    return here, (_yaw(q) if q else None)


def _compass(dx, dy):
    """Compass direction of a point relative to her. North is +y."""
    angle = math.degrees(math.atan2(dx, dy)) % 360     # 0 = north, clockwise
    return COMPASS[int((angle + 22.5) // 45) % 8]


def _relative(dx, dy, yaw):
    """Which way something is, relative to where she is facing."""
    if yaw is None:
        return None
    bearing = math.atan2(dy, dx) - yaw                  # radians, ccw
    degrees = (-math.degrees(bearing)) % 360            # clockwise from ahead
    return RELATIVE[int((degrees + 22.5) // 45) % 8]


def _direction(here, there, yaw):
    dx, dy = there[0] - here[0], there[1] - here[1]
    words = _relative(dx, dy, yaw) or f"to the {_compass(dx, dy)}"
    dz = there[2] - here[2]
    if dz > ABOVE_BELOW:
        words += ", up above you"
    elif dz < -ABOVE_BELOW:
        words += ", down below you"
    return words


def _distance(metres):
    if metres < NEXT_TO:
        return "right next to you"
    return f"about {metres:.0f} m away"


# ---- PEOPLE ----

def people(here, yaw):
    raw = corrade.send(corrade._auth({
        "command": "getavatarsdata",
        "entity": "range",
        "range": str(config.RANGE),
        "data": "FirstName,LastName,ID,Position,ParentID,Velocity"
    }), quiet=True, timeout=10)

    lines = []
    for rec in corrade._records(corrade._corrade_data(raw)):
        name = f"{rec.get('FirstName', '')} {rec.get('LastName', '')}".strip()
        if not name or corrade.is_her(name):
            continue
        there = corrade._numbers(rec.get("Position"))
        if not there:
            continue
        gap = body.ground_distance(here, there)
        parent = str(rec.get("ParentID", "0")).strip()
        sitting = parent not in ("", "0", "00000000-0000-0000-0000-000000000000")
        speed = corrade._numbers(rec.get("Velocity")) or [0, 0, 0]
        moving = math.hypot(speed[0], speed[1]) > 0.5

        shown = corrade.plain_name(name)
        if gap > PEOPLE_RANGE:
            lines.append(f"{shown} is far off, {_distance(gap)} "
                         f"to the {_compass(there[0]-here[0], there[1]-here[1])}.")
            continue
        state = "sitting" if sitting else ("walking about" if moving else "standing")
        lines.append(f"{shown} is {_direction(here, there, yaw)}, "
                     f"{_distance(gap)}, {state}.")
    return lines


# ---- THINGS ----

def _size_word(size):
    biggest = max(size) if size else 0
    if biggest >= 10:
        return "huge "
    if biggest >= 4:
        return "big "
    if biggest < 1:
        return "small "
    return ""


def things(here, yaw):
    lines = []
    for item in vision.named(config.LOOK_RANGE)[:config.LOOK_THINGS]:
        there = item["coords"]
        lines.append(f"a {_size_word(item['size'])}{item['name']} "
                     f"{_direction(here, there, yaw)}, {_distance(item['distance'])}")
    return lines


# ---- HERSELF ----

def wearing():
    raw = corrade.send(corrade._auth({"command": "getwearables"}),
                       quiet=True, timeout=10)
    cells = [str(c).strip() for c in corrade._corrade_data(raw)]
    worn = []
    for i in range(0, len(cells) - 1, 2):
        kind, name = cells[i], cells[i + 1]
        if kind.lower() in ("hair", "skin", "eyes", "tattoo", "shirt", "pants",
                            "jacket", "skirt", "shoes", "socks", "gloves",
                            "undershirt", "underpants", "universal"):
            worn.append(f"{kind.lower()} '{name}'")
    return worn


# ---- THE GLANCE ----

def glance(full=False):
    """One look around, as plain text. full=True adds what she is
    wearing - only wanted when someone asks about her looks."""
    here, yaw = whereabouts()
    if not here:
        return "I can't get my bearings right now."

    lines = []
    place = corrade.where_am_i()
    if place:
        lines.append(f"You are on {place}"
                     + (", at home in Tay's Haven." if corrade.is_home()
                        else ", away from home."))
    else:
        lines.append("You are somewhere you have not heard the name of yet.")

    if yaw is not None:
        facing = _compass(math.cos(yaw), math.sin(yaw))
        lines.append(f"You are facing {facing}.")

    folk = people(here, yaw)
    if folk:
        lines.append("People: " + " ".join(folk))
    else:
        lines.append("Nobody else is nearby.")

    stuff = things(here, yaw)
    if stuff:
        lines.append("Nearby: " + "; ".join(stuff) + ".")
    else:
        lines.append("Nothing named is nearby - open ground, or things "
                     "nobody bothered to name.")

    if full:
        worn = wearing()
        if worn:
            lines.append("You are wearing " + ", ".join(worn) + ".")

    return "\n".join(lines)


# ---- WHEN SHE GETS TO USE IT ----

def wants_a_look(message):
    """Is this message asking about her surroundings?"""
    return LOOK_WORDS.search(str(message or "")) is not None


def wants_her_looks(message):
    """Is this message asking what she looks like or wears?"""
    return WEAR_WORDS.search(str(message or "")) is not None


def on_landing():
    """She has just arrived somewhere. Look around once the region
    has loaded, and keep it in mind for a while."""
    def worker():
        time.sleep(SETTLE_SECONDS)
        try:
            text = glance()
        except Exception as e:
            print(f"  sight: landing glance failed: {e}")
            return
        fresh["text"] = text
        fresh["when"] = time.time()
        print("  sight: looked around after landing:\n    "
              + text.replace("\n", "\n    "))
    threading.Thread(target=worker, daemon=True).start()


def for_message(message):
    """
    The glance to hand her with this message, or None.
    A question about surroundings gets a fresh look; otherwise, a
    recent landing glance is carried for a while.
    """
    if wants_a_look(message) or wants_her_looks(message):
        try:
            return glance(full=wants_her_looks(message))
        except Exception as e:
            print(f"  sight: glance failed: {e}")
            return None
    if fresh["text"] and time.time() - fresh["when"] < FRESH_SECONDS:
        return fresh["text"]
    return None
