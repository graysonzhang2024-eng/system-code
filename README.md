# system-code

一套**隐私优先、跨双机、低维护**的个人 Agent 操作系统框架。用户只需要用自然语言表达需求，Codex、Claude Code 等外部 Agent 负责理解意图并调用本仓工具；任务、日志和规则仍以可读的 Markdown 文件掌握在用户自己手里。

> 本仓是**框架层**：只存代码、schema、模板和脱敏 fixtures，不存真实私人数据。真实数据分别存放在私有的 `work-vault` / `personal-vault`，运行时通过 `.env` 注入。这是不可破坏的隐私边界。

---

## 当前已经能做什么

系统已经越过“只有数据模型”的原型阶段，可用于真实日常管理：

- 通过 `system_os/actions.py` 新建、查询、推进、阻塞和完成任务；完成任务时自动沉淀 worklog。
- 计划外事项即使先做后记，也会补建已完成任务并关联 worklog，避免从任务统计中消失。
- 用知识库管理论文、播客、书籍、课程等学习内容：维护想学/学习中/已学队列与优先级，并在每项下持续追加摘要、思考、疑问和联想。
- 用父子关系组织无限层级任务树，支持依赖、优先级、三层任务视图、敏感遮罩继承和常驻任务。
- 通过 Electron 浮窗在“总待办 → 今日待办 → 专注中”之间推进用户任务；独立知识库窗口展示成长统计、学习队列和条目笔记。
- 用通用 `pending_start → in_progress → pending_decision / pending_review → done` 闭环管理多个专项 Agent；当前已接入系统开发与实习攻略两个执行器。
- 用户可在浮窗随时二次确认并中途接管 Agent 任务；接管会生成完成记录并保留原执行器来源。
- 用“执行器注册表 + 授权任务根”限制专项 Agent 的工作范围，并把业务产物写到仓外配置的独立工作区。
- 自动生成分机每日任务日志，并在关机或跨日后补齐遗漏日志。
- 两台机器并行读写 `work-vault`：写入后自动提交和后台推送，浮窗每 2 分钟同步，冲突时保留双份并提示人工合并。
- 自动检查 `system-code` 更新：只做安全的快进更新；Python 改动下次调用生效，界面改动自动重载或重启。

尚未完成的边界也同样重要：

- 没有内建 LLM 或自主执行器；当前智能来自 Codex / Claude Code 等外部 Agent，仓内提供的是工具、数据和协作协议。
- 心跳层只完成了同步、冲突检查和跨日补日志等基础定时任务；按 `due` / `scheduled` 到点主动提醒尚未上线。
- `planning` / `decision` 已有 schema 与校验，但还没有像 task 一样完整的高层操作和界面闭环。
- 治理层只有规则库、开发协议和“低电不做不可逆决定”等钩子；电量状态机、token 预算、规则毕业与 Agent 自我复盘尚未完整实现。
- `personal-vault` 的真实生活域尚未正式启用；在此之前，显示层隐身不能替代物理数据隔离。

详见 [docs/系统全景.md](docs/系统全景.md) 与 [docs/开发交接.md](docs/开发交接.md)。

---

## 对话角色与协作边界

- **主管家**是生活经营总入口：理解状态与目标，管理优先级，捕获任务和完成事项，恢复日志，
  协调专项 Agent，并承担最终验收责任。
- **系统开发 Agent**维护代码、测试、公开文档和系统架构，使用开发队列的提议—批准—验收闭环。
- **实习攻略 Agent**处理配置授权根内的求职任务，业务产物保存在仓外私有工作区。
- 论文、视频、网页调研和长文档等高上下文执行优先交给独立研究 Agent；主管家负责目标、隐私、
  进度和结果整合，而不是亲自吞下所有执行。

日志是系统的核心记忆能力。Agent 可结合对话、任务和完成记录恢复日报，默认组织为“今日完成、
今日流水账、今日总结”；真实日志始终留在私有位置，公开仓只保存匿名协议。

---

## 架构

### 四层功能架构

| 层 | 职责 | 当前状态 |
|---|---|---|
| 数据层 | Markdown + frontmatter、schema、Vault CRUD | ✅ 已上线 |
| Agent 层 | 外部 Agent 调用 actions、通用专项协作与验收流程 | 🟡 多 Agent 工具链已上线，智能能力待扩展 |
| 心跳层 | 同步、跨日补日志、未来的提醒与推送 | 🟡 基础定时已上线，到点提醒待开发 |
| 治理层 | 隐私边界、状态机、规则与决策保护 | 🟡 核心约束已上线，治理体系待完整化 |

### 三仓数据边界

