# planning.schema —— 规划 / 目标

> 记录「想达成什么」。task 是要做的具体事,planning 是这些事背后的目标/里程碑。
> 一个 planning 会拆解成多条 task;task 用 `planning_ref` 反指回来。

## 存储形态

一个规划项 = 一个 `<id>.md` 文件。frontmatter 存字段,正文写背景、思路。

## 字段

### 必填

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `id` | string | `plan-YYYY-...`(如 plan-2026-q3-01) |
| `title` | string | 一句话标题 |
| `type` | enum | `objective`(目标) / `milestone`(里程碑) / `roadmap_item`(路线项) / `theme`(主题) |
| `horizon` | enum | `now`(当下) / `quarter`(本季) / `year`(本年) / `someday`(有朝一日) |
| `category` | enum | 事业 / 学业 / 人际 / 生活 / 系统(同 task) |
| `status` | enum | `proposed`(提出) / `active`(进行) / `achieved`(达成) / `dropped`(放弃) / `deferred`(推迟) |

### 自动填充

`domain` / `source_machine` / `created_at` / `updated_at`

### 可选

| 字段 | 类型 | 说明 |
|---|---|---|
| `success_criteria` | markdown | 达成判据(怎样算完成) |
| `parent` | planning_id | 上级规划(objective ← milestone 层级) |
| `task_refs` | list[task_id] | 派生出的任务 |
| `decision_refs` | list[decision_id] | 相关决策 |
| `review_interval` | string | 复盘间隔(如 `weekly`/`monthly`),供心跳推送提醒复盘 |
| `tags` | list[string] | 自由标签 |

## 层级示例

```
objective「今年发一篇顶会」
   └─ milestone「Q3 完成 Monarch-MoE 实验」
         └─ task「跑 DISCO+Monarch 消融」
```
