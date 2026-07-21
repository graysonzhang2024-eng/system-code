# rule.schema —— 已验证规则(通用)

> 记录「一条验证过的经验」:什么情况下、该怎么做、为什么、证据是什么。
> 通用 schema,放 `schemas/`。规则是复盘的产物:从 worklog 的 `rule_candidates` 提炼而来。

## 规则从哪来、到哪去

```
worklog.rule_candidates(经历中的候选)
        │ 复盘活提炼
        ▼
      rule(正式规则)
        │ 被引用
        ▼
task.rule_refs / decision.related_rules(下次做事/决策时参考)
```

## 存储形态

一条规则 = 一个 `<id>.md` 文件。frontmatter 存字段,正文可展开说明与反例。

## 字段(通用基座)

### 必填

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `id` | string | `rule-YYYY-NNNN` |
| `statement` | string | 规则本身,一句话(如「卡住超过30分钟就先记下来问人」) |
| `status` | enum | `candidate`(候选) / `validated`(已验证) / `deprecated`(已弃用) |

### 可选(通用)

| 字段 | 类型 | 说明 |
|---|---|---|
| `trigger` | string | 什么场景触发这条规则 |
| `rationale` | markdown | 为什么认可它 |
| `failure_modes` | list[string] | 常见失败模式(什么时候它不适用) |
| `confidence` | enum | `low`/`medium`/`high` |
| `review_interval` | string | 复习间隔(供心跳做间隔重复推送) |
| `tags` | list[string] | 自由标签 |

### 自动填充

`domain` / `source_machine` / `created_at` / `updated_at`

## work 扩展块(仅工作域附加)

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | enum | 事业 / 学业 / 人际 / 生活 / 系统 |
| `evidence_refs` | list[worklog_id] | 证据链:这条规则是从哪些 worklog 提炼的 |

## 证据链的意义

`evidence_refs` 让每条规则可追溯到真实经历,而不是凭空口号。
复盘时若发现某规则的证据都过时了,可将其 `status` 改为 `deprecated`。
