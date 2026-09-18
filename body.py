###############################################
# body.py - everything Train physically does
#
# Where she is, turning, animations, walking.
#
# Walking is driven from here, one nudge at a
# time, the same way the Wizardry and Steamworks
# movement HUD drives Corrade as a drone. Each
# nudge is a small step that finishes straight
# away, so there is never a long command running
# that we cannot cancel.
#
# The loop is: aim at the target, nudge forward,
# check where she ended up, repeat. Stopping is
# simply not sending the next nudge.
#
# All the numbers live in config.py.
###############################################
import time
import threading

import config
import corrade

last_turn = {}
walk_lock = threading.Lock()
_cancel = threading.Event()

# Corrade starts animations by INVENTORY UUID, not by name.
# Get these from the "item" value in an inventory ls listing.
ANIM_UUIDS = {
    "stand2":       "c76a9f03-5393-4226-8be5-da6e061970be",
    "walk1":        "3ad73bd0-fd0c-48bd-b0d0-6ec39f49042c",
    "run1":         "66a8652d-c15e-4455-b649-6cbd7631c84d",
    "jump1":        "435d0a98-3a3f-4590-ab15-fc8e516b5fe3",
    "prejump2":     "7aaf0c31-1a1f-4fa1-bfef-1f3e5985781f",
    "EmmaStandup":  "a36287de-198d-4dc1-b7d6-541aa555e12a",
    "EmmaSit01":    "99b9db20-5769-4acb-a479-d791ba13d494",
    "EmmaSit02":    "1563b386-78e4-42d5-896e-41c844dbcde0",
    "EmmaSit03":    "cbbbbe42-85cf-4602-a4fc-99d0555f8c8c",
    "EmmaGSit01":   "bc9823e7-8be0-476f-a762-3c1eceb1f965",
    "EmmaGSit02":   "eed72f39-0889-43be-bb16-4ec40dfd89d4",
    "EmmaGSit03":   "1a306ecc-c2c0-4b22-a892-5593b00395d4",
    "EmmaFly":      "40a7feec-9661-4c21-97cc-69ae3c8cd340",
    "EmmaFlyUp":    "232dac46-f394-4ad0-afba-7fa875b8f33d",
    "EmmaFlyDown":  "3741fc33-684f-4299-8747-64e541df717f",
    "EmmaFloat":    "98d317c5-9b22-4889-bab2-453991f35e4c",
    "EmmaFalling":  "f3e41c6f-2ddb-4375-9bfd-dd1aa4d9d902",
    "EmmaSwimFwd":  "bd2c0249-ce7c-4aad-9b35-18e3f3c3dfb3",
    "VAVICHLAND2":  "92b77f23-76b2-4a74-af1c-18df4790a0a0",
}


def anim_id(name):
    """Corrade starts animations by inventory UUID, not by name."""
    return ANIM_UUIDS.get(name, name)


# ---------------------------------------------
# WHERE THINGS ARE
# ---------------------------------------------

def my_position():
    """Where Train is standing right now. Returns [x, y, z] or None."""
    raw = corrade.send(corrade._auth({
        "command": "getselfdata",
        "data": "SimPosition"
    }), quiet=True)
    return corrade._numbers(corrade._corrade_data(raw))


def distance_between(a, b):
    """Straight-line distance between two [x, y, z] points."""
    if not a or not b:
        return None
    return ((a[0] - b[0]) ** 2 +
            (a[1] - b[1]) ** 2 +
            (a[2] - b[2]) ** 2) ** 0.5


def ground_distance(a, b):
    """Distance across the ground, ignoring height.

    This is the one that matters for walking. Something on a deck
    three metres up is still right next to you on the map."""
    if not a or not b:
        return None
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def vicinity_for(size=None):
    """How close she needs to get to something to count as arrived.

    Big objects get a bit more room so she is not walking into their
    middle, but the allowance is capped - a 60m flagpole should not
    let her stop fifty metres short and call it arrived."""
    reach = 0.0
    if size:
        reach = max(size[0], size[1]) / 2.0
    return min(config.ARRIVES_WITHIN + reach, config.MAX_STOPPING_DISTANCE)


