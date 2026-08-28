# SW-G2 mls-rs 0.56.0 受限 spike 静态门禁与执行授权包

- 状态：Accepted（静态门禁，2026-08-28；未实施、未下载、未构建、未运行）
- 资料核对日期：2026-08-28
- 计划证据编号：`SW-EXP-003`
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文为 `mls-rs 0.56.0` 对照候选固定首轮依赖、provider、feature、许可证与 advisory 门、Linux ARM64 边界、证据和停止线。它用于在任何依赖下载或代码实施前接受或拒绝运行方案，不构成执行授权，也不选择生产 E2EE 实现、密码套件、credential、FFI、数据库或线格式。

`OpenMLS 0.8.1` 的负向 Phase A 证据不能自动证明 `mls-rs` 安全，也不能把本包变成默认后备路线。2026-08-25 发布的稳定 `OpenMLS 0.9.0` 另行进入静态刷新；两条路线必须各自生成 lockfile、审计完整传递图并使用同一 `SW-G3` 判定口径。

本包明确不授权：

- 新增 `tools/spikes/sw-g2-mls-rs/` 或运行脚本；
- 访问 crates.io、Docker Hub、GitHub advisory DB 或其他外部服务；
- 构建 AWS-LC、SQLite、`mls-rs` 或移动端 wrapper；
- 使用真实身份、联系人、消息、设备密钥或生产数据库；
- 修改 `tools/t0/`、运行 `SW-V*`、启动 VM、操作硬件或产生射频发射。

## 静态门禁评审记录

- 结论：Accepted；
- 日期：2026-08-28；
- 接受范围：`mls-rs 0.56.0`、AWS-LC/SQLite provider、直接 feature、许可证/advisory/source 停止线、证据与分段授权边界；
- 直接结果：该候选可以在未来提交精确的“实施骨架 + Phase A”授权请求，但当前不得创建文件、下载依赖或运行；
- 保留边界：候选未形成 lockfile、完整许可证结论、Linux ARM64 实证或 ADR，不能成为默认后备路线；
- 授权边界：本次接受只冻结静态方案，不授权 Phase A、Phase B、FFI/移动、容器、网络或清理操作。

## 官方基线与适用限制

