###############################################
# ai.py - the connection to Aion, and making
#         sense of what comes back
###############################################

import re
import time
import json

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

session_cost = {"in": 0, "out": 0}


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
        r"^\s*about (?:the )?(?:person|user|him|her|them|taymon)\s*:",
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


def ask(model, messages, max_tokens, label="", _retry=True):
    """Send a request. Returns (text, finish_reason). text is None on failure.

    Aion's models think silently before they answer, and the thinking
    counts against max_tokens. When an answer comes back empty because
    the ceiling was hit, ask once more with double the room before
    giving up - the alternative is her saying the fallback line for
    no good reason."""
    started = time.time()
    try:
        response = client.chat.completions.create(
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
        session_cost["in"] += tin
        session_cost["out"] += tout
        dollars = (session_cost["in"] * config.PRICE_IN +
                   session_cost["out"] * config.PRICE_OUT)
        print(f"  tokens in/out: {tin}/{tout} {label}"
              f"   took {took:.1f}s"
              f"   session total: ${dollars:.4f}")
    else:
        print(f"  took {took:.1f}s {label}")

    choice = response.choices[0]
    finish = getattr(choice, "finish_reason", "") or ""
    content = choice.message.content

    if finish == "length" and not (content or "").strip() and _retry:
        print(f"  (thought too long and said nothing {label} - "
              f"asking again with room for {max_tokens * 2})")
        return ask(model, messages, max_tokens * 2, label, _retry=False)

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


def extract_json(raw):
    """Parse her answer into a dict.

    She sometimes returns more than one JSON object back to back - the
    spoken line in the first, memory notes in the second. Decoding one
    object at a time and merging keeps both. Anything that is not JSON
    is skipped over.
    """
    text = strip_fences(raw)
    decoder = json.JSONDecoder()

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


def clean_list(value, limit=None):
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    out = [str(v).strip() for v in value if str(v).strip()]
    if limit is not None:
        out = out[:limit]
    return out


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
            facts = clean_list(data.get("remember"))
            self_facts = clean_list(data.get("remember_self"))

            # Hard cap across both lists, whatever the prompt said
            room = config.MAX_FACTS_PER_TURN
            facts = facts[:room]
            self_facts = self_facts[:max(0, room - len(facts))]

            return reply, facts, self_facts, corrections

    # Broken or truncated - rescue the spoken line, drop the rest
    salvaged = trim_narration(salvage_reply(raw))
    if salvaged:
        print("  (answer was malformed - kept the reply, discarded notes)")
        print(f"  RAW ANSWER: {str(raw)[:800]}")
        return salvaged, [], [], []

    return None, [], [], []