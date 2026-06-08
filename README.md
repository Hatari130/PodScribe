# podscribe

`podscribe` 是一个给 Claude、Codex、WorkBuddy 等 Agent 使用的播客转录 skill。

你可以把这个目录放进对应工具的 skills 目录里，让 Agent 在需要处理播客时调用它。它的目标不是做一个完整播客客户端，而是帮你把播客内容沉淀成本地可搜索、可总结、可整理的 Markdown 文档。

## 能干嘛

`podscribe` 主要做三件事：

1. 把小宇宙单集链接转成带时间戳的 Markdown 文字稿。
2. 给文字稿自动生成章节和摘要。
3. 管理 RSS 播客库，让 Agent 可以先同步节目列表，再按需选择某一期转录和搜索。

适合这些场景：

- “帮我把这期小宇宙转成文字稿。”
- “这期播客讲了什么，帮我总结一下。”
- “把这个播客 RSS 加到本地库，以后方便搜索。”
- “帮我查一下这个播客最近有没有聊过 AI Agent。”
- “把这期转成 Obsidian 笔记格式。”

## 适合放在哪里

这是一个本地 skill，适合放在：

- Claude 的本地 skills 目录
- Codex 的 skills 目录
- WorkBuddy 的 skills 目录
- 其他能读取本地 skill 并执行命令的 Agent 环境

放好后，Agent 应该在本目录运行命令：

```powershell
python transcribe.py ...
```

## 第一次使用前

需要本机具备：

- Python 3
- `ffmpeg`
- `ffprobe`
- 硅基流动 API Key

Windows 安装 `ffmpeg`：

```powershell
winget install --id=Gyan.FFmpeg -e
```

macOS：

```bash
brew install ffmpeg
```

Ubuntu / Debian：

```bash
sudo apt install ffmpeg python3
```

确认环境：

```powershell
python --version
ffmpeg -version
ffprobe -version
```

生成配置：

```powershell
python transcribe.py --init
```

也可以用环境变量提供 API Key：

```powershell
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", "sk-xxx", "User")
```

```bash
export SILICONFLOW_API_KEY=sk-xxx
```

不要把真实 API Key 提交到仓库。仓库里的 `config.json` 应该保持占位 key，或者改用环境变量。

## 用户怎么用

用户不需要记完整命令，只要把需求交给 Agent。

例如：

```text
帮我转录这期小宇宙，并生成摘要和章节：
https://www.xiaoyuzhoufm.com/episode/xxxxx
```

Agent 应该执行：

```powershell
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxxxx" --summary --chapters
```

如果用户只要全文稿：

```powershell
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxxxx"
```

如果用户要 Obsidian 笔记：

```powershell
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxxxx" --summary obsidian --chapters
```

## Agent 应该怎么用

### 转录单集

当用户给出小宇宙 episode 链接，并要求转录、总结、整理笔记时，优先使用单集转录。

推荐默认命令：

```powershell
python transcribe.py "<episode_url>" --summary --chapters
```

只转录不总结：

```powershell
python transcribe.py "<episode_url>"
```

指定摘要类型：

```powershell
python transcribe.py "<episode_url>" --summary brief
python transcribe.py "<episode_url>" --summary deep
python transcribe.py "<episode_url>" --summary product
python transcribe.py "<episode_url>" --summary investment
python transcribe.py "<episode_url>" --summary obsidian
```

摘要模式含义：

- `brief`：快速看懂这期讲了什么。
- `deep`：更详细的结构化笔记。
- `product`：偏产品经理视角。
- `investment`：偏投资分析视角。
- `obsidian`：适合放进 Obsidian 的笔记格式。

### 使用 RSS 播客库

当用户给的是 RSS，或问“某个播客最近有没有聊过某主题”时，不要默认批量转录所有单集。正确流程是：

1. 添加或同步 RSS。
2. 列出或搜索已有单集。
3. 让用户选择值得转录的那一期。
4. 只转录选中的单集。

添加订阅：

```powershell
python transcribe.py rss add "播客名" "<rss_url>"
```

同步最近 50 期：

```powershell
python transcribe.py rss sync "播客名" --limit 50
```

列出单集：

```powershell
python transcribe.py rss list "播客名" --limit 50
```

搜索主题：

```powershell
python transcribe.py rss search "播客名" "AI Agent" --episodes 50
```

转录选中的某一期：

```powershell
python transcribe.py rss transcribe "播客名" 6 --summary --chapters
```

`selector` 可以是期号、列表里的 `#id`，也可以是 guid 前缀。

搜索结果需要注意：

- 已转录单集会搜索全文。
- 未转录单集只会搜索标题和简介。
- 标题或简介命中，不代表全文里一定详细讨论过这个主题。

## 输出什么

默认会输出 Markdown 文件路径。

全文稿通常是：

```text
<标题>.md
```

摘要文件通常是：

```text
<标题>.summary.brief.md
<标题>.summary.deep.md
<标题>.summary.product.md
<标题>.summary.investment.md
<标题>.obsidian.md
```

RSS 模式下，转录结果会保存在：

```text
podcast_library/transcripts/
```

本地库数据库在：

```text
podcast_library/library.sqlite3
```

订阅列表在：

```text
subscriptions.json
```

## 常用检查

转录前自检：

```powershell
python transcribe.py --preflight-only "https://www.xiaoyuzhoufm.com/episode/xxxxx"
```

查看主命令帮助：

```powershell
python transcribe.py --help
```

查看 RSS 命令帮助：

```powershell
python transcribe.py rss --help
```

## 当前限制

- 目前主要支持小宇宙 episode 链接和标准 RSS 音频源。
- RSS 中没有音频 URL 的单集只能入库标题和简介，不能直接转录。
- 转录模型不会自动区分说话人。
- 自动章节和摘要适合作为初稿，重要内容建议人工复核。
- 长音频耗时取决于音频长度、并发数和 API 限流。
