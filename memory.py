###############################################
# memory.py - long-term memory
#   the cabinet (files on disk, unlimited)
#   the notebook (what she carries per message)
###############################################

import os
import re
import json
import time
import difflib
import threading
from datetime import datetime

import config
import ai
from persona import CONSOLIDATE_PROMPT

os.makedirs(config.MEMORY_DIR, exist_ok=True)
lock = threading.Lock()

STOPWORDS = {
    "the", "and", "that", "this", "with", "have", "has", "had", "you", "your",
    "for", "was", "were", "are", "but", "not", "she", "her", "his", "him",
    "they", "them", "what", "when", "where", "would", "could", "should",
    "about", "there", "then", "than", "from", "just", "like", "into", "some",
    "been", "will", "can", "did", "does", "how", "who", "why", "its", "it's",
    "here", "over", "out", "get", "got", "one", "all", "any", "our"
}
# Her name and Taymon's are in nearly every note, so they say nothing
# about which note is relevant.
STOPWORDS |= {w.lower() for w in (config.OWNER_NAME + " " + config.BOT_NAME).split()}

# ---- MATCHING BY MEANING ----
# Old notes are fetched by what they mean, not just the words they
# share with the question. A small model runs on this machine and
# turns every note into a list of numbers; notes whose numbers point
# the same way as the question's are the relevant ones. The numbers
# live in memory/vectors/, beside the memory files, never inside them.
EMBED_MODEL = "all-MiniLM-L6-v2"
RELEVANCE_FLOOR = 0.45      # below this a note is not really about it
KEYWORD_BONUS = 0.05        # per word shared with the question, on top
KEYWORD_BONUS_CAP = 0.15
VECTOR_DIR = os.path.join(config.MEMORY_DIR, "vectors")

_embed = {"model": None, "state": "loading"}   # loading / ready / unavailable
_embed_lock = threading.Lock()
_vectors = {}               # file key -> {note text: numbers}

# Labels she sometimes glues onto the front of notes - stripped on the way in
PREFIX_PATTERN = re.compile(
    r"^(in|from|per|according to)\s+"
    r"(our|the|his|her|their|shared|your|my)?\s*"
    r"[a-z ]{0,24}"
    r"(backstory|back story|story|lore|history|canon|notes?)"
    r"\s*[,:;-]\s*",
    re.IGNORECASE
)


# ---- SMALL HELPERS ----

