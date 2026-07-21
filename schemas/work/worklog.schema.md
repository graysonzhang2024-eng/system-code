# worklog.schema —— 工作日志(只增不改)

> 记录「做过的一件事」。与 task(要做的事)相对。
> **append-only**:一旦写下就不再修改,是一条时间线上的事实记录。
> 一物两用:既是「已完成的叙事」,又是复盘「提炼规则」的原料(`rule_candidates`)。

## 存储形态

一条日志 = 一个 `<id>.md` 文件。frontmatter 存结构化字段,正文 `what_done` 可写详细过程。

## 字段

### 必填

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | `log-YYYY-NNNN` 或任意唯一串 |
| `date` | date | 这件事发生在哪天 `YYYY-MM-DD` |
| `summary` | string | 一句话概括 |
| `category` | enum | 事业 / 学业 / 人际 / 生活 / 系统(同 task) |

### 自动填充

| 字段 | 类型 | 说明 |
|---|---|---|
| `domain` / `source_machine` | enum | 由机器身份自动决定 |
| `created_at` / `updated_at` | string | 自动时间戳 |

### 可选

| 字段 | 类型 | 说明 | 服务哪个活 |
|---|---|---|---|
| `task_ref` | task_id | 关联的任务(可空,支持无计划的临时工作) | 复盘·追溯 |
| `time_spent` | number | 花了多久(番茄数或小时) | 复盘·精力校准 |
| `energy_actual` | enum | `low`/`medium`/`high`/`drain`,实际消耗(对比 task 的估计) | 复盘·精力校准 |
| `artifacts` | list[string] | 产出物(文件路径 / URL) | 追溯 |
| `learnings` | markdown | 学到了什么 | 复盘 |
| `rule_candidates` | list[string] | 从这次经历提炼的规则候选 → 喂给 rule 库 | 复盘·提炼规则 |
| `tags` | list[string] | 自由标签 | 筛选 |

## 正文约定

`what_done`(具体做了什么)写在正文,可长可短,支持清单、代码块、链接。

## 设计意图

- **只增不改**:日志是历史事实,改它等于篡改历史。要修正就新写一条。
- **rule_candidates 是复盘的原料**:未来「复盘·提炼规则」这个活,会扫描一段时间的 worklog,把 `rule_candidates` 汇总成正式的 `rule` 记录。

## 样例

见 `fixtures/work/`。
