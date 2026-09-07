# RadishLink 仓库治理

本文面向维护者、贡献者和自动化协作者，统一说明仓库内规则、GitHub 远程强制项、证据口径及其演进方式。分支与合并决策见 [ADR 0003](../adr/0003-branch-pr-and-ruleset-governance.md)。

## 家族参考与 RadishLink 取舍

本治理基线审阅了 Radish、RadishMind、RadishLex、RadishCatalyst、RadishFlow 和 RadishAxiom。沿用的是已经在多个项目中反复出现的治理原则，不复制各项目的产品边界、语言栈、发布任务或业务检查清单。

| 参考项目 | 可泛化经验 | RadishLink 的取舍 |
| --- | --- | --- |
| Radish | 风险分层验证、稳定主线和成组检查 | 保留分层思想，不引入 Web、数据库或部署检查 |
| RadishMind | `Candidate Quality` 稳定聚合 context、PR 与 release 检查分离 | 当前只建立 PR 基线；发布方案未冻结，不创建 release workflow |
| RadishLex | `master -> dev` 回流与祖先关系复核、安全和隐私影响面 | 直接采用拓扑闭环，并改写为设备身份、端到端加密和通信数据约束 |
| RadishCatalyst | 定义阶段先完成仓库地基，运行态检查后置 | 当前只强制无第三方依赖的仓库卫生，不用占位构建伪装实现门禁 |
| RadishFlow | 多平台检查作为独立组件进入聚合 job | 未来 Linux 主机、辅助 MCU、手机端和协议测试分别接入，不提前冻结平台矩阵 |
| RadishAxiom | 治理资产层级、可审阅 Ruleset 模板、提交规则放在 PR 范围检查 | 采用同类分层，并进一步移除模板中的远程角色魔法 ID |

因此，RadishLink 的共同拓扑是 `dev -> master -> dev`；确有隔离或评审需要时在前面增加 `topic -> dev`。项目特有门禁围绕无线电法规、设备身份、端到端加密、升级、公共协议、三节点证据和用户数据展开。

## 规则层级

发生冲突时按以下职责判断，不用低层自动化覆盖高层边界：

1. 适用法律、无线电法规、`LICENSE` 与第三方许可证决定法律和合规边界。
2. `SECURITY.md` 决定漏洞报告与披露方式。
3. `docs/product-definition.md` 决定产品长期定位、能力层级和明确非目标。
4. `docs/adr/` 决定已接受的长期架构与治理选择。
5. 本文决定仓库操作、PR、CI、证据口径和远程设置的一致规则。
6. `docs/status/current.md` 决定当前阶段、风险、近期决策和验证入口。
7. 专题文档决定对应架构、安全、硬件、法规、协议和测试边界。
8. `AGENTS.md` / `CLAUDE.md` 决定协作者启动时的任务定界、授权红线和文档路由；详细执行规则由 `docs/governance/agent-collaboration.md` 承接。
9. `.github/` 与 `scripts/` 实施可自动检查的部分，不自行创造新政策。

如果文档、模板、脚本和远程状态不一致，先确认哪一方过期，再在同一治理变更中统一修正。不得只放宽检查器来掩盖政策漂移，也不得把远程尚未启用的模板写成已经生效。

## 治理资产

