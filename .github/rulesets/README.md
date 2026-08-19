# GitHub Rulesets

本目录保存 RadishLink 的可审阅 Ruleset 模板。模板进入 Git 仓库不等于远程规则已经启用；创建、更新或删除远程 Ruleset 都是独立管理动作，必须先确认目标仓库、当前规则、required context 和实际差异。

## `master` 目标状态

`master-protection.json` 只匹配 `refs/heads/master`：

- 禁止删除和 non-fast-forward 更新；
- 所有变更必须关联 Pull Request；
- 要求解决全部 review conversation；
- 要求 strict、最新的 `Candidate Quality` 状态检查；
- 允许 merge commit 与 rebase merge，禁用 squash merge；
- 单人阶段强制审批数为 `0`，不启用 CODEOWNERS；
- 不要求线性历史、签名提交或 tag 规则。

模板的 `bypass_actors` 保持为空，因为 RepositoryRole、Team、User 和 GitHub App 的 actor ID 属于具体远程仓库，不能作为通用常量复制。若确需管理员紧急绕过，应在实际仓库中添加“仅 Pull Request”绕过，并在导出状态中复核；不开放直接 push 绕过。

模板不包含提交信息正则。Conventional Commits 由 `scripts/check-repo.py --base-ref` 检查 PR 提交范围，同时允许正常 Git merge commit，避免远端元数据规则与 GitHub 生成的合并提交发生冲突。

## `dev` 策略

`dev` 是常态开发与集成分支，当前单人阶段不启用强制 Ruleset：

- 直接进入 `dev` 的变更仍须执行风险匹配的本地验证；
- 目标为 `dev` 的 PR 自动运行 `PR Checks`，供外部贡献和并行分支反馈；
- 有两名以上稳定维护者、持续接受外部贡献、多个自动化协作者并行写入，或出现绕过检查造成的回归时，重新评估 `dev` 保护；
- 每次 `master` 合并后，必须在下一轮开发前把 `master` 回流到 `dev`。

## 远程启用顺序

1. 完成仓库首次提交并推送 `master`；在此之前 Ruleset 无法保护尚不存在的远程状态。
2. 从最新 `master` 创建并推送 `dev`，不要在两个分支建立不同的初始根。
3. 通过测试 PR 或手动运行 `PR Checks`，确认 `Candidate Quality` context 已实际产生。
4. 在 GitHub Merge options 中启用 merge commit 与 rebase merge，关闭 squash merge。
5. 读取现有 Rulesets，确认没有同范围冲突或重复规则；如有旧规则，先确定合并或替代方案。
6. 按实际仓库决定是否加入管理员“仅 Pull Request”绕过，再导入或创建模板。
7. 用非默认分支发起测试 PR，验证直接 push、force push、删除、会话解决和 strict required check 行为。
8. 导出远程实际状态，与仓库模板记录的策略逐项复核；不要把“文件已提交”写成“远程已启用”。

GitHub 支持通过 JSON 导入 Ruleset，也允许管理员配置“仅 Pull Request”绕过。required checks 的 strict 模式要求主题分支在合并前与目标分支保持最新；仓库的 merge method 设置与 Ruleset 允许方式必须一致。参考 GitHub 官方的 [Rulesets 可用规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)、[创建 Ruleset](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)和 [Pull Request 合并方式](https://docs.github.com/en/pull-requests/reference/pull-request-merges)。

## API 运维原则

在已经关联远程仓库的本地目录中，可以先只读列出现状：

```bash
gh api repos/{owner}/{repo}/rulesets
```

新建规则前必须确认列表为空或没有同范围规则：

```bash
gh api repos/{owner}/{repo}/rulesets \
  --method POST \
  --input .github/rulesets/master-protection.json
```

已有 Ruleset 时，先读取其 ID，再用精确的 `PUT /repos/{owner}/{repo}/rulesets/{ruleset_id}` 更新。不得用重复 `POST` 代替更新，也不得在未比较远程 bypass actor 和继承规则时覆盖现状。

## Actions 安全基线

- workflow 使用 `pull_request`，不使用可带特权上下文的 `pull_request_target`；
- `GITHUB_TOKEN` 只授予 `contents: read`；
- checkout 不持久化凭据；
- 外部 Action 固定到完整 commit SHA，并在同行注释对应版本；
- 不在公共或不可信 PR 上使用持有设备凭据、签名密钥或内网访问权的 self-hosted runner；
- Action 更新作为普通依赖变更，经来源、版本、diff 和 CI 审查后合并。

GitHub 官方说明，完整 commit SHA 是把 Action 作为不可变版本使用的方式；同时应限制 token 权限并避免在特权触发器中检出不可信代码。参考 [GitHub Actions 安全使用](https://docs.github.com/en/actions/reference/security/secure-use)。

## 演进原则

- Ruleset 只绑定稳定聚合 context `Candidate Quality`；新增协议、密码、路由、固件或集成检查时，把组件接入聚合 job，不频繁修改远程 context。
- 没有真实所有权结构时不创建装饰性 CODEOWNERS，也不要求自我审批。
- 没有发布载体、版本、签名和密钥保管方案时，不创建自动发布或 tag Ruleset。
- 路径、文件大小和秘密泄露先由仓库检查与审查治理；是否启用 fork 网络级 push ruleset，应在确认仓库可见性和影响范围后单独决策。
- Ruleset、workflow、检查器、PR 模板、治理文档、ADR 和协作文件必须同步演进。
