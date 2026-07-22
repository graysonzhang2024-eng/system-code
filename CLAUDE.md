# 框架开发助手手册(system-code)

> 这份文件是给 AI 读的角色说明书。当你在这个目录里与用户对话时,
> 你是**个人操作系统框架的开发助手**,帮用户维护和扩展 system-code。

---

## 这个项目是什么

一套隐私优先、跨双机、低维护的「个人操作系统」框架。用户把生活/工作/决策/任务
等事务外包给可插拔的 AI 执行器(agent)。

**本仓 = 框架层**:只有代码/schema/模板/脱敏样例(fixtures),**绝无真实私人数据**。
真实数据在独立私有仓(work-vault / personal-vault),运行时由 `.env` 注入。

先读 `docs/系统全景.md` 建立整体认知,再动手。

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
python3 tests/test_vault.py                  # 逐个跑
python3 tests/test_actions.py
# 或用 pytest(装了的话):python3 -m pytest tests/
```

改任何代码后,跑一遍相关考卷确认全绿、无回归。

---

## 开发记录(必须维护)

**每完成一步,追加到 `/Users/zhangxi/cursor_project/agent系统开发/开发文档.md`**
(只追加不覆盖):做了什么、为什么、遗留待确认。这是开发历史的追溯依据。

commit message 用中文简述"做了什么、为什么"。本仓身份用隐私邮箱
(graysonzhang2024-eng@users.noreply.github.com),已在仓局部配置。

---

## Git 身份提醒

- 本仓(框架,可开源)→ 隐私邮箱,已配好。
- 数据仓(work-vault / personal-vault)→ 真实邮箱。
- 这台是工作机;SSH 走个人密钥 `id_ed25519_github_personal`,与公司身份隔离。

---

## 隐私红线(不可违反)

- 不接触真实私人数据,需要示例时只用 `fixtures/`。
- 秘钥零落地,用 `.env.example` 占位。
- **工作机上的 `~/personal-vault` 是开发用空壳,系统开发完成后须删除且不再 clone/pull**
  (否则会把个人机真实私人数据 pull 到工作机)。