| 资产 | 职责 |
| --- | --- |
| `LICENSE` | 仓库原创内容的查看、使用、贡献、再许可和责任边界 |
| `AGENTS.md` / `CLAUDE.md` | 启动级长期约束与任务路由，必须逐字一致 |
| `docs/governance/agent-collaboration.md` | 按任务读取的协作、实施、验证、交接与根入口维护细则 |
| `CONTRIBUTING.md` | 贡献入口、分支、提交和验证要求 |
| `CODE_OF_CONDUCT.md` | 协作行为和执行边界 |
| `SECURITY.md` | 私下漏洞报告、安全问题范围和披露方式 |
| `.editorconfig` / `.gitattributes` / `.gitignore` | 编码、换行、二进制和本地状态边界 |
| `scripts/check-repo.*` | 无第三方依赖的本地与 CI 仓库基线 |
| `.github/ISSUE_TEMPLATE/` | 缺陷与提案结构，安全问题分流 |
| `.github/PULL_REQUEST_TEMPLATE.md` | 影响面、证据、验证、风险和回流记录 |
| `.github/workflows/pr-check.yml` | PR 自动检查和稳定聚合 context |
| `.github/rulesets/` | 远程 `master` 保护的可移植模板和运维说明 |
| `docs/adr/` | 已接受决策、理由、后果与替代方案 |

根目录 `LICENSE` 是仓库原创内容的许可条款真相源，当前采用 `RadishLink Source-Available License 1.0`。它只在授权平台上允许个人参考和学习范围内的查看与阅读，不默认授予复制、修改、再分发、衍生开发或商业使用权利；外部贡献按其第 4 节授权，第三方组件和材料继续遵循各自许可证。该许可是 source-available，不得表述为开放源码许可证；其他文档与其冲突时以 `LICENSE` 为准。

许可证决策只比较了 Radish、RadishMind、RadishLex、RadishCatalyst 和 RadishFlow 的实际条款，没有采用 RadishAxiom 的许可证。RadishLink 选择五个参考项目共有的 1.0 基线；RadishCatalyst 1.1 中针对原创美术和游戏资产的专门条款不适用于当前项目边界，因此没有引入。

## 分支与提交

- `master` 是默认稳定主线，只通过 PR 接收阶段性晋级或 hotfix。
- `dev` 是常态开发与集成分支。
- 串行推进的普通任务直接进入 `dev`；外部贡献、并行写入、风险隔离或明确评审需求通过主题分支 PR 进入 `dev`。
- 需要主题分支时，使用 `feature/*`、`fix/*`、`docs/*`、`research/*`、`experiment/*`、`chore/*` 或 `hotfix/*`；Agent 不自动创建 `codex/*` 分支或额外 worktree。
- `research/*` 承载证据收集，`experiment/*` 承载原型；两者的结果都不会自动成为产品承诺或 Accepted ADR。
- 共享分支禁止 force push、reset 或 rebase 造成的历史重写。
- 提交使用 Conventional Commits，并按可审阅主题拆分；正常 Git merge commit 允许存在。
- 提交作者是对变更负责的真实贡献者，不添加 AI 协作者署名。

详细合并方式、回流命令与祖先关系验收见 [ADR 0003](../adr/0003-branch-pr-and-ruleset-governance.md)。

## 变更风险分层

| 等级 | 典型变更 | 最低要求 |
| --- | --- | --- |
| L0 文档卫生 | 错字、链接、格式，不改变事实或流程 | 精准复核、仓库检查、`git diff --check` |
| L1 仓库或局部实现 | 脚本、测试、内部实现，不改变公共边界 | 对应格式化、静态检查、精准测试、仓库检查 |
| L2 公共或安全边界 | 架构、公共协议、持久化格式、身份、密码、升级、用户数据 | 设计或 ADR、兼容性与失败模式、正负例、扩大验证 |
| L3 外部与不可逆状态 | 射频发射、刷写、依赖安装、远程 Ruleset、发布、签名、真实设备或用户数据 | 单独说明目标与副作用，获得明确授权，保存可审计证据和回滚方案 |

风险等级决定验证和审查深度，不授权超出任务范围的外部动作。文档描述命令不等于允许执行该命令。

## PR 审查矩阵

所有 PR 都应说明目标、范围、实际验证、未验证内容、风险和回滚。以下变化还必须覆盖对应问题：

