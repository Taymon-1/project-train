###############################################
# ai.py - the connection to Aion, and making
#         sense of what comes back
###############################################

import re
import time
import json
import threading

from openai import OpenAI

import config

client = OpenAI(api_key=config.API_KEY, base_url=config.API_BASE)

# The Aion library quietly retries a failed or stalled request, up to
# twice, waiting up to ten minutes each time. Make those retries show
# in the console, so a slow turn is never a mystery.
import logging as _logging


class _OnlyRetries(_logging.Filter):
    def filter(self, record):
        return "etry" in record.getMessage()


_retry_log = _logging.getLogger("openai._base_client")
_retry_log.setLevel(_logging.DEBUG)
_handler = _logging.StreamHandler()
_handler.setFormatter(_logging.Formatter("  aion library: %(message)s"))
_handler.addFilter(_OnlyRetries())
_retry_log.addHandler(_handler)
_retry_log.propagate = False

session_cost = {"usd": 0.0}
_cost_lock = threading.Lock()     # background work can ask at the same time


# ---- NARRATION FILTER ----
# Aion sometimes keeps thinking after it has written her spoken line -
# musing about what to remember, what to correct, what it should note.
# None of that is meant to be heard. These patterns mark where the
# talking stops and the thinking starts; everything from there on is
# cut before the reply ever reaches chat.
NARRATION_PATTERNS = [
    re.compile(p, re.I | re.M) for p in [
        r"\bwait,?\s+actually\b",
        r"\bi (?:want|need|should|ought) to (?:remember|note|record|save|correct|add)\b",
        r"\blet me (?:also )?(?:note|remember|record|save|correct|add|update|keep|make sure|think about)\b",
        r"\blet me also\b",
        r"\bi (?:do not|don't|dont)? ?think i need to correct\b",
        r"\bnothing (?:to correct|worth correcting)\b",
        r"^\s*about me\s*:",
        r"^\s*about (?:the )?(?:person|user|him|her|them|taymon|dave)\s*:",
        r"^\s*about [^\n:]{1,40}:\s*$",
        r"\bremember_self\b",
        r"\bmemory note",
        r"\bfacts? (?:to|worth) (?:remember|record|sav)",
        r"\bi should (?:also )?acknowledge that\b",
    ]
]


def trim_narration(text):
    """Cut her reply where the thinking-out-loud starts."""
    if not text:
        return text

    earliest = None
    for pattern in NARRATION_PATTERNS:
        found = pattern.search(text)
        if found and (earliest is None or found.start() < earliest):
            earliest = found.start()

    if earliest is None:
        return text

    kept = text[:earliest].strip().rstrip(" \t\n-*:;,")
    if len(kept) < 10:
        print("  (narration filter would have emptied the reply - left it alone)")
        return text

    print("  (trimmed thinking-out-loud off the end of her reply)")
    return kept


# ---- TYPOS ----
# A real person's fingers slip now and then. One small slip, sometimes,
# in an ordinary lowercase word - never in a name, a place, a web
# address, a number, or a very short word.
import random

_NEARBY = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh",
    "u": "yij", "i": "uok", "o": "ipl", "p": "ol",
    "a": "qsz", "s": "adwx", "d": "sfec", "f": "dgrv", "g": "fhtb",
    "h": "gjyn", "j": "hkum", "k": "jlio", "l": "kop",
    "z": "xas", "x": "zcsd", "c": "xvdf", "v": "cbfg", "b": "vngh",
    "n": "bmhj", "m": "njk",
}
_WORD = re.compile(r"[A-Za-z']+")


def _typo_safe(word, text, start):
    """Is this a word a slip could plausibly land in?"""
    if len(word) < 4 or not word.isalpha() or not word.islower():
        return False                      # short, odd, or Capitalised
    # Part of a web address or a dotted thing? Look around it.
    before = text[max(0, start - 1):start]
    after = text[start + len(word):start + len(word) + 1]
    if before in (".", "/", "@", ":") or after in (".", "/", "@"):
        # a dot right after is fine at the end of a sentence
        if not (after == "." and (start + len(word) + 1 >= len(text)
                                  or text[start + len(word) + 1] in " \n")):
            return False
    return True


