---
name: podscribe
description: 播客订阅、RSS 入库、单集转录、章节生成、全文搜索和基于全文稿摘要的一站式工具。Use when the user gives a xiaoyuzhou episode, RSS feed, podcast name, episode number, or asks to transcribe a podcast, summarize an episode, extract takeaways, create Obsidian notes, search whether a show discussed a topic, recommend podcasts, import feeds, sync subscriptions, or repair podcast RSS sources. Default transcription uses free BcutASR; optional providers are JianYingASR and siliconflow SenseVoice.
---

# PodScribe

Use PodScribe to manage podcast subscriptions, sync RSS metadata, transcribe episodes, generate chapters, search local podcast knowledge, and write summaries from full transcripts.

## Core Contract

Choose the narrowest workflow that matches the user request:

| User request | Action |
|---|---|
| Episode link and transcript | Run `python transcribe.py "<url>" --chapters`; report transcript path and stats. |
| Episode link and summary, takeaways, or notes | Transcribe first, read the generated transcript, then write the requested summary in the final answer. |
| RSS URL or podcast name to add | Add/sync/list metadata; do not batch-transcribe by default. |
| Ask whether a show discussed a topic | Sync or query local library, then distinguish full-text coverage from title/description coverage. |
| Podcast recommendations | Read `podscribe-feeds/feeds/*.json`; recommend by topic and import only when requested. |
| Broken feeds or subscription maintenance | Use `podscribe-feeds/resolve_feeds.py` and `podscribe-feeds/import_feeds.py`. |

Important boundaries:

- Treat `transcribe.py` as the deterministic worker for transcription, chapters, RSS ingestion, and search.
- Generate summaries yourself after reading the transcript. `--summary` is a compatibility/style hint and does not create a summary file.
- Use `bcut` as the default ASR provider; it needs no API key. Only `--asr-provider siliconflow` needs a configured key.
- Query live files or SQLite for current status. Do not rely on fixed subscription counts in documentation.
- If the user asked for a summary, final output must include the summary body, not just “transcription complete.”

## Reference Routing

Read only the file needed for the current task:

- `references/transcription.md`: episode transcription, preflight checks, ASR provider options, output paths.
- `references/summarization.md`: brief, deep, product, investment, and Obsidian summary formats.
- `references/rss-workflows.md`: subscription management, feed catalog import, RSS sync/list/search/transcribe.
- `references/troubleshooting.md`: common failures, encoding issues, API/provider errors, state queries.
- `references/project-layout.md`: repository layout, data files, and path assumptions.

## Fast Commands

```bash
python transcribe.py --preflight-only "<episode-url>"
python transcribe.py "<episode-url>" --chapters
python transcribe.py rss subs
python transcribe.py rss sync "<podcast-name>" --limit 50
python transcribe.py rss list "<podcast-name>" --limit 50
python transcribe.py rss search "<podcast-name>" "<topic>" --days 90
python transcribe.py rss transcribe "<podcast-name>" 6 --chapters
```

For feed catalog maintenance:

```bash
cd podscribe-feeds
python resolve_feeds.py bootstrap
python resolve_feeds.py add "Latent Space" --category ai --country us
python resolve_feeds.py validate feeds/
python import_feeds.py --all
```

## Delivery

Always report generated transcript paths and basic stats when available: duration, segment count, and word/character count. When answering search questions, state the coverage scope: how many episodes have searchable full text and how many only have title/description metadata.
