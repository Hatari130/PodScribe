# PodScribe

[English](./README.en.md) 

播客一站式 skill：**订阅 → 转录 → 知识库**。

自带分领域中英文播客订阅库（AI / 科技商业 / 人文社会 / 文化艺术 / 健康），可一键补全官方 RSS、导入订阅、同步元数据、全文转录、生成章节与摘要、本地全文搜索。

放进 Claude / Codex / WorkBuddy 等 Agent 的 skills 目录即可使用。用户不需要记命令，把需求交给 Agent 就行。

## 能干嘛

```text
"有什么好的 AI 播客？"                    → 查 feeds/ai.json，推荐并导入
"帮我把这期小宇宙转成文字稿"               → 转录单集
"这期播客讲了什么，帮我总结一下"             → 转录 + 摘要 + 章节
"帮我加上 Dwarkesh Podcast"              → resolve_feeds.py add
"把这个 RSS 加到本地库"                   → rss add
"这个播客最近有没有聊过 AI Agent？"         → rss search
"转成 Obsidian 笔记格式"                  → --summary obsidian
"哪些订阅源失效了？"                      → resolve_feeds.py validate
```

## 目录结构

```
podscribe/
├── transcribe.py                # 核心：转录 / RSS 管理 / 搜索
├── config.json                  # 硅基流动 API 配置
├── subscriptions.json           # 活跃订阅列表
├── podcast_library/             # 转录后的本地知识库
│
├── podscribe-feeds/             # 📦 分领域订阅库
│   ├── feeds/
│   │   ├── ai.json              # AI（中英混排，含 Lex Fridman）
│   │   ├── tech-business.json   # 科技与商业（含 Acquired / All-In …）
│   │   ├── humanities-society.json
│   │   ├── culture-art.json
│   │   └── health.json          # 健康（含 Huberman Lab）
│   ├── resolve_feeds.py         # iTunes 解析：bootstrap / add / upgrade / validate
│   └── import_feeds.py          # 合并分类 → subscriptions.json
│
├── SKILL.md                     # Agent 指令文档
└── README.md                    # 本文件
```

## 第一次使用

把github链接发给 Agent ,跟 Agent 说一句就行：

```text
"帮我装一下这个播客工具skill"
"配好播客PodScribe skill，我想开始用了"
```

Agent 会自动完成以下全部步骤：

1. **检查环境** — python / ffmpeg / ffprobe，缺什么装什么
2. **配置 API Key** — 运行 `python transcribe.py --init`，引导你填硅基流动的 Key（RSS 入库不需要，转录时才用）
3. **拉取订阅库** — 运行 `resolve_feeds.py bootstrap`，通过 iTunes 把内置 64 个中英文节目的官方 RSS 全部解析回来
4. **导入订阅** — 运行 `import_feeds.py --all`，合并进 `subscriptions.json`

全程你只需要提供一个硅基流动 API Key，其余 Agent 处理。

> 手动跑也行，见下面的命令，但一般不需要。

<details>
<summary>手动命令（折叠）</summary>

```bash
# 环境
# Windows:  winget install --id=Gyan.FFmpeg -e
# macOS:    brew install ffmpeg
# Ubuntu:   sudo apt install ffmpeg python3
python --version && ffmpeg -version && ffprobe -version

# 配置
python transcribe.py --init
# 或环境变量: export SILICONFLOW_API_KEY=sk-你的Key

# 订阅库
cd podscribe-feeds
python resolve_feeds.py bootstrap
python import_feeds.py --all
```

</details>

## 日常使用

### 转录单集

```bash
# 转录 + 章节 + 摘要（推荐）
python transcribe.py "<小宇宙链接>" --summary --chapters

# 纯转录
python transcribe.py "<小宇宙链接>"

# 指定摘要模式
python transcribe.py "<链接>" --summary deep --chapters
```

摘要模式：`brief`（快速看懂）、`deep`（结构化笔记）、`product`（产品经理视角）、`investment`（投资视角）、`obsidian`（Obsidian 格式）。

### RSS 知识库

不要默认批量转录。正确流程：同步 → 浏览/搜索 → 用户选某一期 → 转录。

```bash
# 添加订阅
python transcribe.py rss add "日谈公园" "https://anchor.fm/s/2389ed24/podcast/rss"

# 同步最近 50 期元数据
python transcribe.py rss sync "日谈公园" --limit 50

# 列出单集
python transcribe.py rss list "日谈公园" --limit 50

# 搜索（已转录的搜全文，未转录的只搜标题/简介）
python transcribe.py rss search "日谈公园" "AI Agent" --days 90

# 转录选中的一期
python transcribe.py rss transcribe "日谈公园" 6 --summary --chapters

# 列出所有订阅及统计
python transcribe.py rss subs
```

### 管理订阅库

```bash
cd podscribe-feeds

# 按名字加一个节目
python resolve_feeds.py add "Latent Space" --category ai --country us
python resolve_feeds.py add "声动早咖啡" --category tech-business --country cn

# 代理源升级为官方源
python resolve_feeds.py upgrade feeds/ --country cn

# 检查链接存活
python resolve_feeds.py validate feeds/

# 导入新增的
python import_feeds.py --all
```

## 输出

全文稿：`<标题>.md`
摘要：`<标题>.summary.brief.md` / `.deep.md` / `.obsidian.md` 等
RSS 转录：`podcast_library/transcripts/`
数据库：`podcast_library/library.sqlite3`
订阅：`subscriptions.json`

## 常用检查

```bash
python transcribe.py --preflight-only "<链接>"   # 转录前自检
python transcribe.py --help                       # 主命令帮助
python transcribe.py rss --help                   # RSS 帮助
```

## 当前限制

- 主要支持小宇宙 episode 链接和标准 RSS 音频源。
- RSS 中没有音频 URL 的单集只能入库标题和简介，不能转录。
- 转录模型不区分说话人。
- 自动章节和摘要适合作为初稿，重要内容建议人工复核。
- 长音频耗时取决于音频长度、并发数和 API 限流。
- `bootstrap` / `add` / `upgrade` 需要能访问 `itunes.apple.com`。
