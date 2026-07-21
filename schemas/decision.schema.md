# decision.schema —— 决策记录(通用)

> 记录「一次选择:面临什么、有哪些选项、选了哪个、为什么」。
> 通用 schema(任何域都能用),放 `schemas/` 而非 `schemas/work/`。
> 工作域附加的字段放「work 扩展块」,不污染通用基座。

## 为什么要记决策

- 事后复盘:当时怎么想的?结果如何?→ 提炼成 rule。
- 治理层:重大且不可逆的决策,低电状态下禁止拍板(见 `reversibility`)。

## 存储形态

一条决策 = 一个 `<id>.md` 文件。frontmatter 存字段,正文写详细权衡过程。

## 字段(通用基座)

### 必填

| 字段 | 类型 | 取值 / 说明 |
|---|---|---|
| `id` | string | `dec-YYYY-NNNN` |
| `title` | string | 这个决策是关于什么的 |
| `date` | date | 做决策的日期 |
| `status` | enum | `open`(未决) / `decided`(已决) / `reviewed`(已复盘) / `reversed`(已推翻) |

### 可选(通用)

| 字段 | 类型 | 说明 |
|---|---|---|
| `context` | markdown | 当时的处境、约束 |
| `options` | list[string] | 备选项 |
| `chosen` | string | 选了哪个 |
| `rationale` | markdown | 为什么这么选 |
| `expected_outcome` | markdown | 预期结果 |
| `review_date` | date | 什么时候回头复盘 |
| `confidence` | enum | `low`/`medium`/`high` 当时的把握 |
| `related_rules` | list[rule_id] | 参考了哪些已验证规则 |
| `tags` | list[string] | 自由标签 |

### 自动填充

`domain` / `source_machine` / `created_at` / `updated_at`

## work 扩展块(仅工作域附加)

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | enum | 事业 / 学业 / 人际 / 生活 / 系统 |
| `reversibility` | enum | `one_way_door`(不可逆:推开就回不来) / `two_way_door`(可逆:随时能退回) |
| `energy_context` | enum | 决策时的精力状态 `low`/`medium`/`high`/`drain` |
| `planning_ref` | list[planning_id] | 关联规划 |
| `task_refs` | list[task_id] | 派生任务 |

## 治理钩子

`reversibility` + `energy_context` 服务治理层:
**低电(energy_context=low/drain)时,禁止做 `one_way_door` 决策**——这条规则将来由心跳/治理层校验。
概念来自 Amazon 的「单向门 / 双向门」决策框架:可逆决策可以快、不可逆决策必须慢且清醒。
