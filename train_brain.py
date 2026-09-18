###############################################
# train_brain.py - the wiring
#
#   config.py       settings
#   persona.py      who she is
#   ai.py           the Aion connection
#   memory.py       long-term memory
#   corrade.py      the Corrade connection
#   body.py         moving, turning, animations
#   vision.py       seeing objects
#   travel.py       teleporting
#   actions.py      carrying out her decisions
#   talk.py         conversation, greetings, diary
#   phone.py        the phone chat page
#
# This file just joins them together.
###############################################

import os
import time
import random
import threading
from collections import deque

from flask import Flask, request as flask_request

import config
import persona
import memory
import corrade
import body
import vision
import travel
import actions
import talk
import phone
import sight

app = Flask(__name__)

startup_time = time.time()

# ---- RUNAWAY GUARD ----
# On a busy region, or when her own words come back at her, she can
# end up answering herself faster than anyone can stop her. Local chat
# and IMs each get their own ceiling, and only things she actually
# said are counted.
REPLY_LIMIT = 10                # replies per minute, per channel
recent_replies = {"local": deque(maxlen=REPLY_LIMIT),
                  "im": deque(maxlen=REPLY_LIMIT)}


def talking_too_much(channel):
    """True when she has hit the ceiling for this channel this minute."""
    said = recent_replies[channel]
    now = time.time()
    while said and now - said[0] > 60:
        said.popleft()
    return len(said) >= REPLY_LIMIT


def note_reply(channel):
    """She just said something - count it."""
    recent_replies[channel].append(time.time())


# ---- ROUTES FROM CORRADE ----

def from_this_machine():
    return flask_request.remote_addr in ("127.0.0.1", "::1")


# People who have just arrived and whom she has not greeted yet. If one
# of them speaks first, the pending greeting is dropped - their words
# were the hello - and she goes over to them right away instead.
pending_arrivals = {}          # plain name, lowercased -> threading.Event


def arrival_spoke(name):
    """Someone just spoke in local chat. Was she about to greet them?"""
    event = pending_arrivals.get(corrade.plain_name(name).lower())
    if event:
        event.set()


@app.route('/chat', methods=['POST'])
def handle_chat():
    """Someone spoke in local chat, near her."""
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    name = params.get('name', '')
    message = params.get('message', '')
    speaker_uuid = corrade.agent_from(params)

    if not message:
        return "OK", 200

    # Scripted objects talk in local chat too. She only answers people.
    entity = str(params.get('entity') or '').strip().lower()
    if entity and entity != "agent":
        print(f"  (ignoring {entity} chat from {name}: {message[:60]})")
        return "OK", 200

    if corrade.is_her(name):
        return "OK", 200

    if corrade.was_recently_said(message):
        print(f"  (ignoring an echo of her own words from {name})")
        return "OK", 200

    if talking_too_much("local"):
        print("  (local chat ceiling reached - staying quiet for a bit)")
        return "OK", 200

    # Away from home she is a guest, and local chat there can be a
    # crowd. She stays out of it entirely - anyone who wants her,
    # Taymon included, can IM her.
    if not corrade.is_home():
        print(f"  (away from home - ignoring local chat from {name}: "
              f"{message[:60]})")
        return "OK", 200

    corrade.remember_agent(name, speaker_uuid)
    print(f"\n>> {name}: {message}")

    arrival_spoke(name)
    threading.Thread(target=body.face,
                     kwargs={"name": name, "uuid": speaker_uuid},
                     daemon=True).start()

    # Answer on a thread of her own, so Corrade gets its acknowledgement
    # at once however long Aion takes.
    def worker():
        reply = talk.respond_to(name, message, from_phone=False,
                                speaker_name=name, channel="local",
                                speaker_uuid=speaker_uuid)
        if reply:
            note_reply("local")
            corrade.say(reply)

    threading.Thread(target=worker, daemon=True).start()
    return "OK", 200


@app.route('/im', methods=['POST'])
def handle_im():
    """Someone sent her an instant message, from anywhere on the grid."""
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    first = params.get('firstname', '')
    last = params.get('lastname', '')
    message = params.get('message', '')
    name = f"{first} {last}".strip()
    sender_uuid = corrade.agent_from(params)

    if not name or not message or corrade.is_her(name):
        return "OK", 200

    if corrade.was_recently_said(message):
        print(f"  (ignoring an echo of her own words from {name})")
        return "OK", 200

    if talking_too_much("im"):
        print("  (IM ceiling reached - staying quiet for a bit)")
        return "OK", 200

    if sender_uuid:
        corrade.remember_agent(name, sender_uuid)
    else:
        print(f"  IM: no agent key in this notification - keys were "
              f"{sorted(params.keys())}")

    print(f"\n>> {name} (IM): {message}")

    def worker():
        reply = talk.respond_to(name, message, from_phone=False,
                                speaker_name=name, channel="im",
                                speaker_uuid=sender_uuid)
        if reply:
            note_reply("im")
            corrade.say_to(name, reply, uuid=sender_uuid)

    threading.Thread(target=worker, daemon=True).start()
    return "OK", 200


