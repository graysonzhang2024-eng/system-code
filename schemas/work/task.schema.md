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
| `status` | enum | `todo` / `in_progress` / `blocked` / `done` / `cancelled`，以及 Agent 闭环的 `pending_start` / `pending_decision` / `pending_review` | 规划·提醒·验收 |
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
| `today_date` | date | 加入“今日待办”的北京时间日期；空值或非当天即回到总待办视图 | 当日缓存·专注 |
| `depends_on` | list[task_id] | 前置依赖(这些没 done 就不能开工) | 规划 |
| `parent` | task_id | 父任务(子任务层级) | 规划 |
| `planning_ref` | list[planning_id] | 关联的规划项 | 复盘·追溯 |
| `decision_refs` | list[decision_id] | 关联的决策 | 追溯 |
| `rule_refs` | list[rule_id] | 应用了哪些已验证规则 | 复盘 |
| `context` | enum | `@computer` / `@errand` / `@call` 等 GTD 语境 | 规划 |
| `tags` | list[string] | 自由标签。子分类放这里,如 `感情`(归在 category=人际 下) | 筛选 |
| `executor` | enum | `user` / `dev_agent` / `internship_agent`。新增执行器必须先进入系统注册表并声明权限根 | 路由·权限·验收 |
| `taken_over_from` | executor | 用户中途接管 Agent 任务时，记录原执行器 | 追溯 |
| `completion_actor` | executor | 实际确认完成任务的角色；用户接管时为 `user` | 追溯·验收 |

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
- 计划外但已经完成的事项允许通过 `record_completed_task` 直接创建为 `done`；该动作必须同时
  建立关联 worklog 并回填 `outcome_ref`，用于补录而不是绕过 Agent 验收。
- `cancelled` 可从任意状态进入,是终态。

Agent 执行任务使用可审核闭环：

```text
todo → pending_start → in_progress
                         ├→ pending_decision → in_progress
                         └→ pending_review → done
```

专项 Agent 的授权不是只看 `executor`：还必须验证任务位于其注册的根任务子树内。
例如 `internship_agent` 只允许操作本机 `.env` 配置的专项任务根及其后代。

## 两根轴的区别(重要)

- `category`(语义轴,5 分类):决定规划/筛选/复盘时怎么归类。
- `domain`(隐私轴,work/personal):决定存哪个仓、哪台机器、隐私边界。
- 二者**相关但不等同**:同为 `学业`,科研写作可能 `domain=work`(工作机),上学内容可能 `domain=personal`(个人机)。

## 三层任务视图

用户任务在浮窗中有三个工作记忆层，但不增加新的任务状态：

```text
总待办（todo） → 今日待办（todo + today_date=今天） → 专注中（in_progress）
```

今日待办只是北京时间当天生效的缓存标记，次日自然失效，不会删除或取消任务。只有用户负责的
叶子任务可以进入今日待办或专注中；父任务、Agent 任务和依赖未完成的任务不能借此绕过原状态机。

## 样例

见 `fixtures/work/`。
