###############################################
# talk.py - the thinking layer
#
# Conversation, greetings, searching, reading
# links and profiles, and the diary. This is where
# Aion gets asked things and where memory is written.
###############################################
import os
import re
import json
import time
import threading
from datetime import datetime

import config
import persona
import ai
import memory
import corrade
import actions
import travel
import websearch
import sight

conversation = []          # short-term chat buffer
session_lines = []         # transcript waiting for the diary
last_message_time = 0.0
session_lock = threading.Lock()

HELP_TEXT = ("Say stop any time and I'll stop walking. "
             "Admin: !memory, !self, !diary, !tidy, !search TEXT, "
             "!read URL, !profile NAME, !tp REGION, !where, !look, !time, !help. "
             "Everything else, just ask me normally.")

URL_PATTERN = re.compile(r'(https?://[^\s<>"\']+|www\.[^\s<>"\']+)', re.I)

PROFILE_HEADER = ("You do not know this person yet, so you glanced at their "
                  "profile before answering - the way anyone would. Use it if "
                  "there is something worth using. Do not read it back to them "
                  "and do not mention that you looked.")

SIGHT_HEADER = ("You looked around. This is what is actually there right now; "
                "directions are from where you are facing. Use it the way "
                "anyone would - mention what matters, do not read it out as "
                "a list.")

# Which way the words came, and who else can hear them.
CHANNEL_NOTES = {
    "local": ("This came to you in local chat. Anyone standing nearby can "
              "read it and can read whatever you say back."),
    "im": ("This came to you privately, as an instant message. Only you and "
           "the sender can see it, and they may not even be in the same "
           "region as you - so do not talk as though they are standing "
           "in front of you unless you know they are."),
}

# What she might put in the "profile" field instead of a name.
SELF_WORDS = {"me", "myself", "my profile", "my own profile", "my own"}
THEM_WORDS = {"him", "her", "them", "you", "this person",
              "their profile", "your profile"}


# ---- THE CLOCK ----

def _clock_line():
    now = datetime.now()
    stamp = now.strftime("%A %d %B %Y, %I:%M %p").replace(" 0", " ")
    return f"Right now it is {stamp}."


def _ago(when):
    """Turn a stored timestamp into plain words. None if unusable."""
    if not when:
        return None
    try:
        then = datetime.fromisoformat(str(when))
    except Exception:
        return None

    seconds = (datetime.now() - then).total_seconds()
    if seconds < 0:
        return None
    if seconds < 120:
        return "a moment ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    days = int(seconds // 86400)
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    months = days // 30
    return "a month ago" if months == 1 else f"{months} months ago"


def _time_block(record=None, name=None):
    """The clock, plus how long since this person was last around."""
    lines = [persona.TIME_HEADER.strip(), _clock_line()]
    if record and name:
        gap = _ago(record.get("last_seen"))
        if gap:
            lines.append(f"You last spoke with {name} {gap}.")
    return {"role": "system", "content": "\n".join(lines)}


# ---- WHERE SHE IS ----

def where_line():
    """One sentence about where she is standing. Empty if unknown."""
    here = corrade.where_am_i()
    if not here:
        return ""
    if corrade.same_person(here, config.HOME_REGION):
        return f"You are home, on your own region {here}, in Tay's Haven."
    return (f"You are away from home right now, on a region called {here} "
            f"that belongs to someone else. You are the visitor here - do "
            f"not welcome people to Tay's Haven while you are standing in "
            f"their place. Home is {config.HOME_REGION}.")


def _place_block():
    line = where_line()
    return {"role": "system", "content": line} if line else None


def _channel_block(channel):
    note = CHANNEL_NOTES.get(channel)
    return {"role": "system", "content": note} if note else None


# ---- PASTED LINKS ----

def find_urls(text):
    """Web addresses in a message, tidied up, in the order they appear."""
    found = []
    for hit in URL_PATTERN.findall(text or ""):
        url = hit.rstrip('.,;:!?)"\'')
        if url.lower().startswith("www."):
            url = "http://" + url
        if url not in found:
            found.append(url)
    return found[:config.MAX_URLS_PER_MESSAGE]


def read_links(urls, name):
    """Open each link and return one block of text, or None."""
    blocks = []
    for url in urls:
        print(f"  READING: {url}")
        page = websearch.read_page(url, limit=config.URL_CHARS)
        if page:
            print(f"  READING: got {len(page)} characters")
            blocks.append(f"Page at {url}:\n{page}")
        else:
            print("  READING: that page could not be read.")
            blocks.append(f"Page at {url}: could not be opened or read.")
    if not blocks:
        return None
    header = persona.PASTED_PAGE_HEADER.format(name=name).strip()
    return header + "\n\n" + "\n\n".join(blocks)