def slip(text):
    """Return the text with one human typo in it, or unchanged."""
    if not getattr(config, "TYPOS_ENABLED", False) or not text:
        return text
    if random.random() >= getattr(config, "TYPO_CHANCE", 0.0):
        return text
    if "://" in text or "www." in text:
        return text                       # a link is in here; leave it all
    if len(text) < 15:
        return text

    spots = [(m.start(), m.group()) for m in _WORD.finditer(text)
             if _typo_safe(m.group(), text, m.start())]
    if not spots:
        return text
    start, word = random.choice(spots)

    kind = random.choice(("double", "swap", "miss", "nearby"))
    i = random.randrange(1, len(word) - 1)          # never first or last letter
    if kind == "double":
        new = word[:i] + word[i] + word[i:]
    elif kind == "swap":
        if word[i] == word[i + 1]:
            return text
        new = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    elif kind == "miss":
        new = word[:i] + word[i + 1:]
    else:
        near = _NEARBY.get(word[i], "")
        if not near:
            return text
        new = word[:i] + random.choice(near) + word[i + 1:]

    if new == word:
        return text
    print(f"  (typo: {word} -> {new})")
    return text[:start] + new + text[start + len(word):]


def ask(model, messages, max_tokens, label="", retries=None, stop=None,
        _retry=True):
    """Send a request. Returns (text, finish_reason). text is None on failure.

    Aion's models think silently before they answer, and the thinking
    counts against max_tokens. When an answer comes back empty because
    the ceiling was hit, ask once more with double the room before
    giving up - the alternative is her saying the fallback line for
    no good reason.

    retries caps how many times the library tries again after a failed
    request; None keeps its default of two.

    stop, if given, is a threading.Event: once it is set the answer is
    no longer wanted. Returns (None, "dropped") then. The request is not
    streamed, so one already waiting on Aion runs to the end - the
    answer is just thrown away when it lands."""
    if stop is not None and stop.is_set():
        return None, "dropped"
    caller = client
    if retries is not None:
        caller = client.with_options(max_retries=retries)

    started = time.time()
    try:
        response = caller.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens
        )
    except Exception as e:
        print(f"  AION API ERROR {label}: {e}")
        return None, "error"

    took = time.time() - started

    usage = getattr(response, "usage", None)
    if usage:
        tin = getattr(usage, "prompt_tokens", 0) or 0
        tout = getattr(usage, "completion_tokens", 0) or 0
        if model == config.MODEL_CHEAP:
            price_in, price_out = config.PRICE_IN_CHEAP, config.PRICE_OUT_CHEAP
        else:
            price_in, price_out = config.PRICE_IN, config.PRICE_OUT
        with _cost_lock:
            session_cost["usd"] += tin * price_in + tout * price_out
            total = session_cost["usd"]
        print(f"  tokens in/out: {tin}/{tout} {label}"
              f"   took {took:.1f}s"
              f"   session total: ${total:.4f}")
    else:
        print(f"  took {took:.1f}s {label}")

    if stop is not None and stop.is_set():
        print(f"  (answer no longer wanted {label} - dropped)")
        return None, "dropped"

    choice = response.choices[0]
    finish = getattr(choice, "finish_reason", "") or ""
    content = choice.message.content

    if finish == "length" and not (content or "").strip() and _retry:
        print(f"  (thought too long and said nothing {label} - "
              f"asking again with room for {max_tokens * 2})")
        return ask(model, messages, max_tokens * 2, label, retries=retries,
                   stop=stop, _retry=False)

    if finish == "length":
        print(f"  WARNING: reply hit the token ceiling {label} - "
              f"raise the token setting in config.py if this repeats.")

    return content, finish