@app.route('/avatars', methods=['POST'])
def handle_avatars():
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    action = str(params.get('action', '')).lower()
    uuid = corrade.agent_from(params)

    if action == "vanish":
        name = corrade.name_cache.get(uuid)
        if name and not corrade.is_her(name):
            print(f"\n  {name} left.")
            talk.note_departure(name)
        return "OK", 200

    if action != "appear":
        return "OK", 200

    if time.time() - startup_time < config.STARTUP_GRACE_SECONDS:
        print(f"  (startup grace - ignoring arrival {uuid[:8]}...)")
        return "OK", 200

    # Nobody welcomes people to a place that isn't theirs.
    if not corrade.is_home():
        print(f"  (away from home - not greeting arrival {uuid[:8]}...)")
        return "OK", 200

    print(f"\n  ARRIVAL: {uuid}")

    def worker():
        name = corrade.resolve_name(uuid)
        if not name or corrade.is_her(name):
            return
        greet = talk.due_for_greeting(name)
        if not greet:
            print(f"  {name} arrived - greeted recently, so no hello, "
                  f"but she'll go over.")

        key = corrade.plain_name(name).lower()
        spoke = threading.Event()
        pending_arrivals[key] = spoke
        try:
            # Nobody notices someone arriving the instant they rez. She
            # looks up a little while later, the way a person would -
            # unless they speak to her first, which wakes her at once.
            if config.HUMAN_TIMING:
                wait = random.uniform(config.ARRIVAL_PAUSE_MIN,
                                      config.ARRIVAL_PAUSE_MAX)
                print(f"  {name} arrived - she'll notice in about "
                      f"{int(wait)}s.")
                spoke.wait(wait)

            if spoke.is_set():
                print(f"  {name} spoke first - that was the hello. "
                      f"Going over.")
            elif greet:
                talk.greet_arrival(name, uuid=uuid)
        finally:
            pending_arrivals.pop(key, None)

        # Wander over to say hello properly.
        body.approach(name=name, uuid=uuid)

    threading.Thread(target=worker, daemon=True).start()
    return "OK", 200


@app.route('/lure', methods=['POST'])
def handle_lure():
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    print(f"\n  TELEPORT OFFER: {params}")

    threading.Thread(target=travel.handle_lure,
                     args=(params,), daemon=True).start()
    return "OK", 200


@app.route('/teleport', methods=['POST'])
def handle_teleport():
    """A teleport started, failed or finished. Logged only - the region
    it names is not trusted, since it has reported the wrong one."""
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    status = params.get('status', '')
    region = params.get('region', '')
    print(f"\n  TELEPORT: {status} {region}".rstrip())
    return "OK", 200


@app.route('/crossing', methods=['POST'])
def handle_crossing():
    """She has changed region, by teleport or by walking over a border.
    Corrade names the old and new region; parse_notification files the
    new one away as it comes through."""
    if not from_this_machine():
        return "no", 403

    params = corrade.parse_notification(flask_request.get_data(as_text=True))
    print(f"\n  MOVED: {params.get('old', '?')} -> {params.get('new', '?')} "
          f"({params.get('action', '')})")
    sight.on_landing()
    return "OK", 200


def subscribe_all():
    corrade.subscribe("local", "/chat")
    time.sleep(1)
    corrade.subscribe("message", "/im")
    time.sleep(1)
    corrade.subscribe("avatars", "/avatars")
    time.sleep(1)
    corrade.subscribe("lure", "/lure")
    time.sleep(1)
    corrade.subscribe("teleport", "/teleport")
    time.sleep(1)
    corrade.subscribe("crossing", "/crossing")


# ---- STARTUP ----

if __name__ == '__main__':
    phone.register(app, talk.respond_to)

    print("=" * 50)
    print("  TRAIN'S BRAIN - Tay's Haven AI Bot")
    print("=" * 50)
    print(f"Corrade server: {config.CORRADE_URL}")
    print(f"Group: {config.GROUP}")
    print(f"Speaking model: {config.MODEL}")
    print(f"Background model: {config.MODEL_CHEAP}")
    print(f"Memory folder: {config.MEMORY_DIR}")
    print(f"Notebook budget: {config.NOTEBOOK_TOKEN_BUDGET} tokens per message")
    print(f"Reply ceiling: {config.MAX_REPLY_TOKENS} tokens")
    print(f"Notes per message: max {config.MAX_FACTS_PER_TURN}")
    print(f"Greeting cooldown: {config.GREET_COOLDOWN_HOURS} hours")
    print(f"Sight range: {config.SCAN_RANGE}m")
    print(f"Reply ceiling: {REPLY_LIMIT} a minute in local chat, "
          f"{REPLY_LIMIT} in IMs")
    print(f"Human timing: {'on' if config.HUMAN_TIMING else 'off'}")

    if not persona.BACKSTORY.strip():
        print("NOTE: persona.py BACKSTORY is empty - she has no history yet.")

    skip = (os.path.basename(config.SELF_FILE),
            os.path.basename(config.GREET_FILE))
    people = [f for f in os.listdir(config.MEMORY_DIR)
              if f.endswith(".json") and f not in skip]
    me = memory.load_self()
    print(f"People remembered: {len(people)}")
    print(f"Self notes: {len(me.get('core', []))} core, "
          f"{len(me.get('archive', []))} archived")
    print(f"Diary entries: {len(me.get('diary', []))}")

    phone.banner()

    corrade.assume_home()
    threading.Timer(3.0, subscribe_all).start()
    threading.Thread(target=talk.diary_watcher, daemon=True).start()

    print(f"Starting web server on {config.LISTEN_HOST}:{config.LISTEN_PORT}...")
    print("Press Ctrl+C to stop.\n")
    app.run(host=config.LISTEN_HOST, port=config.LISTEN_PORT, debug=False)