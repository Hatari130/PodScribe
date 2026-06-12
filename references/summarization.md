# Summarization Workflow

Use this reference after transcription when the user asks for a summary, takeaways, notes, Obsidian output, product insights, or investment analysis.

## Rule

Do not rely on `transcribe.py` to summarize. The script creates transcripts and chapters. The current Agent must read the generated transcript and write the summary in the final answer.

Never answer only with “transcription complete, I can summarize.” If the user requested a summary, include the summary body.

## Default Brief Format

Use this when the user says “summarize,” “what did this episode say,” or does not specify a style. Target 500-900 Chinese characters unless the user asks otherwise.

```text
<标题> — <时长> / <字数> 字 / <段数> 段

一句话概括这期真正的主题，不超过 80 字。

核心线索：

<关键词 1> — 用 2-4 句话说明这一段在讲什么，必须来自全文稿中的具体内容、人物、事件、比喻或判断。

<关键词 2> — ...

<关键词 3> — ...

<关键词 4> — ...

<关键词 5> — ...

最后/最有意思/最动人的一幕 — 用 2-3 句话收束，点出这期播客最值得带走的情绪或判断。
```

## Quality Bar

- Include at least five information points. Use six to eight for dense long episodes.
- Make every point concrete. Avoid vague statements such as “they discussed many things” or “very inspiring.”
- Short quotations are fine; do not copy long transcript passages.
- Prefer stats from the `TranscribeResult` or script output for title, duration, word count, and segment count.
- If the user gives no style, use `brief` without asking follow-up questions.

## Style Modes

| Mode | Final answer shape |
|---|---|
| `brief` | Default short review, 500-900 Chinese characters, optimized for quick understanding. |
| `deep` | Default brief plus structured notes: background, main thread, concepts, memorable lines, follow-up questions. |
| `product` | Extract user needs, scenarios, product insights, content topics, and concrete actions. |
| `investment` | Extract industry judgments, supply-demand shifts, business models, risks, and verifiable signals. |
| `obsidian` | Markdown note with properties, backlink candidates, tags, summary, points, and short original quotes. |

`--summary <mode>` can be passed for compatibility and logging, but the Agent still writes the summary.
