# SW-G2 E2EE 与身份候选决策包

- 状态：Draft（OpenMLS 0.8.1 与 0.9.0 固定图均为 Phase A 负向 `STOP`；0.9.0 单元 E 已形成正式证据并禁止 Phase B；mls-rs A0/A1 已离线实施，候选未执行）
- 资料核对日期：2026-09-01
- 适用 gate：`SW-G2`
- 前置决策：`SW-G0/SW-G1` 已接受

## 目的与结论边界

本文把[端到端加密候选评审](e2ee-candidate-review.md)收敛为可执行、可停止、可比较的 `SW-G2` 决策包。它只确定候选验证顺序、共同问题、证据要求和授权边界，不选择生产实现，不冻结密码套件、credential、线格式、存储或 FFI，也不构成法律意见。

当前执行顺序为：

1. 保留 `OpenMLS 0.8.1` Phase A 作为固定候选图的负向证据，不进入 Phase B；
2. [`OpenMLS 0.9.0` 实施骨架与 Phase A 精确授权包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)已完成 A/A2/A3/A4/A5/C2/D/A6/E；A5 后 bundle `20260830-112214-39636.GpERrj` 已构建并复核 `PASS`。单元 E 对独立 264-package 固定图形成 schema 4/v4 正式 `STOP`：source/audit/feature 为零，独立 audit 未发现 vulnerability 但报告一个 unmaintained 信息项，当前许可证门拒绝三个 `MPL-2.0` crate；不重跑、不进入 Phase B，也不能继承 0.8.1 lockfile、cache 或授权；
3. 以[`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)和已接受的[精确实施与 Phase A 包](../testing/sw-g2-mls-rs-phase-a-authorization.md)对照许可证、advisory、存储、互操作与平台边界；A0/A1 已离线实施，单元 C 固定审计工具 bundle 已复核 `PASS`，单元 D 在固定 94-package 图的 transitive feature gate 正式 `STOP`，不重跑或进入 Phase B；
4. `libsignal v0.101.0` 只做许可证与受支持接口的静态核对，在许可证和 Linux ARM64 集成面关闭前不安装、不链接、不运行。

这个顺序不是采用结论。任一候选只有同时通过许可证、Linux ARM64、身份绑定、去中心化投递、崩溃安全、中继不可解密和独立复核，才可以进入 ADR；`SW-G2` 当前仍为未通过。

## 已核对候选基线

| 候选 | 固定评估基线 | 适配优势 | 当前停止线 | 当前定位 |
| --- | --- | --- | --- | --- |
| `OpenMLS` 旧基线 | `openmls-v0.8.1` / `47dbede` | MIT；Rust；可插拔 crypto/storage；MLS 两成员组与未来群组共用标准语义 | 固定图命中活跃 RustSec advisory，其中包含 AArch64 相关密码错误；`hpke-rs* 0.6.1` 的 `MPL-2.0` 未通过初始 allowlist | Phase A 负向基线；prepared run 禁止进入 Phase B |
| `OpenMLS` 稳定刷新 | `openmls 0.9.0`（2026-08-25） | 官方列出 Linux AArch64 构建与测试；provider/storage 版本线已更新 | 单元 E 的独立 audit 漏洞为零但有 unmaintained 信息项；当前许可证门正式拒绝三个 `MPL-2.0` crate；迁移与 0.8 行为差异仍无结论 | 当前固定图 Phase A 负向 `STOP`；不重跑，Phase B 禁止 |
| `mls-rs` | `0.56.0` | Apache-2.0 OR MIT；Rust；提供 storage traits、SQLite provider、互操作与 FFI/UniFFI 路径 | 官方未给出完整 Linux ARM64 支持矩阵，并明确没有完整第三方安全审计 | 对照候选，不是后备默认值 |
| `libsignal` | `v0.101.0` / `b056faa` | 一对一异步初始协商、逐消息 ratchet 与多设备会话语义最直接 | AGPL-3.0 与本仓库、分发和商店渠道的义务尚未独立确认；官方 native artifact 列表未列 Debian/Linux ARM64；公开 bridge 不是稳定 API 承诺 | 静态核对，未过停止线不进入运行 |

许可证栏只记录上游声明，不判断组合或分发是否合法。MIT/Apache-2.0 候选仍需核对完整依赖图、notice、归属和分发义务；AGPL 候选必须获得独立许可证评审或权利人书面许可，不以工程推断代替结论。

## 上游证据与适用限制

- [`libsignal` 官方仓库](https://github.com/signalapp/libsignal)说明公共 Java、Swift、TypeScript API 由 Rust 实现支撑；[`v0.101.0`](https://github.com/signalapp/libsignal/releases/tag/v0.101.0)是本轮固定的发布基线；[当前许可证](https://raw.githubusercontent.com/signalapp/libsignal/main/LICENSE)为 AGPL-3.0。官方 bridge 说明明确这些接口可能无通知变化，因此不能当作生产兼容承诺。
- [`OpenMLS` 官方仓库](https://github.com/openmls/openmls)与[`openmls-v0.8.1`](https://github.com/openmls/openmls/releases/tag/openmls-v0.8.1)是首轮基线。[持久化说明](https://book.openmls.tech/user_manual/persistence.html)要求持续保存组状态并保护敏感密钥；[安全公告页](https://github.com/openmls/openmls/security)显示历史持久化和 tag 验证问题，固定版本时仍需重查当前公告与传递依赖。
- 2026-08-28 静态刷新确认[`openmls 0.9.0`](https://docs.rs/crate/openmls/0.9.0)已于 2026-08-25 成为稳定发布，公开依赖面转向 `openmls_rust_crypto ^0.6.0`、`openmls_sqlite_storage ^0.3.0` 与 `openmls_traits ^0.6.0`。单元 E 随后以新 lockfile 与独立审计证明当前固定图未命中 vulnerability，但这不等于修复 0.8.1 的全部风险或通过安全审计；`RUSTSEC-2026-0173` unmaintained 信息项仍需登记，`hpke-rs* 0.7.0` 的 `MPL-2.0` 又触发当前许可证停止线。官方安全策略只覆盖主 `openmls` crate，crypto provider 与 storage backend 必须独立查询并保留“无公告不等于安全”的边界。
- [`mls-rs` 官方仓库](https://github.com/awslabs/mls-rs)和[`0.56.0` API 文档](https://docs.rs/mls-rs/latest/mls_rs/)是对照基线；官方说明尚无完整第三方安全审计。[SQLite provider](https://docs.rs/mls-rs-provider-sqlite/latest/mls_rs_provider_sqlite/)只证明存在接口，不证明与覆盖层状态满足同一原子提交边界。
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

1. 重跑 Phase 1 的 Linux ARM64、两成员离线、重启和关键负例最小子集。
2. 核对 SQLite provider 的事务与敏感删除语义、FFI/UniFFI 构建面和移动端限制。
3. 在固定 cipher suite、credential 和 extension 前提下，尝试与 OpenMLS 交换标准 MLS 消息；无法互操作时保留具体边界，不降低判定条件。
4. 将“未完成完整第三方安全审计”作为独立风险，不以测试通过消除。

### Phase 3：决策与 ADR

1. 以同一场景矩阵比较安全性质、状态复杂度、平台、许可证、维护与未来群组路径。
2. 非实现者复核证据、失败与许可证结论。
3. 只有证据足以选择时才起草 ADR；不能选择时记录缺口和停止条件，不创建伪 Accepted 决策。

## 运行授权包要求

本包不授权下载、安装、构建或运行。首轮 OpenMLS 的精确依赖、命令、外部影响、证据、清理和分段授权已形成并执行[`SW-EXP-002` 执行授权包](../testing/sw-g2-openmls-spike-authorization.md)；Phase A 的负向结果已阻断 Phase B。[`OpenMLS 0.9.0` 包](../testing/sw-g2-openmls-0.9-spike-authorization.md)的单元 E 也已形成正式负向 Phase A 并阻断 Phase B，不再申请同基线重跑。[`mls-rs 0.56.0` 静态包](../testing/sw-g2-mls-rs-spike-authorization.md)与[精确包](../testing/sw-g2-mls-rs-phase-a-authorization.md)均已接受并按分段授权执行到单元 D；当前 fixed graph 已在 feature gate `STOP`。进入任何修订 spike 前必须重新满足：

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

当前已完成决策包、上游证据收敛和两份 OpenMLS 固定图 Phase A。0.8.1 最终 run `20260824-215104-90006` 生成 229-package lockfile，来源检查通过；许可证检查拒绝 3 个 `MPL-2.0` `hpke-rs*` crate，`cargo-deny` 命中 3 个活跃 RustSec advisory，其中 `RUSTSEC-2026-0212` 直接涉及 AArch64，`cargo-audit` 共报告 6 个 vulnerability。0.9.0 单元 E run `20260901-123158-75973.3gVtsH` 对 264-package 固定图形成有效 schema 4/v4 证据；source/audit/feature 为零，独立 audit 漏洞为零并报告 `RUSTSEC-2026-0173` unmaintained 信息项，当前许可证门拒绝 3 个 `MPL-2.0` crate。两轮均为正式 `STOP`，Phase B 禁止。`mls-rs 0.56.0` A0/A1 已离线实施，但尚无候选 lockfile、运行实证或 ADR；`SW-G2` 保持未通过。