# ---- IMMEDIATE COMMANDS ----
# Answered without asking Aion, so they are instant - which matters
# when she is stuck and you want her to stop.

def handle_command(speaker, message, is_owner=False):
    """
    Returns a reply for a command, or None if it isn't one.
    Returns "" for a command she should swallow without a word.

    Only Taymon gets to give commands. From anyone else a "!" line is
    dropped silently, and a plain "stop" is just a word like any other.
    """
    command = message.strip().lower()

    if not is_owner:
        if command.startswith("!"):
            print(f"  (command from {speaker} ignored - not Taymon)")
            return ""
        return None

    if command in ("stop", "stop!", "halt", "train stop", "train, stop"):
        if actions.stop_everything():
            return "Alright, stopping."
        return "I'm not going anywhere."

    if command in ("!help", "!commands"):
        return HELP_TEXT

    if command in ("!memory", "!remember"):
        return memory.summary_of(speaker)

    if command in ("!self", "!me"):
        return memory.summary_of_self()

    if command == "!diary":
        return memory.summary_of_diary()

    if command == "!time":
        return _clock_line()

    if command == "!where":
        here = corrade.where_am_i()
        if not here:
            return "I haven't heard where I am yet - say something in local chat."
        return f"I'm on {here}." + ("" if corrade.is_home() else " Away from home.")

    if command == "!look":
        return sight.glance()

    if command == "!tidy":
        threading.Thread(target=memory.force_consolidate,
                         args=(speaker,), daemon=True).start()
        return "Sorting through my notes, give me a moment."

    if command.startswith("!search"):
        query = message.strip()[7:].strip()
        if not query:
            return "Give me something to search for: !search cats"
        if not websearch.available():
            return "No search provider is set up, so I can't search."
        hits = websearch.search(query, count=3)
        if not hits:
            return "Nothing came back."
        return " | ".join(h["title"] for h in hits)

    if command.startswith("!read"):
        urls = find_urls(message)
        if not urls:
            return "Give me a link: !read https://example.com"
        page = websearch.read_page(urls[0], limit=300)
        if not page:
            return "I couldn't read that one."
        return page[:250]

    if command.startswith("!profile"):
        who = message.strip()[8:].strip() or speaker
        text = corrade.get_profile(who, force=True)
        if not text:
            return f"Nothing in {who}'s profile, or I couldn't read it."
        return text[:400].replace("\n", " | ")

    if command.startswith("!tp"):
        where = message.strip()[3:].strip()
        if not where:
            return "Where to? !tp RegionName"
        if travel.go_to(where):
            return "Made it."
        return "That teleport didn't take - the console has the reason."

    if command.startswith("!"):
        # A command she does not have. Never let Aion answer this - it
        # would cheerfully claim to have done it.
        print(f"  (unknown command: {message.strip()[:40]})")
        return ("I don't have a command called "
                f"{message.strip().split()[0]}. Type !help for the list.")

    return None


# ---- THE CONVERSATION ----

def _print_timing(stage):
    """One line saying where a turn's seconds went: getting the bundle
    ready (memory, recall, a glance, a profile), waiting on Aion, any
    search or page read with its second Aion call, and filing notes."""
    t0 = stage.get("begin", 0)
    marks = [("prep", "prep"), ("think", "aion"), ("lookup", "lookup"),
             ("memory", "memory")]
    parts = []
    last = t0
    for key, label in marks:
        if key in stage:
            parts.append(f"{label} {stage[key] - last:.1f}s")
            last = stage[key]
    total = time.time() - t0
    print(f"  timing: {' | '.join(parts)} | total {total:.1f}s")


def last_thing_she_said():
    """Her most recent reply, for 'put that in your profile'."""
    for line in reversed(conversation):
        if line.get("role") == "assistant":
            return str(line.get("content") or "").strip()
    return ""


def _second_pass(messages, reply, prompt_template, results, speaker, label):
    """
    Hand her what she found and ask again. Returns the new
    (reply, facts, self_facts, corrections, data), or None if it failed.
    """
    messages.append({"role": "assistant", "content": reply})
    messages.append({
        "role": "user",
        "content": prompt_template.format(results=results, name=speaker)
    })

    raw, _ = ai.ask(config.MODEL, messages, config.MAX_REPLY_TOKENS, label)
    if raw is None:
        return None

    new_reply, facts, self_facts, corrections = ai.parse_turn(raw)
    if not new_reply:
        print("  Second answer was unreadable - "
              "keeping what she said before.")
        return None

    return new_reply, facts, self_facts, corrections, ai.extract_json(raw) or {}


