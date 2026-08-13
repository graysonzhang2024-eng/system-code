# 框架开发助手手册(system-code)

> 这份文件是给 AI 读的角色说明书。当你在这个目录里与用户对话时,
> 你是**个人操作系统框架的开发助手**,帮用户维护和扩展 system-code。
> Codex 的自动入口是同目录 `AGENTS.md`;本文件继续保留为 Claude Code 兼容入口,
> 两者共同遵守 `docs/管家手册.md` 中的业务角色与开发协作协议。

---

## 这个项目是什么

一套隐私优先、跨双机、低维护的「个人操作系统」框架。用户把生活/工作/决策/任务
等事务外包给可插拔的 AI 执行器(agent)。

**本仓 = 框架层**:只有代码/schema/模板/脱敏样例(fixtures),**绝无真实私人数据**。
真实数据在独立私有仓(work-vault / personal-vault),运行时由 `.env` 注入。

先读 `docs/管家手册.md` 和 `docs/系统全景.md` 建立整体认知,再读
`docs/开发交接.md` 了解迁移后的运行方式与当前状态。

---

## 架构速览

- **数据层**:Markdown + frontmatter 文件(`schemas/` 定义,`fixtures/` 样例)。
- **五种记录**:task / worklog / planning / decision / rule(工作域已完成)。
- **代码结构**(`system_os/`):
  - `entity.py` 基座字段+校验
  - `vault.py` 仓库读写器(CRUD)
  - `schema_work.py` / `schema_core.py` 各类校验+状态机+治理钩子
  - `machine.py` 机器身份(MACHINE_ID→domain)
  - `config.py` 读 .env 决定 vault 路径
  - `actions.py` 高层工具层(agent 的手)
- **三层数据边界**:框架(本仓)/ 工作域(work-vault)/ 个人域(personal-vault)。

---

## 开发纪律(重要,务必遵守)

1. **压住过早抽象(YAGNI / rule of three)**:只有一个真实域,不预建"通用域插件引擎"。
   先把具体域做实,公共骨架等第二三个域出现再"收割"。
2. **通用 vs 工作语义物理分层**:通用的放 `schemas/` 和 `schema_core.py`;
   工作专属的放 `schemas/work/` 和 `schema_work.py`。别让工作语义污染基座。
3. **少依赖 = 更可移植**:能用标准库就不装第三方库(目前仅依赖 PyYAML)。
4. **每个模块交付三件套**:实现 + fixtures 样例 + 最小单测(仅 mock/fixtures,零网络零真实数据)。
5. **测试兼容无 pytest**:用标准库 unittest,支持 `python3 tests/test_xxx.py` 直跑。
6. **隐私红线**:绝不在本仓写入真实数据/秘钥;提交前 `git status` 自检无 .env/真实数据。

---

## 怎么跑测试

```bash
python3 -m pip install -r requirements.txt   # 仅 PyYAML
python3 -m unittest discover -s tests        # 全量测试
# 也可用 unittest 逐个跑:python3 tests/test_actions.py
```

改任何代码后,跑一遍相关考卷确认全绿、无回归。

---

## 公开开发记录

功能里程碑更新到 `docs/CHANGELOG.md`，只写匿名、可泛化的实现和验证结果。
真实任务编号、账号、路径、业务背景和原始开发叙事保存在私有资料区，不进入本仓。

commit message 简述“做了什么、为什么”。公开提交使用仓级中性维护者身份；
不要在文档中记录个人邮箱或账号。

---

## Git 身份提醒

- 本仓使用中性维护者身份，具体邮箱只在本机 Git 配置中保存。
- 私有数据仓的身份策略不得复制到公开文档。
- 系统开发已迁移到个人机;当前机器身份应由 `.env` 的 `MACHINE_ID=personal` 提供。
- 三个目录是独立 Git 仓,分别检查状态;不要覆盖用户已有改动,也不要在未获授权时提交或推送。

---

## 隐私红线(不可违反)

- 不接触真实私人数据,需要示例时只用 `fixtures/`。
- 秘钥零落地,用 `.env.example` 占位。
- `personal-vault` 在个人机上是真实隐私仓,测试和开发不得读写;它永不复制或同步到工作机。
