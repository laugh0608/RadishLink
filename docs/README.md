# RadishLink 文档

`docs/` 是 RadishLink 的正式产品、架构与决策来源。新任务先读取当前状态，再进入对应专题；研究资料只提供证据，不自动成为产品承诺。

## 默认入口

- [当前状态](status/current.md)：当前阶段、已确定事项、风险与下一步。
- [项目执行计划](status/project-execution-plan.md)：产品阶段、近期工作包、待决策事项与 SW/HW/RF 依赖。
- [D0/P0 软件工作计划](status/d0-t0-p0-plan.md)：计划优先顺序、候选设计、决策门与暂停线。
- [产品定义](product-definition.md)：定位、用户价值、范围和验收层级。
- [路线图](roadmap.md)：从软件模拟、三节点原型到随身工程样机的推进顺序。

## 架构与协议

- [系统架构](architecture/system-architecture.md)
- [Node 服务架构与关键选型方案](architecture/node-service-design.md)：已接受 D1—D5 的服务基线及事务恢复、接口、部署和剩余评审。
- [最小文字闭环实现前设计](architecture/minimal-text-slice.md)：待评审的用户路径、事务边界与失败矩阵。
- [网络与路由](architecture/network-and-routing.md)
- [覆盖层消息交付语义](protocol/message-delivery-semantics.md)
- [Node 数据 envelope](protocol/node-data-envelope.md)：不可变核心、MLS AAD、保守时间与 D15 已接受参数。
- [Node 控制传播预算](protocol/node-control-propagation.md)：退出/报告有界转发、逐跳确认与 D16 已接受容量取舍。
- [安全架构](security/security-architecture.md)
- [Node 安全接入设计](security/node-security-integration.md)：D6—D10 的联合事务、证明、撤销与跨 boot 边界。
- [Node 身份与控制 profile](security/node-identity-control-profile.md)：活动绑定、撤销权限、COSE 精确约束与 D11—D14 已接受基线。
- [Node 控制证明依赖评审准备](security/node-control-dependency-review.md)：候选版本、固定源码证据、完整图与采用前缺口。
- [端到端加密候选评审](security/e2ee-candidate-review.md)
- [`SW-G2` E2EE 与身份候选决策包](security/e2ee-sw-g2-decision-package.md)
- [媒体与 QoS](protocol/media-and-qos.md)
- [手机接入方案](mobile/companion-app.md)

## 硬件、合规与验证

