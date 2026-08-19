# ADR 0003：分支、PR 与 Ruleset 治理

日期：2026-08-19

状态：Accepted

## 背景

RadishLink 处于定义、法规预检和三节点 POC 准备阶段。仓库已经有产品、架构、安全、硬件、法规和测试文档，但尚无提交历史、远程仓库、分支治理、PR 模板、自动检查或远程保护策略。

Radish、RadishMind、RadishLex、RadishCatalyst、RadishFlow 和 RadishAxiom 已经反复采用“日常集成分支、稳定主线、PR 门禁、主线合并后回流”的拓扑。本项目采用这一通用原则，但把无线电法规、设备身份、端到端加密、升级、公共协议、三节点证据和用户数据作为自己的审查重点，不复用兄弟项目的应用检查、语言栈和发布流程。

## 决策

### 分支职责

- `master`：GitHub 默认分支和稳定主线，只通过 Pull Request 接收变更。
- `dev`：常态开发与集成分支，承接普通功能、文档、规范、治理和实验收口。
- `feature/*`：边界明确的产品或实现能力。
- `fix/*`：非紧急缺陷修复。
- `docs/*`：不改变运行行为的文档工作。
- `research/*`：外部证据、法规预检和候选比较；研究结论不自动成为 Accepted ADR。
- `experiment/*`：软件模拟、台架、硬件或无线实验；结果不自动外推为外场、量产或法规结论。
- `chore/*`：脚本、CI、依赖和仓库治理。
- `hotfix/*`：仅用于必须直接修复稳定主线的问题。

### 开发与合并拓扑

普通变更以 `topic -> dev -> master -> dev` 形成闭环：

1. 主题分支默认向 `dev` 发起 PR；单人连续开发可直接进入 `dev`，但仍须执行风险匹配的本地验证。
2. 阶段性产品、协议、工具或治理基线稳定后，从 `dev` 向 `master` 发起 PR。
3. `dev -> master` 优先使用 merge commit，保留阶段边界和原始提交身份，并使暂停前进的 `dev` 可以 fast-forward 到合并后的 `master`。
4. 仓库允许 rebase merge；使用后 GitHub 会生成新的提交 SHA，必须通过普通 merge 把 `master` 回流到 `dev`。
5. 禁用 squash merge。项目保留可审计提交粒度，贡献者在合并前整理提交，不把修复噪声留给主线。
6. 任何进入 `master` 的阶段 PR 或 hotfix 合并后，都必须在下一轮 `dev` 开发前完成 `master -> dev` 回流。
7. 共享 `dev` 不通过 rebase、reset 或 force push 伪造同步状态。

回流前先暂停向 `dev` 增加新提交。可 fast-forward 时使用：

```bash
git fetch origin
git switch dev
git pull --ff-only origin dev
git merge --ff-only origin/master
git push origin dev
```

如果 `--ff-only` 失败，先检查分支图；确认属于 rebase merge、hotfix 或并发提交后，用普通 merge 合入 `origin/master`，解决冲突并执行风险匹配的验证。禁止用 reset、rebase 或 force push 丢弃共享历史。

回流后验证：

```bash
git merge-base --is-ancestor origin/master dev
git rev-list --left-right --count origin/master...dev
```

第一条必须成功，第二条左侧计数必须为 `0`。右侧可以大于 `0`，但正常回流窗口中应先完成闭环再开始下一批提交。

### Pull Request 规则

- `master` 禁止直接 push、force push 和删除。
- 所有 `master` 变更必须通过 PR，并解决全部 review conversation。
- `master` PR 必须通过 strict、最新的 `Candidate Quality` 聚合检查。
- 单人维护阶段不要求额外批准；存在稳定且真正参与审查的第二位维护者后，再提升审批数。
- 射频、安全、身份、密钥、升级、公共协议、硬件和用户数据变化必须填写项目专属影响面。
- 所有数字与能力声明必须标明证据类型和条件，不把目标、候选、厂商声明、第三方结果或台架结果写成已验证产品能力。
- 管理员如需绕过，只能在 Pull Request 内进行；不开放直接 push 绕过。

### CI 与 required context