def find_avatar(name=None, uuid=None):
    """Look up one avatar nearby."""
    raw = corrade.send(corrade._auth({
        "command": "getavatarsdata",
        "entity": "range",
        "range": str(config.RANGE),
        "data": "FirstName,LastName,ID,ParentID,Position"
    }), quiet=True)

    records = corrade._records(corrade._corrade_data(raw))

    if not records:
        print(f"  turn: Corrade returned nothing usable. Raw reply below:")
        print(f"  {str(raw)[:500]}")
        return None

    for record in records:
        full_name = f"{record.get('FirstName', '')} {record.get('LastName', '')}".strip()
        record_id = record.get("ID", "")

        matched = False
        if uuid and record_id and record_id.lower() == str(uuid).lower():
            matched = True
        if name and full_name and full_name.lower() == str(name).lower():
            matched = True
        if not matched:
            continue

        parent = record.get("ParentID", "0").strip()
        sitting = parent not in ("", "0", "00000000-0000-0000-0000-000000000000")

        return {
            "name": full_name or name,
            "uuid": record_id or uuid,
            "position": corrade._clean_vector(record.get("Position")),
            "coords": corrade._numbers(record.get("Position")),
            "sitting": sitting
        }

    found = ", ".join(f"{r.get('FirstName', '?')} {r.get('LastName', '')}".strip()
                      for r in records)
    print(f"  turn: {name or uuid} not among those found: {found}")
    return None


# ---------------------------------------------
# TURNING
# ---------------------------------------------

def turn_to_position(position):
    """Rotate Train to face a point. Needs 'movement'."""
    if not position:
        return False
    corrade.send(corrade._auth({
        "command": "turnto",
        "position": position
    }), quiet=True)
    return True


def face(name=None, uuid=None):
    """Turn Train to face whoever just spoke."""
    if name and corrade.is_her(name):
        return False

    key = (uuid or corrade.plain_name(name)).lower()
    now = time.time()
    if key and now - last_turn.get(key, 0) < config.TURN_COOLDOWN:
        return False

    person = find_avatar(name=name, uuid=uuid)
    if not person:
        return False

    if person["sitting"]:
        print(f"  turn: {person['name']} is seated - not turning")
        return False

    if not person["position"]:
        print(f"  turn: no usable position for {person['name']}")
        return False

    turn_to_position(person["position"])
    if key:
        last_turn[key] = now
    print(f"  turn: facing {person['name']} at {person['position']}")
    return True


# ---------------------------------------------
# ANIMATIONS
# ---------------------------------------------

def list_inventory(path):
    """Ask Corrade what it sees in one of its inventory folders.
    Use this to collect the inventory UUIDs for new animations."""
    return corrade.send(corrade._auth({
        "command": "inventory",
        "action": "ls",
        "path": path
    }), quiet=True)


def _animation_command(name, action):
    return corrade.send(corrade._auth({
        "command": "animation",
        "item": anim_id(name),
        "action": action,
        "type": "inventory"
    }), quiet=True)


def start_animation(name):
    """Play an animation from Train's inventory. Needs 'grooming'."""
    return _animation_command(name, "start")


def stop_animation(name):
    """Stop an animation Train is playing."""
    return _animation_command(name, "stop")


STAND_RETRY = 30      # seconds between attempts while Corrade is not ready


def _stand_keeper():
    """Start her stand shortly after startup, then keep it going.
    Animations drop on relog or region crossing, so re-assert it.
    If Corrade is not logged in yet, keep trying rather than giving up
    for the whole session."""
    time.sleep(12)

    print(f"\n  stand: starting '{config.STAND_ANIM}'...")
    while True:
        raw = start_animation(config.STAND_ANIM)
        if corrade._succeeded(raw):
            print(f"  stand: running.\n")
            break
        print(f"  stand: not yet - {str(raw)[:120]} "
              f"(trying again in {STAND_RETRY}s)")
        time.sleep(STAND_RETRY)

    while True:
        time.sleep(config.STAND_REFRESH)
        try:
            # Don't fight the walk animation while she is on the move.
            if not walk_lock.locked():
                start_animation(config.STAND_ANIM)
        except Exception as e:
            print(f"  stand: refresh error: {e}")


threading.Thread(target=_stand_keeper, daemon=True).start()


# ---------------------------------------------
# TAKING CONTROL OF HER FEET
# ---------------------------------------------

def stop_walking():
    """Stop her. The walking loop checks this before every nudge."""
    if walk_lock.locked():
        print("  walk: stop requested.")
        _cancel.set()
        return True
    return False


def cancelled():
    """Has she been told to stop? Used between steps of a list."""
    return _cancel.is_set()


def begin_walk(timeout=10.0):
    """Take control of her feet for a walk you asked for.
    Cancels anything already running rather than queueing behind it."""
    _cancel.set()
    if not walk_lock.acquire(timeout=timeout):
        print("  walk: could not take over - the last walk is still finishing.")
        return False
    _cancel.clear()
    return True


