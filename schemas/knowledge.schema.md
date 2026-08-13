# knowledge / knowledge-note.schema —— 学习内容与具体笔记

知识库使用两级实体，避免“要不要学、先学什么”的宏观队列和长篇具体笔记混在一起。

## knowledge item

一条 `knowledge-*.md` 代表一个可学习对象，例如论文、播客、书籍、课程、文章或视频。正文用于
保存该内容的概述或学习背景。

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 内容标题 |
| `kind` | enum | `paper / podcast / book / course / article / video / other` |
| `status` | enum | `want / learning / learned / archived` |
| `priority` | enum | `P0 / P1 / P2 / P3`，决定想学队列顺序 |
| `category` | enum | 事业 / 学业 / 人际 / 生活 / 系统 |
| `creator` | string | 作者、主讲人或播客主播（可选） |
| `source_url` | string | 原始来源（可选） |
| `published_on` | date | 发布日期（可选） |
| `learned_on` | date | 学完日期；进入 learned 时自动补当天（可选） |
| `duration_minutes` | number | 阅读或收听时长，非负（可选） |
| `rating` | integer | 1–5 分（可选） |
| `tags` | list | 主题标签（可选） |

## knowledge note

一条 `knote-*.md` 代表挂在具体知识条目下的一次记录，正文保存原始笔记内容。一个条目可以有
任意多条笔记，适合分多次学习和持续补充思考。

| 字段 | 类型 | 说明 |
|---|---|---|
| `knowledge_ref` | knowledge_id | 必须指向一个存在的知识条目 |
| `note_type` | enum | `summary / insight / question / connection / action / quote` |
| `captured_on` | date | 记录日期 |
| `title` | string | 本条笔记的小标题（可选） |
| `tags` | list | 主题标签（可选） |

知识条目记录“学什么和学到哪”，具体笔记记录“学到了什么、我怎么想”。已经提炼为可复用行为
经验的内容仍应进入 `rule`；对应一次完成行动的事实仍由 task/worklog 负责。
