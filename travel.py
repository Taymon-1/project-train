###############################################
# travel.py - teleporting
#
# Accepting teleport offers, and taking herself
# somewhere on her own.
###############################################
import config
import corrade

# Where she lands when no position is given.
DEFAULT_ARRIVAL = "<128, 128, 25>"


def go_home():
    """
    Home, from anywhere.

    First choice is a landmark of home from her inventory - a landmark
    carries the grid address inside it, so it works from another grid.
    Second choice is Corrade's own gohome, which from another grid
    drops her connection and logs her back in at home a minute or two
    later. Last resort is the home region by name, which only works
    when she is already on her own grid.
    """
    print("  teleport: going home...")

    if config.HOME_LANDMARK:
        before = corrade.forget_region()
        raw = corrade.send(corrade._auth({
            "command": "teleport",
            "entity": "landmark",
            "item": config.HOME_LANDMARK
        }), quiet=True, timeout=90)
        if corrade._succeeded(raw):
            print("  teleport: home, by landmark.")
            return True
        corrade.restore_region(before)
        print(f"  teleport: landmark failed - {str(raw)[:200]}")

    before = corrade.forget_region()
    raw = corrade.send(corrade._auth({"command": "gohome"}),
                       quiet=True, timeout=90)
    if corrade._succeeded(raw):
        print("  teleport: home.")
        return True

    corrade.restore_region(before)
    print(f"  teleport: gohome failed - {str(raw)[:200]}")
    print("  teleport: trying the home region by name instead...")
    return teleport_to(config.HOME_REGION, config.HOME_POSITION)


def go_to(region, position=None):
    """Teleport by region name, with a sensible landing spot."""
    return teleport_to(region, position or DEFAULT_ARRIVAL)


def teleport_to(region, position):
    """Teleport to a position on a named region. Needs 'movement'."""
    print(f"  teleport: {region} {position}")
    before = corrade.forget_region()
    raw = corrade.send(corrade._auth({
        "command": "teleport",
        "entity": "region",
        "region": region,
        "position": position
    }), quiet=True, timeout=90)

    if corrade._succeeded(raw):
        print("  teleport: arrived.")
        return True

    corrade.restore_region(before)
    print(f"  teleport: failed - {str(raw)[:300]}")
    return False


def reply_to_lure(session, action="accept"):
    """Accept or decline a teleport offer. Needs 'movement'."""
    before = corrade.forget_region() if action == "accept" else None
    raw = corrade.send(corrade._auth({
        "command": "replytoteleportlure",
        "session": session,
        "action": action
    }), quiet=True, timeout=90)

    if corrade._succeeded(raw):
        print(f"  lure: {action}ed.")
        return True

    if before is not None:
        corrade.restore_region(before)
    print(f"  lure: {action} failed - {str(raw)[:300]}")
    return False


def is_trusted(name, uuid=""):
    """Is this someone she takes teleports from without asking?
    Taymon is known by his key; anyone else on the list by name,
    whichever grid they offered from."""
    if corrade.is_owner(uuid):
        return True
    return any(corrade.same_person(name, trusted)
               for trusted in config.TRUSTED_TELEPORTS)


def handle_lure(params):
    """Someone has offered her a teleport. Decide what to do about it."""
    session = params.get("session") or ""
    first = params.get("firstname") or ""
    last = params.get("lastname") or ""
    who = f"{first} {last}".strip()
    uuid = corrade.agent_from(params)

    if uuid:
        corrade.remember_agent(who, uuid)

    if not session:
        print(f"  lure: no session in the notification - {params}")
        return

    if is_trusted(who, uuid):
        print(f"  lure: from {who} - accepting.")
        corrade.say("On my way.")
        reply_to_lure(session, "accept")
        return

    print(f"  lure: from {who} - not on the trusted list, declining.")
    corrade.say_to(who, f"Thanks {first}, but I'll stay put for now.",
                   uuid=uuid)
    reply_to_lure(session, "decline")