- [硬件策略](hardware/hardware-strategy.md)
- [低成本硬件验证计划](hardware/hardware-validation-plan.md)
- [原型采购清单](hardware/poc-purchase-list.md)
- [无线电合规前置条件](regulatory/radio-compliance.md)
- [外场验证计划](testing/field-validation-plan.md)
- [Node 第一批服务与事务基础](testing/node-service-foundation.md)：固定依赖、SQLite 联合事务、离线故障验证及生产接入边界。
- [Node 服务运行可靠性](testing/node-service-reliability.md)：生命周期、schema 迁移、控制容量预留、周期维护及安全接入核对。
- [Node D16 控制持久化与尝试预算](testing/node-control-persistence.md)：schema v4、固定预留、活动/对象/邻居责任与离线迁移故障验证。
- [Node 证明生命周期与恢复边界](testing/node-receipt-lifecycle.md)：提交后证明意图、schema v3、原消息截止时间与离线故障验证。
- [Node 安全候选新图精确评审包](testing/node-security-graph-review-package.md)：固定输入、G1/G2 命令与来源/资源/证据合同，非执行授权。
- [Node 帧边界与新图离线输入验证](testing/node-framing-and-graph-inputs.md)：D15 接收缓存/超时实现、G0 输入准备与尚未满足的真实运行前置。
- [三节点软件探索与验证规范](testing/t0-p0-software-validation.md)
- [`SW-EXP-002` OpenMLS 受限 spike 执行授权包](testing/sw-g2-openmls-spike-authorization.md)：Phase A / Phase B 合同与历史结果。
- [`SW-EXP-003` mls-rs 0.56.0 静态门禁与执行授权包](testing/sw-g2-mls-rs-spike-authorization.md)：候选静态门与停止条件。
- [`SW-EXP-003` mls-rs 0.56.0 实施与 Phase A 精确授权包](testing/sw-g2-mls-rs-phase-a-authorization.md)：固定依赖图、实施单元与 Phase A 结果。
- [`SW-EXP-003` mls-rs 0.56.0 许可证/NOTICE 补证与非实现者复核包](testing/sw-g2-mls-rs-license-notice-review.md)：许可证取证合同、运行结果与 R2 前置。
- [`SW-EXP-003` mls-rs 0.56.0 R1d-L 独立许可证处置评审](testing/sw-g2-mls-rs-license-disposition-review.md)：固定对象、分发渠道与独立处置意见。
- [`SW-EXP-003` `debug_tree 0.4.0` R1d-U-P 上游澄清设计](testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md)：已冻结的公开澄清与只读收集合同。
- [`SW-EXP-004` OpenMLS 0.9.0 静态门禁与执行授权包](testing/sw-g2-openmls-0.9-spike-authorization.md)：候选静态门与停止条件。
- [`SW-EXP-004` OpenMLS 0.9.0 实施骨架与 Phase A 精确授权包](testing/sw-g2-openmls-0.9-phase-a-authorization.md)：审计工具、精确实施与 Phase A 结果。
- [`SW-G3` 确定性故障与证据设计](testing/sw-g3-deterministic-validation-design.md)：版本化 profile、故障矩阵、证据与待评审勘误。
- [`SW-G3` 实现前修订评审包](testing/sw-g3-revision-2-review.md)：待评审的重试、长度、故障划分与版本方案。
- [后续 `SW-G4` 离线实施单元 I1](testing/sw-g4-synthetic-i1-plan.md)：重试算法、长度边界、精确范围与离线验证记录。
- [后续 `SW-G4` 有界读写单元 I2](testing/sw-g4-synthetic-i2-plan.md)：frame 限额、V0 兼容、短写拒绝与离线验证记录。
- [后续 `SW-G4` 持久文字路径单元 I3](testing/sw-g4-synthetic-i3-plan.md)：合成 envelope、队列资源、文件提交恢复合同与完整离线路径验证记录。
- [后续 `SW-G4` 场景与证据接入单元 I4](testing/sw-g4-synthetic-i4-plan.md)：离线 variant、版本化事实/断言、三次比较与实施验证记录。
- [后续 `SW-G4` 三进程文字闭环单元 I5](testing/sw-g4-synthetic-i5-plan.md)：独立进程/TCP、监督屏障与证据合同；I5-I 离线验收记录及 I5-R 运行边界。
- [I5 整批资源隔离设计](testing/sw-g4-synthetic-i5-resource-isolation.md)：保留 768 MiB、构建与写入隔离要求、入口停止检查及重新开放条件。
- [I5 专用环境准备评审包](testing/sw-g4-synthetic-i5-environment-preparation.md)：工具来源候选、身份交接与宿主容量缺口，非安装授权。
- [I5 环境可行性与下一次操作包](testing/sw-g4-synthetic-i5-environment-feasibility.md)：安装差量草案、768 MiB 完整核算及验签/离线解析候选，非执行授权。
- [I5 准备执行合同与原生证据候选](testing/sw-g4-synthetic-i5-execution-contract.md)：执行源闭包、纯一致性校验、物理前置条件与真实证据模型，非执行授权。
- [I5 原生初始化与 bootstrap 离线实施](testing/sw-g4-synthetic-i5-native-initialization.md)：物理承载候选、Linux 后端职责、固定源码组装与独立证据绑定，非真实环境通过结论。
- [I5 宿主写入边界与原生生命周期离线接入](testing/sw-g4-synthetic-i5-host-delivery.md)：完整写入裁决、独立库包交付、父监督职责与离线故障验收，真实入口保持停止。
- [I5 宿主可行性裁决与真实 FD loader 合同草案](testing/sw-g4-synthetic-i5-host-loader-decision.md)：当前承载 NO-GO、替代路线、稳定预期与本次观察、可信加载职责及决策状态。
- [I5 路线 A 已有 Linux 资源与准备预算](testing/sw-g4-synthetic-i5-linux-host-assessment.md)：宿主最低条件、完整准备包络候选、现有资源差距与后续前置。
- [`SW-G4 / SW-V0` Harness 最小实现与运行授权包](testing/sw-g4-sw-v0-harness-authorization.md)：harness 实施、运行合同与结论边界。
- [技术证据](research/technology-evidence.md)