def begin_walk_if_free():
    """Take control only if she is idle. Used for things she does
    on her own, which should never interrupt an instruction."""
    if not walk_lock.acquire(blocking=False):
        return False
    _cancel.clear()
    return True


def end_walk():
    _cancel.clear()
    try:
        walk_lock.release()
    except RuntimeError:
        pass


# ---------------------------------------------
# WALKING
# ---------------------------------------------

def nudge(direction="forward"):
    """One small step. Fire and forget - the reply does not matter,
    which is how the movement HUD uses it too."""
    corrade.send(corrade._auth({
        "command": "nudge",
        "direction": direction
    }), quiet=True, timeout=10)


def walk_to_position(position, vicinity=None, label=""):
    """Walk to a point, one nudge at a time.

    Returns: 'arrived', 'stuck', 'stopped', 'gave up', 'lost'.
    Whoever calls this must already hold the walk lock."""
    target = corrade._numbers(position)
    if not target:
        return "lost"

    if vicinity is None:
        vicinity = config.ARRIVES_WITHIN

    started = time.time()
    last_seen = None
    last_progress = time.time()
    checks = 0

    # Point her at it before the first step.
    turn_to_position(position)

    while True:
        if _cancel.is_set():
            return "stopped"

        here = my_position()
        if not here:
            return "lost"

        gap = ground_distance(here, target)
        if gap is not None and gap <= vicinity:
            return "arrived"

        # Is she actually getting anywhere?
        if last_seen is not None:
            moved = distance_between(here, last_seen) or 0
            if moved >= config.PROGRESS_METRES:
                last_progress = time.time()
            elif time.time() - last_progress >= config.STUCK_SECONDS:
                print(f"  walk: no progress for {config.STUCK_SECONDS}s - "
                      f"stuck {gap:.1f}m short{label}.")
                return "stuck"
        last_seen = here

        if time.time() - started > config.WALK_GIVES_UP_AFTER:
            return "gave up"

        # Correct her heading now and then - she drifts, and the
        # target may have moved if it is a person.
        if checks % config.REAIM_EVERY == 0:
            turn_to_position(position)
        checks += 1

        # A short burst of steps, then look again.
        for _ in range(config.NUDGES_PER_CHECK):
            if _cancel.is_set():
                return "stopped"
            nudge("forward")
            time.sleep(config.NUDGE_GAP)


# ---------------------------------------------
# WALKING TO A PERSON
# ---------------------------------------------

def approach(name=None, uuid=None, force=False, hold_lock=False,
             say=corrade.say):
    """Walk over to someone.

    force=True means you asked her to come - she drops whatever she
    was doing and comes even if you are standing close.
    force=False is her own idea, so she waits her turn.
    hold_lock=True means the caller already owns her feet.
    say is how she answers back - local chat or an IM."""
    if name and corrade.is_her(name):
        return False

    if not hold_lock:
        if force:
            if not begin_walk():
                return False
        else:
            if not begin_walk_if_free():
                print("  walk: busy - not wandering over.")
                return False

    walking = False
    try:
        person = find_avatar(name=name, uuid=uuid)
        if not person or not person["position"]:
            if force:
                say("I can't work out where you are.")
            return False

        if person["sitting"] and not force:
            print(f"  walk: {person['name']} is seated - staying put")
            return False

        here = my_position()
        gap = ground_distance(here, person["coords"])

        if gap is None:
            print("  walk: could not work out the distance - staying put")
            return False

        if not force and gap < config.APPROACH_IF_FURTHER:
            print(f"  walk: {person['name']} is {gap:.1f}m away - close enough")
            return False

        if gap > config.AVATAR_MAX_DISTANCE:
            print(f"  walk: {person['name']} is {gap:.1f}m away - too far")
            if force:
                say(f"You're {gap:.0f} metres away. "
                    f"Offer me a teleport instead?")
            return False

        print(f"  walk: heading to {person['name']}, {gap:.1f}m away...")

        # Swap her stand for the walk, or she slides along in her standing pose.
        stop_animation(config.STAND_ANIM)
        start_animation(config.WALK_ANIM)
        walking = True

        outcome = walk_to_position(person["position"],
                                   label=f" of {person['name']}")
        print(f"  walk: {outcome}.")

        if force and outcome == "stuck":
            say("I can't get to you, something's in the way.")

        return outcome == "arrived"

    finally:
        # Whatever happened, put her back on her feet.
        if walking:
            try:
                stop_animation(config.WALK_ANIM)
                start_animation(config.STAND_ANIM)
            except Exception as e:
                print(f"  walk: could not restore the stand: {e}")
        if not hold_lock:
            end_walk()