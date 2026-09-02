# RadishLink 文档

`docs/` 是 RadishLink 的正式产品、架构与决策来源。新任务先读取当前状态，再进入对应专题；研究资料只提供证据，不自动成为产品承诺。

## 默认入口

- [当前状态](status/current.md)：当前阶段、已确定事项、风险与下一步。
- [项目执行计划](status/project-execution-plan.md)：产品阶段、SW/HW/RF 证据轨、依赖与总 gate。
- [D0/P0 软件工作计划](status/d0-t0-p0-plan.md)：计划优先顺序、候选设计、决策门与暂停线。
- [产品定义](product-definition.md)：定位、用户价值、范围和验收层级。
- [路线图](roadmap.md)：从软件模拟、三节点原型到随身工程样机的推进顺序。

## 架构与协议

- [系统架构](architecture/system-architecture.md)
- [网络与路由](architecture/network-and-routing.md)
- [覆盖层消息交付语义](protocol/message-delivery-semantics.md)
- [安全架构](security/security-architecture.md)
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
- [三节点软件探索与验证规范](testing/t0-p0-software-validation.md)
- [`SW-EXP-002` OpenMLS 受限 spike 执行授权包](testing/sw-g2-openmls-spike-authorization.md)：Phase A lockfile、审计 `STOP` 与 Phase B 门禁。
- [`SW-EXP-003` mls-rs 0.56.0 静态门禁与执行授权包](testing/sw-g2-mls-rs-spike-authorization.md)：单元 D 在固定 94-package 图的旧 feature gate 保留历史 `STOP`；A2/A3 已形成 package-qualified gate 与固定图消费合同，D2 对同一图正式 `PASS`，人工许可证/NOTICE 与非实现者复核未完成，Phase B 禁止。
- [`SW-EXP-003` mls-rs 0.56.0 实施与 Phase A 精确授权包](testing/sw-g2-mls-rs-phase-a-authorization.md)：记录 A0–A3、C、D 与 D2；D2 run `20260902-130415-49997.8P5Td6` 的 schema 2/v2 四门全零，仓库 lockfile 与 seed/evidence 一致；不授权联网补证、重跑或 Phase B。
- [`SW-EXP-003` mls-rs 0.56.0 许可证/NOTICE 补证与非实现者复核包](testing/sw-g2-mls-rs-license-notice-review.md)：R0 已离线固定 11 个 package、3 个上游仓库、6 个不可变 commit、受限联网来源、证据合同和独立复核清单；R1/R2 与 Phase B 未授权。
- [`SW-EXP-004` OpenMLS 0.9.0 静态门禁与执行授权包](testing/sw-g2-openmls-0.9-spike-authorization.md)：单元 E 已形成 schema 4/v4 正式 `STOP`；独立 audit 漏洞为零但有 unmaintained 信息项，当前许可证门拒绝三个 `MPL-2.0` crate，Phase B 禁止。
- [`SW-EXP-004` OpenMLS 0.9.0 实施骨架与 Phase A 精确授权包](testing/sw-g2-openmls-0.9-phase-a-authorization.md)：记录成功 bundle、单元 D 无效结果、A6 修复与单元 E 正式负向证据；不授权重跑、Phase B 或放宽门禁。
- [`SW-G3` 确定性故障与证据设计](testing/sw-g3-deterministic-validation-design.md)：已接受的 profile、seed、数值、manifest 与 `PASS/FAIL/INVALID` 口径。
- [`SW-G4 / SW-V0` Harness 最小实现与运行授权包](testing/sw-g4-sw-v0-harness-authorization.md)：实施与 Docker 运行已分别授权并完成，四个 profile 各三次通过；不构成重跑或后续 `SW-V*` 授权。
- [技术证据](research/technology-evidence.md)

## 决策记录

- [ADR 索引](adr/README.md)
- [ADR 0001：主机、长距无线与近距接入基线](adr/0001-radio-and-host-baseline.md)
- [ADR 0002：分离无线承载层与 RadishLink 覆盖层](adr/0002-underlay-overlay-separation.md)
- [ADR 0003：分支、PR 与 Ruleset 治理](adr/0003-branch-pr-and-ruleset-governance.md)

## 协作与治理

- [Agent 协作与执行规则](governance/agent-collaboration.md)：根入口、专题规则、当前状态与记录的职责边界，以及任务实施、验证和交接细则。
- [仓库治理](governance/repository-governance.md)：规则层级、PR、CI、Ruleset、证据口径和演进停止线。
- [参与贡献](../CONTRIBUTING.md)
- [安全策略](../SECURITY.md)
- [社区行为准则](../CODE_OF_CONDUCT.md)
- [许可条款](../LICENSE)

## 文档规则

- 带距离、速率、续航和时延的数字必须标明测试条件或明确写为目标。
- 厂商峰值、标准上限和实测应用吞吐不得混写。
- 安全结论必须说明端到端、逐跳或本地静态数据的保护边界。
- 频段可用性按实际测试地区和设备区域版本确认，不从“全球频段”宣传语推导合法性。
- 尚未通过三节点实测的能力使用“候选”“目标”或“待验证”，不写成已经支持。
- 远程 Ruleset、Actions、分支或发布设置只有实际启用并复核后才写成生效；仓库模板本身只是声明。
