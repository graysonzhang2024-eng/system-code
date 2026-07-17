# 架构说明

## 1. 为什么这样设计

用户在为自己搭建一套隐私优先、跨双机、低维护的「个人操作系统」,把消耗精力的事务(生活/工作/决策/情绪/任务)外包给可插拔的 AI 执行器。

设计的第一性原则:**按「数据可共享度」划线,而不是按「哪台机器」划线。**

原始设想是「公司机零真实数据 / 个人机跑一切」,但实际机器只有两台且分工交叉混合(工作机也承担部分工作、也会持有真实工作数据)。用机器划线会失效,于是改用数据敏感度划三层:

| 层 | 内容 | 存储 | 流向 | 可开源 |
|---|---|---|---|---|
| 框架层 | 代码/schema/模板/fixtures | `system-code` | 双机共享 | ✅ |
| 工作域 | 任务/worklog/规划/工作决策 | `work-vault` | 工作机 → 单向同步个人机 | ❌ |
| 个人域 | 情绪/健康/画像/内核卡片 | `personal-vault` | 仅个人机 | ❌ |

**物理分离、逻辑统一**:三仓各自独立 git remote(硬隐私边界 + 抗离职迁移),但共用同一套 schema 与工具。

## 2. 四层功能架构

- **数据层**:Markdown + frontmatter 文件。frontmatter 存结构化字段(机器读),正文存叙述(人读)。
- **Agent 层(可插拔执行器)**:执行器接收 `(playbook 模板 + 从 vault 取到的上下文)`,产出 `(结构化结果 + 可选写回草稿)`。执行器种类:`openclaw`(长期主力)/`cursor`(过渡)/`claude_code`(框架开发)。playbook 不绑定任何单一执行器。
- **心跳层**:always-on 的定时任务(出门提醒/复习推送/日志催收/精力 check-in)。规则优先、零成本,绝不做昂贵推理。
- **治理层**:行为准则 + 电量状态机 + token 预算。例:低电状态禁止做不可逆(one-way-door)决策。

## 3. 通用 vs 工作语义:物理分层

避免框架被工作场景绑死:

- `schemas/`(通用):`entity` 基座 / `decision` / `rule` —— 任何域都能用。
- `schemas/work/`(工作专属):`task` / `worklog` / `planning`,以及 `category`/`energy_cost`/`reversibility` 等生产力味的字段。

将来出现第二个域(如个人生活域)时,不会被工作分类污染。

## 4. 关键工程决策

- **A→B 翻转靠配置不靠改码**:代码默认读 `fixtures/`;`.env` 里填了 `WORK_VAULT_PATH` 就切到真实数据。满足「pull 后填 .env 即可运行」。
- **压住过早抽象(重要纪律)**:只有一个真实域时,不预建「通用域插件引擎」。先把工作域做具体做真实,公共骨架事后收割(rule of three / YAGNI)。
- **单写者原则**:每条记录带 `source_machine` 字段;跨机同步单向(work→personal),个人机对 imports 只读,避免双向编辑冲突。

## 5. 数据模型概览(详见各 schema 文件)

- 复用:`entity` 基座(id/created_at/updated_at/tags/domain/source_machine)、`decision`、`rule`。
- 工作域新增:`task`(状态机 todo→in_progress→done,旁挂 blocked/cancelled)、`worklog`(append-only,兼作规则抽取原料)、`planning`(objective/milestone/roadmap)。
- 扩展(加块不改基座):decision +reversibility/energy_context;rule +evidence_refs。

## 6. 开发路线

见 README「开发状态」与 `agent系统开发/开发文档.md`(只追加,含每步的决策与遗留)。