Ruleset 只绑定稳定 context `Candidate Quality`。当前它聚合无第三方运行依赖的 `Repo Hygiene`。实现栈冻结后，协议、密码、路由、Linux、辅助 MCU、手机和供应链检查作为可定位的组件加入聚合 job，远程 required context 保持不变。

Conventional Commits 由仓库检查器针对 PR commit range 验证，不在 Ruleset 中添加提交信息正则。这样既能检查贡献者提交，又不会把 GitHub 或 Git 生成的正常 merge commit 当作违规元数据。

workflow 使用 `pull_request` 与只读 token，外部 Action 固定完整 SHA，不使用特权触发器执行不可信 PR 代码。

### 可移植 Ruleset 与远程实例

仓库 JSON 只包含可跨仓库复用的规则，`bypass_actors` 为空。RepositoryRole、Team、User 和 GitHub App 的 actor ID 属于远程实例，不写入通用模板。

远程创建时，如确需管理员紧急通道，按实际仓库添加“仅 Pull Request”绕过，并在创建前后导出状态复核。仓库模板不会自动修改 GitHub；远程创建、更新、删除、Merge options 和安全设置均需单独授权。

### `dev` 的阶段性保护

当前单人阶段不保护 `dev`，普通 push 不触发 CI；目标为 `dev` 的 PR 会运行完整 `PR Checks`，用于外部贡献和并行工作反馈。

满足任一条件时重新评估 `dev` Ruleset：

- 有两名或以上稳定维护者；
- 持续接受外部贡献；
- 多个自动化协作者并行写入共享分支；
- 曾因绕过检查造成协议、安全、治理或构建基线回归。

### 暂不启用

- 不创建 CODEOWNERS；当前没有真实多人所有权结构。
- 不要求签名提交；签名、密钥恢复和机器人身份方案尚未建立。
- 不创建 tag Ruleset、release workflow 或自动部署；版本、许可证、兼容性、签名和发布载体尚未冻结。
- 不把 `main` 加入模板作为备用匹配；默认分支若迁移，必须通过新的治理变更同步更新全部资产。
- 不创建 fork 网络级 push ruleset；仓库可见性和对 fork 的影响尚未确认，路径和文件大小先由仓库检查治理。

## 未采用的方案

### 所有日常变更直接进入 `master`

会混合实验与稳定基线，也无法建立阶段晋级和远程保护边界，因此拒绝。

### 强制 squash merge

会丢失原始提交身份，并让长期 `dev` 在每次阶段晋级后与 `master` 形成重写历史，不利于回流闭环，因此禁用。

### 强制线性历史

与优先使用 merge commit 的阶段边界冲突，也会增加共享 `dev` 的重写诱因，因此不启用。

### 单人阶段要求一名审批者

会形成无法满足或依赖管理员绕过的装饰性门禁，不产生真实独立审查，因此当前审批数为 `0`。

### 在 Ruleset 写入 Conventional Commits 正则

可能作用于 GitHub 生成的合并提交，并把可读提交规范与远程合并机制耦合。改由 PR 范围检查器执行。

### 在模板写死管理员 RepositoryRole ID

远程 actor ID 属于具体仓库和账号上下文，复制会降低可移植性并可能产生错误绕过，因此模板保持为空。

## 后果

收益：

- 稳定主线、日常集成、研究和实验边界清楚；
- `master` 每次合并都会成为下一轮 `dev` 的祖先；
- required context 在检查组件增长时保持稳定；
- 无线电、安全、协议与证据变化在 PR 中显式审查；
- 单人阶段不会被虚假自我审批阻塞；
- 远程角色与仓库通用模板分离，减少不可移植配置。

代价：

- 阶段性合并后多一次强制回流和拓扑确认；
- 禁用 squash 后，贡献者需要维护可审阅的提交历史；
- Ruleset、workflow、检查器、模板和文档必须同步维护；
- `dev` 未保护期间，直接提交者承担本地验证责任；
- 远程启用时必须补充实例化配置并验证实际状态。

## 变更要求

调整分支职责、合并方式、required context、审批数、bypass、CODEOWNERS、签名、发布或 `dev` 保护时，必须同步更新本 ADR、仓库治理文档、Ruleset 模板与说明、PR 模板、workflow、检查器和协作文件。
