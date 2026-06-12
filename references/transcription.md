# Transcription Workflow

Use this reference when the user wants an episode converted to a transcript or when an RSS episode has been selected for transcription.

## Preconditions

Check the local runtime when needed:

```bash
ffmpeg -version
ffprobe -version
python --version
```

Install missing `ffmpeg` with the platform package manager: Windows `winget install Gyan.FFmpeg`, macOS `brew install ffmpeg`, Ubuntu `apt install ffmpeg`.

## Configuration

Run the wizard only when configuration is missing or the user asks to initialize:

```bash
python transcribe.py --init
```

Default transcription uses BcutASR and needs no API key. `--asr-provider siliconflow` is the legacy SenseVoice path and needs `SILICONFLOW_API_KEY` or a key in `config.json`.

Configuration priority: command-line arguments, `config.json`, environment variables, built-in defaults.

## Preflight

```bash
python transcribe.py --preflight-only "<episode-url>"
```

Preflight checks `ffmpeg`, `ffprobe`, ASR provider setup, and episode page parsing. Only siliconflow checks an API key.

## Direct Episode Transcription

Use chapters by default:

```bash
python transcribe.py "<episode-url>" --chapters
```

Use plain transcription only when the user explicitly does not want chapters:

```bash
python transcribe.py "<episode-url>"
```

Switch ASR provider only when needed:

```bash
python transcribe.py "<episode-url>" --asr-provider jianying --chapters
python transcribe.py "<episode-url>" --asr-provider siliconflow --chapters
```

## RSS Episode Transcription

After syncing and listing a podcast, transcribe the selected episode by index or id:

```bash
python transcribe.py rss transcribe "<podcast-name>" 541 --chapters
python transcribe.py rss transcribe "<podcast-name>" "#12" --chapters
```

## Common Parameters

| Parameter | Purpose |
|---|---|
| `--chapters` | Write automatic chapters into the transcript. |
| `--summary [mode]` | Compatibility/style hint for the Agent; does not create a summary file. |
| `--asr-provider` | ASR engine: `bcut`, `jianying`, or `siliconflow`. |
| `--segment-seconds N` | Target transcript paragraph length; default is about 30 seconds. |
| `--workers N` | Concurrent workers; default is 5. |
| `--free-asr-chunk-minutes N` | Long-audio chunk size for free ASR; default is 10 minutes. |
| `--free-asr-overlap-seconds N` | Chunk overlap for free ASR; default is 10 seconds. |
| `--free-asr-workers N` | Chunk transcription concurrency; default is 3. |
| `--clean` / `--no-clean` | Enable or disable terminology cleanup. |
| `--keep-audio` | Keep temporary audio files. |
| `--output PATH` | Set transcript output path. |
| `--config PATH` | Set config file path. |
| `--skip-preflight` | Skip preflight checks. |

## Output

Direct episode output is a Markdown transcript path chosen by `transcribe.py` or `--output`.
RSS transcript output is under `podcast_library/transcripts/`.

Report the generated path and any printed stats. If the user also requested a summary, read the transcript file before answering.
