# RSS Workflows

Use this reference for podcast subscription management, local library sync, browsing, search, and RSS episode transcription.

## Mental Model

`podscribe-feeds/feeds/*.json` is the catalog: what is available to subscribe to.
`subscriptions.json` is the active subscription list: what the local library follows.
`podcast_library/library.sqlite3` stores synced episode metadata and transcript state.

Do not batch-transcribe by default. Use this sequence: sync metadata, browse or search, let the user choose an episode, then transcribe.

## Browse And Add Subscriptions

```bash
python transcribe.py rss browse-feeds
python transcribe.py rss add-from-feeds "跳岛FM"
python transcribe.py rss add-from-feeds "Huberman"
python transcribe.py rss add "日谈公园" "https://anchor.fm/s/2389ed24/podcast/rss"
python transcribe.py rss subs
```

## Sync And List Episodes

```bash
python transcribe.py rss sync "日谈公园" --limit 50
python transcribe.py rss list "日谈公园" --limit 50
```

## Search

```bash
python transcribe.py rss search "日谈公园" "AI Agent 大模型" --days 90
```

When answering search questions, always state coverage:

```text
我检查了 日谈公园 的 38 期。
全文可搜索: 6 期
仅标题/简介可搜索: 32 期

在已转录全文里找到 2 期: ...
另外 3 期标题/简介可能相关，但还没转录: ...
```

Never describe title/description hits as if they were found in the full transcript.

## Transcribe A Selected RSS Episode

```bash
python transcribe.py rss transcribe "日谈公园" 541 --chapters
python transcribe.py rss transcribe "日谈公园" "#12" --chapters
```

## Feed Catalog Maintenance

Use these when the user wants recommendations, first-time setup, source repair, or feed validation.

```bash
cd podscribe-feeds

python resolve_feeds.py bootstrap
python resolve_feeds.py add "声动早咖啡" --category tech-business --country cn
python resolve_feeds.py add "Latent Space" --category ai --country us
python resolve_feeds.py upgrade feeds/ --country cn
python resolve_feeds.py validate feeds/
python import_feeds.py --category ai health
python import_feeds.py --all
```

`bootstrap`, `add`, and `upgrade` need access to `itunes.apple.com`.

## Batch Sync

Batch sync is allowed only with an explicit scope:

```bash
python transcribe.py rss sync-feeds --category AI --limit 20
python transcribe.py rss sync-feeds --all --limit 20
```

Run `python transcribe.py rss browse-feeds` first when the scope is unclear.

## Direct SQLite Queries

For browsing and status questions, querying SQLite is often faster than transcription:

```bash
python -X utf8 -c "
import sqlite3, sys; sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('podcast_library/library.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT s.name, COUNT(e.id) as eps FROM subscriptions s LEFT JOIN episodes e ON s.id = e.subscription_id GROUP BY s.id ORDER BY eps DESC').fetchall()
for r in rows: print(f'  {r[\"name\"]}: {r[\"eps\"]} eps')
"
```

Search titles for a topic:

```bash
python -X utf8 -c "
import sqlite3, sys; sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('podcast_library/library.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT e.title, e.published_at, s.name as podcast FROM episodes e JOIN subscriptions s ON s.id = e.subscription_id WHERE e.title LIKE ? ORDER BY e.published_at DESC LIMIT 20', ('%AI%',)).fetchall()
for r in rows: print(f'[{r[\"published_at\"][:10]}] {r[\"podcast\"]}: {r[\"title\"]}')
"
```
