# 能力专题、实施切片与证据地图

本文面向产品、软件、硬件、安全和验证协作者，连接整体规划、跨阶段能力、既有子专题及任务 / 验收来源。它不修改已接受 ADR、协议、实验合同、参数、预算、运行授权或证据，不建立第二份 gate 状态表。

整体目标见[产品定义](product-definition.md)，阶段出口见[路线图](roadmap.md)，跨轨依赖与工作包标准见[项目执行计划](status/project-execution-plan.md)。实际能力、近期顺序、风险与停止线只从[current](status/current.md)进入。

## 层级、编号与进度来源

- 大专题按跨阶段能力划分，子专题使用现有架构 / 协议 / 安全 / 硬件文档或稳定章节。原实施记录与 testing 中的切片、操作包和证据不重新组织为一套平行合同。
- D0/P0/P1/P2/E0 是产品成熟度，SW/HW/RF/EXP 是证据轨，SW-G / HW-G / RF-R 是对应决策或执行门；这些维度都不等同于大专题。
- D1–D18 是原设计决定，I1–I5 是原软件实施单元，I5-I 与 I5-R 分别承载其原实施 / 运行范围；SW-V、R1/R2 与 G0/G1/G2 各保持原来源和定义，不合并或重新编号。
- current 维护实际状态、跨专题顺位和停止线；执行计划维护工作包产物、责任与进入 / 关闭条件；原专题维护设计、局部实施和验收，带日期记录保存历史过程。地图只登记主要归属和协同。

原计划中的日期段和批次结果按原时点理解；最新情况以 current 及其链接证据为准。设计接受、有限离线实现、真实软件运行、实体台架、射频与产品阶段通过必须分别判断，局部证据不沿主线自动升级。

## 大专题

| 能力主线 | 价值与范围 | 阶段 / 证据协同 | 目标范围完成条件 |
| --- | --- | --- | --- |
| Node 本地服务与活动生命周期 | 事务、持久化、恢复、活动作用域、历史与归档 | D0/P0 起；SW 与 HW，消息 / 安全协同 | 原联合事务、显式迁移、容量与失败恢复成立；同 boot 和跨 boot 的证据独立，生产入口不能由离线实现解锁 |
| 消息交付与网络路由 | 邻接、覆盖层、持久消息、预算、确认、排队与传输 | P0 起，P1/P2 负载协同；SW/HW/RF | 三节点交付、故障、资源与实际 transport 具备对应证据；overlay hop 不等同物理 hop |
| 身份、安全与控制 | E2EE、配对、活动身份、COSE、撤销、证明、依赖与许可前置 | D0 安全设计至各阶段；所有主线共享约束 | 设计、固定图、来源 / 许可证、R2、安全适配与真实运行分别满足；依赖工具 PASS 不证明安全能力或分发义务完成 |
| 终端交互与媒体 | Node 独立操作、可断开手机界面、文字 / 状态 / 语音与后续视频 | P0/P1，P2 后置；Node / 安全 / 硬件协同 | 独立设备主路径、身份权限和媒体降级在原条件下验证；手机不能成为 Node 运行前提，首台 E0 不以 P2 为前置 |
| 硬件、能源与便携交付 | Linux 三节点、辅助域、接口、电源、热、体积、BOM 与携带 | HW0–HW3、E0；SW 和 RF 合流 | 方案 / BSP 依据、采购、实体台架、交互 Demo 与工程预算各自闭合；纸面参数和查价不等于实体通过 |
| 无线合规与链路验证 | 地区、SKU、监管域、天线、功率及无线环境下的距离和链路 | RF-R*；P0/P1 与 E0 集成 | 对应地区 / 配置前提与实际射频证据成立；厂商范围、PHY 峰值、有线结果不能代替合法配置或外场应用指标 |
| 验证工具与受控运行环境 | 确定性故障、harness、profile、证据、监督、宿主与资源预算 | SW-G3/G4、I1–I5 及各主线验收支撑 | 固定输入、运行身份、计费与失败关闭可复验；helper / 仿真不替代实际硬上限、环境资格和正式运行 |

## 子专题主要归属

每个下列正式来源入口只登记一个主要归属；共同协议、ADR 与测试材料可被多条能力引用，但不复制正文、状态或阈值。