| 变化 | 必需说明 |
| --- | --- |
| 无线与法规 | 国家或地区、SKU、监管域、频段、带宽、功率、天线和合法测试前提 |
| 网络与路由 | 邻居、路径、TTL、去重、存储转发、分区恢复、元数据和资源上限 |
| 身份与加密 | 信任根、配对、密钥生命周期、撤销、恢复、降级、重放和中继可见性 |
| 升级与恢复 | 签名、Secure Boot、回滚保护、失败恢复、救砖和版本兼容 |
| 公共协议与格式 | 版本、兼容性、迁移、未知字段、拒绝策略和失败模式 |
| 媒体与 QoS | 码率、时延、丢包、优先级、降级、拥塞和端到端保护边界 |
| 用户数据与诊断 | 收集目的、最小化、留存、删除、脱敏、访问权和日志边界 |
| 硬件与功耗 | 角色边界、供电、热、天线隔离、可维修性和量产外推限制 |
| CI 与供应链 | 权限、外部 Action/依赖来源、固定版本、秘密可见性和发布影响 |

PR 审查验证实现是否满足已声明规范，不替代对规范本身、法规结论或密码设计的专业评审。

## 声明与证据词汇

仓库使用以下词汇防止结论漂移：

- **产品目标**：希望达到且具有验收条件，但尚未证明。
- **架构候选**：仍在比较或等待验证的方案。
- **Accepted ADR**：已经接受的长期决策，不代表实现和实测均已完成。
- **厂商声明**：由供应商发布，未经过 RadishLink 自有复核。
- **第三方结果**：来自外部测试或标准材料，适用条件必须保留。
- **台架结果**：只覆盖记录的实验环境，不外推为外场或法规结论。
- **RadishLink 实测**：由项目按可复现方法取得，仍只覆盖记录的硬件、固件、环境和负载。
- **已验证能力**：只有相应三节点、端到端安全和环境指标真实通过后才能使用。

测试报告必须保存失败样例和条件。重跑成功不能自动消除不稳定性，`iperf3`、静态检查或两节点直连也不能替代其未覆盖的产品路径。

## CI 与 required context

`Candidate Quality` 是 Ruleset 唯一绑定的稳定聚合 job。当前组件只有 `Repo Hygiene`，覆盖：

- 必需治理和项目真相源是否存在；
- UTF-8、BOM、LF、末尾换行、NUL 和尾随空格；
- JSON 可解析性、Markdown 相对链接、路径与文件大小；
- `AGENTS.md` / `CLAUDE.md` 同步；
- Ruleset、workflow、聚合 context 和 Action SHA 固定契约；
- 本地或 PR diff 空白检查；
- PR 提交范围的 Conventional Commits；
- 仓库文档中意外出现的本机绝对路径。

已有工具也需要行为验证，不以生产技术栈尚未冻结为由无限延后；后续组件应按职责逐步加入聚合，而不把所有逻辑塞进一个难定位的 job：

- 覆盖层消息、路由、存储转发和资源限制测试；
- 身份、密钥、端到端加密、升级与负例测试；
- Linux 主机、可选辅助 MCU 和手机伴侣的构建与静态检查；
- 三节点网络命名空间模拟和故障注入；
- 依赖、许可证、固件与供应链检查。

真实 HaLow 发射、外场距离、天线、功耗、温升和实验室合规检查不适合伪装成普通云 CI；这些结果进入受控测试记录，并在 PR 中准确标注环境和人工步骤。

### 已有工具的质量入口演进

截至 2026-09-05，workflow 仍只运行 `Repo Hygiene`，以下是待实施清单，不是已生效的 job 或 required context：

- 优先接入 `tools/t0` 已存在的 Go 离线单元测试，区分 command package 尚无测试的覆盖缺口，不把 `go test` 绿灯解释为 CLI 全流程已验证；
- 为相关脚本选择已有的无网络 self-test、语法和 manifest 检查，逐项确认不会隐式启动容器、安装依赖、访问真实凭据或清理旧 evidence；
- 工具链准备与测试运行分离；依赖/Action 固定策略、网络和执行时长在 CI 实施时明确，不把工具准备失败默认为跳过成功；
- 接入后验证聚合 job 对测试失败真实返回非零，继续使用稳定 `Candidate Quality` 名称；不自动改变 dev push 触发方式或远程 Ruleset。