def est_tokens(text):
    return max(1, len(text) // 4)


def keywords(text):
    words = re.findall(r"[A-Za-z']{3,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def tidy_fact(text):
    """Normalise one incoming note - strip labels, collapse whitespace, trim."""
    text = " ".join(str(text).split())
    text = PREFIX_PATTERN.sub("", text).strip()
    if text:
        text = text[0].upper() + text[1:]
    return text[:config.MAX_FACT_LENGTH]


def normalize_fact(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def fit_lines(lines, budget):
    """Keep as many lines as fit the token budget, newest first."""
    kept = []
    used = 0
    for line in reversed(lines):
        cost = est_tokens(line) + 2
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    return kept, used


def write_json(path, record):
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        os.replace(temp, path)
    except Exception as e:
        print(f"  WRITE ERROR ({path}): {e}")


# ---- LOADING AND SAVING ----

def path_for(name):
    """
    The file for one person.

    The same person reaches her under different names depending on
    where they are standing - "Taymon Jules" at home, but
    "Taymon Jules @tays-haven.outworldz.net:8002" or
    "Taymon.Jules @some.grid:8002" from anywhere else. The grid is a
    return address, not part of who they are, so it comes off before
    the filename is chosen and everyone keeps one file wherever they
    wander in from.
    """
    text = str(name or "").strip()
    if "@" in text:
        text = text.split("@", 1)[0]
    text = text.replace(".", " ")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", text.strip()).strip("_").lower()
    return os.path.join(config.MEMORY_DIR, (safe or "unknown") + ".json")


def blank_person(name):
    return {
        "name": name,
        "first_seen": datetime.now().isoformat(timespec="seconds"),
        "last_seen": None,
        "chats": 0,
        "pending": 0,
        "core": [],
        "archive": []
    }


def blank_self():
    return {
        "name": config.BOT_NAME,
        "created": datetime.now().isoformat(timespec="seconds"),
        "updated": None,
        "pending": 0,
        "core": [],
        "archive": [],
        "diary": []
    }


def _upgrade(data, fallback):
    """Fill in any field an older file is missing."""
    for key, value in fallback.items():
        data.setdefault(key, value)
    return data


def load_person(name):
    path = path_for(name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["name"] = data.get("name") or name
            return _upgrade(data, blank_person(name))
        except Exception as e:
            print(f"  MEMORY READ ERROR for {name}: {e}")
    return blank_person(name)


def save_person(record):
    write_json(path_for(record.get("name", "unknown")), record)


def load_self():
    if os.path.exists(config.SELF_FILE):
        try:
            with open(config.SELF_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _upgrade(data, blank_self())
        except Exception as e:
            print(f"  SELF MEMORY READ ERROR: {e}")
    return blank_self()


def save_self(record):
    record["updated"] = datetime.now().isoformat(timespec="seconds")
    write_json(config.SELF_FILE, record)


# ---- WRITING FACTS ----

def find_similar(buckets, fact):
    """Locate an existing note that already says this. Returns (bucket, index)."""
    target = normalize_fact(fact)
    if not target:
        return None, -1
    for bucket in buckets:
        for i, existing in enumerate(bucket):
            other = normalize_fact(existing)
            if not other:
                continue
            if target == other:
                return bucket, i
            if len(target) > 15 and (target in other or other in target):
                return bucket, i
            if similarity(target, other) >= config.SIMILARITY_THRESHOLD:
                return bucket, i
    return None, -1


def add_facts(record, new_facts, core_limit):
    """Add notes, skipping anything already known. Returns what was new."""
    core = record.setdefault("core", [])
    archive = record.setdefault("archive", [])
    added = []

    for raw in new_facts:
        fact = tidy_fact(raw)
        if not fact:
            continue

        bucket, index = find_similar([core, archive], fact)
        if bucket is not None:
            existing = bucket[index]
            if len(fact) > len(existing) * 1.2:
                bucket[index] = fact
                print(f"  [MEMORY ~] refined: {existing}")
                print(f"             now:     {fact}")
            else:
                print(f"  [MEMORY =] already known: {fact}")
            continue

        core.append(fact)
        added.append(fact)

    while len(core) > core_limit:
        archive.append(core.pop(0))

    record["pending"] = record.get("pending", 0) + len(added)
    return added


def apply_corrections(record, corrections):
    changed = []
    for item in corrections:
        if not isinstance(item, dict):
            continue
        old = str(item.get("old", "")).strip()
        new = tidy_fact(item.get("new", ""))
        if not old:
            continue
        for bucket_name in ("core", "archive"):
            lines = record.get(bucket_name, [])
            match = difflib.get_close_matches(old, lines, n=1, cutoff=0.6)
            if not match:
                continue
            index = lines.index(match[0])
            if new:
                lines[index] = new
                changed.append(f"{match[0]}  ->  {new}")
            else:
                changed.append(f"{match[0]}  ->  (dropped)")
                lines.pop(index)
            break
    return changed


# ---- CONSOLIDATION (the tidy-up pass) ----

def _merge_notes(facts):
    listing = "\n".join(f"- {f}" for f in facts)
    raw, _ = ai.ask(
        config.MODEL_CHEAP,
        [{"role": "system", "content": CONSOLIDATE_PROMPT},
         {"role": "user", "content": listing}],
        config.MAX_TIDY_TOKENS,
        "(tidy)"
    )
    if raw is None:
        return None

    data = ai.extract_json(raw)
    if not data:
        return None

    merged = [tidy_fact(f) for f in ai.clean_list(data.get("facts"))]
    merged = [f for f in merged if f]
    if not merged:
        return None

    if len(merged) < max(2, len(facts) // 3):
        print(f"  [TIDY] result looked lossy ({len(facts)} -> {len(merged)}), "
              f"leaving the file alone.")
        return None

    return merged


def consolidate(is_self, name=None):
    """Merge overlapping notes in one file. Safe to run in a thread."""
    with lock:
        record = load_self() if is_self else load_person(name)
        core = list(record.get("core", []))
        pending = record.get("pending", 0)

    label = "herself" if is_self else name
    if pending < config.CONSOLIDATE_EVERY or len(core) < config.CONSOLIDATE_MINIMUM:
        return

    print(f"\n  [TIDY] {len(core)} notes about {label} - looking for overlaps...")
    merged = _merge_notes(core)

    with lock:
        record = load_self() if is_self else load_person(name)
        if merged:
            since = [f for f in record.get("core", []) if f not in core]
            record["core"] = merged + since
            print(f"  [TIDY] {len(core)} notes -> {len(record['core'])}")
        record["pending"] = 0
        if is_self:
            save_self(record)
        else:
            save_person(record)


def maybe_consolidate(is_self, name=None):
    threading.Thread(target=consolidate, args=(is_self, name), daemon=True).start()


def force_consolidate(name):
    """Used by !tidy - skips the counter."""
    with lock:
        me = load_self()
        me["pending"] = config.CONSOLIDATE_EVERY
        save_self(me)
        record = load_person(name)
        record["pending"] = config.CONSOLIDATE_EVERY
        save_person(record)
    consolidate(True)
    consolidate(False, name)


# ---- THE MEANING MODEL ----

def _vector_key(record):
    """Which vectors file a memory record's notes belong in."""
    return os.path.splitext(os.path.basename(path_for(record.get("name", ""))))[0]


SELF_KEY = os.path.splitext(os.path.basename(config.SELF_FILE))[0]


def _vector_path(key):
    return os.path.join(VECTOR_DIR, key + ".json")


def _load_vectors(key):
    if key in _vectors:
        return _vectors[key]
    table = {}
    path = _vector_path(key)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if stored.get("model") == EMBED_MODEL:
                table = stored.get("notes", {})
        except Exception as e:
            print(f"  memory: could not read {os.path.basename(path)}: {e}")
    _vectors[key] = table
    return table


def _save_vectors(key, keep_texts):
    """Write the vectors file, dropping numbers for notes that no
    longer exist (edited, merged or removed)."""
    table = _vectors.get(key, {})
    pruned = {t: v for t, v in table.items() if t in keep_texts}
    _vectors[key] = pruned
    os.makedirs(VECTOR_DIR, exist_ok=True)
    write_json(_vector_path(key), {"model": EMBED_MODEL, "notes": pruned})


def _encode(texts):
    """Numbers for each text. Assumes the model is ready."""
    import numpy as np
    with _embed_lock:
        vecs = _embed["model"].encode(list(texts), batch_size=64,
                                      normalize_embeddings=True)
    return [[round(float(x), 4) for x in row] for row in np.asarray(vecs)]


def _vectors_for(key, texts):
    """Numbers for every text given, computing and saving any missing."""
    table = _load_vectors(key)
    missing = [t for t in dict.fromkeys(texts) if t and t not in table]
    if missing:
        for text, vec in zip(missing, _encode(missing)):
            table[text] = vec
        _save_vectors(key, set(texts))
    return table


def _warm_up():
    """Load the model in the background and index every note, so the
    first message after startup is not slowed down by it."""
    started = time.time()
    # No progress bars in the brain window, and no trip to the model
    # website when the model is already on this machine. These have
    # to be set before the library is loaded, or they are ignored.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub",
                         "models--sentence-transformers--" + EMBED_MODEL)
    if os.path.isdir(cache):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        _embed["state"] = "unavailable"
        print("  memory: sentence-transformers is not installed - old notes "
              "are matched by keyword only. To fix: pip install sentence-transformers")
        return
    try:
        model = SentenceTransformer(EMBED_MODEL, device="cpu")
    except Exception as e:
        _embed["state"] = "unavailable"
        print(f"  memory: could not load the meaning model ({e}) - "
              f"matching by keyword only.")
        return
    _embed["model"] = model
    _embed["state"] = "ready"

    # Index what is already on file.
    count = 0
    try:
        with lock:
            me = load_self()
            people = [f for f in os.listdir(config.MEMORY_DIR)
                      if f.endswith(".json")
                      and f not in (os.path.basename(config.SELF_FILE),
                                    os.path.basename(config.GREET_FILE))]
            records = [load_person(os.path.splitext(f)[0].replace("_", " "))
                       for f in people]
        texts = me.get("archive", []) + [e.get("entry", "") for e in me.get("diary", [])]
        _vectors_for(SELF_KEY, texts)
        count += len(texts)
        for rec in records:
            texts = rec.get("archive", [])
            if texts:
                _vectors_for(_vector_key(rec), texts)
                count += len(texts)
    except Exception as e:
        print(f"  memory: indexing old notes failed: {e}")
    _encode(["warm up"])     # the first question is slow otherwise
    print(f"  memory: matching old notes by meaning - ready, "
          f"{count} notes indexed in {time.time() - started:.0f}s")


threading.Thread(target=_warm_up, daemon=True).start()


# ---- BUILDING THE NOTEBOOK ----

def _score(line, wanted):
    return len(keywords(line) & wanted)


def _fetch_by_keyword(record, self_record, message, person_lines, self_lines):
    """The old way: notes that share words with the question."""
    wanted = keywords(message)
    if not wanted:
        return [], []

    candidates = []
    for line in person_lines:
        candidates.append((_score(line, wanted), line))
    for line in self_lines:
        candidates.append((_score(line, wanted), "About me: " + line))
    candidates = [c for c in candidates if c[0] > 0]
    candidates.sort(key=lambda c: c[0], reverse=True)
    archive_hits = [line for _, line in candidates[:config.FETCH_ARCHIVE_LINES]]

    diary = self_record.get("diary", [])
    keep = config.RECENT_DIARY_ENTRIES
    older = diary[:-keep] if len(diary) > keep else []
    scored = [(_score(e.get("entry", ""), wanted), e) for e in older]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: s[0], reverse=True)
    diary_hits = [e for _, e in scored[:config.FETCH_DIARY_ENTRIES]]

    return archive_hits, diary_hits


def _fetch_by_meaning(record, self_record, message, person_lines, self_lines):
    """Notes whose meaning is close to the question, with a small
    bonus for sharing actual words. Same limits as the keyword way."""
    import numpy as np

    query = np.asarray(_encode([message])[0])
    wanted = keywords(message)

    def rate(text, vec):
        closeness = float(np.dot(query, np.asarray(vec)))
        bonus = min(KEYWORD_BONUS * len(keywords(text) & wanted), KEYWORD_BONUS_CAP)
        return closeness + bonus

    diary = self_record.get("diary", [])
    keep = config.RECENT_DIARY_ENTRIES
    older = diary[:-keep] if len(diary) > keep else []
    diary_texts = [e.get("entry", "") for e in older]

    person_vecs = _vectors_for(_vector_key(record), person_lines) if person_lines else {}
    self_vecs = _vectors_for(SELF_KEY, self_lines + diary_texts)

    candidates = []
    for line in person_lines:
        if line in person_vecs:
            candidates.append((rate(line, person_vecs[line]), line))
    for line in self_lines:
        if line in self_vecs:
            candidates.append((rate(line, self_vecs[line]), "About me: " + line))
    candidates = [c for c in candidates if c[0] >= RELEVANCE_FLOOR]
    candidates.sort(key=lambda c: c[0], reverse=True)
    archive_hits = [line for _, line in candidates[:config.FETCH_ARCHIVE_LINES]]

    scored = []
    for entry, text in zip(older, diary_texts):
        if text in self_vecs:
            scored.append((rate(text, self_vecs[text]), entry))
    scored = [s for s in scored if s[0] >= RELEVANCE_FLOOR]
    scored.sort(key=lambda s: s[0], reverse=True)
    diary_hits = [e for _, e in scored[:config.FETCH_DIARY_ENTRIES]]

    return archive_hits, diary_hits


def _fetch_relevant(record, self_record, message, carried_person=(),
                    carried_self=()):
    """
    Older notes worth pulling in for this message: everything in the
    archives, plus any close-at-hand notes that did not fit in the
    notebook this time (the pile grows past what she can carry, and
    the oldest quietly fall off the end - this is how they get back).
    """
    person_lines = [l for l in record.get("core", []) if l not in carried_person]
    person_lines += record.get("archive", [])
    self_lines = [l for l in self_record.get("core", []) if l not in carried_self]
    self_lines += self_record.get("archive", [])

    if _embed["state"] == "ready":
        try:
            return _fetch_by_meaning(record, self_record, message,
                                     person_lines, self_lines)
        except Exception as e:
            print(f"  memory: meaning match failed ({e}) - using keywords")
    return _fetch_by_keyword(record, self_record, message,
                             person_lines, self_lines)


def _diary_line(entry):
    return f"[{entry.get('date', '')[:10]}] {entry.get('entry', '')}"


def build_notebook(record, self_record, message, system_text, history=None):
    """
    Assemble the memory blocks she carries for this one reply.
    Returns a list of system messages.
    """
    budget = config.NOTEBOOK_TOKEN_BUDGET
    budget -= est_tokens(system_text)
    for line in (history or []):
        budget -= est_tokens(line.get("content", ""))
    budget -= est_tokens(message)
    budget = max(budget, 500)

    self_core, used = fit_lines(self_record.get("core", []), int(budget * 0.20))
    budget -= used
    person_core, used = fit_lines(record.get("core", []), int(budget * 0.55))
    budget -= used

    recall_started = time.time()
    archive_hits, diary_hits = _fetch_relevant(record, self_record, message,
                                               carried_person=set(person_core),
                                               carried_self=set(self_core))
    recall_took = time.time() - recall_started
    recent = self_record.get("diary", [])[-config.RECENT_DIARY_ENTRIES:]
    diary_texts = [_diary_line(e) for e in diary_hits + recent]
    fetched, used = fit_lines(archive_hits + diary_texts, budget)
    if archive_hits or diary_hits or recall_took > 1.0:
        how = "meaning" if _embed["state"] == "ready" else "keywords"
        print(f"  [RECALL by {how}, {recall_took:.2f}s] {len(archive_hits)} note(s), "
              f"{len(diary_hits)} diary entr{'y' if len(diary_hits) == 1 else 'ies'}"
              + (": " + " | ".join(l[:50] for l in archive_hits[:3])
                 if archive_hits else ""))

    blocks = []
    name = record.get("name", "this person")

    if self_core:
        blocks.append("Things you remember about yourself:\n" +
                      "\n".join(f"- {f}" for f in self_core))
    else:
        blocks.append("You have no personal memories saved yet.")

    if person_core:
        last = (record.get("last_seen") or "unknown")[:10]
        blocks.append(f"What you know about {name} "
                      f"(you have spoken {record.get('chats', 0)} times, "
                      f"last on {last}):\n" +
                      "\n".join(f"- {f}" for f in person_core))
    else:
        blocks.append(f"You have not met {name} before. "
                      f"This is your first conversation.")

    if fetched:
        blocks.append("Older memories that seem relevant right now:\n" +
                      "\n".join(f"- {f}" for f in fetched))

    return [{"role": "system", "content": b} for b in blocks]


def existing_notes_block(people):
    """Shown to her during the diary pass so she doesn't write it all down twice."""
    parts = []
    me = load_self()
    if me.get("core"):
        parts.append("Notes you already have about yourself:\n" +
                     "\n".join(f"- {f}" for f in me["core"]))
    for who in people:
        record = load_person(who)
        if record.get("core"):
            parts.append(f"Notes you already have about {who}:\n" +
                         "\n".join(f"- {f}" for f in record["core"][-60:]))
    return "\n\n".join(parts)


# ---- READBACKS (the ! commands) ----

def summary_of(name):
    with lock:
        record = load_person(name)
    core = record.get("core", [])
    archive = record.get("archive", [])
    if core or archive:
        return (f"About {name} I keep {len(core)} notes close and "
                f"{len(archive)} filed away. Recent: " + "; ".join(core[-5:]))
    return f"I don't have anything saved about {name} yet."


def summary_of_self():
    with lock:
        me = load_self()
    core = me.get("core", [])
    if core:
        return (f"I keep {len(core)} notes about myself. Recent: " +
                "; ".join(core[-5:]))
    return "I haven't saved anything about myself yet."


def summary_of_diary():
    with lock:
        me = load_self()
    diary = me.get("diary", [])
    if diary:
        return (f"I have {len(diary)} diary entries. Last one: " +
                diary[-1].get("entry", ""))
    return "My diary is still empty."