def respond_to(speaker, message, speaker_name=None,
               channel=None, speaker_uuid=None):
    """
    The one path local chat and IMs both go through.
    Returns what she says, or None when she has nothing to say.
    """
    global last_message_time

    # Everyone is judged by their key.
    is_owner = corrade.is_owner(speaker_uuid)

    canned = handle_command(speaker, message, is_owner)
    if canned is not None:
        return canned or None

    if not channel:
        channel = "local"

    started = time.time()
    stage = {"begin": started}        # where the seconds go, for the console
    if channel == "local":
        corrade.typing(True)

    # What she is shown as the speaker's name. From another grid a
    # name arrives as "Taymon.Jules @tays-haven.outworldz.net:8002" -
    # the same person wearing a return address. She should see the
    # person, not the address, or she treats a friend as a stranger.
    shown = corrade.plain_name(speaker)

    try:
        system_text = persona.system_prompt()

        with memory.lock:
            record = memory.load_person(speaker)
            me = memory.load_self()

        history = conversation[-config.MAX_HISTORY:]
        messages = [{"role": "system", "content": system_text}]
        messages.append(_time_block(record, shown))

        for block in (_place_block(), _channel_block(channel)):
            if block:
                messages.append(block)

        # A look around, when asked about it or when she just landed.
        seen = sight.for_message(message)
        if seen:
            messages.append({"role": "system",
                             "content": SIGHT_HEADER + "\n\n" + seen})

        # Someone she has no notes on - glance at their profile first.
        if not (record.get("core") or record.get("archive")):
            profile = corrade.get_profile(speaker_name or speaker,
                                          uuid=speaker_uuid)
            if profile:
                messages.append({"role": "system",
                                 "content": PROFILE_HEADER + "\n\n" + profile})

        messages.extend(memory.build_notebook(record, me, message,
                                              system_text, history))
        messages.extend(history)

        if channel == "im":
            prefix = f"{shown} sends you an instant message"
        else:
            prefix = f"{shown} says in local chat"

        # ---- A LINK WAS PASTED AT HER ----
        holding_line = None
        urls = find_urls(message) if config.READ_PASTED_URLS else []
        if urls:
            if channel == "local":
                corrade.say(config.READING_LINE)
                print(f"<< Train: {config.READING_LINE}")
                holding_line = config.READING_LINE
            pages = read_links(urls, shown)
            if pages:
                messages.append({"role": "user", "content": pages})

        messages.append({"role": "user", "content": f"{prefix}: {message}"})
        stage["prep"] = time.time()

        raw, _ = ai.ask(config.MODEL, messages, config.MAX_REPLY_TOKENS,
                        f"({channel})")
        stage["think"] = time.time()
        if raw is None:
            return config.FALLBACK_LINE

        reply, facts, self_facts, corrections = ai.parse_turn(raw)
        if not reply:
            print("  Nothing usable came back - saying the fallback line.")
            return config.FALLBACK_LINE

        data = ai.extract_json(raw) or {}

        # ---- SHE WANTED TO GO AND LOOK ----
        query = ""
        link = ""
        if config.SEARCH_ENABLED:
            query = str(data.get("search") or "").strip()
            link = str(data.get("read") or "").strip()

        if (query or link) and not websearch.available():
            print("  SEARCH: asked for, but no provider is set up.")
            query = link = ""

        person = str(data.get("profile") or "").strip()
        if person:
            low = person.lower()
            # Her own name, in any of the ways she might write it
            # ("Train", "Train Jules", "me"), means her own profile.
            own_names = {config.BOT_NAME.lower(),
                         config.BOT_NAME.split()[0].lower()}
            if low in SELF_WORDS or low in own_names:
                person = config.BOT_NAME
            elif low in THEM_WORDS:
                person = speaker_name or speaker

        note = None
        if query or link or person:
            if channel == "local":
                corrade.pace(started, channel, reply, speaker)
                corrade.say(reply)
                print(f"<< Train: {reply}")
                holding_line = reply
                started = time.time()

            if query:
                results = websearch.look_up(query)
                template = persona.SEARCH_RESULTS_PROMPT
                label = "(search)"
                note = f"(looked up: {query})"
                if not results:
                    results = "The search came back empty - nothing was found."
            elif link:
                print(f"  READING: {link}")
                page = websearch.read_page(link, limit=config.URL_CHARS)
                results = (f"Page at {link}:\n{page}" if page
                           else f"The page at {link} could not be read.")
                template = persona.PAGE_PROMPT
                label = "(read)"
                note = f"(read: {link})"
            else:
                them = corrade.same_person(person, speaker_name or speaker)
                text = corrade.get_profile(person, force=True,
                                           uuid=speaker_uuid if them else None)
                results = (text if text
                           else f"{person} has an empty profile, or it could "
                                f"not be read.")
                template = persona.PROFILE_PROMPT
                label = "(profile)"
                note = f"(read profile: {person})"

            outcome = _second_pass(messages, reply, template, results,
                                   shown, label)
            if outcome:
                reply, facts, self_facts, corrections, data = outcome
            else:
                # The follow-up failed. In local chat the holding line
                # has already been said, so say something honest now
                # rather than the same line twice; in an IM this is the
                # only thing the other person will ever get.
                reply = config.LOOKUP_FAILED_LINE
                data = {}
        stage["lookup"] = time.time()

        conversation.append({"role": "user", "content": f"{prefix}: {message}"})
        conversation.append({"role": "assistant", "content": reply})
        if len(conversation) > config.MAX_HISTORY:
            del conversation[:-config.MAX_HISTORY]

        with session_lock:
            tag = {"im": " (IM)"}.get(channel, "")
            session_lines.append(f"{speaker}{tag}: {message}")
            if holding_line and holding_line != reply:
                session_lines.append(f"Train: {holding_line}")
            if note:
                session_lines.append(note)
            session_lines.append(f"Train: {reply}")
            last_message_time = time.time()

        with memory.lock:
            record = memory.load_person(speaker)
            fixed = memory.apply_corrections(record, corrections)
            added = memory.add_facts(record, facts, config.CORE_LIMIT)
            record["chats"] = record.get("chats", 0) + 1
            record["last_seen"] = datetime.now().isoformat(timespec="seconds")
            memory.save_person(record)

            me = memory.load_self()
            self_added = memory.add_facts(me, self_facts, config.SELF_CORE_LIMIT)
            if self_added:
                memory.save_self(me)
        stage["memory"] = time.time()

        for fact in added:
            print(f"  [MEMORY +] {speaker}: {fact}")
        for change in fixed:
            print(f"  [MEMORY ~] {change}")
        for fact in self_added:
            print(f"  [SELF +] {fact}")

        # If she decided to move, set it going - but only Taymon can
        # send her anywhere. Anyone else's "come here" stays words.
        wanted = str(data.get("do") or "").strip() if data else ""
        if wanted and not is_owner:
            print(f"  action: '{wanted}' ignored - {speaker} is not Taymon")
        elif wanted:
            actions.perform(wanted, speaker=speaker_name or speaker,
                            speaker_uuid=speaker_uuid, message=message,
                            channel=channel)

        corrade.pace(started, channel, reply, speaker)
        _print_timing(stage)
        print(f"<< Train: {reply}")
        return reply

    finally:
        if channel == "local":
            corrade.typing(False)


