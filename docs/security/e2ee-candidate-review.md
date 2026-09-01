# 端到端加密候选评审

资料核对日期：2026-09-01

## 用途与非目标

本文为 P0 选择成熟密码协议与实现库定义候选集和停止线，读者是安全、协议与平台实现者。当前结论是“候选待验证”，不是算法、库、版本、密码套件或生产技术栈冻结，也不授权安装依赖或写入真实密钥。

本评审属于[D0/P0 软件工作计划](../status/d0-t0-p0-plan.md)的 `SW-G2` 输入。[覆盖层消息交付语义](../protocol/message-delivery-semantics.md)已于 2026-08-24 通过 `SW-G1`，当前可以继续评审认证绑定、许可证、平台和状态安全；候选顺序、受限 spike、接受条件和授权边界已收敛到[`SW-G2` 决策包](e2ee-sw-g2-decision-package.md)。`SW-EXP-002` 与 `SW-EXP-004` Phase A 均已按各自授权执行并停止；任何后续库 spike、固定依赖修订、依赖安装或运行仍需精确方案与另行授权，`SW-G2` 未形成 ADR 前不把任何候选接入 `SW-V3/P0`。

本评审不自行拼装密码原语，不用 TLS/WPA3 代替应用层 E2EE，也不因 `SW-EXP-001` 合成明文通过而宣称 B 无法读取内容。

## P0 必需能力

- 支持接收端离线时建立或延续一对一会话，并处理丢包、重复和有界乱序；
- 提供消息机密性、完整性、发送者认证、forward secrecy 与 post-compromise security 的清楚边界；
- 身份验证、密钥变化、设备新增/撤销和会话重建必须有应用可表达的状态；
- 持久状态更新在断电、重启、回滚和并发发送下不能导致 nonce/key 重用或静默降级；
- Linux ARM64 是 P0 必需平台，Android/iOS 与未来多设备的接入成本必须可评估；
- 实现应持续维护、有明确许可证、安全公告与互操作/测试向量路径；
- 中继只获得版本、目标提示、寿命、优先级、大小和防环所需的最少元数据。

## 候选 A：Signal 协议实现

