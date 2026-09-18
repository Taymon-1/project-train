###############################################
# vision.py - seeing objects, and walking to one
###############################################
import re

import config
import corrade
import body

# Default names carry no meaning, so they are not searchable targets.
UNNAMED = {"", "object", "primitive"}

# Words she may use that describe a thing rather than name it.
DESCRIBERS = {"small", "little", "big", "large", "huge", "tiny", "the", "a",
              "an", "that", "this", "one", "nearest", "closest", "far"}


def _flatten(text):
    """'flag pole', 'Flag-Pole' and 'flagpole' all come out the same."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w]


_SKIP = {_flatten(name) for name in UNNAMED}


def scan(radius=None):
    """Everything she can see. Nearest first."""
    if radius is None:
        radius = config.SCAN_RANGE

    here = body.my_position()
    if not here:
        print("  scan: could not work out where she is")
        return []

    raw = corrade.send(corrade._auth({
        "command": "getobjectsdata",
        "entity": "range",
        "range": str(radius),
        "data": "Properties.Name,Position,Scale,ID"
    }), quiet=True, timeout=60)

    records = corrade._records(corrade._corrade_data(raw))
    if not records:
        print(f"  scan: nothing usable came back - {str(raw)[:200]}")
        return []

    seen = []
    for record in records:
        coords = corrade._numbers(record.get("Position"))
        if not coords:
            continue

        # Attachments worn by avatars report tiny local coordinates,
        # so they land far outside the radius and drop out here.
        gap = body.distance_between(here, coords)
        if gap is None or gap > radius + 5:
            continue

        seen.append({
            "name": str(record.get("Properties.Name", "")).strip(),
            "coords": coords,
            "size": corrade._numbers(record.get("Scale")) or [0, 0, 0],
            "uuid": str(record.get("ID", "")).strip(),
            # How far she would have to walk, not how far away it is.
            "distance": body.ground_distance(here, coords)
        })

    seen.sort(key=lambda item: item["distance"])
    print(f"  scan: {len(seen)} objects within {radius}m")
    return seen


def named(radius=None):
    """Only the objects you have actually given a name to."""
    return [item for item in scan(radius)
            if _flatten(item["name"]) not in _SKIP]


def find(search, radius=None):
    """
    Named objects that fit what she asked for, nearest first.

    She rarely uses a thing's exact name. "forked tree" should find
    "Forked Spring Tree Newly Leafed", "cappuccino cup" should find
    "grande cup of cappuccino", and "small chair" should find "chair"
    even though "small" was a description, not part of the name.
    So: first the whole phrase, then every word she used, then every
    word that is not just a description, then any one of them.
    """
    items = named(radius)
    phrase = _flatten(search)
    if not phrase:
        return []

    hits = [i for i in items if phrase in _flatten(i["name"])]
    if hits:
        return hits

    words = _words(search)
    plain = [w for w in words if w not in DESCRIBERS] or words
    for wanted in (words, plain):
        hits = [i for i in items
                if all(w in _flatten(i["name"]) for w in wanted)]
        if hits:
            return hits

    return [i for i in items if any(w in _flatten(i["name"]) for w in plain)]


def goto(search, say=corrade.say):
    """Walk to a named object. Assumes the walk lock is already held.
    'say' is how she speaks back - local chat or an IM.

    Returns one of: 'arrived', 'stuck', 'stopped', 'gave up', 'lost',
    'not found', 'too far'."""
    matches = find(search)

    if not matches:
        say(f"I can't see anything called {search} from here.")
        return "not found"

    # Several fit? The nearest one is the one anyone would mean.
    target = matches[0]
    if len(matches) > 1:
        print(f"  goto: {len(matches)} things fit '{search}' - "
              f"taking the nearest, {target['name']}")

    if target["distance"] > config.OBJECT_MAX_DISTANCE:
        say(f"The {target['name']} is {target['distance']:.0f} "
            f"metres away. That's a long walk.")
        return "too far"

    # Walk at the thing's own height and let the simulator handle any
    # climb, the same as holding the forward key.
    destination = (f"<{target['coords'][0]}, "
                   f"{target['coords'][1]}, {target['coords'][2]}>")

    vicinity = body.vicinity_for(target["size"])

    print(f"  goto: {target['name']} at {destination}, "
          f"{target['distance']:.1f}m away, stopping within {vicinity:.1f}m")

    walking = False
    try:
        body.stop_animation(config.STAND_ANIM)
        body.start_animation(config.WALK_ANIM)
        walking = True

        outcome = body.walk_to_position(destination, vicinity=vicinity,
                                        label=f" of the {target['name']}")
        print(f"  goto: {outcome}.")

        if outcome == "stuck":
            say(f"I'm stuck trying to get to the {target['name']}. "
                f"Something's in my way.")
        elif outcome in ("gave up", "lost"):
            say(f"I couldn't get to the {target['name']}.")

        return outcome

    finally:
        if walking:
            try:
                body.stop_animation(config.WALK_ANIM)
                body.start_animation(config.STAND_ANIM)
            except Exception as e:
                print(f"  goto: could not restore the stand: {e}")