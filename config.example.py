###############################################
# config.example.py - copy this to config.py and fill in
# your own values. config.py is ignored by git and never
# published; this example is.
###############################################
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- WHO SHE IS ON THE GRID ----
BOT_NAME = "First Last"
OWNER_NAME = "First Last"      # the person she belongs to
OWNER_UUID = "00000000-0000-0000-0000-000000000000"   # his avatar key - the
                                 # same from any grid, and it cannot be faked

# ---- CORRADE ----
CORRADE_URL = "http://127.0.0.1:8080"
GROUP = "Your Corrade Group"
PASSWORD = "your-corrade-group-password"
RANGE = 240                      # Corrade's own radar range, metres

# ---- AION API ----
API_KEY = "your-aion-api-key"
API_BASE = "https://api.aionlabs.ai/v1"
MODEL = "aion-labs/aion-3.0"              # what she speaks with
MODEL_CHEAP = "aion-labs/aion-3.0-mini"   # diary, tidying, background work
PRICE_IN = 3.00 / 1_000_000               # dollars per input token
PRICE_OUT = 6.00 / 1_000_000              # dollars per output token
MAX_REPLY_TOKENS = 2000    # room for the reply AND its memory notes.
                           # The model thinks silently first and that
                           # counts; at 900 an unlucky long think came
                           # back empty (17 Sep 2026). Typical use 80-300.
MAX_DIARY_TOKENS = 2500    # the cheap model thinks silently first and
MAX_TIDY_TOKENS = 6000     # that counts; at 500/2000 entries were lost

# ---- PHONE CHAT ----
LISTEN_HOST = "0.0.0.0"    # 0.0.0.0 = reachable from your home network
LISTEN_PORT = 5000
PHONE_PASSWORD = "choose-a-password"
PHONE_USER = OWNER_NAME    # whose memory file the phone chat writes to

# ---- HER BODY ----
STAND_ANIM = "stand2"      # her resting pose
WALK_ANIM = "walk1"        # played while she is on the move
STAND_REFRESH = 300        # re-assert the stand every 5 minutes

# ---- HER EYES ----
SCAN_RANGE = 120           # metres - how far she looks for a thing to walk to
OBJECT_MAX_DISTANCE = 120  # metres - further than this, she won't walk
LOOK_RANGE = 180           # metres - how far a glance around reaches.
                           # 180 answers in under 2s here; asking for
                           # Corrade's full 240 never came back.
LOOK_THINGS = 10           # nearest named things a glance mentions

# ---- WALKING ----
# She walks by nudging forward repeatedly and checking her position,
# rather than one long command. Stopping is simply not sending the
# next nudge.
ARRIVES_WITHIN = 2.5       # metres - close enough to count as arrived
MAX_STOPPING_DISTANCE = 6.0  # never stop further short than this,
                             # however big the object is
APPROACH_IF_FURTHER = 5.0  # metres - closer than this, she stays put
AVATAR_MAX_DISTANCE = 60.0 # metres - furthest she will walk to a person
WALK_GIVES_UP_AFTER = 300.0  # seconds - ceiling on any one walk
STUCK_SECONDS = 4.0        # no progress for this long means stuck
PROGRESS_METRES = 0.3      # less movement than this counts as no progress
NUDGES_PER_CHECK = 4       # steps taken between position readings
NUDGE_GAP = 0.12           # seconds between steps
REAIM_EVERY = 2            # re-face the target every N checks
TURN_COOLDOWN = 20         # seconds before facing the same person again

# ---- HOW SHE PACES HERSELF ----
# An instant answer is the one thing no person ever manages. These
# pad her replies out to a human rhythm. The wait already spent on
# Aion counts towards it, so a slow answer is not delayed twice.
HUMAN_TIMING = True         # False makes her instant for everyone
PACE_FOR_OWNER = False      # False = no pausing when talking to Taymon
TYPING_INDICATOR = True     # show "Train is typing" in local chat
LOCAL_PAUSE_MIN = 2.0       # seconds - thinking, in local chat
LOCAL_PAUSE_MAX = 6.0
IM_PAUSE_MIN = 1.0          # seconds - thinking, in an IM
IM_PAUSE_MAX = 3.5
TYPING_SPEED = 18.0         # characters a second she "types"
MAX_PAUSE = 14.0            # never take longer than this, whatever the sums say
ARRIVAL_PAUSE_MIN = 25      # seconds after someone appears before she
ARRIVAL_PAUSE_MAX = 70      # notices them - she is not a doorbell

