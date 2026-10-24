# RadishLink 当前状态

更新日期：2026-10-24

## 当前阶段

项目处于 `D0：产品定义、法规预检与三节点 POC 准备`。已有消息语义、确定性验证设计、harness 和密码候选依赖检查；尚无已验证的产品 E2EE 闭环、实体 Linux 台架、HaLow 距离或媒体能力。

本页只保存当前结论、关键风险、下一项决策与停止线。历史 run、hash、失败时间线和当时授权见[2026-09-03 状态与批次快照](2026-09-03-progress.md)及对应测试专题；I1 算法、I2 有界读写与 I3 合成持久路径均完成离线验证，不重判历史结果，不代表重新执行正式实验或复核远程配置。

I1–I5-I 已提交并通过有限离线验证；容量核验和受限双构建 helper 尚未接入运行入口，真实环境与 daemon 隔离未完成，整批预算仍为 768 MiB。2026-10-06 宿主结果回收与有效 guest 盘点通过：Debian 13 ARM64、Landlock ABI 6，已查包和路径未发现 Go/Docker/containerd/runc；构建身份、克隆身份处理及四个容量域仍未准备。详见[实测结果](../testing/sw-g4-synthetic-i5-resource-isolation.md#宿主回收与第二次盘点实测结果2026-10-06)。

[环境准备评审包](../testing/sw-g4-synthetic-i5-environment-preparation.md)已细化官方工具候选、身份交接与完整容量关系；Docker 索引摘要一致但签名未验证，依赖闭包及宿主 backing/日志硬上限仍缺。启动事件、宿主输入源诊断和前置失败报告修复的历史证据保留在该专题。

2026-10-09 包表 stdout 专属 512 KiB 调整获准应用，随后[完整补充盘点和正常回收通过](../testing/sw-g4-synthetic-i5-environment-preparation.md#完整补充盘点与正常回收通过2026-10-09)：取得 1565 个包记录，确认 guest 已有 APT/dpkg/gpgv/sqv；swap 位于 `/dev/vda4`、约 2.584 GiB，采样未用，根/EFI 仍可写，Docker/containerd unit 及 policy-rc.d 不存在。最终结果 474110 bytes，仍低于原 512 KiB 上限；VM 正常停止、未强制关机，配置和全部 VM 状态一致。下一步基于完整基线收敛验签、安装差量与系统盘/swap/宿主写入硬边界；本次不代表这些门已通过。七个 VM 相关单次包及一次宿主观察均已消费，I5-R 继续禁止。

## 已确定的产品与工程基线

- 项目名 `RadishLink`，标语 `无网亦可达`；正式设备同时具备终端与中继能力，中继启用受电量、温度、用户策略和网络状态约束。
- 设备必须独立完成联系人选择、文字收发、按键通话和基本状态查看；手机是附近伴侣，不是运行前提。
- 主系统为嵌入式 Linux；ESP32-S3 只作为交互、电源、唤醒等辅助域候选。
- 长距承载首选评估 Wi-Fi HaLow，近距使用独立 2.4 GHz Wi-Fi/BLE；无线承载与覆盖层分离，不冻结量产器件、监管域或路由实现。
- 应用 E2EE 与逐跳保护分层，中继不得获得内容明文；三节点是中继验证的最低规模，替代路径恢复另需可用的替代链路。
- 产品阶段保留 `D0/P0/P1/P2/E0`；首台文字/语音 E0 不以 P2 为前置。2026-10-09 所有者已选择 Node 持有身份、会话与受保护历史，手机为可断开的已授权界面；具体安全机制和 SW-G2 仍未通过，见[项目执行计划](project-execution-plan.md)。
- 首期为 3–5 人熟人小队入场前配对，交换短文字、状态与按键通话；一次白天 6–8 小时活动、当天可充电，首台允许背包携带，均为设计目标。2026-10-24 按所有者授权采用[使用量与携带规划值](../product-definition.md#使用量与携带规划基线2026-10-24)，不是实测或正式 profile 参数。上海地区不变；整套目标 2000–3000 元、累计硬上限 3000 元，首轮有线台架新增支出评审上限 1000 元。无可复用设备；2026-10-24 所有者确认累计已支出 0 元。所有者已反馈整份 BOM 价格，暂不另计供电线合计 2024 元，超出原首轮上限 1024 元；预算取舍待实际采购前决定，合法无线配置仍未关闭。
- 硬件按三台 Linux 有线台架、单台交互 Demo 顺序推进；无可复用设备，优先评估 Radxa ZERO 3E 2GB 全新增方案，未冻结或采购。许可证先评审所有者控制的 Linux ARM64 合成实验且暂不对他人交付，优先推进固定 mls-rs 0.56.0；两包处置与未来渠道仍须分别评审。
- 原创内容采用根目录 `LICENSE` 的 `RadishLink Source-Available License 1.0`，不是开放源码许可证。
- 串行普通开发在 `dev`，`master` 为默认稳定主线；主题分支与 PR 适用条件见[仓库治理](../governance/repository-governance.md)。远程 Ruleset、合并选项和私密漏洞入口的既有核对记录不等于本轮实时复核。

## 各证据轨状态

| 证据轨 / gate | 当前结论 | 后续缺口与正式记录 |
| --- | --- | --- |
| `PLAN-G0 / SW-G0 / SW-G1` | 已接受计划、术语和消息交付语义 | [执行计划](project-execution-plan.md)、[软件计划](d0-t0-p0-plan.md)、[消息语义](../protocol/message-delivery-semantics.md) |
| `SW-G3` | 1.0 设计已接受；修订未整体接受，Node 证据寿命规则由 ADR 0005 D10 有限接受 | [修订评审包](../testing/sw-g3-revision-2-review.md)补齐证据返回责任与迟到调度规则；原参数和历史证据不变 |
| `SW-G4 / SW-V0` | 已完成；四个 canonical profile 各三次通过且归一化一致 | 只证明 harness；[正式记录](../testing/sw-g4-sw-v0-harness-authorization.md)不授权重跑或扩展 |
| 后续 `SW-G4 / I1` | 有限范围已接受，离线算法实施与验证通过 | [I1 记录](../testing/sw-g4-synthetic-i1-plan.md)覆盖重试与长度边界；全量回归先受沙盒缓存权限阻断，获准同命令复验通过；无正式场景结果 |
| 后续 `SW-G4 / I2` | 有限范围已接受，实施与离线验证通过 | [I2 记录](../testing/sw-g4-synthetic-i2-plan.md)覆盖显式限额、V0 兼容和短写拒绝；全量 vet/test 首次受缓存权限阻断，同命令获准复验通过；[队列/事务接入](../architecture/minimal-text-slice.md#队列与事务的接入设计)仍为候选 |
| 后续 `SW-G4 / I3` | 有限范围已接受，十文件实施与离线验证通过 | [I3 记录](../testing/sw-g4-synthetic-i3-plan.md)覆盖合成 envelope/store v1、四消息资源、完整持久路径、事务错误与进程重开；全量 vet/test 首次缓存权限失败，同命令获准复验通过；不等于真实安全或正式场景 |
| 后续 `SW-G4 / I4` | 有限范围已接受，实施与离线验证通过 | [I4 记录](../testing/sw-g4-synthetic-i4-plan.md)覆盖观测/证据合同、五 profile 七子用例共 21 个独立样本及三次比较、事实篡改拒绝；全量 vet/test 通过，不是正式 SW-V1/V2 结果 |
| 后续 `SW-G4 / I5` | I5-I 有限范围已接受，实施与离线验收通过；I5-R 未执行且入口停止 | [I5 方案](../testing/sw-g4-synthetic-i5-plan.md)覆盖控制/节点/监督器与 V3 证据；[资源隔离补充设计](../testing/sw-g4-synthetic-i5-resource-isolation.md)保留 768 MiB，证据计费、容量探测和受限双构建 helper 离线通过；运行接入、daemon 隔离与真实环境验收未完成，实际 TCP 三容器矩阵未运行 |
| `SW-EXP-001` | Docker/Ethernet 合成载荷探索成立 | 不是正式消息实现、E2EE 或 P0 验收 |
| OpenMLS `0.8.1` | Phase A `STOP`：advisory 与许可证门 | [历史授权与结果](../testing/sw-g2-openmls-spike-authorization.md)，Phase B 禁止 |
| OpenMLS `0.9.0` | 单元 E：固定 264-package 图 Phase A `STOP` | 独立 audit 未发现 vulnerability，但有 unmaintained 信息项；当前门拒绝三个 MPL-2.0 crate；[正式记录](../testing/sw-g2-openmls-0.9-phase-a-authorization.md) |
| mls-rs `0.56.0` | D2：同一固定 94-package 图 Phase A `PASS`；D 的旧 feature-gate `STOP` 保留 | [Phase A 记录](../testing/sw-g2-mls-rs-phase-a-authorization.md)；工具通过不等于分发义务或安全适配完成 |
| mls-rs 许可证证据 | R1/R1b 传输负向；R1c-R 为 `STOP/license-evidence`；R1d-L 为 `STOP/license-disposition` | [补证与复核包](../testing/sw-g2-mls-rs-license-notice-review.md)、[处置评审](../testing/sw-g2-mls-rs-license-disposition-review.md)；R2 前置未满足 |
| `SW-G2 / SW-V1..V3` | E2EE 决策未通过，后续正式场景未执行 | [决策包](../security/e2ee-sw-g2-decision-package.md)；没有已验证 E2EE 或产品软件闭环 |
| `HW` | 已定位 b1 镜像/内核/引导版本和双接口源码依据，所有者反馈 BOM 小计 2024 元，首轮超预算；详细 `HW-G0/G1` 待评审，未进入实体台架 | [低成本验证计划](../hardware/hardware-validation-plan.md)、[2026-10-24 BOM 评审](../hardware/poc-purchase-list.md#三节点全新增-bom-评审2026-10-24) |
| `RF` | 上海地区输入已确认，SKU/配置与法规结论未关闭，保持 `RF-R0` | [法规预检](../regulatory/radio-compliance.md)，采购与发射暂停 |

mls-rs 当前实质缺口：R1c-R 已为 9 个 mls-rs package 取得 Apache-2.0/MIT 正文；`debug_tree 0.4.0` 缺绑定固定源码的 MIT notice/holder，`r-efi 6.0.0` 的 `AUTHORS` 含完整 MIT 正文与归属，但缺另两项声明 alternative 的完整正文。前者的 R1d-U-P/I 已完成澄清设计及离线 helper，公开发送 X 与只读收集 R 均未执行；后者等待独立法律评审后再分流。这是证据和处置缺口，不是许可证不存在、违法或候选淘汰结论。

## 当前优先级

2026-10-24 所有者接受 D11—D14 后，已固化 [ADR 0006](../adr/0006-node-identity-and-control-profile.md) 并提交为 `5d2ebfc`；随后接受 D15/D16，固化 [ADR 0007](../adr/0007-node-envelope-and-control-budget.md) 并提交为 `fdefa3b`，见[接受记录](project-execution-plan.md#node-d15d16-接受记录2026-10-24)。接续完成[帧边界与新图离线输入开发](../testing/node-framing-and-graph-inputs.md)：4 邻居/64 KiB/10 秒组装边界，Node 75 项测试及 Python 19 项测试通过；G0 实际生成并核验 7957-byte 审阅输入。framing 未接入 transport/Service，CBOR/MLS/D16 尚未实施；[新图](../testing/node-security-graph-review-package.md)真实硬资源/网络监督环境未验证，G1/G2 未执行。现有 manifest/lock/schema 不变，全部停止线保留。

2026-10-24 按所有者要求提交证明生命周期与安全接入基线（`a5ef086`），随后完成[身份绑定、撤销和 COSE profile](../security/node-identity-control-profile.md)及[依赖评审准备](../security/node-control-dependency-review.md)。所有者随后已接受 [ADR 0006 D11—D14](../adr/0006-node-identity-and-control-profile.md)：活动内逐对绑定、严格 Ed25519 控制 profile、自身退出权限与候选依赖方向。已核对标准/公开 API 及既有固定源码，尚未解析新图、安装或运行密码候选；完整 envelope/控制传播实现、许可证/R2 和独立复核仍未关闭。全部既有停止线不变。

2026-10-24 所有者进一步接受 [ADR 0005 D6—D10](../adr/0005-node-security-integration.md)，固化[安全接入设计](../security/node-security-integration.md)：正式 storage traits、两端 MLS 与独立证明、分层撤销、冷启动隔离及证明原 deadline。授权先推进不受停止线阻塞的 Node 自有持久边界与离线验证；实际候选、许可证/R2/Phase B、平台与网络操作未放行。同批已完成[证明生命周期开发](../testing/node-receipt-lifecycle.md)：T-C 意图与提交后转换、schema v3 显式迁移、原 deadline 与有界控制清理；63 项本机离线测试通过，真实签验与可信恢复仍未通过。

2026-10-24 所有者要求先完成 Node 服务架构与关键选型，再集中确认。已形成 [Node 服务设计提案](../architecture/node-service-design.md)：推荐 Rust 单进程、串行状态提交、SQLite 单库事务，并细化数据保护、时间/崩溃恢复、设备与手机接口、ARM64 部署及四批实施验收。所有者随后明确接受 D1—D5，形成 [ADR 0004](../adr/0004-node-service-foundation.md)，并授权提交文档后推进第一批服务/事务基础开发。首批 `node/` 服务与事务基础已实施，28 项本机离线测试通过，见[实施与验证记录](../testing/node-service-foundation.md)。生产运行入口仍明确拒绝；真实密码、平台解锁、网络与 ARM64 未接入，依赖安装及原安全/运行停止线不变。

同日首批实现提交为 `2936c6e`；随后完成[服务运行可靠性开发](../testing/node-service-reliability.md)，包括显式 schema v1→v2 迁移、中继返回证据容量预留、请求背压/停止协调、周期维护及事件批调度，47 项本机离线测试与静态/仓库检查通过。安全候选的[关键源码核对](../security/e2ee-sw-g2-decision-package.md#node-联合事务接入源码核对2026-10-24)确认现成 SQLite provider 不能直接参与 Node 联合事务，后续优先评审正式 storage trait 适配；真实安全、平台时钟、跨 boot 恢复和设备运行仍未通过。

2026-10-24 完成[三节点 BOM 纸面评审](../hardware/poc-purchase-list.md#三节点全新增-bom-评审2026-10-24)及[内部 ARM64 安全评审输入](../security/e2ee-sw-g2-decision-package.md#内部-linux-arm64-实验评审输入2026-10-24)。板卡、供电、存储、双接口、首次配置/恢复、测量及税运均已列项；已查两家境外商店的 2GB variant 缺货，国内完整人民币到手价仍未知，不能判定首轮或整套预算可行。固定 mls-rs manifest、target 和 94-package lock 已只读核对，未来产物/命令只是评审提案，专业评审与运行前置仍缺。使用量、断连容忍、重量/体积已有可调整规划值，并形成基于目标功率的能量敏感性计算；没有新实测，阶段与全部 STOP 不变。

同日公开资料核对已定位 b1 资产、配置/包表摘要、内核/U-Boot 和 RTL8153/板载 Ethernet 源码依据；镜像本体与设备未验证。所有者随后提供[淘宝查价表](../hardware/poc-purchase-list.md#所有者自行查价的搜索清单)：暂不另计赠送供电线，合计 2024 元；若仅赠送三条，第四条测量线另补。当前组合超原首轮上限 1024 元，按整套 3000 元核算名义余额 976 元，尚未覆盖后续硬件增量；暂缓功率计时为 1824 元。价格核算到此收口，继续软件开发与硬件接口准备，不再扩展询价。未采购，累计已支出仍为 0 元，预算上限未自动调整。

2026-10-18 已完成 RPC/宿主生命周期、初始化与容量评审、合成暂存收尾、执行合同纯校验、原生初始化和 P/N/S/W 生命周期的离线实现，最新实现提交为 `fa48743`。完整提交清单、代码/文档核对与[接下来的事项](2026-10-18-progress.md#接下来的事项)见当天回顾。宿主保守 897 秒/绝对 900 秒、guest 540 秒不变；真实 FD loader、来源/物理边界及运行授权仍缺，离线结果不证明 Linux/UTM 实测通过。

宿主决策与预算设计已提交为 `40520ae`。所有者选择 A：保留完整写入合同、优先已有 Linux 资源、暂不新增采购，并确认目前只有已记录的 Mac/UTM；[路线 A 评估](../testing/sw-g4-synthetic-i5-linux-host-assessment.md)判定暂无合格宿主。完整准备候选为 3608 MiB（424 + 3184），只适用于复用既有 Linux 基线、不重装/整盘迁移，尚未证明够用或获执行批准；正式 I5 768 MiB 不变。资源事实不变时不重复盘点或扩大实现，全部真实入口继续 STOP。

具体产物、决策责任和关闭标准统一放在[项目执行计划的近期工作包](project-execution-plan.md#近期工作包与决策顺序)。当前顺序为：

1. 开发优先：接续 ADR 0004—0007 及已完成的[证明生命周期与恢复拒绝验证](../testing/node-receipt-lifecycle.md)，按已接受 D15/D16 推进 Node 自有离线边界，准备正式 storage trait、可信平台与新图执行环境；实际功能接入仍须满足许可证/R2/Phase B 前置。所有者于 2026-10-24 决定自行按[搜索清单](../hardware/poc-purchase-list.md#所有者自行查价的搜索清单)在淘宝查价并反馈；Agent 已按反馈完成一次核算，停止扩展询价流程和重复价格检索。采购预算取舍不阻塞独立的软件设计、离线开发或硬件准备，但不放行既有安全/运行停止线；Mac 串口候选已有记录，仍未安装或连接设备。
2. 基于已整理的内部 Linux ARM64 产物评审表，冻结实际复制/留存范围、评审者与下一精确包；分别处置 `debug_tree` 固定源码正文/归属与 `r-efi` 的 MIT alternative。专业意见、新证据与执行合同仍待完成，保留全部现行 STOP 和 R2 条件。
3. 在已选择的 Node 身份与手机界面职责下收敛首次信任、撤销、物理与覆盖层路由边界，以及安全状态、应用事务、relay-clear proof 的候选映射。
4. I5 后续先满足[路线 A 宿主资源门](../testing/sw-g4-synthetic-i5-linux-host-assessment.md)，不把当前 Mac/UTM 改名或增加 guest 配额当作达标。资源条件变化后复核完整准备预算、真实输入与可信基座，冻结真实 FD loader、非 UTM 控制面和新版执行合同，再另行授权实现、原生环境验收及验签/APT。安装、冷构建、daemon/store 计费和正式 21 样本 I5-R 仍各有前置；不直接创建满额四盘后安装，不在域外先构建。V0 历史合同与 SW-G2 安全门不变。
5. 规划已有离线测试的 CI 接入与重复实验工具维护，形成全新增硬件及能量/体积/成本预算；I4 本轮未修改 CI。

## 关键风险

- **上海合规与预算可行性未关闭**：所有者查价小计 2024 元已超过原首轮上限，后续增量仍需覆盖；上海合法无线配置未关闭。MM8108 覆盖范围与国外支持地区不能推导上海合法配置，地区问题可能改变承载路线。
- **安全适配未证明**：依赖图通过不能证明离线建组、分区并发、撤销传播、崩溃原子性或中继清理证明可实现；mls-rs 完整第三方安全审计缺口仍在。
- **安全与交互机制未冻结**：Node/手机职责已选定，首次信任、撤销与 COSE 已有 D11—D14 已接受设计基线但未实现；真实事务与严格解析资源仍待证明。覆盖层 hop 不自动等于物理 hop，未来手机独立端点也不自动继承 Node 会话。
- **工程样机预算缺少实测**：Linux、双无线、常开中继和媒体共同影响电池、温度、体积与成本；开发板和 PHY 峰值不能替代产品数据。
- **验证和维护成本偏重**：`SW-EXP-001` 不能继承为产品协议；已有脚本重复和长文件需要在后续相关实施中收敛，当前 CI 仍只检查仓库卫生。
- **I5-R 运行前资源边界未关闭**：Go cache/temp、bootstrap 和 Docker builder/daemon 写入不能靠 artifact 采样约束；证据/诊断已有写前计费，容量探测与构建持续检查仅完成 helper 离线验证；实际接入、daemon/store 阶段预留及控制请求阻塞期间检查仍待实施。入口保持停止；五部分合计 768 MiB 已无域外开销余量，实际 guest 设备须在各域完整额度内为有硬上限的 backing/环境写入留空间。补充盘点确认系统盘 `/dev/vda4` 有约 2.584 GiB swap（采样 used=0），宿主配置仍为可写 QCOW2 系统盘；二者没有完整额度归属，不代表已发生超额写入，但容量可行性和真实拒绝证据仍待验证。

## 当前停止线

- 既有七个 VM 相关单次操作包及一次宿主观察均已结束并消费，不能继承为再次启动/重跑授权。最新一次正常关机，不消除此前强制停止后的系统盘完整性未检查这一缺口。I5 shell preflight/run 与直接 Go synthetic-run 均因缺少整批资源隔离而停止；不绕过停止检查、先在域外构建或自动调整共享 daemon。环境准备需另行精确授权，离线拒绝回归不构成资源修复完成或 I5-R 放行。
- 不采购 HaLow、不射频发射、不做量产 PCB；Node 基线按 ADR 0004、安全接入方向按 ADR 0005 接受；精确密码算法/实现、线格式、依赖完整图和硬件选择不自动冻结；`HW-G2` 前不采购，`HW-G3` 前不刷写或启动实体台架，无线操作另受 `RF-R*` 约束。
- OpenMLS 两个固定图的 Phase B 禁止；mls-rs D2 的 `PASS` 不授权 Phase B。许可证证据轨和 R2 未完成，`SW-G2` 未通过。
- 不自动第四次运行 R1、不扩展 selector、不补写或重判 R1c evidence、不改 gate/allowlist/advisory ignore、版本、provider、source 或 lockfile；新证据与策略变更须另行明确范围。
- `debug_tree` X/R 继续遵循[已冻结的精确澄清合同](../testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md)。公开账号和逐字消息须预审；发送、收集、回复接受性分别按合同处理，不自动监控、追问、编辑或关闭 Issue。
- `r-efi` 的 MIT alternative 须独立法律评审；R1d-L 不能替代 R2。R2 仅在新证据轨有效完整通过后，由所有者指定符合条件的复核者执行。
- 既有 `SW-V0`、审计 bundle、D2 和其他实验运行的单次授权不延续；不重跑、扩展 profile/schema、安装密码依赖或清理旧 evidence/cache。
- I1/I2/I3/I4 的有限离线实施均已完成；I4 只增加 offline-i3 variant 的有限 profile/evidence schema 2 与观测接口，不构成网络运行、完整矩阵、安全适配或外部写入授权；无射频证据与地区法规分别关门。

## 验证入口与结论边界

默认文档/仓库检查：

```bash
./scripts/check-repo.sh
git diff --check
```

已有 Go 工具的离线单元测试方法见[软件工作计划](d0-t0-p0-plan.md)。单元测试与仓库卫生通过只覆盖对应代码和文本，不代表 harness 的正式 Docker run 或产品验收。

探索性 `./scripts/run-t0-three-node.sh` 与正式 harness `./scripts/run-sw-v0-harness.sh run` 都不是默认重跑入口。前者的历史 `T0 PASS` 仅对应未加密合成探针，后者只验证 topology、fault hit、clock 与 evidence；均不证明 P0、HaLow、E2EE、距离、媒体、功耗或法规能力。