Signal 的 [PQXDH](https://signal.org/docs/specifications/pqxdh/)面向接收端离线的异步初始密钥协商，[Double Ratchet](https://signal.org/docs/specifications/doubleratchet/)覆盖逐消息密钥演进与有界乱序，[Sesame](https://signal.org/docs/specifications/sesame/)描述异步多设备会话管理。这一能力组合与 P0 一对一离线消息最直接匹配。

首选评估现成 [`libsignal`](https://github.com/signalapp/libsignal)，而不是照规范重写。当前核对基线为 `v0.101.0` / `b056faa`。当前阻塞项：

- 官方仓库主要公开 Java、Swift、TypeScript API，native artifact 列表未列 Debian/Linux ARM64，bridge 也不是稳定接口承诺；
- `libsignal` 当前采用 AGPL-3.0，必须先完成它与 RadishLink Source-Available License、分发方式和未来 App Store 渠道的许可证评审；
- 需要验证预密钥服务如何映射到无中心、可分区的 RadishLink 网络，以及 crash-safe session state、跳号上限和备份/恢复边界；
- 不把 Signal 产品行为、服务器或 sealed sender 等相邻能力自动算入 RadishLink。

结论：功能语义优先候选，许可证与受支持集成面未关闭前不得采用。

## 候选 B：IETF MLS 实现

[RFC 9420](https://www.rfc-editor.org/rfc/rfc9420.html)定义 MLS 协议；[RFC 9750](https://www.rfc-editor.org/rfc/rfc9750.html)说明其架构、Authentication Service 与 Delivery Service 边界，并明确两客户端组也可获得同类安全保证。它为未来群组和成员变更提供标准化方向，但不是完整即时通信协议，身份、投递、应用格式和运维策略仍由 RadishLink 定义。

两个实现库进入比较：

- [`OpenMLS`](https://github.com/openmls/openmls)：首轮基线 `openmls-v0.8.1` / `47dbede` 的 Phase A 是负向证据；稳定 `0.9.0` 已于 2026-08-25 发布，官方列出 Linux AArch64 构建与测试，但新依赖图、许可证、advisory 与存储迁移尚未经过 RadishLink 审计；
- [`mls-rs`](https://github.com/awslabs/mls-rs)：对照基线为 `0.56.0` / `8f1b43f`；Rust、Apache-2.0 OR MIT，提供 SQLite state provider、互操作测试与 FFI；上游把 AWS-LC provider 标为 stable，但明确说明尚未完成完整第三方安全审计。[静态门禁与执行授权包](../testing/sw-g2-mls-rs-spike-authorization.md)已形成，尚未执行。

当前阻塞项：

- `OpenMLS 0.8.1 + openmls_rust_crypto 0.5.1` 的固定图已在 Phase A 命中 advisory 与许可证停止线：实际检查图含 3 个未获准的 `MPL-2.0` `hpke-rs*` crate，并包含与 AArch64 直接相关的 `RUSTSEC-2026-0212`；该 prepared run 禁止进入 Phase B；
- `OpenMLS 0.9.0` 的稳定发布只解除 prerelease 停止线，不能证明旧 advisory、许可证和持久化风险已经关闭；[`SW-EXP-004` Phase A](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)首轮因原固定 SQLite 依赖冲突而 `STOP`；A3 对齐后生成的图只有 `rusqlite 0.37.0` / `libsqlite3-sys 0.35.0`。A5 后固定 bundle `20260830-112214-39636.GpERrj` 已复核 `PASS`；单元 D 生成 264-package 仓库 lockfile，source/feature 返回零且许可证门拒绝三个 `MPL-2.0`，但 `cargo-audit` 调用和 Phase A manifest finalizer 失败，整体 `INVALID`。A6 已离线修复，未来完整 Phase A 仍需新授权；官方安全策略只覆盖主 `openmls` crate，crypto provider 与 storage backend 必须独立审计；
- 两成员组的离线并发 commit、乱序 epoch、分区合并和设备恢复复杂度必须以三节点故障矩阵验证；
- Authentication Service、KeyPackage 发布/过期、Delivery Service 和联系人验证如何去中心化仍需设计；
- 必须固定 provider、cipher suite、credential、extension、持久化事务和敏感 debug feature 策略；
- 需继续核对审计、安全公告响应、移动平台 FFI、二进制体积与 ARM64 资源成本。

结论：MLS 仍是标准化与未来群组方向候选。OpenMLS 0.8.1 当前固定图是负向 Phase A 证据；OpenMLS 0.9.0 和 mls-rs 0.56.0 是两个待独立审计的稳定候选，而不是已通过修复或默认替代。P0 一对一复杂度、实现审计和许可证未关闭前不得采用。

## 不进入候选：自行组合原语

libsodium、RustCrypto、OpenSSL、Noise primitives 或单独 AEAD 都可以成为成熟协议实现的底层 provider，但它们本身不提供 RadishLink 所需的异步会话、身份变化、重放窗口、多设备和 crash-safe ratchet 状态。直接用这些原语拼接“类似 Signal/MLS”的方案属于自研密码协议，本轮明确拒绝。

## 冻结前验证门

1. 许可证：确认静态/动态链接、源码提供、修改公开、移动商店和第三方归属要求；
2. 维护：固定候选版本/commit，检查发布节奏、安全公告、受支持平台和淘汰策略；
3. 互操作：至少两个独立进程跨 Linux ARM64 重启，覆盖首次会话、离线接收、乱序、重复、丢失和密钥变化；
4. 持久化：在每一个 ratchet/epoch 状态写入点注入崩溃，证明没有 nonce/key 重用、错误确认或静默状态回退；
5. 安全负例：篡改密文与认证元数据、重放历史消息、伪造确认、替换身份和耗尽 skipped-key/epoch 队列均被拒绝；
6. 元数据：记录 B 可见字段与日志，证明正文、附件密钥和会话密钥不进入中继；
7. 平台：比较 Linux ARM64、Android、iOS 的 FFI、二进制大小、CPU/内存、备份与硬件密钥包装路径；
8. 独立评审：由非实现者复核威胁模型、测试证据、许可证和失败恢复后再形成 ADR。

## 当前建议

暂不二选一，也不在 `SW-V*` 引入密码依赖。当前按[`SW-G2` 决策包](e2ee-sw-g2-decision-package.md)保留 OpenMLS 0.8.1 Phase A 负向证据；[`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)已接受但未执行；[OpenMLS 0.9.0 Phase A](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)已确认依赖图可解析、固定 bundle 可复核，并取得许可证拒绝的 partial evidence，但单元 D 整体无效。A6 clean revision 与新的精确 L3 单元 E 授权形成前不得重跑。`libsignal v0.101.0` 在许可证和 Linux ARM64 集成面关闭前仍只做静态核对。只有候选通过精确依赖、advisory、许可证、命令、副作用和运行授权，才以同一套已接受 `SW-G3` A—B—C 故障矩阵比较安全、状态复杂度、平台和许可证，再由 ADR 冻结；在此之前项目继续使用“E2EE 候选/待验证”。