| 仓 | 内容 | 分布与同步 | 是否可开源 |
|---|---|---|---|
| `system-code` | 框架代码、schema、文档、脱敏 fixtures | 两机共享，可自动快进更新 | ✅ |
| `work-vault` | 真实任务、日志、规则等工作域数据 | 两机私有仓双向同步 | ❌ |
| `personal-vault` | 情绪、健康、画像等生活隐私 | 仅个人机；不得进入工作机 | ❌ |

`work-vault` 的“工作机只显示本机创建记录”属于**显示层可见性规则**，不是物理隔离；文件仍会随私有仓同步到两台机器。真正的个人隐私必须进入只存在于个人机的 `personal-vault`。

### 主调用链

```text
用户自然语言
    ↓
Codex / Claude Code 等外部 Agent
    ↓
system_os/actions.py（业务动作）
    ↓
system_os/vault.py（Markdown CRUD）
    ↓
work-vault（当前）/ personal-vault（正式启用后）
```

桌面浮窗复用同一套业务逻辑：

```text
Electron UI → system_os/os_api.py → actions.py → vault.py
```

---

## 技术栈与目录

- 数据：Markdown + YAML frontmatter，人机皆可读，可由 git 保存完整历史。
- 逻辑：Python；运行时第三方依赖目前只有 PyYAML。
- 界面：Electron 桌面浮窗。
- 同步：git 私有仓；不引入数据库或常驻中心服务。

```text
system-code/
├── system_os/
│   ├── actions.py       # 面向 Agent 的高层业务动作
│   ├── executors.py     # 执行器注册表、显示名与授权任务根
│   ├── agent_workspace.py # 专项 Agent 外挂工作区的安全路径与文本写入
│   ├── schema_knowledge.py # 学习条目与具体笔记校验
│   ├── vault.py         # Markdown CRUD 与类型目录路由
│   ├── sync.py          # 数据同步、冲突保双份、代码自动更新
│   ├── os_api.py        # Electron 与 Python 的 JSON 桥
│   ├── config.py        # .env 与 vault 路径
│   ├── machine.py       # work / personal 机器身份与 id 后缀
│   └── schema_*.py      # 数据校验、任务状态机、治理钩子
├── ui/                  # Electron 浮窗与验收窗口
├── schemas/             # task/worklog/planning/decision/rule 说明
├── fixtures/            # 唯一允许进入代码仓的脱敏样例数据
├── tests/               # 临时 vault / mock / 本地 git 测试
├── docs/                # 全景、管家手册、交接与匿名公开 changelog
├── playbooks/           # 专项 Agent 启动清单；尚未建设通用 playbook 引擎
└── governance/          # 预留；治理体系尚未完整化
```

---

## 快速验证

```bash
git clone <system-code-remote> system-code
cd system-code
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests
```

测试只使用 fixtures、临时目录和本地临时 git 仓，不应接触真实 vault。

启动浮窗：

```bash
cd ui
npm install
npm start
```

接入真实数据前，复制配置模板并填写当前机器身份与真实仓的绝对路径：

```bash
cp .env.example .env
```

`.env` 必须保持本地私有，禁止提交。个人机使用 `MACHINE_ID=personal`，工作机使用 `MACHINE_ID=work`；机器身份决定新记录的 `source_machine`、默认 domain 与 id 后缀。

实习攻略 Agent 还需要在个人机 `.env` 配置 `INTERNSHIP_WORKSPACE_PATH`。该目录保存简历、岗位材料等业务产物，不属于 `system-code`，也不会被复制进 fixtures。Codex 桌面版中以 `system-code` 为主目录、实习攻略目录为附加目录；详细启动步骤见 [playbooks/internship-agent-start.md](playbooks/internship-agent-start.md)。

---

## 开发纪律

- 先读 `AGENTS.md`（Codex）和 `docs/管家手册.md`；`CLAUDE.md` 保留为 Claude Code 兼容入口。
- 每轮先查看开发队列，按“提议 → 批准 → 实现 → 提交验收 → 用户验收”推进。
- 新功能必须有相称的测试；测试使用临时 vault，不能修改真实数据。
- `docs/CHANGELOG.md` 只记录匿名公开里程碑；原始开发史留在私有资料区。
- 代码仓由开发者审查后提交；真实数据仓的正常写操作由工具自动同步。
- 依赖、抽象和后台服务遵循 YAGNI：有真实需求再增加，不为设想中的多域、多执行器提前搭空框架。
- 删除、批量迁移、冲突合并等高风险操作必须先确认目标并保留可恢复路径。

---

## 近期路线

1. 使用本地私有或脱敏样例验证专项 Agent 的授权根、验收闭环与外挂工作区接入。
2. 上线按时间提醒待办，补齐第一个真正面向用户的心跳能力。
3. 根据真实使用反馈完善 planning / decision 操作、规则治理和 Agent 自我复盘。

路线不预设大型插件系统、数据库或后台自治框架；先解决已经出现的实际问题，再抽取稳定共性。