实验工具维护按已经存在的重复职责收敛：资源监控、精确进程清理、manifest 收口、checksum 与结果分类；候选专属 feature/source/版本规则保留显式配置。改动固定合同消费者时同时检查历史兼容与负例，不新建无实际需求的通用实验框架。

## 远程 Ruleset 基线

当前目标状态：

| 项目 | 策略 |
| --- | --- |
| 保护分支 | 仅 `master` |
| PR 要求 | 必须 |
| 删除 / force push | 禁止 |
| required context | `Candidate Quality` |
| strict / up-to-date | 启用 |
| review conversation | 必须解决 |
| 审批数 | 单人阶段为 `0` |
| CODEOWNERS | 暂不启用 |
| 合并方式 | merge commit、rebase merge |
| squash merge | 禁用 |
| bypass | 通用模板为空；远程如需管理员绕过，只允许 PR 内 |
| commit signature | 暂不强制 |
| tag / release rules | 版本、签名与发布载体冻结后另行设计 |

只有远程 GitHub 设置具有强制力。仓库模板负责审阅、复现和防止策略丢失；启用顺序、只读核对和 API 运维见 [Ruleset 说明](../../.github/rulesets/README.md)。

## Actions 与供应链停止线

- workflow 使用最小 `GITHUB_TOKEN` 权限，不向 PR 代码暴露发布、设备或签名秘密。
- 不使用 `pull_request_target` 检出和执行不可信 PR 代码。
- 外部 Action 固定完整 commit SHA，版本注释与更新审查同时维护。
- 公共或不可信 PR 不使用持有内网、开发机密钥或真实设备访问权的 self-hosted runner。
- 依赖安装、工具链下载、固件签名、artifact 发布和部署必须有独立授权与可复现来源。
- 固件、移动端和服务器依赖建立后，再决定依赖更新机器人、SBOM、漏洞扫描和许可证门禁，不提前创建空洞绿灯。

## 变更同步矩阵

| 变更 | 必须同步检查 |
| --- | --- |
| 分支或合并策略 | ADR、本文、Ruleset README/JSON、PR 模板、协作文件 |
| required context 或 CI 组件 | workflow、Ruleset、检查器、ADR、验证入口 |
| 当前阶段或下一决策 | `docs/status/current.md`、文档入口、相关专题 |
| 无线地区或合规结论 | 法规文档、硬件候选、测试计划、PR 影响面 |
| 身份、密码、升级或公共协议 | 安全文档、架构/协议专题、ADR、兼容性和负例测试 |
| 用户数据或诊断 | 安全文档、隐私边界、日志/fixture/截图规则 |
| 许可证或外部贡献 | `LICENSE`、CONTRIBUTING、README、当前状态与相关策略 |
| 安全报告方式 | SECURITY、Issue 分流、PR 模板和远程安全设置 |

## 演进停止线

- 不复制兄弟项目的业务检查、平台矩阵或发布方式；许可证与贡献条款必须由 RadishLink 明确记录，不因家族项目选择自动外推。
- 没有稳定实现和可执行测试时，不创建占位 required job。
- 没有真实多人所有权时，不创建装饰性 CODEOWNERS 或自我审批门禁。
- 没有版本、签名、密钥保管和恢复方案时，不自动发布固件、应用、镜像或 Release。
- 没有目标地区法规结论时，不用 CI 绿灯替代合法发射前置条件。
- 稳定规则一旦可以可靠机器验证，应进入检查器；自动化不能可靠判断的法规、安全评审和实验条件继续由文档与人工门禁承担。
