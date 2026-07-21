# task.schema —— 任务

> 工作/生活任务的统一结构。task 是整个系统的**枢纽**:捕获会*生产*它,规划会*读写*它,提醒会*读*它,复盘会*读*完成的它。
> 每个字段都对应某个「活」的挂载点——没有哪个字段是凭空存在的。

## 存储形态

一条任务 = 一个 `<id>.md` 文件。frontmatter 存下列字段,正文写任务的详细描述(给人读)。

## 字段

### 必填

| 字段 | 类型 | 取值 / 说明 | 服务哪个活 |
|---|---|---|---|
| `id` | string | `task-YYYY-NNNN`(如 task-2026-0001)或任意唯一串 | 全部 |
| `title` | string | 一句话标题 | 全部 |
| `status` | enum | `todo` / `in_progress` / `blocked` / `done` / `cancelled` | 规划·提醒 |
| `priority` | enum | `P0` / `P1` / `P2` / `P3`(P0 最急) | 规划排序 |
| `category` | enum | **事业 / 学业 / 人际 / 生活 / 系统** | 规划·筛选·复盘 |
| `energy_cost` | enum | `low` / `medium` / `high` / `drain`(消耗精力等级) | 规划(低电只排轻任务) |

### 自动填充(无需手填)

| 字段 | 类型 | 说明 |
|---|---|---|
| `domain` | enum | `work` / `personal`。由机器身份(MACHINE_ID)自动决定,不手标。 |
| `source_machine` | enum | `work` / `personal`。同上,记录产生在哪台机。 |
| `created_at` / `updated_at` | string | ISO 时间戳,vault store 自动盖章 |

### 可选

| 字段 | 类型 | 说明 | 服务哪个活 |
|---|---|---|---|
| `due` | date | 截止日 `YYYY-MM-DD` | 提醒 |
| `scheduled` | date | 计划执行日 | 提醒·规划 |
| `depends_on` | list[task_id] | 前置依赖(这些没 done 就不能开工) | 规划 |
| `parent` | task_id | 父任务(子任务层级) | 规划 |
| `planning_ref` | list[planning_id] | 关联的规划项 | 复盘·追溯 |
| `decision_refs` | list[decision_id] | 关联的决策 | 追溯 |
| `rule_refs` | list[rule_id] | 应用了哪些已验证规则 | 复盘 |
| `context` | enum | `@computer` / `@errand` / `@call` 等 GTD 语境 | 规划 |
| `tags` | list[string] | 自由标签。子分类放这里,如 `感情`(归在 category=人际 下) | 筛选 |

### 条件字段

| 字段 | 类型 | 触发条件 |
|---|---|---|
| `blocked_reason` | string | `status=blocked` 时**必填**(卡住必须写清为什么) |
| `outcome_ref` | worklog_id | `status=done` 时**建议**回填(指向记录产出的 worklog) |

## 状态机

```
        ┌─────────────────────────────┐
        ▼                             │
  todo ──▶ in_progress ──▶ done       │
             ▲    │                   │
             │    ▼                   │
           blocked ────────────────────┘
   (任意状态) ──▶ cancelled
```

**合法流转规则**(由 `schema_work.py` 校验强制):
- 进入 `blocked` 必须带 `blocked_reason`。
- `depends_on` 未全部 `done` 时,不允许进入 `in_progress`(依赖未清不开工)。
- 进入 `done` 建议(不强制)回填 `outcome_ref`。
- `cancelled` 可从任意状态进入,是终态。

## 两根轴的区别(重要)

- `category`(语义轴,5 分类):决定规划/筛选/复盘时怎么归类。
- `domain`(隐私轴,work/personal):决定存哪个仓、哪台机器、隐私边界。
- 二者**相关但不等同**:同为 `学业`,科研写作可能 `domain=work`(工作机),上学内容可能 `domain=personal`(个人机)。

## 样例

见 `fixtures/work/`。
