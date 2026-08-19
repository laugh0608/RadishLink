# RadishLink 文档

`docs/` 是 RadishLink 的正式产品、架构与决策来源。新任务先读取当前状态，再进入对应专题；研究资料只提供证据，不自动成为产品承诺。

## 默认入口

- [当前状态](status/current.md)：当前阶段、已确定事项、风险与下一步。
- [产品定义](product-definition.md)：定位、用户价值、范围和验收层级。
- [路线图](roadmap.md)：从软件模拟、三节点原型到随身工程样机的推进顺序。

## 架构与协议

- [系统架构](architecture/system-architecture.md)
- [网络与路由](architecture/network-and-routing.md)
- [安全架构](security/security-architecture.md)
- [媒体与 QoS](protocol/media-and-qos.md)
- [手机接入方案](mobile/companion-app.md)

## 硬件、合规与验证

- [硬件策略](hardware/hardware-strategy.md)
- [原型采购清单](hardware/poc-purchase-list.md)
- [无线电合规前置条件](regulatory/radio-compliance.md)
- [外场验证计划](testing/field-validation-plan.md)
- [技术证据](research/technology-evidence.md)

## 决策记录

- [ADR 索引](adr/README.md)
- [ADR 0001：主机、长距无线与近距接入基线](adr/0001-radio-and-host-baseline.md)
- [ADR 0002：分离无线承载层与 RadishLink 覆盖层](adr/0002-underlay-overlay-separation.md)
- [ADR 0003：分支、PR 与 Ruleset 治理](adr/0003-branch-pr-and-ruleset-governance.md)

## 协作与治理

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
