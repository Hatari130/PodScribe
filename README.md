# xiaoyuzhou-transcribe

把小宇宙播客单集转成带时间戳的 Markdown 文字稿，并可自动生成章节和摘要。也支持把播客 RSS 先入库，用户选择某一期转录后沉淀到本地知识库。

当前实现使用硅基流动的 `FunAudioLLM/SenseVoiceSmall` 转录接口，适合中文播客。脚本只依赖 Python 标准库，音频处理依赖本机 `ffmpeg` / `ffprobe`。

## 工作流

```text
小宇宙 episode 链接
  -> 启动前自检配置、ffmpeg、API、小宇宙页面
  -> 抓取页面 HTML,提取标题和 media.xyzcdn.net 音频直链
  -> 下载音频
  -> ffmpeg 转单声道 MP3
  -> 按 segment_seconds 预切片
  -> 并发调用 SiliconFlow audio/transcriptions
  -> 清洗术语和转录文本
  -> 生成带时间戳的 Markdown
  -> 可选生成章节和摘要
```

RSS 模式：

```text
RSS 链接
  -> 读取最近 N 期或最近 N 天
  -> 入库标题、发布时间、简介、音频 URL、原始链接
  -> 用户选择某一期转录
  -> 转录结果写入本地库
  -> 搜索时区分“已转录全文”和“仅标题/简介”
```

## 安装依赖

### Windows

```powershell
winget install --id=Gyan.FFmpeg -e
python --version
ffmpeg -version
ffprobe -version
```

如果 `python` 不可用，去 <https://www.python.org/downloads/> 安装，并勾选 `Add Python to PATH`。

### macOS

```bash
brew install ffmpeg
python3 --version
ffmpeg -version
ffprobe -version
```

### Ubuntu / Debian

```bash
sudo apt install ffmpeg python3
python3 --version
ffmpeg -version
ffprobe -version
```

## 配置

推荐用配置向导：

```powershell
python transcribe.py --init
```

这会在当前目录生成 `config.json`。真实 API Key 不要提交到 git；本目录的 `.gitignore` 已忽略 `config.json`。

也可以手动创建：

```json
{
  "siliconflow_api_key": "sk-替换成你的硅基流动APIKey",
  "model": "FunAudioLLM/SenseVoiceSmall",
  "api_endpoint": "https://api.siliconflow.cn/v1/audio/transcriptions",
  "segment_seconds": 30,
  "workers": 5,
  "audio_bitrate": "64k",
  "output": null,
  "keep_audio": false,
  "library_dir": "podcast_library",
  "summary_model": "Qwen/Qwen2.5-7B-Instruct",
  "summary_api_endpoint": "https://api.siliconflow.cn/v1/chat/completions"
}
```

也可以不用配置文件，改用环境变量：

```powershell
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", "sk-你的Key", "User")
```

```bash
export SILICONFLOW_API_KEY=sk-你的Key
```

配置优先级：

```text
命令行参数 > config.json > 环境变量 > 内置默认值
```

如果 `config.json` 里的 key 仍是占位符，但环境变量里有真实 key，脚本会使用环境变量。

## 启动前自检

```powershell
python transcribe.py --preflight-only "https://www.xiaoyuzhoufm.com/episode/xxxxx"
```

自检会确认 `config.json` 或环境变量、API Key、`ffmpeg`、`ffprobe`、硅基流动 API、小宇宙页面解析是否正常。

## 使用

只转录：

```powershell
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxxxx"
```

转录并生成摘要和章节：

```powershell
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxxxx" --summary --chapters
```

摘要模式：

```powershell
python transcribe.py "<url>" --summary brief
python transcribe.py "<url>" --summary deep
python transcribe.py "<url>" --summary product
python transcribe.py "<url>" --summary investment
python transcribe.py "<url>" --summary obsidian
```

默认会做基础术语清洗。需要关闭时：

```powershell
python transcribe.py "<url>" --no-clean
```

## RSS CLI MVP

RSS 入库不需要 API Key；只有选择某一期转录时才需要硅基流动 API Key。

所有 RSS 订阅会同时保存在 `subscriptions.json`（人类可读）和 SQLite 数据库中。

### 查看所有订阅

```powershell
python transcribe.py rss subs
```

输出示例：

```text
共 2 个订阅:

[1] 日谈公园  (0/50 期已转录)  添加于 2026-06-04  最近同步 2026-06-04
    RSS: https://anchor.fm/s/2389ed24/podcast/rss
```

### 添加与同步

添加订阅：

```powershell
python transcribe.py rss add "日谈公园" "<rss_url>"
```

同步最近 50 期，或只同步最近 90 天：