# ---- GREETING ARRIVALS ----

def load_greeted():
    if os.path.exists(config.GREET_FILE):
        try:
            with open(config.GREET_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def due_for_greeting(name):
    """One entry per person, whichever grid they arrived from."""
    key = corrade.plain_name(name)
    with memory.lock:
        greeted = load_greeted()
        last = greeted.get(key, 0)
        if time.time() - last < config.GREET_COOLDOWN_HOURS * 3600:
            return False
        greeted[key] = time.time()
        memory.write_json(config.GREET_FILE, greeted)
        return True


def greet_arrival(name, uuid=None):
    global last_message_time
    started = time.time()
    last_message_time = started       # company counts as not-quiet
    system_text = persona.system_prompt()
    place = corrade.where_am_i()
    if not place:
        place = config.HOME_REGION if corrade.is_home() else "a region away from home"
    shown = corrade.plain_name(name)

    with memory.lock:
        record = memory.load_person(name)
        me = memory.load_self()

    known = bool(record.get("core") or record.get("archive"))
    template = persona.GREET_KNOWN if known else persona.GREET_STRANGER

    messages = [{"role": "system", "content": system_text}]
    messages.append(_time_block(record, shown))

    block = _place_block()
    if block:
        messages.append(block)

    if not known:
        profile = corrade.get_profile(name, uuid=uuid)
        if profile:
            messages.append({"role": "system",
                             "content": PROFILE_HEADER + "\n\n" + profile})

    messages.extend(memory.build_notebook(record, me, name, system_text))
    messages.append({"role": "user",
                     "content": template.format(name=shown, place=place)})

    corrade.typing(True)
    try:
        raw, _ = ai.ask(config.MODEL, messages, config.MAX_REPLY_TOKENS,
                        "(greeting)")
        if raw is None:
            return

        reply, facts, self_facts, corrections = ai.parse_turn(raw)
        if not reply:
            print("  Greeting came back unreadable - staying quiet.")
            return

        with memory.lock:
            record = memory.load_person(name)
            record["last_seen"] = datetime.now().isoformat(timespec="seconds")
            memory.apply_corrections(record, corrections)
            memory.add_facts(record, facts, config.CORE_LIMIT)
            memory.save_person(record)
            if self_facts:
                me = memory.load_self()
                memory.add_facts(me, self_facts, config.SELF_CORE_LIMIT)
                memory.save_self(me)

        conversation.append({"role": "assistant", "content": reply})
        if len(conversation) > config.MAX_HISTORY:
            del conversation[:-config.MAX_HISTORY]

        with session_lock:
            session_lines.append(f"({name} arrived)")
            session_lines.append(f"Train: {reply}")

        corrade.pace(started, "local", reply, name)
        print(f"<< Train greets {name}: {reply}")
        corrade.say(reply)
    finally:
        corrade.typing(False)


def note_departure(name):
    """Record that someone left, for the diary."""
    with session_lock:
        session_lines.append(f"({name} left)")


# ---- THE DIARY ----

def write_diary_entry(lines):
    transcript = "\n".join(lines)
    # Who was in the conversation. Lines in brackets are her own notes
    # ("(looked up: ...)", "(Taymon arrived)"), not people, and a
    # hypergrid name is the same person as the plain one.
    people = set()
    for line in lines:
        if ":" not in line or line.startswith("Train") or line.startswith("("):
            continue
        who = line.split(":", 1)[0].replace(" (phone)", "").replace(" (IM)", "")
        who = corrade.plain_name(who)
        if who and not corrade.is_her(who):
            people.add(who)
    people = sorted(people)
    print(f"\n  [DIARY] room quiet, writing entry...")

    with memory.lock:
        known = memory.existing_notes_block(people)

    messages = [{"role": "system", "content": _clock_line()}]
    if known:
        messages.append({"role": "system", "content": known})
    messages.append({"role": "system", "content": persona.DIARY_PROMPT})
    messages.append({"role": "user", "content": transcript})

    raw, _ = ai.ask(config.MODEL_CHEAP, messages, config.MAX_DIARY_TOKENS,
                    "(diary)")
    if raw is None:
        return

    data = ai.extract_json(raw)
    if not data:
        print("  [DIARY] could not read the entry, skipping.")
        return

    entry = str(data.get("entry", "")).strip()
    if not entry:
        return

    touched = set()

    with memory.lock:
        me = memory.load_self()
        me.setdefault("diary", []).append({
            "date": datetime.now().isoformat(timespec="seconds"),
            "with": people,
            "entry": entry
        })
        memory.add_facts(me, ai.clean_list(data.get("remember_self"), 3),
                         config.SELF_CORE_LIMIT)
        memory.save_self(me)

        for item in (data.get("remember") or [])[:3]:
            if not isinstance(item, dict):
                continue
            who = str(item.get("person", "")).strip()
            fact = str(item.get("fact", "")).strip()
            if not who or not fact:
                continue
            record = memory.load_person(who)
            if memory.add_facts(record, [fact], config.CORE_LIMIT):
                print(f"  [DIARY +] {who}: {fact}")
            memory.save_person(record)
            touched.add(who)

    print(f"  [DIARY] {entry}")

    memory.maybe_consolidate(True)
    for who in touched:
        memory.maybe_consolidate(False, who)


def diary_watcher():
    while True:
        time.sleep(60)
        try:
            with session_lock:
                if not session_lines:
                    continue
                if time.time() - last_message_time < config.IDLE_MINUTES * 60:
                    continue
                if len(session_lines) < 4:
                    session_lines.clear()
                    continue
                lines = list(session_lines)
                session_lines.clear()
            write_diary_entry(lines)
        except Exception as e:
            print(f"  DIARY WATCHER ERROR: {e}")