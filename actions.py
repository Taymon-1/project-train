###############################################
# actions.py - carrying out what she decides
#
# Reads the "do" field from her reply and makes
# it happen. Several things can be given at once,
# separated by semicolons, and they run in order.
#
# A new instruction cancels whatever she was
# doing before rather than queueing behind it.
###############################################
import re
import threading

import config
import corrade
import body
import vision
import travel

# Outcomes that mean there is no point carrying on down the list.
ABANDON_LIST = {"stuck", "stopped", "gave up", "lost",
                "not found", "too many", "too far"}

# Phrases that show someone actually asked her to move.
COME_PATTERN = re.compile(
    r"\b(come|here|follow|over|closer|to me|towards? me|find me|join me)\b", re.I)
MOVE_PATTERN = re.compile(
    r"\b(walk|go|goto|head|move|run|get|make your way|stroll|wander)\b", re.I)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def asked_for(step, message):
    """
    Did the message she is answering actually ask for this move?

    Aion gets into habits - after being sent home three times it
    starts putting "home" in every answer, so she teleports off on a
    plain "hi". A move only counts when the message itself asked for
    it: "home" needs the word home, "come" needs come/here/to me, and
    walking to a thing needs either the thing named or a plain
    movement word like walk or go.
    """
    lowered = step.lower()
    text = str(message or "")
    said = _words(text)

    if lowered in ("home", "go home", "goto home"):
        return "home" in said

    if lowered in ("come", "come here", "follow"):
        return COME_PATTERN.search(text) is not None

    if lowered.startswith("goto"):
        # A short walk is harmless, so this only has to catch the
        # habit case: a bare greeting with no hint of movement in it.
        target = _words(step[4:])
        if target & said or MOVE_PATTERN.search(text):
            return True
        return len(said) > 2

    return True


HOME_SPOT_RADIUS = 6.0     # metres - closer than this to the couch is "home"


def _at_home_spot():
    """On the home region AND standing near the home spot. Being on
    Welcome but off at the far end after a wander is not home."""
    if not corrade.is_home():
        return False
    here = body.my_position()
    spot = corrade._numbers(config.HOME_POSITION)
    if not here or not spot:
        return False
    gap = body.ground_distance(here, spot)
    return gap is not None and gap <= HOME_SPOT_RADIUS


def _voice(channel, speaker, speaker_uuid):
    """How she answers back about a move: where the request came from."""
    if channel == "im":
        return lambda text: corrade.say_to(speaker, text, uuid=speaker_uuid)
    return corrade.say


def _one_step(text, speaker, speaker_uuid, say):
    """Do a single thing. Returns an outcome word."""
    lowered = text.lower()

    if lowered in ("home", "go home", "goto home"):
        return "arrived" if travel.go_home() else "lost"

    if lowered in ("come", "come here", "follow"):
        if not speaker and not speaker_uuid:
            say("I'm not sure where you are.")
            return "lost"
        # The key finds him whatever grid-flavoured name he arrived under.
        got_there = body.approach(name=speaker, uuid=speaker_uuid,
                                  force=True, hold_lock=True, say=say)
        return "arrived" if got_there else "stuck"

    if lowered.startswith("goto"):
        target = text[4:].strip()
        if not target:
            return "lost"
        return vision.goto(target, say=say)

    print(f"  action: don't know how to '{text}'")
    return "lost"


def _run(instruction, speaker=None, speaker_uuid=None, message="",
         channel="local"):
    """Do everything she asked for, in order. Runs on its own thread."""
    text = str(instruction or "").strip()
    lowered = text.lower()
    say = _voice(channel, speaker, speaker_uuid)

    if lowered in ("stop", "halt", "wait"):
        if not body.stop_walking():
            say("I'm not going anywhere.")
        return

    steps = [part.strip() for part in text.split(";") if part.strip()]

    kept = []
    for step in steps:
        if step.lower() in ("home", "go home", "goto home") and _at_home_spot():
            print("  action: 'home' dropped - she is already at the home spot.")
        elif not asked_for(step, message):
            print(f"  action: '{step}' dropped - nobody asked for it "
                  f"(message was: {str(message)[:60]})")
        else:
            kept.append(step)
    steps = kept
    if not steps:
        return

    # Take over her feet once for the whole list, so a second step
    # never has to fight the first one for control.
    if not body.begin_walk():
        say("Hang on, I can't seem to stop what I'm doing.")
        return

    try:
        for number, step in enumerate(steps, start=1):
            if body.cancelled():
                print("  action: cancelled - dropping the rest of the list.")
                return

            if len(steps) > 1:
                print(f"  action: step {number} of {len(steps)} - {step}")

            outcome = _one_step(step, speaker, speaker_uuid, say)

            if outcome in ABANDON_LIST:
                remaining = len(steps) - number
                if remaining > 0:
                    print(f"  action: {outcome} - dropping "
                          f"{remaining} remaining step(s).")
                return

    finally:
        body.end_walk()


def perform(instruction, speaker=None, speaker_uuid=None, message="",
            channel="local"):
    """Called after she has spoken. Never blocks."""
    if not str(instruction or "").strip():
        return
    print(f"  action: {instruction}")
    threading.Thread(target=_run,
                     args=(instruction, speaker, speaker_uuid, message,
                           channel),
                     daemon=True).start()


def stop_everything():
    """Used when you say stop in local chat - no waiting on the AI."""
    return body.stop_walking()