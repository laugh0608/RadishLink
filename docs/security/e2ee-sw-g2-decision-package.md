# SW-G2 E2EE 与身份候选决策包

- 状态：Draft（OpenMLS 0.8.1 与 0.9.0 固定图均为 Phase A 负向 `STOP`；mls-rs D 保留历史 `STOP`，D2 对同一固定图正式 `PASS`；人工许可证/NOTICE 与非实现者 evidence 复核未完成，Phase B 禁止）
- 固定候选上游资料核对日期：2026-09-02；项目决策同步日期：2026-10-09（不重跑或升级固定图）
- 适用 gate：`SW-G2`
- 前置决策：`SW-G0/SW-G1` 已接受

## 目的与结论边界

本文把[端到端加密候选评审](e2ee-candidate-review.md)收敛为可执行、可停止、可比较的 `SW-G2` 决策包。它只确定候选验证顺序、共同问题、证据要求和授权边界，不选择生产实现，不冻结密码套件、credential、线格式、存储或 FFI，也不构成法律意见。

历史候选执行顺序与结果如下；2026-10-09 所有者已接受后续优先推进固定 `mls-rs 0.56.0` 的评审方向，具体近期输入见[本次选择](#2026-10-09-所有者选择与近期评审输入)。该顺位不恢复 Phase B 或改变任何固定图：

1. 保留 `OpenMLS 0.8.1` Phase A 作为固定候选图的负向证据，不进入 Phase B；
2. [`OpenMLS 0.9.0` 实施骨架与 Phase A 精确授权包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)已完成 A/A2/A3/A4/A5/C2/D/A6/E；A5 后 bundle `20260830-112214-39636.GpERrj` 已构建并复核 `PASS`。单元 E 对独立 264-package 固定图形成 schema 4/v4 正式 `STOP`：source/audit/feature 为零，独立 audit 未发现 vulnerability 但报告一个 unmaintained 信息项，当前许可证门拒绝三个 `MPL-2.0` crate；不重跑、不进入 Phase B，也不能继承 0.8.1 lockfile、cache 或授权；
3. 以[`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)和已接受的[精确实施与 Phase A 包](../testing/sw-g2-mls-rs-phase-a-authorization.md)对照许可证、advisory、存储、互操作与平台边界；A0/A1/A2/A3 已离线实施并形成 clean revision，单元 C 固定审计工具 bundle 已复核 `PASS`，单元 D 在固定 94-package 图的旧 transitive feature gate 形成正式历史 `STOP`。D2 随后只读 seed 同一 final lock、拒绝重新解析和旧 mutable cache，形成正式 Phase A `PASS` 并提升同一仓库 lockfile；[许可证/NOTICE 与非实现者复核包](../testing/sw-g2-mls-rs-license-notice-review.md)已完成 R1c-R 固定对象补证和 R1d-L 独立处置评审，分别保持 `STOP/license-evidence` 与 `STOP/license-disposition`；debug_tree 澄清设计/helper 已离线形成但未发送，R2 前置不满足，Phase B 禁止；
4. `libsignal v0.101.0` 只做许可证与受支持接口的静态核对，在许可证和 Linux ARM64 集成面关闭前不安装、不链接、不运行。

这个顺序不是采用结论。任一候选只有同时通过许可证、Linux ARM64、身份绑定、去中心化投递、崩溃安全、中继不可解密和独立复核，才可以进入 ADR；`SW-G2` 当前仍为未通过。

## 已核对候选基线

| 候选 | 固定评估基线 | 适配优势 | 当前停止线 | 当前定位 |
| --- | --- | --- | --- | --- |
| `OpenMLS` 旧基线 | `openmls-v0.8.1` / `47dbede` | MIT；Rust；可插拔 crypto/storage；MLS 两成员组与未来群组共用标准语义 | 固定图命中活跃 RustSec advisory，其中包含 AArch64 相关密码错误；`hpke-rs* 0.6.1` 的 `MPL-2.0` 未通过初始 allowlist | Phase A 负向基线；prepared run 禁止进入 Phase B |
| `OpenMLS` 稳定刷新 | `openmls 0.9.0`（2026-08-25） | 官方列出 Linux AArch64 构建与测试；provider/storage 版本线已更新 | 单元 E 的独立 audit 漏洞为零但有 unmaintained 信息项；当前许可证门正式拒绝三个 `MPL-2.0` crate；迁移与 0.8 行为差异仍无结论 | 当前固定图 Phase A 负向 `STOP`；不重跑，Phase B 禁止 |
| `mls-rs` | `0.56.0` | Apache-2.0 OR MIT；Rust；提供 storage traits、SQLite provider、互操作与 FFI/UniFFI 路径 | D2 固定图 Phase A 已 `PASS`；11 个 crate archive 的随包证据不足以覆盖全部声明正文及适用归属，人工分发义务与非实现者复核未关闭；完整第三方审计、X.509 支持面、资源边界和 Linux ARM64 实证仍未关闭 | 对照候选，不是后备默认值；Phase B 禁止 |
| `libsignal` | `v0.101.0` / `b056faa` | 一对一异步初始协商、逐消息 ratchet 与多设备会话语义最直接 | AGPL-3.0 与本仓库、分发和商店渠道的义务尚未独立确认；官方 native artifact 列表未列 Debian/Linux ARM64；公开 bridge 不是稳定 API 承诺 | 静态核对，未过停止线不进入运行 |

许可证栏只记录上游声明，不判断组合或分发是否合法。MIT/Apache-2.0 候选仍需核对完整依赖图、notice、归属和分发义务；AGPL 候选必须获得独立许可证评审或权利人书面许可，不以工程推断代替结论。

## 上游证据与适用限制

- [`libsignal` 官方仓库](https://github.com/signalapp/libsignal)说明公共 Java、Swift、TypeScript API 由 Rust 实现支撑；[`v0.101.0`](https://github.com/signalapp/libsignal/releases/tag/v0.101.0)是本轮固定的发布基线；[当前许可证](https://raw.githubusercontent.com/signalapp/libsignal/main/LICENSE)为 AGPL-3.0。官方 bridge 说明明确这些接口可能无通知变化，因此不能当作生产兼容承诺。
- [`OpenMLS` 官方仓库](https://github.com/openmls/openmls)与[`openmls-v0.8.1`](https://github.com/openmls/openmls/releases/tag/openmls-v0.8.1)是首轮基线。[持久化说明](https://book.openmls.tech/user_manual/persistence.html)要求持续保存组状态并保护敏感密钥；[安全公告页](https://github.com/openmls/openmls/security)显示历史持久化和 tag 验证问题，固定版本时仍需重查当前公告与传递依赖。
- 2026-08-28 静态刷新确认[`openmls 0.9.0`](https://docs.rs/crate/openmls/0.9.0)已于 2026-08-25 成为稳定发布，公开依赖面转向 `openmls_rust_crypto ^0.6.0`、`openmls_sqlite_storage ^0.3.0` 与 `openmls_traits ^0.6.0`。单元 E 随后以新 lockfile 与独立审计证明当前固定图未命中 vulnerability，但这不等于修复 0.8.1 的全部风险或通过安全审计；`RUSTSEC-2026-0173` unmaintained 信息项仍需登记，`hpke-rs* 0.7.0` 的 `MPL-2.0` 又触发当前许可证停止线。官方安全策略只覆盖主 `openmls` crate，crypto provider 与 storage backend 必须独立查询并保留“无公告不等于安全”的边界。
- [`mls-rs` 官方仓库](https://github.com/awslabs/mls-rs)和[`0.56.0` API 文档](https://docs.rs/mls-rs/latest/mls_rs/)是对照基线；官方说明尚无完整第三方安全审计。[SQLite provider](https://docs.rs/mls-rs-provider-sqlite/latest/mls_rs_provider_sqlite/)只证明存在接口，不证明与覆盖层状态满足同一原子提交边界。D 保留图进一步证明 core 的 `rfc_compliant` 只展开为 `x509`，`fast_serialize` 只展开为 codec `preallocate`；接受这两个固定 alias 不等于接受顶层聚合 feature、X.509 credential 或无界预分配，也不构成 RFC 9420 互操作结论。D2 只证明固定图在记录的 RustSec revision 和门禁下通过 Phase A；工具 license metadata 结果不能替代上游正文、NOTICE、归属与目标分发复核。
- [RFC 9420](https://www.rfc-editor.org/rfc/rfc9420.html)定义 MLS；[RFC 9750](https://www.rfc-editor.org/rfc/rfc9750.html)允许两成员组和去中心化 Delivery Service，但也把身份绑定、投递可用性、并发 commit 与分区协调留给应用和服务架构。标准可用不等于 RadishLink 映射已经安全。

以上证据只覆盖所列版本、页面和核对日期；上游 `main`、候选发布或后续许可证变化不会自动更新本结论。

## RadishLink 身份与投递映射候选

### Authentication Service

- 每台设备持有稳定设备身份；协议 credential 与设备身份的绑定由成熟候选库支持的机制完成，不自造签名格式或密钥派生。
- 首次联系人验证采用面对面二维码或短认证串，至少覆盖双方稳定身份和当前 credential 指纹；界面必须区分未验证、已验证、密钥变化和已撤销。
- spike 可用合成身份和 `BasicCredential` 验证协议流程，但必须把完整公钥指纹放入带外验证；它不能直接成为生产身份方案。
- 无中心身份服务器不等于没有 Authentication Service。P0 将 AS 职责放到设备和用户的带外验证流程，设备新增、撤销与分区合并仍需单独定义并测试。

### Delivery Service 与 KeyPackage

- A/C 的覆盖层共同承担 MLS Delivery Service 职责，B 只缓存和转发不透明的 `KeyPackage`、`Welcome`、`Commit` 与应用密文，不获得群组、消息或附件密钥。
- `KeyPackage` 必须有不透明对象 ID、有效期、单次或有界使用规则、每来源配额和消费记录；私有部分只保留在创建端安全存储中。
- A 与 C 不直连时，B 可以转发初始材料，但恶意或过期 B 可能丢弃、回滚或重复提供 `KeyPackage`。spike 必须覆盖耗尽、重复消费、过期和分区后重用。
- 两成员 MLS 组在标准上成立，但双方同时创建组、并发 commit、旧 epoch 应用消息和分区 fork 必须有确定的拒绝或协调策略，不能依赖“最后到达者成功”。

### 与 SW-G1 交付证据的绑定

- relay custody 只证明下一跳已认证接纳信封，是逐跳状态，不是目的端 E2EE 交付。
- 目的端 delivery evidence 必须同时满足：A 能验证它来自目标端 E2EE 会话，B 能在不知道正文和 read 状态时验证删除条件。
- spike 评估一份 E2EE 目的端 receipt 与一份可分离的 relay-clear proof：后者绑定覆盖层消息引用、密文认证引用、receipt 类型和协议版本，只暴露删除所需最小字段；read receipt 始终留在 E2EE 内。
- relay-clear proof 的 credential、签名或 MAC 构造必须来自最终选定的成熟身份/E2EE 实现。本包只定义要证明的性质，不批准自建密码构造。
- B 只有在 proof 验证和本地持久提交都成功后才能删除副本；A/C 对重复 proof 幂等处理，未知版本或身份变化一律拒绝并保留可诊断原因。

## 崩溃安全与状态原子性

候选库自己的 storage provider 不等于应用状态已经安全。spike 必须证明以下状态能形成明确的提交顺序或同一事务边界：

- origin 的 ratchet/epoch 推进与待发送密文入队；
- destination 的消息验证、去重、ratchet/epoch 推进与 delivery evidence 生成；
- relay 的 custody、队列、配额、proof 验证与删除；
- `KeyPackage` 私有部分、发布记录、消费记录与过期清理。

在每个提交点前后注入崩溃并重启。通过条件是：不重复使用 key/nonce，不在安全状态落盘前发送成功证据，不因回滚接受重放，不把存储失败降级为成功，也不让 B 通过日志或错误上下文获得正文、密钥或完整联系人身份。

若候选库的状态更新无法与覆盖层存储安全协调，应记录为候选不适配；不得用跨库补偿队列、默认成功或静默重试掩盖原子性缺口。

## 受限 spike 设计

### Phase 0：只读与许可证门

1. 固定版本、commit、源码归档校验值和 lockfile；枚举直接与传递依赖许可证、notice 和安全公告。
2. 对目标链接、修改、分发、Android/iOS 商店和服务端部署方式做独立许可证复核。
3. 核对 Linux ARM64、Android、iOS 的官方支持面、FFI 稳定性和弃用策略。
4. `libsignal` 若未同时获得许可证和 Linux ARM64 接口结论，在本 phase 停止。

### Phase 1：OpenMLS 稳定刷新与最小实证

`OpenMLS 0.8.1 + openmls_rust_crypto 0.5.1` 已在 Phase A 命中 advisory 和许可证停止线，以下场景不得在该 prepared run 上执行。`OpenMLS 0.9.0` 单元 E 也已因当前许可证门正式 `STOP`，以下场景同样不得执行；恢复本 phase 必须先出现新的产品/许可证决策与独立精确包，不能把重跑、allowlist 例外或版本替换当作既有授权的延续：

1. 在 Linux ARM64 构建并运行两个独立进程，保存工具链、目标 triple、版本与二进制证据。
2. 用 A—B—C 不直连拓扑验证两成员组、离线 `KeyPackage`、`Welcome`、应用密文和重启恢复。
3. 覆盖丢失、重复、乱序、过期、身份变化、同时建组、并发 commit、旧 epoch 和分区 fork。
4. 在 storage provider 与覆盖层提交边界注入崩溃，核对 key/nonce、去重和 delivery evidence 不变量。
5. 记录 B 的可见字段、落盘数据和日志，验证其不能解密内容，并评估 relay-clear proof 映射。

### Phase 2：mls-rs 0.56.0 对照

单元 D 的正式历史 `STOP` 保留；D2 已只读消费 D final lock，在不重新解析传递版本或复用旧 mutable cache 的条件下对同一固定依赖图形成有效 Phase A `PASS`。人工许可证/NOTICE 与非实现者 evidence 复核仍未完成，以下场景继续禁止；D2 `PASS` 本身不构成 Phase B 授权。

1. 重跑 Phase 1 的 Linux ARM64、两成员离线、重启和关键负例最小子集。
2. 核对 SQLite provider 的事务与敏感删除语义、FFI/UniFFI 构建面和移动端限制。
3. 在固定 cipher suite、credential 和 extension 前提下，尝试与 OpenMLS 交换标准 MLS 消息；无法互操作时保留具体边界，不降低判定条件。
4. 将“未完成完整第三方安全审计”作为独立风险，不以测试通过消除。

### Phase 3：决策与 ADR

1. 以同一场景矩阵比较安全性质、状态复杂度、平台、许可证、维护与未来群组路径。
2. 非实现者复核证据、失败与许可证结论。
3. 只有证据足以选择时才起草 ADR；不能选择时记录缺口和停止条件，不创建伪 Accepted 决策。

## 运行授权包要求

本包不授权下载、安装、构建或运行。首轮 OpenMLS 的精确依赖、命令、外部影响、证据、清理和分段授权已形成并执行[`SW-EXP-002` 执行授权包](../testing/sw-g2-openmls-spike-authorization.md)；Phase A 的负向结果已阻断 Phase B。[`OpenMLS 0.9.0` 包](../testing/sw-g2-openmls-0.9-spike-authorization.md)的单元 E 也已形成正式负向 Phase A 并阻断 Phase B，不再申请同基线重跑。[`mls-rs 0.56.0` 静态包](../testing/sw-g2-mls-rs-spike-authorization.md)与[精确包](../testing/sw-g2-mls-rs-phase-a-authorization.md)均已接受并按分段授权执行到 D2；历史 fixed graph 的旧 feature-gate `STOP` 保留，D2 对同一固定图形成正式 Phase A `PASS`。[许可证/NOTICE 与非实现者复核包](../testing/sw-g2-mls-rs-license-notice-review.md)已记录 R1/R1b 传输负向、R1c-R 实质证据缺口和 R1d-L 处置 STOP；debug_tree 的 R1d-U-P/I 已完成，X/R 尚未执行。当前状态见[项目状态](../status/current.md)。任何后续上游操作、R2 独立复核、D2 重跑、Phase B 或修订 spike 均须先关闭各自前置并明确：

- 精确依赖版本、commit、校验值、来源、许可证和 lockfile 变更；
- 精确命令、目标平台、网络访问、临时目录、预计时长和最大资源占用；
- 只使用合成身份与临时密钥，不读取真实联系人、设备凭据或用户数据；
- 产物位置、后台进程、容器/VM/系统状态、副作用、清理与回滚方法；
- 逐项场景、期望结果、证据格式、停止条件和失败保留方式。

依赖安装、VM/容器、系统网络、真实设备或外部状态仍按各自 L3 边界取得当前任务授权。

## SW-G2 接受条件

只有以下条件全部满足，`SW-G2` 才可接受：

1. 选定实现及传递依赖的许可证、notice、分发和目标渠道结论可复核；
2. 版本、commit、校验值、维护状态和安全公告已固定；
3. Linux ARM64 真实构建/运行证据通过，移动 FFI 风险已登记；
4. 离线首次联系、身份验证、密钥变化、设备新增/撤销和恢复语义明确；
5. 去中心化 AS/DS、`KeyPackage` 生命周期和分区并发行为有明确策略；
6. crash-safe 密码状态与 `SW-G1` 队列、去重、custody、delivery evidence 原子边界通过；
7. B 不可解密且只获得最少元数据的正例、负例和日志证据通过；
8. 篡改、重放、乱序、耗尽、旧 epoch、fork 与失败恢复结果可复现；
9. 独立复核完成并以 Accepted ADR 冻结选择、限制和迁移边界。

当前已完成决策包、上游证据收敛和两份 OpenMLS 固定图 Phase A。0.8.1 最终 run `20260824-215104-90006` 生成 229-package lockfile，来源检查通过；许可证检查拒绝 3 个 `MPL-2.0` `hpke-rs*` crate，`cargo-deny` 命中 3 个活跃 RustSec advisory，其中 `RUSTSEC-2026-0212` 直接涉及 AArch64，`cargo-audit` 共报告 6 个 vulnerability。0.9.0 单元 E run `20260901-123158-75973.3gVtsH` 对 264-package 固定图形成有效 schema 4/v4 证据；source/audit/feature 为零，独立 audit 漏洞为零并报告 `RUSTSEC-2026-0173` unmaintained 信息项，当前许可证门拒绝 3 个 `MPL-2.0` crate。两轮均为正式 `STOP`，Phase B 禁止。`mls-rs 0.56.0` 单元 D 的 94-package 图 source/audit/deny 为零、旧 feature gate 为一，正式历史 `STOP` 保留；D2 run `20260902-130415-49997.8P5Td6` 对同一图形成 schema 2/v2 正式 `PASS`，四门全零且仓库 lockfile 与 seed/evidence 摘要一致。11 个 crate archive 的随包证据不足以覆盖全部声明正文及适用归属，R1c-R 已补齐 9 个 mls-rs package 的 Apache-2.0/MIT 正文，debug_tree 和 r-efi 的固定对象处置仍未关闭，R1d-L 不是 R2；这不是无许可证判定，也不授权新的联网补证或 Phase B。当前没有候选运行实证或 ADR，`SW-G2` 保持未通过。

## 候选适配的优先证明项

依赖检查通过后，最早的受限场景应优先回答下列可实现性问题，再扩展媒体、群组或跨平台集成。此处是后续方案的设计输入，不恢复当前被禁止的 Phase B。

| 问题 | 必须提交的设计 / 证据 | 不接受的替代 |
| --- | --- | --- |
| 密码与应用事务 | 候选库具体 API、提交点、失败传播，以及 outbox/inbox、去重、receipt 与安全状态的同一原子边界或等价 crash-safe 协调 | 仅声称 SQLite provider 已提供事务 |
| 离线并发 | 同时建组、并发 Commit、旧 epoch、KeyPackage 重用与分区重合后的确定拒绝/重建路径 | 最后到达者成功、静默丢弃失败 |
| relay-clear proof | 固定成熟机制、实际库支持、验证者凭据来源、与消息引用的认证绑定及元数据暴露评审 | 因规范提出了性质，就假定 Signal/MLS 库提供该功能；自行拼装新握手或密钥协议 |
| 端点撤销与恢复 | Node/手机角色、丢失后的会话处理、分区期间撤销未知状态和重新验证入口 | 宣称离线撤销可立即对所有节点生效 |

RFC 9750 的 [AS/DS 架构与投递说明](https://www.rfc-editor.org/rfc/rfc9750.html)允许去中心化实现，但投递一致性和身份映射仍由应用明确。库支持两成员组不是 RadishLink 离线闭环的通过证据。

无法找到被接受的 proof 映射或事务边界时，应给出候选不适配及重新评审 SW-G1/SW-G2 的影响，不在实现中绕过既有删除或确认不变量。

## 按实际分发范围评审许可证（政策修订候选）

提出日期：2026-09-05；2026-10-09 所有者接受按实际产物与渠道分阶段评审的方向。专业适用性意见及改变执行 gate 的精确合同仍未完成，不改变当前 allowlist、R1/R2 合同或任何历史 STOP。

应分别记录“权利或义务问题”“材料不足”“项目政策未接受”“适配/安全问题”，避免用一个 STOP 原因代替全部结论。Mozilla 的 [MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)说明其文件级 copyleft 与 Larger Work 的关系；这支持按具体分发物评审，不构成 RadishLink 的许可证兼容结论或允许直接采用的授权。

| 渠道 | 待冻结输入 | 评审重点 |
| --- | --- | --- |
| 内部 Linux 受限实验 | 操作者与接收者、target、实际编译 feature、依赖与工具来源、是否外传 | 本轮复制/构建/使用权与证据范围；不能仅凭“内部”免除许可核对 |
| 提供给他人的测试镜像 | 接收范围、镜像内容、修改状态、SBOM | 实际交付组件、正文/归属、源码提供与通知义务 |
| 正式 Linux 设备镜像 | 产品 target、rootfs/固件/应用、静态或动态链接、更新包 | 整个分发物的义务、材料位置和可重复生成方式 |
| Android / iOS | 分别固定构建 target、FFI、静态库、应用包与渠道条款 | 不把 Linux 结论外推为移动分发许可 |
| 服务端 | 仅运行服务还是交付镜像/二进制、修改与接收方 | 按具体许可证核对网络使用和分发触发条件 |
| 源码 / vendor / cache 包 | 包含的实际源码、构建工具、归档与 third-party 材料 | 不以最终二进制未链接为由忽略随包材料 |

所有者与适当专业评审者需明确：哪些义务属于当前实验前置，哪些需要在未来相应渠道启用前关闭；未启用渠道不得被记成 PASS 或无需审查。只有形成被接受的政策修订和新的精确合同后，才能改变未来 gate。debug_tree 的固定源码授权/归属缺口与 r-efi 的 MIT alternative 判断继续分案处理；当前 R2 和 Phase B 停止线保持。

## 2026-09-26 许可证评审输入与责任

本节保留 2026-09-26 当时的待填输入，没有形成新法律意见、上游证据或渠道 PASS；不重判 [R1d-L](../testing/sw-g2-mls-rs-license-disposition-review.md)。当时产品范围为中国上海熟人小队文字/语音优先、整套预算 2000 元；预算与使用/接收范围已由下节 2026-10-09 选择更新，其他未知项仍待补齐。

### 2026-09-26 建议先评审的渠道

先以“内部 Linux 受限实验”为候选近期渠道，所有者仍须确认实际操作者/接收者和是否外传。其他渠道保留原 STOP/适用性状态，不为尚无产物的渠道预填结论。

| 必填输入 | 已有依据 | 本轮缺口 |
| --- | --- | --- |
| package 与固定对象 | 使用 D2 固定 94-package 图及 R1c-R/R1d-L 的 package/version/checksum/commit 引用 | 不更新版本、feature、source 或 lock；任何变化另案评审 |
| 目标与产物 | 既有候选验证目标为 Linux ARM64，Phase A prepare-only 已记录 | 精确 target triple、最终 feature、artifact 类型及构建命令待下一精确包固定；不能把评审环境视为产品镜像 |
| 使用/接收范围 | 首期使用地区按中国上海记录 | 操作者、接收者、是否仅本机、是否向他人交付，均待所有者指定 |
| 包内实际内容 | 历史处置区分最终 binary 与 source/vendor/cache | 下轮是否携带源码、归档、cache、容器或修改，待明确；未知不按排除处理 |
| 第三方材料入口 | 必须可追溯固定对象及实际复制内容 | 正文/归属/NOTICE 的位置、生成与校验入口待渠道和处置接受后设计 |
| 责任与时限 | 工程证据、法律判断、所有者决定分别记录 | 专业评审者、工程复核者、投入上限与复核日期未指定；不自动派单或发送材料 |

### 两包分流与关闭动作

| 对象 | 下一个具体动作 | 责任及关闭标准 |
| --- | --- | --- |
| `debug_tree 0.4.0` | 按[冻结澄清合同](../testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md)预审实际账号、逐字消息与公开对象；当前不发送 | 所有者确认外部动作；有效回复须绑定固定历史源码和完整适用 notice/holder，再按新 evidence 轨复核；无有效回复按合同评估 R1d-V |
| `r-efi 6.0.0` | 将固定 `AUTHORS` 材料与实际渠道输入交独立合格法律评审者，询问是否接受 MIT alternative 及保留内容 | 人员尚未指定；明确接受后才设计 R1d-G/R1d-D，不接受则按原处置转 R1d-E 或其他已定义分支 |
| R2 | 保持阻断 | 新证据/合同轨完整通过后，由所有者指定符合条件的非实现者；本轮设计者不自行宣布 R2 完成 |

本轮完成标准是待填输入与两条处置路线可直接审阅；当前没有发送 Issue、联系专业方、收集回复、修改 gate 或启动 Phase B。若下轮仍无接收范围或合格评审者，继续推进已授权的合成设计；不以补写清单代替许可材料和判断。

## 2026-10-09 所有者选择与近期评审输入

所有者接受以下方向；这是范围与优先级决定，不是独立法律意见、安全审核通过或实现库采用 ADR。整套设备预算按[产品定义](../product-definition.md#当前范围细化2026-10-09)更新；I5 的 768 MiB 资源合同独立且不变。

| 项目 | 已接受的方向 | 仍须关闭的输入 / 证据 |
| --- | --- | --- |
| 近期候选 | 优先推进固定 `mls-rs 0.56.0`、D2 同一 94-package 图；不自动升级、不冻结生产实现 | 许可证新证据、R2、Linux ARM64 适配、完整第三方安全审计风险及正式 SW-G2 证明 |
| 身份职责 | Node 持有身份、会话和受保护历史；手机为可断开的已授权界面，长期私钥不进入浏览器 | 首次信任、界面授权/撤销、密码存储、事务及 proof 机制；[身份专题](../mobile/companion-app.md#首期身份与阶段选择2026-10-09) |
| 当前使用/接收范围 | 项目所有者控制的 Linux ARM64 受限实验，只用合成数据，暂不向其他人交付测试镜像或安装包 | 精确操作者、目标 triple、feature、构建命令、artifact 和是否含 source/vendor/cache；准备包不得将尚未确认的内容视为已排除 |
| 未来渠道 | 给他人的测试镜像、正式设备、移动应用、服务端和源码包分别在启用前评审 | 当前均未通过；专业评审与新合同明确阶段义务后才可调整执行 gate，不能以“内部实验”免除许可核对 |
| `debug_tree 0.4.0` | 优先按已冻结方案取得适用于固定历史源码的完整 MIT 正文及归属 | 公开账号与逐字消息预审、精确发送授权和有效回复；无法闭合时按原合同转 R1d-V-P 评估升级、移除或替换，不自行补 MIT 模板 |
| `r-efi 6.0.0` | 优先提交“选择 MIT alternative 并保留完整 AUTHORS”的独立合格法律评审，同时核对目标产物与随包源码 | 评审者及实际产物输入尚未齐备；接受后才设计 R1d-G/R1d-D，不以 binary 未链接忽略 source/vendor/cache 义务 |
| OpenMLS / MPL | 保留按实际组合与分发物重新评审的备选方向 | 不把 MPL 名称直接判为整个产品必须开放源码；仍无 RadishLink 适用性结论，不改 allowlist 或历史 STOP |

来源复核：2026-10-09 查看 [mls-rs 上游安全说明](https://github.com/awslabs/mls-rs#security-notice)，仍声明未完成完整第三方安全审计；[r-efi v6.0.0](https://github.com/r-efi/r-efi/tree/v6.0.0)声明 `MIT OR Apache-2.0 OR LGPL-2.1-or-later` 并指向 AUTHORS；[Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)解释文件级义务与 Larger Work。这些网页核对不是新的 R1 evidence，不替代固定归档、适用性意见或 R2。

后续安全适配的首批验收仍按本包既有要求：A/C 通信的纯中继 B 不可解密；密码状态、队列与送达确认在崩溃恢复时一致；重放、身份变化、分区并发、撤销及 relay-clear proof 有明确成熟机制。B 在其他会话作为合法端点的角色不与纯中继负例混同。手机离开不退出 Node 会话，未来独立手机身份不能靠复制 Node 私钥或静默同步历史实现。

近期可交接材料为固定对象证据索引、当前使用范围、两包各自的待判断问题和已冻结澄清全文；专业评审者、公开发送账号及精确执行包尚待指定。本次未联系上游或专业方、未安装依赖、未变更 lockfile/gate、未进入 R2/Phase B；不设自动监控或虚构回复期限。
