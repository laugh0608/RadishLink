# D0/P0 软件工作计划

- 状态：Accepted（`SW-G0`，2026-08-24）
- 更新日期：2026-09-02
- 适用范围：D0 的无射频软件方案设计，以及进入 P0 前的 `SW-*` 证据准备
- 目标读者：产品、网络、安全、协议与测试协作者

## 目的

本计划纠正“先实现、后补方案”的顺序。2026-08-20 已完成的 Docker A—B—C 运行只作为探索性探针，用来暴露设计问题和验证本机工具可用；它不是 P0 实现基线、协议决策或阶段验收。

从本计划起，工作顺序固定为：

1. 明确需求、非目标和证据口径；
2. 评审覆盖层消息语义、安全边界和故障模型；
3. 冻结测试设计与可复现证据格式；
4. 获得实现与外部运行授权；
5. 才修改工具、执行验证并判断是否进入 P0。

在第 4 步前，现有 `tools/t0/` 和 `scripts/run-t0-three-node.sh` 只维护阻断性缺陷，不扩展故障注入、生产协议、密码、媒体或硬件能力。

## SW-G0 评审记录

- 结论：Accepted；
- 日期：2026-08-24；
- 接受范围：D0/P0 边界、`SW-EXP-001` 的探索性证据定位、设计优先的工作顺序和实现暂停线；
- 直接结果：下一工作包是[覆盖层消息交付语义](../protocol/message-delivery-semantics.md)的 `SW-G1` 评审；
- 授权边界：本 gate 只允许继续设计与只读核对，不授权修改或重跑测试实现，也不授权安装或集成密码依赖。

## 计划边界

本计划负责：

- 强制 A 与 C 不可直连、B 为唯一中继的无射频测试拓扑；
- 文字消息的去重、lifetime、hop budget、确认、custody 与存储转发设计；
- 延迟、丢包、限速、乱序、重复、断链和重启的确定性故障模型；
- E2EE 候选选择前的需求、许可证、平台和持久状态评审；
- 测试配置、指标、日志、结果与结论边界。

明确不负责：

- HaLow 采购、发射、距离、法规、功耗、温升、天线或媒体验收；
- 量产硬件、生产语言、操作系统发行版、公共线格式或数据库冻结；
- 自研密码协议，或在库未确认前用合成载荷宣称 E2EE；
- 邻居发现、大规模 Mesh、群组媒体和多中继优化。

## 当前证据与不足

探索性探针已经证明：本机 OrbStack/Docker 可以建立两张 internal bridge；A/C 没有共享网络；B 可以持久保存合成消息，并在 A/C 都断开时跨进程重启恢复。探针还覆盖了重复 ID、hop limit、lifetime 和未认证的目的端确认语义。

这些结果只回答“最低成本环境能否工作”，没有回答：

- 测试信封是否对应未来消息语义；
- 确认和删除提示如何认证，恶意 B 是否能伪造；
- 去重范围、缓存上限、时间语义、队列配额和淘汰顺序；
- 持久状态如何版本化、迁移、事务提交与崩溃恢复；
- 故障注入如何保持确定性且不改变被测语义；
- E2EE 库、身份、预密钥/KeyPackage、ratchet/epoch 状态与许可证；
- 结果产物如何复核、比较和判定阶段通过。

因此，脚本的 `T0 PASS` 只表示脚本内断言通过，不表示本计划、`SW-V*` 或 P0 已通过。该次运行统一登记为 `SW-EXP-001`。

## 待后续 gate 评审的设计候选

以下是下一轮评审的候选方案，不是已接受 ADR。

### 拓扑与承载

- 保留 `A—ab—B—bc—C` 两网隔离；A/C 永不加入同一 bridge，也不映射 host port；
- B 使用两个独立邻接接口，覆盖层只依赖可发送有界 frame 的承载接口；
- Docker/OrbStack 是当前最低成本执行环境，Linux network namespace 是无需改变上层语义的后备；
- 测试承载不得进入产品包格式、节点身份或路由真相源。