## 决策记录

- [2026-10-24 开发回顾与接续事项](status/2026-10-24-progress.md)：当天提交、Node 代码与文档核对、新图执行前置及下一步建议。

- [2026-10-18 开发回顾与接续事项](status/2026-10-18-progress.md)：当天全部提交、代码与文档核对、路线 A 资源门及接下来的事项。

- [2026-10-13 开发回顾与接续事项](status/2026-10-13-progress.md)：当天全部提交、I5 准备链代码与文档核对、离线验证边界及后续事项。
- [2026-10-09 开发回顾与明日事项](status/2026-10-09-progress.md)：当天全部提交、补充盘点与生命周期代码核对、文档同步及次日接续顺序。
- [2026-10-06 开发回顾与明日事项](status/2026-10-06-progress.md)：当天全部提交、guest 盘点与回收代码核对、环境准备缺口及次日接续顺序。
- [2026-10-01 开发回顾与明日事项](status/2026-10-01-progress.md)：当天全部提交、资源隔离实施核对、专用 VM 准备边界及次日接续顺序。
- [2026-09-26 开发回顾与明日事项](status/2026-09-26-progress.md)：当天提交、代码与文档核对、I5-R 前置缺口及次日接续顺序。
- [2026-09-03 状态与批次快照](status/2026-09-03-progress.md)：历史流水与证据引用，非当前授权。
- [ADR 索引](adr/README.md)
- [ADR 0001：主机、长距无线与近距接入基线](adr/0001-radio-and-host-baseline.md)
- [ADR 0002：分离无线承载层与 RadishLink 覆盖层](adr/0002-underlay-overlay-separation.md)
- [ADR 0003：分支、PR 与 Ruleset 治理](adr/0003-branch-pr-and-ruleset-governance.md)
- [ADR 0004：Node 服务、事务与本地数据基线](adr/0004-node-service-foundation.md)
- [ADR 0005：Node 安全接入、撤销与证据寿命](adr/0005-node-security-integration.md)
- [ADR 0006：Node 活动身份与控制证明 profile](adr/0006-node-identity-and-control-profile.md)
- [ADR 0007：Node 数据 envelope 与控制传播预算](adr/0007-node-envelope-and-control-budget.md)

## 协作与治理

- [Agent 协作与执行规则](governance/agent-collaboration.md)：根入口、专题规则、当前状态与记录的职责边界，以及任务实施、验证和交接细则。
- [仓库治理](governance/repository-governance.md)：规则层级、PR、CI、Ruleset、证据口径和演进停止线。
- [参与贡献](../CONTRIBUTING.md)
- [安全策略](../SECURITY.md)
- [社区行为准则](../CODE_OF_CONDUCT.md)
- [许可条款](../LICENSE)

## 文档规则

- 当前结果与下一步统一从 `status/current.md` 进入；索引不重复批次结果，专题中的历史结果标明时点。
- 带距离、速率、续航和时延的数字必须标明测试条件或明确写为目标。
- 厂商峰值、标准上限和实测应用吞吐不得混写。
- 安全结论必须说明端到端、逐跳或本地静态数据的保护边界。
- 频段可用性按实际测试地区和设备区域版本确认，不从“全球频段”宣传语推导合法性。
- 尚未通过三节点实测的能力使用“候选”“目标”或“待验证”，不写成已经支持。
- 远程 Ruleset、Actions、分支或发布设置只有实际启用并复核后才写成生效；仓库模板本身只是声明。
