###############################################
# websearch.py - her connection to the internet
#
# Two providers, chosen in config.py:
#   "tavily" - cleaned-up text, needs a key
#   "ddg"    - the ddgs library, no key
#
# Nothing here talks to Aion. It hands back
# plain text for talk.py to pass along.
###############################################
import threading

import requests

import config

_lock = threading.Lock()   # one search at a time
_warned = False


# ---------------------------------------------------------------
# DUCKDUCKGO (the ddgs library)
# ---------------------------------------------------------------

def ddg_available():
    """True if the ddgs library is installed."""
    global _warned
    try:
        import ddgs  # noqa: F401
        return True
    except Exception:
        if not _warned:
            print("  SEARCH: the ddgs library is not installed - "
                  "run: pip install ddgs")
            _warned = True
        return False


def _engine():
    from ddgs import DDGS
    return DDGS(timeout=config.SEARCH_TIMEOUT)


def ddg_search(query, count=None):
    """Returns a list of {title, url, snippet, page}."""
    if not ddg_available():
        return []
    count = count or config.SEARCH_RESULTS
    try:
        with _lock:
            hits = _engine().text(query,
                                  max_results=count,
                                  backend=config.SEARCH_BACKEND)
    except Exception as e:
        print(f"  DDG ERROR: {e}")
        return []

    out = []
    for hit in hits or []:
        title = str(hit.get("title", "")).strip()
        url = str(hit.get("href", "")).strip()
        snippet = str(hit.get("body", "")).strip()
        if not (title or snippet):
            continue
        out.append({"title": title,
                    "url": url,
                    "snippet": snippet[:config.SEARCH_SNIPPET_CHARS],
                    "page": ""})
    return out


def ddg_read(url, limit):
    if not ddg_available() or not url:
        return None
    try:
        with _lock:
            result = _engine().extract(url, fmt="text_plain")
    except Exception as e:
        print(f"  DDG READ ERROR ({url}): {e}")
        return None

    text = ""
    if isinstance(result, dict):
        text = str(result.get("content", ""))
    elif isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            text = str(first.get("content", ""))
    return text[:limit] if text else None


# ---------------------------------------------------------------
# TAVILY
# ---------------------------------------------------------------

def tavily_available():
    return bool(str(config.TAVILY_KEY or "").strip())


def _tavily_post(path, body):
    """Returns the parsed answer, or None if the call failed."""
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {config.TAVILY_KEY}"}
    try:
        with _lock:
            response = requests.post(f"{config.TAVILY_URL}{path}",
                                     json=body, headers=headers,
                                     timeout=config.SEARCH_TIMEOUT)
    except Exception as e:
        print(f"  TAVILY ERROR ({path}): {e}")
        return None

    if response.status_code == 401:
        print("  TAVILY: the key was refused - check TAVILY_KEY in config.py")
        return None
    if response.status_code == 429:
        print("  TAVILY: out of credits for this month.")
        return None
    if response.status_code != 200:
        print(f"  TAVILY: got status {response.status_code} from {path}")
        return None

    try:
        return response.json()
    except Exception as e:
        print(f"  TAVILY: could not read the answer: {e}")
        return None


def tavily_search(query, count=None):
    """Returns (answer, results). answer may be an empty string."""
    if not tavily_available():
        print("  TAVILY: no key set in config.py")
        return "", []

    data = _tavily_post("/search", {
        "query": query,
        "max_results": count or config.SEARCH_RESULTS,
        "search_depth": config.TAVILY_DEPTH,
        "include_answer": config.TAVILY_ANSWER,
        "include_raw_content": config.TAVILY_RAW,
    })
    if not data:
        return "", []

    answer = str(data.get("answer") or "").strip()
    out = []
    for hit in data.get("results") or []:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title", "")).strip()
        url = str(hit.get("url", "")).strip()
        snippet = " ".join(str(hit.get("content", "")).split())
        page = " ".join(str(hit.get("raw_content") or "").split())
        if not (title or snippet):
            continue
        out.append({"title": title,
                    "url": url,
                    "snippet": snippet[:config.TAVILY_SNIPPET_CHARS],
                    "page": page[:config.SEARCH_PAGE_CHARS]})
    return answer, out


def tavily_read(url, limit):
    if not tavily_available() or not url:
        return None
    data = _tavily_post("/extract", {"urls": [url],
                                     "extract_depth": config.TAVILY_EXTRACT_DEPTH})
    if not data:
        return None
    for item in data.get("results") or []:
        if isinstance(item, dict):
            text = " ".join(str(item.get("raw_content") or "").split())
            if text:
                return text[:limit]
    return None


# ---------------------------------------------------------------
# WHAT THE REST OF THE BRAIN CALLS
# ---------------------------------------------------------------

def available():
    if config.SEARCH_PROVIDER == "tavily":
        return tavily_available() or (config.SEARCH_FALLBACK and ddg_available())
    return ddg_available()


def search(query, count=None):
    """A plain list of results. Used by the !search command."""
    if config.SEARCH_PROVIDER == "tavily":
        _, hits = tavily_search(query, count)
        if hits or not config.SEARCH_FALLBACK:
            return hits
        print("  SEARCH: falling back to DuckDuckGo.")
    return ddg_search(query, count)


def read_page(url, limit=None):
    """Fetch a page and return its text. None if it can't be read."""
    limit = limit or config.SEARCH_PAGE_CHARS
    if config.SEARCH_PROVIDER == "tavily":
        text = tavily_read(url, limit)
        if text or not config.SEARCH_FALLBACK:
            return text
    return ddg_read(url, limit)


def look_up(query):
    """
    The one call talk.py makes. Returns a block of text for the AI,
    or None when nothing came back at all.
    """
    query = str(query or "").strip()
    if not query:
        return None
    print(f"  SEARCH ({config.SEARCH_PROVIDER}): {query}")

    answer = ""
    hits = []

    if config.SEARCH_PROVIDER == "tavily":
        answer, hits = tavily_search(query)
        if not hits and config.SEARCH_FALLBACK:
            print("  SEARCH: falling back to DuckDuckGo.")
            hits = ddg_search(query)
    else:
        hits = ddg_search(query)

    if not hits:
        print("  SEARCH: nothing came back.")
        return None

    lines = [f'Web search results for "{query}":', ""]
    if answer:
        lines.append(f"Short answer from the search service: {answer}")
        lines.append("")

    for number, hit in enumerate(hits, start=1):
        lines.append(f"{number}. {hit['title']}")
        if hit["snippet"]:
            lines.append(f"   {hit['snippet']}")
        if hit["url"]:
            lines.append(f"   {hit['url']}")
        lines.append("")

    # Full page text. Tavily usually hands it over with the results;
    # otherwise fetch the first one.
    page = hits[0].get("page") or ""
    source = hits[0]["url"]
    if config.SEARCH_READ_TOP and not page and source:
        page = read_page(source) or ""

    if page:
        print(f"  SEARCH: full text of {source} ({len(page)} characters)")
        lines.append(f"Full text from the first result ({source}):")
        lines.append(page[:config.SEARCH_PAGE_CHARS])

    print(f"  SEARCH: {len(hits)} result(s)")
    return "\n".join(lines)