```powershell
python transcribe.py rss sync "日谈公园" --limit 50
python transcribe.py rss sync "日谈公园" --limit 50 --days 90
```

列出已入库单集：

```powershell
python transcribe.py rss list "日谈公园"
python transcribe.py rss list "日谈公园" --days 90 --limit 50
```

选择某一期转录并写入知识库。选择器可以用列表里的期号、`#id` 或 guid 前缀：

```powershell
python transcribe.py rss transcribe "日谈公园" 541 --summary --chapters
python transcribe.py rss transcribe "日谈公园" "#12"
```

搜索最近 90 天。已转录内容会搜索全文；未转录内容只搜索标题和简介：

```powershell
python transcribe.py rss search "日谈公园" "AI OpenAI Agent 大模型" --days 90
```

示例输出会明确标注覆盖范围：

```text
我检查了 日谈公园 的 38 期。
时间范围: 最近 90 天
全文可搜索: 6 期
仅标题/简介可搜索: 32 期

在已转录全文里找到 2 期:
...

另外有 3 期标题/简介可能相关,但还没转录:
...
```

默认库目录是 `podcast_library/`，里面会生成 `library.sqlite3` 和 `transcripts/`。可以在 `config.json` 里改 `library_dir`，也可以用：

```powershell
python transcribe.py rss --library-dir "D:\podcast_library" list "日谈公园"
```

## 命令行参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--init` | - | 交互式生成 `config.json` |
| `--force` | - | 配合 `--init` 覆盖已存在配置 |
| `--preflight-only` | - | 只运行启动前自检 |
| `--skip-preflight` | - | 跳过启动前自检 |
| `--config` | 自动查找 `config.json` | 配置文件路径 |
| `--output` / `-o` | `./<标题>.md` | 输出 Markdown 路径 |
| `--segment-seconds` | `30` | 时间戳分段窗口大小 |
| `--workers` | `5` | 并发转录请求数 |
| `--model` | `FunAudioLLM/SenseVoiceSmall` | 转录模型 |
| `--api-endpoint` | SiliconFlow transcription endpoint | OpenAI 兼容转录接口 |
| `--audio-bitrate` | `64k` | 转码后的 MP3 码率 |
| `--clean` / `--no-clean` | `true` | 是否做术语纠错和基础清洗 |
| `--chapters` | - | 在全文稿中写入自动章节 |
| `--chapter-window` | `300` | 自动章节窗口秒数 |
| `--summary` | - | 转录后生成摘要，可选 `brief/deep/product/investment/obsidian` |
| `--summary-output` | 同目录派生 | 摘要输出路径 |
| `--summary-model` | `Qwen/Qwen2.5-7B-Instruct` | 摘要模型 |
| `--keep-audio` / `--no-keep-audio` | `false` | 是否保留临时音频文件 |
| `rss add` | - | 添加或更新 RSS 订阅（同时更新 `subscriptions.json`） |
| `rss subs` | - | 列出所有已订阅的播客名称、RSS 链接和转录统计 |
| `rss sync` | `--limit 50` | 读取 RSS，把单集元数据入库 |
| `rss list` | `--limit 20` | 列出已入库单集和转录状态 |
| `rss transcribe` | - | 选择一期转录并写入本地库 |
| `rss search` | `--episodes 50` | 搜索已转录全文，并提示未转录的标题/简介命中 |

## 输出格式

```markdown
# <播客单集标题>

- **来源**: <原链接>
- **节目**: <节目名>
- **时长**: HH:MM:SS
- **转录时间**: 2026-06-04 12:00
- **模型**: FunAudioLLM/SenseVoiceSmall

---

## 章节

- **00:00** 开场与主题

---

**[00:00 - 00:30]** 这一段的转录文字……
```

摘要默认写到全文稿同目录，例如：

```text
<标题>.summary.brief.md
<标题>.obsidian.md
```

## 已知限制

- 小宇宙页面解析依赖 `media.xyzcdn.net` 音频直链和 `og:title` meta；如果小宇宙页面结构改版，需要更新 `parse_episode()`。
- RSS 模式依赖 feed 里的 `enclosure` 音频 URL；如果某期没有音频 enclosure，只能入库标题和简介，不能直接转录。
- RSS 搜索会区分覆盖范围：未转录单集不会被当作全文搜索结果。
- SenseVoice 当前不输出 speaker label，所以不会自动区分说话人。
- 自动章节是规则生成，适合作为初稿；严格章节名仍建议人工校对。
- 摘要优先调用硅基流动 chat completions；失败时脚本会使用本地规则兜底。
- 大文件通过本地切片规避单次上传限制，但总耗时仍取决于音频长度、并发数和 API 限流。
