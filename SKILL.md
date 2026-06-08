---
name: xiaoyuzhou-transcribe
description: 把小宇宙播客 (xiaoyuzhoufm.com) 或 RSS 播客单集转成带时间戳的 Markdown 文字稿，并可自动生成章节和摘要。用户给 episode 链接时直接转录；用户给 RSS 或想查询某个播客最近内容时，先同步 RSS 元数据，让用户选择具体单集转录，转录后自动缓存到本地知识库。使用硅基流动 SenseVoice 转录模型。
allowed-tools: Bash(python:*), Bash(python3:*), Bash(ffmpeg:*), Bash(ffprobe:*), Read
---

# 小宇宙播客转文字稿

## 何时使用

用户给了一个小宇宙 episode 链接，并希望：

- 转成文字 / 转录 / 生成文字稿
- 总结这期播客，先转录再总结
- 提取播客内容

用户给了 RSS 链接，或询问某个播客最近是否聊过某个主题时：

- 先用 RSS 命令同步标题、简介、发布时间、音频 URL
- 不要默认批量转录全部单集
- 让用户选择具体哪一期值得转录
- 已转录单集会自动进入本地知识库，可被全文搜索
- 未转录单集只能基于标题和简介判断相关性

链接格式通常是：

```text
https://www.xiaoyuzhoufm.com/episode/<id>
```

## 前置检查

执行前确认：

```bash
ffmpeg -version
ffprobe -version
python --version
```

如果缺少 `ffmpeg`：

- Windows: `winget install --id=Gyan.FFmpeg -e`
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`

## 配置

第一次使用优先运行配置向导：

```bash
python transcribe.py --init
```

这会在当前目录生成 `config.json`。真实 API Key 不要提交到 git。

也可以手动创建 `config.json`：

```json
{
  "siliconflow_api_key": "sk-你的Key",
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

如果没有配置文件，也可以读取环境变量：

- `SILICONFLOW_API_KEY`
- `SILICON_API_KEY`

配置优先级：

```text
命令行参数 > config.json > 环境变量 > 内置默认值
```

如果 `config.json` 中的 key 仍是占位符，但环境变量中有真实 key，脚本会使用环境变量。

## 启动前自检

转录前推荐先跑：

```bash
python transcribe.py --preflight-only "<小宇宙 episode 链接>"
```

自检会确认：

- `config.json` 或环境变量是否存在
- API Key 是否不是占位符
- `ffmpeg` / `ffprobe` 是否可用
- 硅基流动 API 是否可访问
- 小宇宙页面是否能解析出标题和音频 URL

## 执行

在本 skill 目录下直接调用：

```bash
python transcribe.py "<小宇宙 episode 链接>"
```

转录并生成摘要和章节：

```bash
python transcribe.py "<小宇宙 episode 链接>" --summary --chapters
```

## RSS 知识库流程

RSS 入库不需要 API Key；只有选择单集转录时需要 API Key。

所有 RSS 订阅会同时保存在 `subscriptions.json`（人类可读）和 SQLite 数据库中。

### 订阅管理

列出所有已订阅的播客：

```bash
python transcribe.py rss subs
```

输出示例：

```text
共 2 个订阅:

[1] 日谈公园  (0/50 期已转录)  添加于 2026-06-04  最近同步 2026-06-04
    RSS: https://anchor.fm/s/2389ed24/podcast/rss
[2] 硬地骇客  (3/30 期已转录)  添加于 2026-06-03  最近同步 2026-06-04
    RSS: https://feeds.example.com/hardhack
```

添加订阅：

```bash
python transcribe.py rss add "日谈公园" "<rss_url>"
```

同步最近 50 期或最近 90 天：

```bash
python transcribe.py rss sync "日谈公园" --limit 50
python transcribe.py rss sync "日谈公园" --limit 50 --days 90
```

列出单集，让用户选择要转录哪一期：

```bash
python transcribe.py rss list "日谈公园" --limit 50
```

转录用户选中的一期并写入知识库。选择器可以是期号、`#id` 或 guid 前缀：

```bash
python transcribe.py rss transcribe "日谈公园" 541 --summary --chapters
python transcribe.py rss transcribe "日谈公园" "#12"
```

搜索主题：

```bash
python transcribe.py rss search "日谈公园" "AI OpenAI Agent 大模型" --days 90
```

回答搜索类问题时必须说明覆盖范围：

```text
我检查了 日谈公园 的 38 期。
全文可搜索: 6 期
仅标题/简介可搜索: 32 期

在已转录全文里找到 2 期:
...

另外有 3 期标题/简介可能相关,但还没转录:
...
```

不要把“标题/简介命中”说成“全文里聊到”。如果用户想详细了解某一期，使用 `rss transcribe` 转录那一期。

可选参数：

- `--init`: 交互式生成 `config.json`
- `--preflight-only`: 只运行启动前自检
- `--skip-preflight`: 跳过启动前自检
- `--config <path>`: 指定配置文件路径
- `--output <path>` / `-o`: 指定输出 Markdown 路径
- `--segment-seconds <N>`: 分段时长，默认 30 秒
- `--workers <N>`: 并发请求数，默认 5
- `--model <name>`: 转录模型
- `--clean` / `--no-clean`: 是否做术语纠错和基础清洗，默认开启
- `--chapters`: 在全文稿开头写入自动章节
- `--chapter-window <N>`: 自动章节窗口秒数，默认 300
- `--summary [mode]`: 转录后生成摘要，默认 `brief`
- `--summary-output <path>`: 指定摘要输出路径
- `--summary-model <name>`: 指定摘要模型
- `--keep-audio` / `--no-keep-audio`: 是否保留临时音频文件

- `rss add`: 添加或更新 RSS 订阅（同时更新 `subscriptions.json`）
- `rss subs`: 列出所有已订阅的播客名称、RSS 链接和转录统计
- `rss sync`: 读取 RSS，把单集元数据入库
- `rss list`: 列出已入库单集和转录状态
- `rss transcribe`: 选择一期转录并写入本地库
- `rss search`: 搜索已转录全文，并提示未转录的标题/简介命中

摘要模式：

- `brief`: 3 分钟看完
- `deep`: 深度笔记
- `product`: 产品经理视角
- `investment`: 投资视角
- `obsidian`: Obsidian 笔记格式

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

## 交付给用户

转录完成后：

1. 告诉用户生成的文件路径。
2. 如果生成了摘要，也告诉用户摘要文件路径。
3. 报告总时长、分段数和总字数。
4. 用户要“总结下说了啥”时，优先使用 `--summary --chapters`，不要只交付全文稿。
5. 如果摘要模型失败，脚本会用本地规则兜底；需要说明摘要是兜底生成的。

## 失败处理

- 提取不到音频 URL: 检查链接是否是 episode 页面，不是 podcast 主页。
- 自检失败: 按脚本列出的修复项处理，常见是缺少 `config.json`、key 仍是占位符、`ffmpeg` 不在 PATH。
- HTTP 401: API Key 失效或填错，让用户检查 `config.json` 或环境变量。
- HTTP 429: 速率受限，脚本会自动等待后重试。
- HTTP 402: 余额不足，让用户检查硅基流动账户额度。
- ffmpeg `Invalid data`: 音频下载可能不完整，重跑。
