# Train

*What she is, what she can do, and how she works. Written 12 September 2026, after the first full review and rebuild.*

## What Train is

Train is an AI person who lives on Tay's Haven, a private OpenSim grid run on a laptop in Ohio. She has an avatar, a voice, a memory, a diary, and a life of her own on the grid. People talk to her in local chat, by private message, or from a phone, and she answers as herself. She remembers who she has met and what they told her. She walks, teleports, and looks around.

She is made of three parts:

- **Corrade** is her body. It is a "scripted agent", a program that logs into the grid as an avatar the way a person's viewer does. It hears chat, sees who and what is nearby, walks, teleports, and speaks. It does nothing on its own.
- **The brain** is a Python program that sits beside Corrade on the same laptop. Everything Corrade hears is passed to the brain. The brain decides what she says and does, keeps her memory, and passes her words back to Corrade to speak.
- **Aion** is the mind she thinks with, a large language model reached over the internet. The brain hands it a carefully packed bundle for every message: who she is, the time, where she is, what she remembers, what was just said. Aion answers with what she says out loud and, separately, what she is thinking: what to remember, whether to move, whether to look something up.

The brain was written one file at a time over a few weeks by Taymon with help from Claude, then reviewed as a whole and rebuilt over 10 and 11 September 2026.

## How she was on 10 September, before the review

She already worked, and a lot of her was good.

**She could:**

- Talk in local chat, by private message, and from Taymon's phone, in one consistent voice.
- Remember. One file of notes per person, one for herself, and a diary she writes when the room goes quiet. Notes are sorted into a close-at-hand pile and an archive, duplicates are caught, and a tidy-up pass merges overlaps.
- Look things up on the web, read a page someone pastes, and read a person's in-world profile before answering a stranger.
- Know the date and time, and how long since she last saw someone.
- Turn to face whoever speaks to her.
- Walk to a named object, walk to a person, and stop on command.
- Accept teleport offers from Taymon and go home.
- Greet people who arrive, with a human-like pause first.
- Pace her replies like a person typing, and show the typing indicator.
- Survive an echo of her own words without answering herself forever.

**What was wrong, found in the review:**

- After a teleport she did not know where she was. She learned her region only when someone spoke in local chat, so she once welcomed two visitors "to Tay's Haven" while standing on someone else's grid.
- She greeted and walked over to every arrival, everywhere, including a room full of bots.
- Anyone at all could give her commands: teleport her away, read her diary aloud, read her private notes.
- She answered scripted objects as if they were people.
- Every trip home from another grid took two to four minutes and knocked her offline, because of a network quirk between Corrade and the grid.
- Her control port was open to the whole home network.
- Leftovers from a four-minute echo loop, three misspelt files for one visitor, a file for "Claude", and a file for "Object" were sitting in her memory.
- Slow answers from Aion could make Corrade give up waiting on her.
- Her standing pose gave up for the whole session if Corrade was not ready the moment she started.

## How she is now, 12 September

Everything above still works, and:

**Awareness**

- She knows where she is the moment she lands anywhere, using Corrade's own "I have changed region" announcement, and she knows whether that is home.
- She can see. A glance describes what is around her in plain words: who is here, how far, which way relative to where she is facing, whether they are sitting or moving; the nearest ten named things, their size and direction; and, if asked, what she is wearing. She takes a glance automatically a few seconds after landing anywhere new, and whenever someone asks her about what she can see or where something is. Nothing was added to her standing instructions for this. The glance is simply handed to her when it matters.
- She can walk to things by rough description. "The forked tree" finds "Forked Spring Tree Newly Leafed". "The cappuccino cup" finds "grande cup of cappuccino". If several things fit, she goes to the nearest.

**Behaviour**

- Away from home she is a guest. She greets nobody, ignores local chat entirely, and answers private messages only. At home she is herself.
- Only Taymon can command her, and he is known by his avatar key, which is the same from any grid and cannot be faked. Anyone else typing a command gets silence, and anything she decides to do on someone else's say-so is dropped before it runs.
- She only moves when the message she is answering actually asks for it. She had picked up a habit of going home whenever she felt like it; now "home" needs the word home, "come" needs come or here, and a walk needs a movement word or the thing named.
- "Home" means the couch area, not just the region. From anywhere on Welcome or from any other grid, "go home" brings her to the couch in about a second.
- Both local chat and private messages have a ten-a-minute ceiling, counting only things she actually said, so no loop can run away with her.
- If she goes to look something up and the lookup fails, she says so once, honestly, instead of saying "hang on" twice or leaving a private message unanswered.
- Objects talking in local chat are ignored.

**Memory**

