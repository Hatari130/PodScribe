# Troubleshooting

Use this reference when commands fail, output encoding breaks, or the user asks for current library state.

## Common Failures

| Symptom | Handling |
|---|---|
| Cannot extract audio URL | Confirm the input is an episode URL, not a podcast homepage. |
| Preflight fails | Follow the printed hints. Common causes are missing `ffmpeg` or `ffprobe`; only siliconflow needs an API key. |
| BcutASR timeout or failure | Retry later or switch to `--asr-provider jianying` or `--asr-provider siliconflow`. |
| JianYingASR timeout or failure | Retry later or switch to `--asr-provider bcut` or `--asr-provider siliconflow`. |
| HTTP 401 | API key is invalid or wrong, usually only for siliconflow. |
| HTTP 429 | Rate limited; retry later. |
| HTTP 402 | Insufficient balance, only for siliconflow. |
| `ffmpeg Invalid data` | Audio download may be incomplete; rerun. |
| iTunes cannot connect during bootstrap/add/upgrade | Confirm access to `itunes.apple.com`. |
| RSS 404 or SSL error | Feed source may be stale; try resolving it again with `resolve_feeds.py add`. |
| Windows GBK encoding error | Run Python with `-X utf8` or configure stdout as UTF-8 in the command. |

## Current State Queries

Do not rely on static docs for counts. Query current files:

```bash
python -X utf8 transcribe.py rss subs
python -X utf8 transcribe.py rss browse-feeds
```

Database path:

```text
podcast_library/library.sqlite3
```

Useful Python pattern for Windows:

```bash
python -X utf8 -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); print('ok')"
```

## Known Limits

- Primary supported inputs are xiaoyuzhou episode links and standard RSS audio sources.
- RSS items without audio URLs can be stored as title/description metadata but cannot be transcribed.
- Transcription does not reliably identify speakers.
- Automatic chapters and summaries are first drafts; important content may need human review.
- Default ASR uses a non-official Bcut cloud interface. It is free and configuration-free, but may be affected by interface changes or rate limits.
- Long audio runtime depends on episode length, ASR provider, network, and cloud limits.
