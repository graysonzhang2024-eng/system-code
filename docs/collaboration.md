# 双机协作与同步流程

## 机器角色

| 机器 | 持有的仓 | 说明 |
|---|---|---|
| 工作电脑 | `system-code` + `work-vault` | 承担公司工作 + 部分其他工作;产生真实工作数据。**无 personal-vault 凭据** |
| 个人电脑 | `system-code` + `work-vault` + `personal-vault` | 承担学业/副业/部分主业 + 生活隐私;是唯一聚合枢纽 |

## 三条同步通道

```
system-code   ←→  双向:两台机器一起开发框架
work-vault     →  单向:工作机 push,个人机 pull 到 imports/work/
personal-vault    仅个人机本地,永不上传到任何工作机可达的 remote
```

### 为什么工作数据能同步、生活隐私却不泄漏

1. **三仓各自独立 remote**:工作机的 git 配置里根本没有 `personal-vault` 的 remote,物理上取不到生活数据。
2. **单向 work→personal**:个人机只 pull 工作数据,不把个人任务 push 回工作机。
3. **单写者原则**:`work-vault` 条目 `source_machine=work`,个人机对 `imports/work/` 只读;要基于工作数据做个人决策,则在 personal 侧新建聚合层条目。

## 日常流程

**开发框架(A 类)**
```
在任一台机器改 system-code → git commit → git push
另一台 git pull 同步
```

**记录工作(B 类,在工作机)**
```
新增/更新 work-vault 里的 task/worklog/... → git commit → git push
```

**个人机聚合规划**
```
git pull work-vault → 读 imports/work/ → 在 personal 侧做统一规划/决策
```

## 提交前自检

- `git status` 确认没有 `.env` / 真实 vault / token 被加入暂存区。
- `.gitignore` 已覆盖 `.env`、`vault-real/`、`work-vault/`、`personal-vault/`、`*.private.*`。
- 发现疑似真实隐私内容 → 立即停止并标注,不提交。

## 待个人机侧确认的清单(占位,后续补)

- [ ] 三个仓的私有 remote 地址(GitHub private / 自建 git)
- [ ] 真实 `work-vault` / `personal-vault` 的本地绝对路径
- [ ] 是否引入 Notion(当前 git 已足够,Notion 为可选)
