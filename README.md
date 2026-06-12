# PodScribe

> Turn podcasts into a searchable text knowledge base — subscribe, transcribe, summarize, search.

[简体中文](./README.zh-CN.md) · MIT License · Zero Python dependencies

PodScribe is a command-line tool (and an optional AI-agent skill) that takes a
podcast episode link or an RSS feed and gives you a **timestamped transcript**,
**auto chapters**, a **structured summary**, and a **full-text searchable local
library**. It ships with a curated, categorized library of high-quality
Chinese & English podcast feeds so you can discover and subscribe in one step.

Transcription uses [SiliconFlow](https://siliconflow.cn)'s **SenseVoice** model;
summaries use **Qwen**. RSS ingestion and search need **no API key** — only
transcription does.

---

## Why PodScribe

- 🎙️ **Transcribe** any [Xiaoyuzhou](https://www.xiaoyuzhoufm.com) episode or
  standard RSS audio item into a timestamped Markdown transcript.
- 📝 **Summarize & chapter** automatically, with 5 modes: `brief`, `deep`,
  `product`, `investment`, `obsidian`.
- 📚 **Curated feed library** across 5 domains (AI / Tech & Business /
  Humanities & Society / Culture & Art / Health) — auto-resolves official RSS
  URLs via the public iTunes API.
- 🔍 **Local full-text search** over everything you've transcribed, backed by
  SQLite. Ask "did this show ever discuss AI agents?"
- 🪶 **Zero third-party dependencies.** Pure Python standard library. The only
  external requirement is `ffmpeg`.

---

## Requirements

- **Python 3.10+**
- **ffmpeg** and **ffprobe** on your `PATH`
  - Windows: `winget install --id=Gyan.FFmpeg -e`
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
- A free [SiliconFlow API key](https://cloud.siliconflow.cn) — **only needed
  for transcription**, not for RSS ingestion or search.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/<your-username>/podscribe.git
cd podscribe

# 2. Configure your API key (only needed for transcription)
cp config.example.json config.json
#   then edit config.json and paste your SiliconFlow key,
#   OR run the guided wizard:
python transcribe.py --init
#   OR use an env var instead of a config file:
export SILICONFLOW_API_KEY=sk-your-key   # Windows: setx SILICONFLOW_API_KEY sk-your-key

# 3. (Optional) Bootstrap the curated feed library via iTunes
cd podscribe-feeds
python resolve_feeds.py bootstrap   # resolves official RSS URLs for the built-in list
python import_feeds.py --all        # merges into ../subscriptions.json
cd ..
```

Config resolution order: **CLI args > `config.json` > environment variable > built-in defaults.**

---

## Usage

### Transcribe a single episode

```bash
# Transcript + chapters + summary (recommended)
python transcribe.py "<episode-url>" --summary --chapters

# Transcript only
python transcribe.py "<episode-url>"

# Pick a summary mode
python transcribe.py "<episode-url>" --summary deep --chapters
```

Summary modes: `brief` (fast read), `deep` (structured notes),
`product` (PM lens), `investment` (investor lens), `obsidian` (Obsidian-ready).

Run a self-check before transcribing:

```bash
python transcribe.py --preflight-only "<episode-url>"
```

### RSS knowledge base

```bash
# Browse the curated feed library (categorized, marks subscribed/unsubscribed)
python transcribe.py rss browse-feeds

# Subscribe by fuzzy name from the library
python transcribe.py rss add-from-feeds "Huberman"

# Or add any RSS URL directly
python transcribe.py rss add "Show Name" "https://example.com/feed.rss"

# Sync recent episode metadata (no API key needed)
python transcribe.py rss sync "Show Name" --limit 50

# Search (full text where transcribed; title/description otherwise)
python transcribe.py rss search "Show Name" "AI agent" --days 90

# Transcribe a chosen episode by number or #id
python transcribe.py rss transcribe "Show Name" 6 --summary --chapters

# List all subscriptions + transcription stats
python transcribe.py rss subs
```

> Recommended flow: **sync → browse/search → pick an episode → transcribe.**
> Avoid bulk-transcribing entire feeds.

### Manage the feed library

```bash
cd podscribe-feeds
python resolve_feeds.py add "Latent Space" --category ai --country us
python resolve_feeds.py add "声动早咖啡" --category tech-business --country cn
python resolve_feeds.py upgrade feeds/ --country cn   # proxy feed -> official Apple feed
python resolve_feeds.py validate feeds/               # health-check RSS links
python import_feeds.py --all
```

---

## Project layout

```
podscribe/
├── transcribe.py            # Core: transcription / RSS management / search
├── config.example.json      # Copy to config.json and add your key
├── podscribe-feeds/         # Curated, categorized feed library
│   ├── feeds/               # ai / tech-business / humanities-society / culture-art / health
│   ├── resolve_feeds.py     # iTunes resolver: bootstrap / add / upgrade / validate
│   └── import_feeds.py      # Merge category files -> subscriptions.json
├── SKILL.md                 # Instructions for AI-agent integration (Claude/Codex/etc.)
└── README.md
```

Files **not** in the repo (generated locally, see `.gitignore`):
`config.json`, `subscriptions.json`, and `podcast_library/` (your SQLite DB and
transcripts).

---

## Use as an AI-agent skill

PodScribe also works as a skill for AI coding agents (Claude Code, Codex,
WorkBuddy, …). Drop the folder into your agent's skills directory and the agent
reads [`SKILL.md`](./SKILL.md) to drive the commands for you — you just describe
what you want ("summarize this episode", "find me a good AI podcast").

---

## Limitations

- Built for Xiaoyuzhou episode links and standard RSS audio feeds.
- Episodes without an audio URL in their RSS can only be indexed by
  title/description — they can't be transcribed.
- The transcription model does not perform speaker diarization.
- Auto chapters and summaries are first drafts; review important content
  manually.
- `bootstrap` / `add` / `upgrade` require access to `itunes.apple.com`.

---

## Legal & ethics

This tool transcribes audio you choose to process. Podcast audio and the
resulting transcripts may be **copyrighted** by their creators. **Do not
redistribute transcripts or summaries of copyrighted shows**, and respect each
podcast's terms of use. PodScribe ships only public RSS feed URLs — never any
transcribed content. Use for personal research, accessibility, and note-taking.

---

## Contributing

Issues and PRs welcome — especially additions to the curated feed library
(`podscribe-feeds/feeds/*.json`). Each entry just needs a name, public RSS URL,
category, and a short note.

## License

[MIT](./LICENSE)
