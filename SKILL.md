---
name: podscribe
description: |
  播客一站式工具：自带分领域中英文播客 RSS 订阅库（AI / 科技商业 / 人文社会 / 文化艺术 / 健康），可一键通过 iTunes 补全官方源、导入订阅、同步元数据、全文转录、章节与摘要生成、本地知识库搜索。
  触发场景：
  - 用户给了小宇宙 episode 链接，想转录/总结/提取内容
  - 用户给了 RSS 链接，或问某个播客最近是否聊过某个主题
  - 用户想订阅/发现/管理播客（如"有什么好的 AI 播客""帮我找健康类播客"）
  - 用户想批量导入播客订阅、补全 RSS 地址、检查链接是否失效
  - 用户想搜索已转录的播客内容（全文搜索）
  使用硅基流动 SenseVoice 转录 + Qwen 摘要。订阅库通过 iTunes 公开接口解析官方 RSS。
allowed-tools: Bash(python:*), Bash(python3:*), Bash(ffmpeg:*), Bash(ffprobe:*), Read
---

# PodScribe — 播客订阅·转录·知识库

一站式播客工具。自带分领域中英文订阅库，支持一键补全官方 RSS → 导入 → 同步 → 转录 → 摘要 → 全文搜索。

## 目录结构

```
podscribe/
├── transcribe.py                # 核心：转录 / RSS 管理 / 搜索
├── config.json                  # 硅基流动 API 配置
├── subscriptions.json           # PodScribe 的活跃订阅（transcribe.py 读写）
├── podcast_library/             # 转录后的本地知识库
├── podscribe-feeds/             # 📦 分领域订阅库（本 skill 附带）
│   ├── feeds/
│   │   ├── ai.json              # AI（中文 + 英文 Lex Fridman 等）
│   │   ├── tech-business.json   # 科技与商业（中英混排）
│   │   ├── humanities-society.json
│   │   ├── culture-art.json
│   │   └── health.json
│   ├── resolve_feeds.py         # iTunes 解析：bootstrap / add / upgrade / validate
│   └── import_feeds.py          # 合并分类文件 → subscriptions.json
├── SKILL.md
└── README.md
```

---

## 一、播客订阅库（podscribe-feeds）

### 何时使用

- 用户想发现/推荐播客："有什么好的 AI 播客""推荐英文健康类节目"
- 用户想批量导入订阅：第一次用 PodScribe 时初始化
- 用户想添加某个节目："帮我加上 Dwarkesh Podcast"
- 用户想检查/修复 RSS 链接："哪些源失效了"

### 初始化（首次使用）

```bash
cd podscribe-feeds

# 1) 一键拉全内置清单（64 个中英文高质量节目）的官方 RSS
#    需要能访问 itunes.apple.com
python resolve_feeds.py bootstrap

# 2) 把 feeds/*.json 去重合并进上级的 subscriptions.json
python import_feeds.py --all
```

### 按需操作

```bash
# 按名字添加一个节目（中文用 --country cn）
python resolve_feeds.py add "声动早咖啡" --category tech-business --country cn
python resolve_feeds.py add "Latent Space" --category ai --country us

# 把代理源（rsshub）升级为 Apple 官方源
python resolve_feeds.py upgrade feeds/ --country cn

# 体检：检查哪些 RSS 链接还活着
python resolve_feeds.py validate feeds/

# 只导入某几个领域
python import_feeds.py --category ai health
```

### 内置领域与节目数

| 领域 | 文件 | 预置真实 RSS | bootstrap 补充 |
|------|------|-------------|---------------|
| AI | ai.json | 9（含 Lex Fridman） | +22 英文（Dwarkesh / 80k Hours / AXRP …） |
| 科技商业 | tech-business.json | 26（含 Acquired / All-In / Founders …） | +12 |
| 人文社会 | humanities-society.json | 15 | +12（Hidden Brain / Ezra Klein …） |
| 文化艺术 | culture-art.json | 4 | +10（99% Invisible / Song Exploder …） |
| 健康 | health.json | 1（Huberman Lab） | +8（Peter Attia / Found My Fitness …） |

---

## 二、转录（transcribe.py）

### 何时使用

- 用户给了小宇宙链接（`xiaoyuzhoufm.com/episode/<id>`），想转文字/总结/提取
- 用户选了某一期想详细听，先转录再聊

### 前置检查

```bash
ffmpeg -version && ffprobe -version && python --version
```