- She recalls old notes by meaning, not spelling. A small model runs on the laptop and turns each note into numbers; a question is matched against them. "How old is Ben" finds "his son's name is Ben". Notes that used to fall silently off the end of her notebook because the pile grew too big are now searchable too.
- The echo-loop leftovers, the junk files, and the soured notes from a long day of testing are gone, with backups kept.
- Hypergrid visitors keep one file however they arrive, and the greeting list and diary guest list no longer count "Taymon Jules @somegrid" as a second person.

**Self**

- She knows what she is wearing, by name, if asked.

**Plumbing**

- Corrade only accepts commands from this laptop. The phone page is still reachable from the home network, as intended.
- Corrade now logs her in through the grid's public front door, the same way a viewer does. That was the fix for the slow trips home: the grid compares the address she logged in from with the address she comes home from, and they now match.
- Chat is answered on its own thread, so a slow Aion can never make Corrade give up on her.
- Her standing pose keeps trying until Corrade is ready.
- Unused sample regions, an unused group, and a stale subscription were removed from Corrade's settings.

## How she is built, for someone who does not code

The brain is fourteen files, each with one job. Think of them as the departments of a small company that exists to run one person.

- **train_brain** is the switchboard. Corrade posts everything it hears to it: local chat, private messages, arrivals and departures, teleport offers, region changes. It sends each to the right department.
- **config** is the settings page. Every number, name and switch lives there. Change behaviour here, not in the other files.
- **corrade** is the telephone line to her body. Sending commands, subscribing to what Corrade should report, speaking, the typing indicator, reading profiles, and unpicking Corrade's replies. It also holds the "where am I" memory and the guards against answering her own echo.
- **talk** is the thinking department. For every message it assembles the bundle for Aion: who she is, the clock, where she is, which channel the words came on, a glance at a stranger's profile, a look around if relevant, and her memory notebook. It sends the bundle, reads the answer, speaks, acts, and files away what she wants to remember. The instant commands live here too.
- **ai** is the connection to Aion and the parser that makes sense of what comes back, including rescuing a reply when Aion's answer is broken or cut short, and trimming thinking-out-loud off the end of her spoken line.
- **memory** is the filing cabinet: the per-person files, her own file, the diary, duplicate detection, the tidy-up pass, the meaning-based recall, and the notebook builder that fits the most useful notes into a fixed budget for each message.
- **persona** is who she is: her identity, her backstory, the rules for how Aion must answer, and the templates for greetings, search follow-ups, and the diary. This is the file meant to be edited by hand. It is kept deliberately lean; making it three times bigger once made her repeat herself and leak her thoughts into speech.
- **body** is her physical self: position, turning, animations, and walking, done as a series of small nudges with a stuck detector, so she can always be stopped mid-step.
- **vision** finds named objects nearby, by rough description, and walks her to one.
- **sight** turns the grid's facts into the plain-English glance, with directions relative to where she faces.
- **actions** carries out what she decided: home, come, walk to something, several in a row, and the "did anyone actually ask?" guard.
- **travel** is teleporting: offers, going home by landmark, and the fallbacks.
- **websearch** is her connection to the internet, with a fallback search engine.
- **phone** serves the chat page for Taymon's phone.

**How one message flows.** Someone speaks. Corrade hears it and posts it to the brain. The brain checks: is this a person, not an object; is it her own echo; is she home; has she said too much this minute; is it a command from Taymon. Then it assembles the bundle, asks Aion, and gets back a small structured answer: the words to say, and separately the things nobody hears: notes to remember, a correction to an old note, a search to run, a profile to read, a move to make. The brain speaks the words, files the notes, and starts the move on its own thread. Four to six seconds, most of the time, all of it waiting on Aion.

**What it costs.** Roughly a cent per three or four messages with the main model, and a fraction of a cent for background work like the diary and the tidy-up, which use a cheaper model.

*Writing her own profile was built on 11 September and removed on 18 September: it could not be driven reliably in plain conversation, and a version that understood more sentences wrote chat lines into her profile by mistake. Reading profiles stays. Wandering on her own was built on 11 September and removed on 18 September. It worked, but she kept getting stuck on the same two targets and it cost real money to leave running all day. Taymon chose to take it out for good.*

**What she cannot do, honestly.** There is no camera. She cannot see faces, expressions or light. Her "sight" is the grid's own knowledge of what is where, described in words. She cannot tell where the ground drops away, because the commands that report land and terrain time out on this grid. She cannot sit yet.

## Rules that keep her safe

- Commands and movement answer only to Taymon, by key.
- Away from home: greet nobody, ignore local chat, answer private messages only.
- Move only when asked, and only for Taymon.
- Ten replies a minute per channel, and her own echo is never answered.
- Corrade takes orders only from this laptop.

## Parked for later

- Moving her keys out of the settings file and getting fresh ones.
- Sitting on things.
- Knowing when the ground drops away.
- Making her less quippy, if wanted, which is a personality edit rather than code.
