# system-code

一套**隐私优先、跨双机、低维护**的「个人操作系统」框架。用来把生活 / 工作 / 决策 / 任务等消耗精力的事务,外包给可插拔的 AI 执行器(agent)。

> 本仓是**框架层**:只有代码、schema、模板和脱敏样例(fixtures),**绝无任何真实私人数据**。真实数据存放在各自独立的私有仓(`work-vault` / `personal-vault`),运行时由配置注入。这条边界让本仓可以安全开源。

---

## 核心理念:开发与使用分离

| | 内容 | 存放 | 是否可开源 |
|---|---|---|---|
| **开发** | 框架代码 / schema / 模板 / 工具 | 本仓 `system-code` | ✅ 可开源 |
| **使用** | 你的真实工作数据(任务/规划/决策) | 私有仓 `work-vault` | ❌ 私有 |
| **使用** | 你的生活隐私数据(情绪/健康/画像) | 私有仓 `personal-vault` | ❌ 私有 |

改框架不碰你的数据;换机器只需 `git pull` + 填 `.env`,无需改代码。

---

## 四层架构(用「开饭馆」比喻)

| 层 | 作用 | 比喻 | 目录 |
|---|---|---|---|
| 数据层 | 存放结构化资料 | 食材仓库 | `schemas/` `fixtures/` |
| Agent 层 | 干活的 AI 引擎 + 套路 | 厨师 + 菜谱 | `adapters/executor/` `playbooks/` |
| 心跳层 | 定时自动提醒/推送 | 闹钟 | `heartbeat/` |
| 治理层 | 给 AI 定的规矩 | 后厨守则 | `governance/` |

---

## 三层数据边界(按「数据可共享度」划线,而非按机器)

```
① 框架层 system-code   —— 零真实数据,跨机共享,可开源
② 工作域 work-vault    —— 真实工作数据,工作机为源 → 单向同步个人机
③ 个人域 personal-vault—— 生活隐私数据,仅个人机,永不进工作机
```

三仓各自独立 git remote(硬隐私边界),但共用同一套 schema 与工具(逻辑统一)。

---

## 技术栈

- **数据 = Markdown + frontmatter**:每条记录是一个 `.md` 文件,顶部 frontmatter 放机器要读的结构化字段,正文放人读的叙述。人机皆可读,可用 git 存历史,无需数据库。
- **逻辑 = Python**:读写 / 校验 / 同步的胶水代码;agent 生态最通用的语言。
- 可移植、16G Mac 可跑;本地模型预留 ollama 接口。

一条记录示例:
```markdown
---
id: task-2026-0001
status: todo
priority: P1
category: company
---
这里是任务的详细描述,人能直接读。
```

---

## 目录结构

```
system-code/
  README.md                # 本文件
  .gitignore               # 隐私保险丝:排除 .env / 真实 vault / 秘钥
  .env.example             # 环境变量模板(复制为 .env 填真实值)
  docs/                    # 架构与协作文档
  schemas/                 # 数据结构定义
    work/                  #   工作域专属 schema(task/worklog/planning...)
  adapters/                # 适配层(可插拔)
    notion/                #   Notion 日志适配(mock 版,可选)
    executor/              #   可插拔执行器抽象(openclaw/cursor/claude_code)
  playbooks/               # 给执行器用的流程模板(占位符,不含真实内容)
  heartbeat/               # 心跳层脚本(规则优先,零成本)
    scripts/
  fixtures/                # 脱敏样例数据(唯一允许的「内容」)
    work/
  governance/              # 行为准则 / 电量状态机 / token 预算
  system_os/               # Python 代码(vault store / 校验 / 同步)
  tests/                   # 单测(仅针对 fixtures/mock,零网络零真实数据)
```

---

## 如何在新机器上接管运行

```bash
git clone <system-code 私有 remote> system-code
cd system-code
cp .env.example .env          # 填入真实 vault 路径 / key / token
python3 -m pytest             # 跑单测,确认框架正常(仅用 fixtures)
```

真实数据仓单独 clone,通过 `.env` 的 `WORK_VAULT_PATH` / `PERSONAL_VAULT_PATH` 注入。

---

## 开发约定

- **`agent系统开发/开发文档.md` 只追加不覆盖**,记录每一步「做了什么、为什么、遗留待确认」。
- 每个模块交付三件套:schema/接口 + 实现 + fixtures 样例 + 最小单测。
- 秘钥零落地:任何 key/token 只进本地 `.env`,用 `.env.example` 占位。
- feature 分支开发,commit message 中文简述。

---

## 开发状态

- [x] 步骤 0:仓骨架 + 隐私边界 + 技术栈选定
- [ ] 步骤 1:entity 基座 + vault store(markdown+frontmatter CRUD)
- [ ] 步骤 2:task / worklog schema
- [ ] 步骤 3:planning / decision / rule schema
- [ ] 步骤 4+:真实数据翻转 / 同步器 / playbook / executor / governance

详见 `docs/architecture.md`。