| 项目 | 固定基线 | 已知事实 | 仍需验证 |
| --- | --- | --- | --- |
| `mls-rs` | [`0.56.0`](https://docs.rs/crate/mls-rs/0.56.0)，tag commit [`8f1b43f`](https://github.com/awslabs/mls-rs/commit/8f1b43f) | 2026-08-19 发布；`Apache-2.0 OR MIT`；MSRV `1.82.0`；上游声明 RFC 9420 conformance | 完整依赖图、advisory、RadishLink 身份/投递映射、Linux ARM64 原生运行 |
| crypto provider | `mls-rs-crypto-awslc = 0.25.0` | 上游把 AWS-LC provider 标为 stable；支持 cipher suite 1、2、3、5、7 | wrapper 与固定传递版本、构建工具、二进制体积、原生 ARM64 和移动集成 |
| storage provider | `mls-rs-provider-sqlite = 0.23.0` | 上游提供 group/key package/secret storage 所需 SQLite provider | schema/migration、事务边界、损坏恢复、SQLite 来源与许可证表达 |
| codec | `mls-rs-codec = 0.7.0` | 与 `mls-rs 0.56.0` manifest 的直接版本范围一致 | 规范编码、未知输入、长度上限和跨实现互操作 |
| 移动接口 | tag workspace 中的 `mls-rs-ffi` / `mls-rs-uniffi` | 存在 FFI 与 UniFFI 路径 | 发布 crate 与 tag 的版本配套、Kotlin/Swift API 完整性、密钥暴露和移动生命周期 |

[`mls-rs 0.56.0` 文档](https://docs.rs/crate/mls-rs/0.56.0)明确说明尚未完成完整第三方安全审计。AWS-LC 的[平台说明](https://github.com/aws/aws-lc#platform-support)列出 Linux、Android 和 iOS AArch64，但这只覆盖底层库的官方范围，不证明 `mls-rs-crypto-awslc`、RadishLink wrapper 或移动构建已经通过。

本轮选择 AWS-LC 作为首个静态图，是因为 `mls-rs` 把它列为 stable，且底层平台方向覆盖 Linux/移动 AArch64；这不是生产 provider 决策。OpenSSL 保留为后续独立候选，不能在 AWS-LC 失败时自动替换；上游标为 experimental 的 RustCrypto provider 不进入本轮。

## 固定直接依赖与 feature

计划 crate 只能声明下列直接依赖；所有版本使用精确 `=`，不使用 git dependency、branch、`main`、通配版本或 prerelease：

| crate | 固定版本 | feature 与用途 |
| --- | --- | --- |
| `mls-rs` | `=0.56.0` | `default-features = false`；只启用 `std`、`private_message`、`out_of_order`、`prior_epoch`、`tree_index` |
| `mls-rs-crypto-awslc` | `=0.25.0` | `default-features = false`；只启用 `non-fips` |
| `mls-rs-provider-sqlite` | `=0.23.0` | `default-features = false`；只启用 `sqlite-bundled` |
| `mls-rs-codec` | `=0.7.0` | 标准 MLS 对象编码与解析 |
| `serde` | `=1.0.229` | 只用于脱敏证据结构 |
| `serde_json` | `=1.0.151` | 只用于 manifest/summary 输出 |
| `tempfile` | `=3.27.0` | 仅 dev dependency，隔离测试状态 |

首轮不启用：

- `rfc_compliant` 聚合 feature，因为它会连带启用本轮不使用的 X.509 等功能；实际能力缺口逐项记录，不能借 feature 名称宣称 RFC 全面互操作；
- `fast_serialize`、`rayon`、`external_client`、`serde`、`sqlcipher*`、`test_util`、`benchmark*`、`fuzz_util`、`post-quantum` 或 `fips`；
- `cfg(mls_build_async)`；首轮只比较同步、单进程命令入口，不把异步模式缺口隐藏在运行差异中；
- `mls-rs-ffi` 或 `mls-rs-uniffi`；移动接口在核心 Linux ARM64 状态安全通过后形成独立依赖图和授权。

首轮 cipher suite 固定为 `MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519`。身份使用合成 A/C 标识和最小自定义 `IdentityProvider`；不得把显示名当 credential，不启用 X.509，也不生成真实设备身份。SQLite 只验证 provider 的状态接口，不等于覆盖层消息、去重、receipt 和 MLS 状态已经处于同一事务。

## Phase A：lockfile、来源、许可证与 advisory 门

### 计划入口

只有实施范围与 L3 副作用另行明确授权后，才允许新增并执行：

```bash
./scripts/run-sw-g2-mls-rs-spike.sh prepare
```

计划使用与 `SW-EXP-002` 相同的 fixed-digest Linux ARM64 Rust 1.96.1 image 和隔离规则，但使用新的目录、label 与 evidence ID，不能复用或修改 OpenMLS prepared run。实现必须：

1. 只在 `tools/spikes/sw-g2-mls-rs/` 声明上表直接依赖，并保存包管理器生成的 `Cargo.lock`；
2. 只允许 crates.io registry source；未知 registry、git source、path override、yanked crate 或 lockfile 漂移立即 `STOP`；
3. 在本轮专用 `CARGO_HOME` / `CARGO_TARGET_DIR` 获取固定图，不读写主机 Cargo home；
4. 固定 `cargo-audit 0.22.2` 与 `cargo-deny 0.20.2`，保存 advisory DB revision、metadata、tree、许可证、source 与退出码；
5. 许可证初始 allowlist 仅为 `MIT`、`Apache-2.0`、`BSD-2-Clause`、`BSD-3-Clause`、`ISC`、`Unicode-3.0`、`Zlib`；SQLite 的 public-domain 表达、未知表达式、缺失许可证和任何新许可证都进入人工复核，不自动放行；
6. 任一未解释 advisory、未知来源、许可证拒绝、工具失败或证据缺失均输出 `STOP`，不自动进入 Phase B；
7. manifest 和 checksum 至少满足 `SW-EXP-002` schema 2 的同等字段，并另记固定 direct dependency/features 与生成 package 数量。

### 预计影响

以下只是运行授权前的保守估计，不是已发生事实：

- 首次耗时约 20–50 分钟，取决于镜像、crates 与审计工具 cache；
- 网络下载约 0.8–2.5 GiB；
- 本轮忽略目录磁盘峰值不超过 5 GiB；
- 可能保留 fixed-digest Rust image 和本轮 `.work` cache；
- 不创建长期容器、网络、端口、服务，不访问项目远程或提交任何内容。

上述命令、版本、下载范围或镜像发生变化时，原授权包失效，必须重新评审。不得通过 advisory ignore、许可证例外、`cargo update`、手改 lockfile、换 provider 或启用 prerelease 继续。

## Phase B：无网络 Linux ARM64 最小对照

Phase B 只有在 Phase A 的完整依赖图、许可证和 advisory 全部通过并由非实现者复核后，才能形成单独授权。它计划在 `--platform linux/arm64 --network none --read-only` 容器内，仅使用 Phase A cache 和合成数据覆盖：

| ID | 场景 | 必须成立 | 立即失败条件 |
| --- | --- | --- | --- |
| `M01` | provider/codec 最小启动 | 固定 suite、provider 和 feature 与 manifest 一致 | 运行时静默换 provider/suite |
| `M02` | A 创建两成员组，C 离线加入 | `KeyPackage` / `Welcome` 可由不透明 B 转存 | B 获得 group secret 或正文 |
| `M03` | A→B→C 应用密文 | C 验证并只交付一次，B 只见允许字段 | B 可解密或 duplicate 再交付 |
| `M04` | 丢失/重复/乱序 | 使用 `SW-G3` 固定 profile，窗口耗尽显式失败 | 静默扩大 epoch/skipped window |
| `M05` | A/C 独立重启 | SQLite 恢复后状态继续且密钥不复用 | 内存 snapshot 伪装持久化 |
| `M06` | 提交点崩溃 | 恢复后要么未推进，要么状态与证据完整 | 安全状态、消息、去重或 receipt 分裂 |
| `M07` | 篡改与旧 epoch 重放 | 有界拒绝，不产生 delivery evidence | 接受篡改、状态回退或默认成功 |
| `M08` | B 可见性盘点 | 只保存对象类型、大小、相对名和 SHA-256 | 保存 plaintext、credential 私钥或会话密钥 |

本阶段不验证 FFI、Android/iOS、群组规模、性能、产品数据库或无线承载；通过也只形成 `mls-rs 0.56.0 + AWS-LC + SQLite` 在记录条件下的候选实证，不能直接通过 `SW-G2` 或宣称产品 E2EE。

## 证据、清理与授权单位

每轮证据固定在：

```text
artifacts/sw-g2-mls-rs/<run-id>/
├── manifest.json
├── generated-lock-sha256.txt
├── cargo-metadata.json
├── cargo-tree.txt
├── cargo-audit.json
├── cargo-deny.txt
├── audit-exit-codes.json
├── advisory-db-revision.txt
├── checksums.sha256
└── run.log
```

Phase B 获准后才增加 scenario summary、B inventory 与各节点脱敏时间线。不得保存 endpoint database、私钥、完整 credential、随机种子原值、合成 plaintext、core dump 或敏感 debug 输出。

授权必须拆分为：

1. **实施骨架 + Phase A**：新增精确文件、下载固定依赖并生成/审计 lockfile；
2. **Phase B**：Phase A 通过后构建并运行无网络 Linux ARM64 场景；
3. **FFI/移动静态门与运行**：另建依赖图，不继承核心结果；
4. **可选清理**：复核精确 run 目录、容器引用和镜像前置状态后另行授权。

本文静态门禁已接受。`SW-EXP-003` 尚未发生，不存在 lockfile、依赖许可证结论、构建、运行或平台实证；`SW-G2` 继续保持未通过。