缺 ffmpeg：Windows `winget install Gyan.FFmpeg`、macOS `brew install ffmpeg`、Ubuntu `apt install ffmpeg`。

### 配置

首次使用运行配置向导：

```bash
python transcribe.py --init
```

生成 `config.json`（硅基流动 API Key）。也可用环境变量 `SILICONFLOW_API_KEY`。

配置优先级：命令行参数 > config.json > 环境变量 > 内置默认值。

### 自检

```bash
python transcribe.py --preflight-only "<episode 链接>"
```

确认 config / API Key / ffmpeg / 硅基流动 API / 小宇宙页面解析。

### 执行

```bash
# 纯转录
python transcribe.py "<episode 链接>"

# 转录 + 章节 + 摘要（推荐）
python transcribe.py "<episode 链接>" --summary --chapters
```

### 摘要模式

| 模式 | 用途 |
|------|------|
| `brief` | 3 分钟看完（默认） |
| `deep` | 深度笔记 |
| `product` | 产品经理视角 |
| `investment` | 投资视角 |
| `obsidian` | Obsidian 笔记格式 |

```bash
python transcribe.py "<链接>" --summary deep --chapters
```

---

## 三、RSS 知识库（transcribe.py rss）

### 何时使用

- 用户问"某播客最近有没有聊 AI Agent"→ 先同步再搜索
- 用户想浏览某播客的最近几期 → list
- 用户想转录某一期 → transcribe

RSS 入库不需要 API Key；只有转录时需要。

### 订阅管理

```bash
# 列出所有订阅及转录统计
python transcribe.py rss subs

# 手动添加
python transcribe.py rss add "日谈公园" "https://anchor.fm/s/2389ed24/podcast/rss"

# 同步最近 50 期元数据
python transcribe.py rss sync "日谈公园" --limit 50

# 列出单集（让用户选）
python transcribe.py rss list "日谈公园" --limit 50
```

### 搜索

```bash
python transcribe.py rss search "日谈公园" "AI Agent 大模型" --days 90
```

回答搜索类问题时**必须说明覆盖范围**：

```
我检查了 日谈公园 的 38 期。
全文可搜索: 6 期
仅标题/简介可搜索: 32 期

在已转录全文里找到 2 期: ...
另外 3 期标题/简介可能相关，但还没转录: ...
```

不要把"标题/简介命中"说成"全文里聊到"。

### 转录入库

```bash
# 按期号或 #id 转录
python transcribe.py rss transcribe "日谈公园" 541 --summary --chapters
python transcribe.py rss transcribe "日谈公园" "#12"
```

---

## 四、输出格式

```markdown
# <标题>

- **来源**: <链接>
- **节目**: <节目名>
- **时长**: HH:MM:SS
- **转录时间**: 2026-06-04 12:00
- **模型**: FunAudioLLM/SenseVoiceSmall

---

## 章节

- **00:00** 开场与主题
- **05:30** …

---

**[00:00 - 00:30]** 这一段的转录文字……
```

## 五、交付给用户

1. 告诉用户生成的文件路径。
2. 如果有摘要，告诉摘要文件路径。
3. 报告总时长、分段数、总字数。
4. 用户要"总结下说了啥"时优先用 `--summary --chapters`，不要只给全文稿。
5. 如果摘要模型失败脚本会用本地规则兜底，需说明。

## 六、常见参数速查

| 参数 | 作用 |
|------|------|
| `--summary [mode]` | 生成摘要（brief/deep/product/investment/obsidian） |
| `--chapters` | 自动章节 |
| `--segment-seconds N` | 分段时长（默认 30s） |
| `--workers N` | 并发数（默认 5） |
| `--clean / --no-clean` | 术语纠错（默认开） |
| `--keep-audio` | 保留临时音频 |
| `--output PATH` | 指定输出路径 |
| `--config PATH` | 指定配置文件 |
| `--skip-preflight` | 跳过自检 |

## 七、失败处理

| 错误 | 处理 |
|------|------|
| 提取不到音频 URL | 确认是 episode 链接，不是 podcast 主页 |
| 自检失败 | 按提示修，常见: 缺 config.json / key 是占位符 / ffmpeg 不在 PATH |
| HTTP 401 | API Key 失效或填错 |
| HTTP 429 | 速率受限，脚本自动等待重试 |
| HTTP 402 | 余额不足，检查硅基流动账户 |
| ffmpeg Invalid data | 音频下载不完整，重跑 |
| iTunes 连不上（bootstrap） | 确认能访问 itunes.apple.com，大陆直连通常可用 |