### 故障注入

- 首选每跳一个标准库用户态 link proxy，使用固定 seed 和显式 profile 注入延迟、丢包、限速、乱序与重复；
- proxy 只改变传输时序和交付，不解析或修改消息正文；
- Linux `tc netem` 保留为后续对照，不作为首选，因为它需要 Linux、`NET_ADMIN` 和额外外部状态授权；
- 不引入 Toxiproxy 等第三方依赖，除非标准库方案不能表达已确认的测试需求。

### 消息与确认

- 把 message lifetime 与 forwarding hop budget 分为两个字段，分别定义到期和防环；
- destination delivery、relay custody 和 user read receipt 是三种不同状态，不能共用一个 `ACK`；
- 中继删除副本必须由可验证的 destination delivery evidence 或本地到期/配额策略触发；
- 重复检测至少绑定协议版本、origin、message ID 与会话/epoch，精确键和认证方式等待安全设计；
- 当前 JSON `version: 0` 和 240-bit 摘要 ACK ID 仅为探针实现，不进入正式候选。

### 持久化

- 正式设计先定义状态机、原子提交边界、崩溃点和恢复不变量，再比较 SQLite、append-only log 或其他成熟存储；
- 当前全量 JSON snapshot 只用于少量合成消息，不支持并发、配额、迁移或损坏恢复结论；
- 必须先写出 schema version、未知字段、降级拒绝、迁移和回滚策略，之后才能选择实现。

### 证据

- 每轮运行使用版本化 manifest，记录代码 revision、拓扑、seed、profile、消息规模、超时和期望结果；
- 输出机器可读 summary、失败时间线和节点日志校验值；默认不提交大日志，只提交必要的脱敏结论与复现入口；
- 所有结论标注 `simulation`，不使用 `HaLow`、距离、无线吞吐、媒体、功耗或法规措辞。

## 决策门

### SW-G0：计划与术语

已于 2026-08-24 接受。评审确认 D0/P0 边界、探索性证据定位、工作顺序和暂停线；该结论不替代 `SW-G1..G4`。

### SW-G1：覆盖层消息语义

已于 2026-08-24 接受[覆盖层消息交付语义](../protocol/message-delivery-semantics.md)，覆盖：

- ID、版本、origin/destination、lifetime、hop budget 和优先级；
- destination delivery、relay custody、read receipt 与删除提示；
- 去重范围、重放区别、乱序、重试、配额与淘汰；
- 正例、负例、未知版本、时钟异常、存储失败和崩溃恢复。

`SW-G1` 只冻结语义和不变量，不冻结二进制编码、生产语言或数据库，也不构成实现授权。

### SW-G2：E2EE 与身份候选