| 主要归属 | 子专题 / 原来源 | 实施、验收与证据入口 |
| --- | --- | --- |
| Node 本地服务与活动生命周期 | [Node 服务基线](architecture/node-service-design.md)、[活动生命周期](architecture/node-activity-lifecycle.md) | D1–D5 / D17–D18 与原 ADR；[服务基础](testing/node-service-foundation.md)、[运行可靠性](testing/node-service-reliability.md)、[活动与归档](testing/node-activity-lifecycle.md)，迁移 / 切换 / 崩溃分别验证 |
| Node 本地服务与活动生命周期 | [数据持久化](testing/node-data-persistence.md)、[控制持久化](testing/node-control-persistence.md)、[证明生命周期](testing/node-receipt-lifecycle.md) | 原 schema、事务和恢复实施切片；协议约束来自 D15/D16 与安全主线，局部持久化不等于真实签验 / transport 闭环 |
| 消息交付与网络路由 | [网络与路由](architecture/network-and-routing.md)、[消息语义](protocol/message-delivery-semantics.md)、[最小文字切片](architecture/minimal-text-slice.md) | SW-G1、SW-G3 与 I1–I5；原断链、确认丢失、去重、lifetime 和队列失败矩阵，不把探索协议迁作产品合同 |
| 消息交付与网络路由 | [数据 envelope](protocol/node-data-envelope.md)、[控制传播](protocol/node-control-propagation.md)、[共享外发](testing/node-outbound-scheduling.md) | D15/D16、持久尝试与责任轮转；framing、实际路由、传输公平及安全接入各按原前置，不扩大内部接线结论 |
| 身份、安全与控制 | [安全架构](security/security-architecture.md)、[Node 安全接入](security/node-security-integration.md)、[身份与控制 profile](security/node-identity-control-profile.md) | D6–D14 与原 ADR；[业务政策](testing/node-business-policy.md)、[控制入站](testing/node-control-ingress.md)及首次信任 / 签验 / 联合事务原清单，可信平台与跨 boot 隔离保持 |
| 身份、安全与控制 | [E2EE 候选](security/e2ee-candidate-review.md)、[SW-G2 决策包](security/e2ee-sw-g2-decision-package.md)、[控制依赖评审](security/node-control-dependency-review.md) | 原固定版本 / 依赖图、候选 Phase A/B 和采用条件；状态从 current 的证据轨进入，不从设计接受推导依赖采用 |
| 身份、安全与控制 | [mls-rs Phase A](testing/sw-g2-mls-rs-phase-a-authorization.md)、[许可证 / NOTICE 补证](testing/sw-g2-mls-rs-license-notice-review.md)、[处置评审](testing/sw-g2-mls-rs-license-disposition-review.md)、[debug_tree 澄清合同](testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md) | 原 R1、R1d、X/R 与 R2 条件；debug_tree 与 r-efi 分别处置，不据工程复核代替专业意见或重用一次性授权 |
| 身份、安全与控制 | [OpenMLS 0.8.1](testing/sw-g2-openmls-spike-authorization.md)、[OpenMLS 0.9.0 Phase A](testing/sw-g2-openmls-0.9-phase-a-authorization.md) | 固定候选历史与 STOP 原样保留；记录不授权 Phase B 或重新选择依赖图 |
| 身份、安全与控制 | [新图 G0/G1/G2](testing/node-security-graph-review-package.md)、[帧与图输入](testing/node-framing-and-graph-inputs.md) | 精确依赖输入、原执行合同与帧边界；输入可复现不等于实际 lock / 来源核验、硬资源、监督或安全准入 |
| 终端交互与媒体 | [手机伴侣](mobile/companion-app.md)、[媒体与 QoS](protocol/media-and-qos.md)、[Node 本地接口](architecture/node-service-design.md#应用接口与本地-web-信任) | 原首期场景、P0/P1/P2 与 Talk/View 目标；权限、断连、降级、时延与资源在各自条件下验收 |
| 硬件、能源与便携交付 | [硬件策略](hardware/hardware-strategy.md)、[硬件验证计划](hardware/hardware-validation-plan.md)、[BOM](hardware/poc-purchase-list.md) | HW0–HW3、HW-G0–G4；实体 Linux 三节点与单节点交互 Demo 分开，预算取舍和采购授权保留 |
| 无线合规与链路验证 | [地区法规预检](regulatory/radio-compliance.md)、[外场验证](testing/field-validation-plan.md) | RF-R*、原地区 / SKU 条件与目标环境；未关闭前不从硬件或 SW 通过推出发射与距离结论 |
| 验证工具与受控运行环境 | [确定性设计](testing/sw-g3-deterministic-validation-design.md)、[修订评审](testing/sw-g3-revision-2-review.md)、[SW-V0 harness](testing/sw-g4-sw-v0-harness-authorization.md) | SW-G3/G4 与正式 profile、断言、归一化和证据边界；历史运行合同及未接受修订不改写 |
| 验证工具与受控运行环境 | [I1 算法](testing/sw-g4-synthetic-i1-plan.md)、[I2 有界读写](testing/sw-g4-synthetic-i2-plan.md)、[I3 持久路径](testing/sw-g4-synthetic-i3-plan.md)、[I4 场景与证据](testing/sw-g4-synthetic-i4-plan.md)、[I5 三进程闭环](testing/sw-g4-synthetic-i5-plan.md) | 原实施范围与验收；I3 合成存储不替代 Node 产品数据库，I4 样本不替代全部矩阵，I5-I 与 I5-R 分开 |
| 验证工具与受控运行环境 | [资源隔离](testing/sw-g4-synthetic-i5-resource-isolation.md)、[环境准备](testing/sw-g4-synthetic-i5-environment-preparation.md)、[环境可行性](testing/sw-g4-synthetic-i5-environment-feasibility.md) | 原整批预算、写入归属、工具来源、验签与计费条件；历史盘点不当作当前状态，不反复消耗旧操作包 |
| 验证工具与受控运行环境 | [执行合同](testing/sw-g4-synthetic-i5-execution-contract.md)、[原生初始化](testing/sw-g4-synthetic-i5-native-initialization.md)、[宿主交付](testing/sw-g4-synthetic-i5-host-delivery.md)、[FD loader 决策](testing/sw-g4-synthetic-i5-host-loader-decision.md)、[路线 A 评估](testing/sw-g4-synthetic-i5-linux-host-assessment.md) | 原身份 / 输入闭包、Linux 父监督、真实 loader 和完整预算；等待资源事实变化后按原前置推进，不把 Mac/UTM 改名当合格宿主 |

## 当前五项接续的阅读链

顺序以[current 当前优先级](status/current.md#当前优先级)为准；[执行计划的近期工作包](status/project-execution-plan.md#近期工作包与决策顺序)保存产物、责任和关闭标准。下表只映射归属，不重新分配优先级或填写执行状态。

| 接续项 | 牵头 / 协同 | 原任务与验收来源 |
| --- | --- | --- |
| 1. 就绪集合 / 传输公平及 framing、工作池、输出授权交接 | Node 本地服务；安全、消息协同 | [共享外发](testing/node-outbound-scheduling.md)、[帧边界](testing/node-framing-and-graph-inputs.md)、D17 / D18 活动方案与实施记录；D18 后的实际接续以 current 为准。锁风险见[运行可靠性诊断](testing/node-service-reliability.md#store-锁并发诊断2026-11-02)，内部离线证据不解除安全 / 运行门 |
| 2. 内部 Linux ARM64 产物与许可证处置 | 身份、安全与控制；验证主线协同 | SW-G2 决策包、R1d、debug_tree 与 r-efi 原评审，冻结实际复制 / 留存范围和复核责任；专业意见、新证据和 R2 条件不相互替代 |
| 3. 首次信任、签验与联合事务验证输入 | 身份、安全与控制；Node、消息与终端协同 | 已接受 D11–D16、控制 profile、手机身份和路由边界；实际接入保留许可证 / Phase B / 可信平台前置，不重复讨论已接受设计 |
| 4. I5 路线 A 资源条件与真实环境准备 | 验证工具与受控运行环境；Node / 供应链协同 | 路线 A 评估 → 预算与可信基座 → FD loader / 控制面 / 新执行合同 → 原生验收与各精确授权；资源不变时不重复盘点，I5-R 不因离线通过开放 |
| 5. 离线测试 CI 与重复工具维护、硬件联合预算 | 验证主线与硬件主线协同 | 原工作包、HW0/BOM、能量 / 体积 / 成本与治理规范；测试接入、采购、台架与 RF 分别判断，不把 CI 或预算表当产品交付 |

SW/HW/RF 可以在各自前置满足时积累证据；最终产品阶段仍以原路线图退出标准整合评审。当前所有缺口、预算取舍、一次性包消费和停止线保持原来源，本页不授权网络、设备、采购、法律结论、真实运行或外部消息。
