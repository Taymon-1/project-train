# Project Train

Train is an AI-powered avatar who lives in an [OpenSimulator](http://opensimulator.org/) virtual world. She talks to people in local chat, by private message, or from a phone; she remembers who she has met and what they told her; she keeps a diary; she looks around, walks to things, teleports, and writes her own profile.

This is a learning project built by one person, one file at a time, with help from AI assistants along the way. It is shared as-is, in the hope that it is useful or interesting to someone building their own.

The story of the build, with the wins and the dead ends, is on the blog: **https://projecttrain.org/**

## How it fits together

- **Corrade** is her body: a scripted agent that logs into the grid as an avatar, hears chat, sees what is nearby, walks and speaks.
- **The brain** (this repository) is a Python program running beside Corrade. Everything Corrade hears is passed to it; it decides what she says and does, keeps her memory, and passes her words back.
- **Aion 3.0** is the language model she thinks with, reached through an OpenAI-compatible API.

`ABOUT_TRAIN.md` describes what she can do and how each file contributes, in plain English.

## Running it

1. Install Python 3.12 or newer, then `pip install flask requests openai sentence-transformers ddgs qrcode`.
2. Install and configure [Corrade](https://grimore.org/secondlife/scripted_agents/corrade) with a group that has the `talk`, `grooming`, `notifications`, `movement`, `interact` and `inventory` permissions, and its HTTP server listening on this machine.
3. Copy `config.example.py` to `config.py` and fill in your own names, keys and passwords. `config.py` is ignored by git and is never published.
4. Run `start_brain.bat` (or `python train_brain.py`).

## Built with

- [Corrade](https://grimore.org/secondlife/scripted_agents/corrade) by Cinderblocks (Wizardry and Steamworks), the scripted agent that is her body
- [Aion 3.0](https://aionlabs.ai/) by Aion Labs, the language model she thinks with
- [Tavily](https://tavily.com/), for web search and page reading
- [DreamGrid](https://www.outworldz.com/Outworldz_installer/), the one-click OpenSimulator grid she lives on
- [OpenSimulator](http://opensimulator.org/), the virtual world platform itself

## What is not here

Her diary and memory files are private and are not included. They live in a `memory/` folder that git ignores, along with `config.py`, which holds keys and passwords. Her personality file, `persona.py`, is included so the structure of her prompt can be seen.

## About the wander feature

For a week she could wander around the region on her own when nobody was talking to her, choosing where to go and why. It worked. The developer decided to shelve it in favor of future plans, and it was removed intentionally rather than left switched off. The rest of her movement, coming when called and walking to things she is asked to, is unchanged.

## License

No license has been chosen yet. Until one is, treat this as "look, learn, ask before reusing".
