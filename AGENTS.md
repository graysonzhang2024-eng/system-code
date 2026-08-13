# system-code · Codex 开发说明

你是这套个人操作系统框架的开发 Agent，负责维护 Python 工具层、Electron 浮窗、schema、
测试和框架文档。本仓只允许代码、模板、脱敏 fixtures 和文档，绝不放真实私人数据。

`CLAUDE.md` 是 Claude Code 的兼容入口；两份说明应保持原则一致。Codex 以本文件为自动
入口，业务角色与协作协议的权威来源仍是 `docs/管家手册.md`。

## 开始工作前

按任务所需读取以下文档，不凭旧会话记忆猜测当前实现：

1. `docs/管家手册.md`：系统管家角色、隐私边界、开发队列协议。
2. `docs/系统全景.md`：当前整体架构和数据流。
3. `docs/开发交接.md`：个人电脑接管方式、代码地图、已知问题。
4. `docs/architecture.md`：需要理解设计取舍时再读。
5. `docs/CHANGELOG.md`：只记录适合公开的匿名功能里程碑；原始开发史留在私有资料区。
6. `docs/agents/`：专项 Agent 的权威角色与任务范围；不要把专项业务提示词散落到真实资料目录。

如果是在推进系统开发任务，每轮先通过 `actions.list_dev_queue()` 扫描开发队列，并按
`docs/管家手册.md` 的「开发 agent 协作协议」推进所有已进入“开发中”的任务。不要用
普通代码编辑替代 `propose_task / request_decision / submit_for_review / accept_task` 等流程
状态变更。Electron/os_api 使用的短命令名与 Python 函数名不同，直接调用 Python 时以
`actions.py` 中的真实函数名为准。

## 代码地图

- `system_os/actions.py`：面向 Agent 的高层业务动作。
- `system_os/vault.py`：Markdown + frontmatter 的 CRUD。
- `system_os/config.py`：读取仓根 `.env` 和 vault 路径。
- `system_os/machine.py`：机器身份、默认 domain 和 ID 后缀。
- `system_os/sync.py`：数据仓同步、冲突保双份、框架代码更新。
- `system_os/os_api.py`：Electron 到 Python 的 JSON 命令桥。
- `system_os/schema_knowledge.py`：知识条目、学习状态与条目笔记校验。
- `system_os/schema_*.py`、`schemas/`：校验、状态机和数据结构。
- `ui/`：Electron 浮窗。
- `tests/`、`fixtures/`：只使用假数据的测试与样例。

## 开发纪律

1. 保持 YAGNI：先解决真实问题，出现多个真实域后再抽象公共插件机制。
2. 通用语义与工作域语义物理分层；通用逻辑放 core，工作专属逻辑放 work。
3. 优先标准库，运行时依赖保持最少；新增依赖必须有明确收益。
4. 功能交付至少包含实现、脱敏样例（适用时）和最小单测。
5. 测试使用 `unittest`，不得读取或写入真实 `work-vault` / `personal-vault`。
6. 真实配置只进被忽略的 `.env`；密钥、真实记录和绝对个人路径不得进入可提交文件。
7. 当前开发机身份是 `personal`，但实现必须从配置获取身份，不能依赖主机名或硬编码。
8. 修改前后检查 `git status`，保护用户已有改动；未经当前任务授权不提交或推送。
9. UI 现场验证不得占用用户主工作区：先跑自动化与静态检查；必须打开应用时提前说明，窗口放在
   屏幕边缘且不长期置顶，取证完成后立即关闭或最小化。不要为了录屏/截图持续遮挡用户的视频、
   浏览器或其他前台工作。

## 验证

从本仓根目录运行：

```bash
python3 -m unittest discover -s tests
```

修改 Electron 代码时，至少对涉及的 JavaScript 文件运行语法检查；涉及交互时再做短暂 UI
验证，并遵守上面的非干扰约束。测试失败必须说明是本次回归、环境问题还是已有故障，不能只报
“未验证”。

## 开发任务收尾

- 在任务正文写清具体改动和验证结果，再调用 `submit_review` 交给用户验收。
- 更新 `docs/CHANGELOG.md` 时只写匿名、可泛化的功能变化，不复制真实任务或私有开发史。
- 同时根据优先级、依赖和上下文选择下一项开发待办提出，不机械按编号取任务。
- 代码仓和两个数据仓是独立 Git 仓；分别检查状态，提交身份和同步行为不要混用。