# ---- TELEPORTING ----
HOME_REGION = "YourRegionName"          # the region, not the grid name
HOME_POSITION = "<128, 128, 25>" # the couch area - her home base since
                                 # 10 September 2026 (was <316, 493, 22>)
# A landmark of home in her inventory, by its inventory UUID - Corrade
# refuses the name or the path. From another grid a region name means
# nothing, but a landmark carries the grid address inside it.
# Get it from: python -c "import body; print(body.list_inventory('/My Inventory/Landmarks'))"
HOME_LANDMARK = "00000000-0000-0000-0000-000000000000"
TRUSTED_TELEPORTS = {OWNER_NAME}  # whose offers she accepts unasked

# ---- WEB SEARCH ----
SEARCH_ENABLED = True
SEARCH_PROVIDER = "tavily"  # "tavily" or "ddg"
SEARCH_FALLBACK = True      # if Tavily fails, quietly try DuckDuckGo
SEARCH_RESULTS = 5          # how many results she gets back
SEARCH_TIMEOUT = 15         # seconds before a search gives up
SEARCH_READ_TOP = True      # also read the full text of the first result
SEARCH_PAGE_CHARS = 40000   # how much of that page she reads (was 2500)
SEARCH_SNIPPET_CHARS = 300  # how much of each other result she sees
SEARCHING_LINE = "Hang on, let me look that up."

# Tavily - 1,000 free credits a month, resets monthly
TAVILY_KEY = "your-tavily-key"
TAVILY_URL = "https://api.tavily.com"
TAVILY_DEPTH = "basic"        # "basic" = 1 credit, "advanced" = 2
TAVILY_EXTRACT_DEPTH = "advanced"  # page reading: "advanced" also pulls
                                   # tables and embedded content; "basic"
                                   # is plain text and cheaper
TAVILY_ANSWER = True          # a short written answer alongside the results
TAVILY_RAW = True             # full page text with the results
TAVILY_SNIPPET_CHARS = 700    # Tavily's snippets are worth more room

# DuckDuckGo (the ddgs library)
SEARCH_BACKEND = "auto"     # "auto" tries several engines; "duckduckgo" pins it

# ---- READING LINKS ----
READ_PASTED_URLS = True     # read any web address someone pastes at her
MAX_URLS_PER_MESSAGE = 2    # how many links from one message she'll open
URL_CHARS = 40000           # how much of a pasted page she reads (was 4000)
READING_LINE = "Give me a second, I'm reading that."

# ---- MEMORY ----
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
SELF_FILE = os.path.join(MEMORY_DIR, "train_self.json")
GREET_FILE = os.path.join(MEMORY_DIR, "greeted.json")
NOTEBOOK_TOKEN_BUDGET = 5000   # how much she carries per message
CORE_LIMIT = 120               # core notes kept per person
SELF_CORE_LIMIT = 60           # core notes kept about herself
FETCH_ARCHIVE_LINES = 12       # archive lines pulled in per message
FETCH_DIARY_ENTRIES = 3        # older diary entries pulled in per message
RECENT_DIARY_ENTRIES = 3       # newest diary entries always carried
MAX_FACT_LENGTH = 200          # characters
MAX_FACTS_PER_TURN = 4         # most notes one message may produce
MAX_HISTORY = 20               # short-term chat lines held in memory

# ---- DUPLICATE HANDLING ----
SIMILARITY_THRESHOLD = 0.82    # how alike two notes must be to count as one
CONSOLIDATE_EVERY = 20         # new notes before a tidy-up pass runs
CONSOLIDATE_MINIMUM = 8        # don't tidy a file smaller than this

# ---- TIMING ----
IDLE_MINUTES = 10              # silence before she writes a diary entry
GREET_COOLDOWN_HOURS = 12      # before greeting the same person again
STARTUP_GRACE_SECONDS = 30     # ignore arrivals right after startup

# ---- FALLBACK ----
# Said out loud when her answer comes back unreadable.
FALLBACK_LINE = "Sorry, I lost my train of thought there. Say that again?"
# Said when she went to look something up and the follow-up failed,
# so nobody is left with just "hang on".
LOOKUP_FAILED_LINE = "I went and looked, but I couldn't get anything useful. Sorry."