def strip_fences(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    return text


def _merge(into, extra):
    """Fold a second object into the first without losing anything.
    Lists join, empty values never overwrite real ones."""
    for key, value in extra.items():
        if key not in into or into[key] in (None, "", [], {}):
            into[key] = value
            continue
        existing = into[key]
        if isinstance(existing, list) and isinstance(value, list):
            into[key] = existing + value
    return into


# A comma left before a closing bracket - {"a": 1,} - which JSON refuses.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _decode_all(text, strict=True):
    """Every complete JSON object in text, in order. Anything around or
    between them is skipped over. strict=False lets a real line break
    stand inside a string."""
    decoder = json.JSONDecoder(strict=strict)
    found = []
    index = text.find("{")
    while index != -1:
        try:
            obj, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        index = text.find("{", end)
    return found


def extract_json(raw):
    """Parse her answer into a dict.

    She sometimes returns more than one JSON object back to back - the
    spoken line in the first, memory notes in the second. Decoding one
    object at a time and merging keeps both. Anything that is not JSON
    is skipped over.

    A second, forgiving read allows two common slips - a real line break
    inside a string, and a comma before a closing bracket - and is used
    when it recovers more than the strict one. An answer cut off before
    its closing brace is NOT pieced back together: its last note could
    be half a sentence. parse_turn still keeps its spoken line.
    """
    text = strip_fences(raw)
    found = _decode_all(text)
    if "{" in text:
        forgiving = _decode_all(_TRAILING_COMMA.sub(r"\1", text), strict=False)
        if len(forgiving) > len(found):
            print("  (repaired a slightly broken answer - kept what was in it)")
            found = forgiving

    if not found:
        return None

    merged = found[0]
    for extra in found[1:]:
        merged = _merge(merged, extra)
    if len(found) > 1:
        print(f"  (merged {len(found)} JSON blocks from one answer)")
    return merged


def salvage_reply(raw):
    """
    Pull just the spoken line out of a broken or truncated answer.
    Returns the reply text, or None if nothing usable is there.
    This is what stops raw JSON ever reaching local chat.
    """
    text = strip_fences(raw)
    match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
    if match:
        try:
            return json.loads('"' + match.group(1) + '"').strip()
        except Exception:
            return match.group(1).replace('\\"', '"').replace("\\n", " ").strip()

    # An unterminated reply string - truncation cut it mid-sentence
    match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)$', text, re.S)
    if match:
        salvaged = match.group(1).replace('\\"', '"').replace("\\n", " ").strip()
        if len(salvaged) > 10:
            return salvaged

    # Not JSON at all, and no stray braces - treat it as plain speech
    if "{" not in text and '"reply"' not in text:
        return text.strip() or None

    return None


NOTE_TEXT_KEYS = ("fact", "text", "note", "new")


def clean_list(value, limit=None):
    """A list of plain note sentences.

    Now and then the model puts a small object in a notes list instead
    of a sentence - {"fact": ..., "source": ...} or a correction. Turning
    that into text saved the object itself as a "note" (three of those
    broke a tidy on Chat Train, 23 Sep 2026). Take the sentence out of it
    instead, and drop anything with no sentence in it."""
    if not value:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    out = []
    for item in value:
        if isinstance(item, dict):
            text = next((item[k] for k in NOTE_TEXT_KEYS
                         if isinstance(item.get(k), str) and item[k].strip()), "")
            print(f"  (a note arrived as an object with fields {sorted(item)} - "
                  f"{'kept its sentence' if text else 'dropped it'})")
            item = text
        if not isinstance(item, str):
            if item is not None:
                print(f"  (dropped a note that was a {type(item).__name__}, not text)")
            continue
        if item.strip():
            out.append(item.strip())
    if limit is not None:
        out = out[:limit]
    return out


def _split_corrections(items):
    """Pull correction objects ({"old": ..., "new": ...}) out of a notes
    list, where the model sometimes puts them by mistake. Returns
    (the rest, the corrections)."""
    if not isinstance(items, list):
        return items, []
    rest, fixes = [], []
    for item in items:
        if isinstance(item, dict) and "old" in item:
            fixes.append(item)
        else:
            rest.append(item)
    if fixes:
        print(f"  ({len(fixes)} correction(s) arrived in a notes list - "
              f"treated as corrections)")
    return rest, fixes


def parse_turn(raw):
    """
    Read one of her answers.
    Returns (reply, facts_about_them, facts_about_her, corrections).
    reply is None only if nothing usable came back at all.
    """
    data = extract_json(raw)
    if data:
        reply = trim_narration(str(data.get("reply", "")).strip())
        if reply:
            corrections = data.get("correct") or []
            if not isinstance(corrections, list):
                corrections = []
            remember, fixes = _split_corrections(data.get("remember"))
            remember_self, self_fixes = _split_corrections(data.get("remember_self"))
            corrections = corrections + fixes + self_fixes
            facts = clean_list(remember)
            self_facts = clean_list(remember_self)

            # Hard cap across both lists, whatever the prompt said
            room = config.MAX_FACTS_PER_TURN
            facts = facts[:room]
            self_facts = self_facts[:max(0, room - len(facts))]

            return slip(reply), facts, self_facts, corrections

    # Plain words, or broken/truncated JSON - rescue the spoken line.
    # Chat Train found every "malformed" answer up to 24 Sep 2026 was
    # the first kind: no JSON at all, so no notes were ever in it to lose.
    salvaged = trim_narration(salvage_reply(raw))
    if salvaged:
        text = strip_fences(raw)
        if "{" not in text and '"reply"' not in text:
            print("  (answered in plain words, not JSON - kept the reply; "
                  "there were no notes in it)")
        else:
            print("  (answer was malformed - kept the reply, discarded notes)")
            print(f"  RAW ANSWER: {str(raw)[:800]}")
        return slip(salvaged), [], [], []

    return None, [], [], []