按[端到端加密候选评审](../security/e2ee-candidate-review.md)比较 Signal 与 MLS 路线。[`SW-G2` 决策包](../security/e2ee-sw-g2-decision-package.md)已收敛候选顺序、无中心身份/投递映射、crash-safe 状态、许可证停止线、受限 spike 与接受条件。OpenMLS 0.8.1 Phase A 已在 advisory/许可证门正式 `STOP`；OpenMLS 0.9.0 的[Phase A 精确授权包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)也已由单元 E 对 264-package 固定图形成正式 `STOP`：独立 audit 漏洞为零但有 unmaintained 信息项，当前许可证门拒绝三个 `MPL-2.0` crate。两者 Phase B 均禁止。[`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)和[精确实施与 Phase A 包](../testing/sw-g2-mls-rs-phase-a-authorization.md)均已接受并执行到 A3；固定 94-package 图的 source/audit/deny 均为零，旧 transitive feature gate 因 `mls-rs-core` 默认 `fast_serialize` / `rfc_compliant` 形成正式历史 `STOP`。A2 已依据保留图离线改成 package-qualified 精确判定，A3 已实现只读 fixed graph 消费合同，但都不构成 Phase A `PASS`；D2 与 Phase B 未授权。最终选择通过 ADR 接受；未通过 `SW-G2`，只能测试合成不透明载荷，不能测试或宣称 E2EE。

### SW-G3：验证设计

已于 2026-08-28 接受[`SW-G3` 确定性故障与证据设计](../testing/sw-g3-deterministic-validation-design.md)，冻结 profile schema、固定 seed、单变量故障、指标、观察窗、停止条件、证据目录和 `PASS/FAIL/INVALID` 判定。该 gate 只允许继续形成 `SW-G4` 精确授权包，不授权实现或运行。

### SW-G4：实现授权

[`SW-G4 / SW-V0` Harness 最小实现与运行授权包](../testing/sw-g4-sw-v0-harness-authorization.md)已接受并按两个授权单位完成。四个 canonical profile 各三次通过且归一化一致；该结果只接受 harness 有效，不授权重跑、修改 profile/schema 或扩展 `SW-V1/V2/V3`。

### SW-G5：阶段判定

只有代码审查、单元/负向测试、三节点矩阵和证据复核都通过，才能把对应能力写为“Docker/Ethernet 软件模拟已验证”。是否进入 P0 还需要 `SW-G2` 的安全路线和 D0 的其他退出条件共同满足。

## 建议工作包

| 顺序 | 工作包 | 主要产物 | 当前状态 |
| --- | --- | --- | --- |
| 1 | 证据归档与计划纠偏 | 本计划、探索性探针边界 | `SW-G0` 已接受 |
| 2 | 消息交付语义 | [覆盖层消息交付语义](../protocol/message-delivery-semantics.md) | `SW-G1` 已接受 |
| 3 | E2EE/身份决策 | [`SW-G2` 决策包](../security/e2ee-sw-g2-decision-package.md)、[`SW-EXP-002` 执行授权包](../testing/sw-g2-openmls-spike-authorization.md)、[`mls-rs` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)与[精确包](../testing/sw-g2-mls-rs-phase-a-authorization.md)、[`OpenMLS 0.9.0` 静态门禁](../testing/sw-g2-openmls-0.9-spike-authorization.md)、[`SW-EXP-004` Phase A 精确包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)与 ADR | OpenMLS 0.8.1 与 0.9.0 固定图均为正式 Phase A `STOP`；mls-rs D 保留历史 `STOP`，A2/A3 已完成，D2/Phase B 未授权；无候选运行实证或 ADR |
| 4 | 故障与证据设计 | [`SW-G3`](../testing/sw-g3-deterministic-validation-design.md) | `SW-G3` 已接受 |
| 5 | `SW-V*` 工具调整 | [`SW-G4 / SW-V0` 授权包](../testing/sw-g4-sw-v0-harness-authorization.md) | `SW-V0` 已完成并通过；无重跑或后续 `SW-V*` 授权 |
| 6 | 三节点矩阵 | 可复现结果与限制 | 暂停 |
| 7 | P0 进入评审 | D0 退出证据汇总 | 未开始 |

## 授权与停止线

- 文档评审和只读盘点不授权修改代码、安装依赖或运行容器；
- 修改测试实现需要明确范围；运行容器前再次说明命令、目标、副作用、时长和清理；
- 依赖安装、VM 启动、系统网络、`NET_ADMIN`、射频、硬件、真实密钥和外部状态分别授权；
- 任一设计缺失会影响安全、兼容、数据或结论时，停止实现并回到相应决策门；
- `SW-G2` 未完成前，OpenMLS 0.9.0 当前基线不再重跑或进入 Phase B；mls-rs 单元 D 保留正式历史 `STOP`，A2 只修正未来 package-qualified gate。A3 已固定只读 seed D final lock、拒绝重新解析与旧 mutable cache 的合同并形成 clean revision；下一步仅申请 D2 单次 L3 授权。任何 D2 运行、进一步 gate 变化、依赖/provider/source 变化均须另行精确授权，不得复用 OpenMLS lockfile/cache 或相邻授权，也不得由 `SW-V0 PASS` 推导重跑或授权 `SW-V3`。
