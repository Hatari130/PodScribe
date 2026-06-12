# Project Layout

Use this reference when changing the skill structure, explaining where files live, or debugging path assumptions.

## Layout

```text
podscribe/
├── SKILL.md
├── references/
│   ├── transcription.md
│   ├── summarization.md
│   ├── rss-workflows.md
│   ├── troubleshooting.md
│   └── project-layout.md
├── agents/
│   └── openai.yaml
├── transcribe.py
├── config.json
├── subscriptions.json
├── podcast_library/
│   ├── library.sqlite3
│   └── transcripts/
└── podscribe-feeds/
    ├── feeds/
    │   ├── ai.json
    │   ├── tech-business.json
    │   ├── humanities-society.json
    │   ├── culture-art.json
    │   └── health.json
    ├── resolve_feeds.py
    └── import_feeds.py
```

## Path Assumptions

The executable scripts currently live at the repository root and under `podscribe-feeds/` to preserve relative paths used by existing commands.

Do not move `transcribe.py`, `podscribe-feeds/resolve_feeds.py`, or `podscribe-feeds/import_feeds.py` into `scripts/` unless you also update command examples, imports, working-directory assumptions, and any path logic in the code.

## Skill Packaging Notes

A strict skill package needs `SKILL.md`. `references/` is for detailed instructions loaded on demand. `agents/openai.yaml` is UI metadata. `scripts/` is useful for deterministic helper scripts, but this project already has operational scripts in established locations.

`podcast_library/` and `subscriptions.json` are runtime state. They are useful in this local working skill, but should be excluded or reset for a clean distributable template if the skill is packaged for others.
