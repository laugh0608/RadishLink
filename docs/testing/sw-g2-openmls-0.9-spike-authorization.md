# SW-G2 OpenMLS 0.9.0 受限 spike 静态门禁与执行授权包

- 状态：Accepted（静态门禁，2026-08-28；未实施、未下载、未生成 lockfile、未构建、未运行）
- 资料核对日期：2026-08-28
- 计划证据编号：`SW-EXP-004`
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文为稳定 `OpenMLS 0.9.0` 建立独立于 `SW-EXP-002` 的依赖、provider、feature、许可证、advisory、存储格式和 Linux ARM64 门禁。它只允许在运行前评审精确方案，不构成实施或执行授权，也不把 0.9.0 写成 0.8.1 advisory、许可证或持久化问题的已验证修复。

`SW-EXP-002` 的源码、lockfile、prepared cache、审计结果和运行授权不得复用。新候选必须生成自己的 lockfile、完整传递图和证据编号；任何“版本更新后应该已修复”的推断都不能替代审计。

本包明确不授权：

- 新增 `tools/spikes/sw-g2-openmls-0.9/`、运行脚本或修改 `SW-EXP-002`；
- 访问 crates.io、Docker Hub、GitHub advisory DB 或其他外部服务；
- 安装审计工具、生成 lockfile、构建 OpenMLS/SQLite 或启动容器；
- 迁移任何真实数据库，或使用真实身份、联系人、消息和设备密钥；
- 修改 `tools/t0/`、运行 `SW-V*`、启动 VM、操作硬件或产生射频发射。

## 静态门禁评审记录

- 结论：Accepted；
- 日期：2026-08-28；
- 接受范围：固定候选版本与 feature、Phase A/Phase B 分段、许可证与 advisory 停止线、自描述 JSON storage、新建 SQLite 基线、Linux ARM64 目标、证据和清理边界；
- 直接结果：[`SW-EXP-004` 实施骨架与 Phase A 精确授权包](sw-g2-openmls-0.9-phase-a-authorization.md)已接受并完成实施单元 A；L3 单元 B 仍未授权，不得联网、下载、安装、生成 lockfile、构建、容器运行或迁移；
- 结论限制：当前没有实际解析图、许可证结论、安全公告结论或运行证据；`OpenMLS 0.9.0` 仍只是待独立验证的候选，不能接入 `SW-V3/P0`。

## 官方基线与新增停止线

| 项目 | 固定基线 | 官方事实 | RadishLink 仍需验证 |
| --- | --- | --- | --- |
| 主 crate | [`openmls 0.9.0`](https://docs.rs/crate/openmls/0.9.0) | 2026-08-25 稳定发布；MIT；MSRV `1.91` | 发布 tag revision、完整依赖图、许可证、advisory、行为差异 |
| RustCrypto provider | `openmls_rust_crypto 0.6.0` | 版本线改用 `hpke-rs 0.7`，其 HPKE 依赖启用 `experimental` feature | 0.7 实际解析图是否仍含 RustSec/许可证停止项；AArch64 行为 |
| SQLite provider | `openmls_sqlite_storage 0.3.0` | 使用 `rusqlite`，初始化入口为 `run_migrations()` | bundled SQLite 来源、许可证表达、事务/损坏恢复和 schema 演进 |
| traits/credential | `openmls_traits 0.6.0`、`openmls_basic_credential 0.6.0` | 与 0.9.0 版本线配套 | 身份绑定、错误面和自定义 provider 组合 |
| 目标平台 | `aarch64-unknown-linux-gnu` | 上游声明在 CI 构建并测试 Linux AArch64 | RadishLink fixed image 中原生构建、运行和资源证据 |

[0.9.0 release notes](https://book.openmls.tech/releases/0.9.0.html)把 MSRV 提升到 Rust 1.91，并声明非自描述 storage format 不再受支持；[迁移说明](https://book.openmls.tech/user_manual/migration.html)要求旧版本使用 `migration-export`、新版本使用 `migration-import`，通过自描述编码桥接。RadishLink 当前没有可迁移的产品数据库，所以首轮只允许新建 JSON 编码的合成 SQLite；不得把 `SW-EXP-002` 临时状态伪装成产品迁移实证。

[`OpenMLS` 官方安全策略](https://github.com/openmls/openmls/security/policy)的协调披露范围只覆盖主 `openmls` crate；crypto provider 与 storage backend 明确不在同一保障范围内。Phase A 必须分别检查 `openmls_rust_crypto`、`openmls_sqlite_storage` 及其完整传递图；“主 crate 未列出 advisory”不能写成 provider 或 storage 已安全。官方迁移说明同时指出 storage traits 不提供事务 API，因此 provider 的 SQLite 测试通过也不能证明覆盖层消息状态与 MLS 安全状态已经原子提交。

0.9.0 还把不支持的 ciphersuite 提前变成显式错误，并改变 own message、pending commit 与 AppDataUpdate 的部分处理结果。Phase B 必须把这些结果映射为显式状态，不能以 catch-all、默认成功或静默忽略保持旧行为。

## 固定直接依赖与 feature

计划 crate 只能声明下列直接依赖；所有版本使用精确 `=`，不使用 git dependency、branch、`main`、通配版本或 prerelease：

| crate | 固定版本 | feature 与用途 |
| --- | --- | --- |
| `openmls` | `=0.9.0` | `default-features = false`；只启用 `fork-resolution` |
| `openmls_basic_credential` | `=0.6.0` | 合成 A/C credential 与签名材料 |
| `openmls_rust_crypto` | `=0.6.0` | 不启用可选 draft/test feature；其固定 manifest 会向 `hpke-rs 0.7` 传递 `experimental` feature，必须在解析图中显式保留并审计 |
| `openmls_sqlite_storage` | `=0.3.0` | 合成 endpoint 安全状态持久化 |
| `openmls_traits` | `=0.6.0` | 组合 RustCrypto、随机源与 SQLite storage provider |
| `rusqlite` | `=0.32.1` | 只启用 `bundled`，固定 SQLite 构建来源；必须与 provider 解析范围兼容 |
| `serde` | `=1.0.229` | `derive`；自描述 JSON storage codec 与脱敏证据 |
| `serde_json` | `=1.0.151` | JSON storage codec、manifest 和 summary |
| `tls_codec` | `=0.5.0` | MLS 对象编码；启用 `derive`、`serde`、`mls` |
| `tempfile` | `=3.27.0` | 仅 dev dependency，隔离合成数据库 |

首轮 cipher suite 固定为 `MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519`。身份只使用合成 A/C 标识和 BasicCredential；显示名不能充当稳定身份，也不启用 X.509。

首轮不启用：

- `content-debug`、`crypto-debug`、`test-utils`、`backtrace` 或任何输出密钥/正文的 feature；
- `libcrux-provider`、PQ、virtual client、targeted message、extensions draft 或其他实验 feature；
- `migration-import`、`0-8-1-storage-format` 或旧版 `migration-export`；迁移验证另建双版本依赖图和授权，不混入新建状态基线；
- WASM、Android/iOS、FFI、SQLCipher 或系统 SQLite；这些平台与分发边界后续独立评审。

若 crates.io manifest 显示任一直接版本、feature 或 `rusqlite =0.32.1` 不兼容，Phase A 在生成 lockfile 前停止并回到本文修订；不得放宽为版本范围或运行 `cargo update` 猜测可用组合。

## Phase A：独立 lockfile、来源、许可证与 advisory 门

### 计划入口

只有实施范围与 L3 副作用另行明确授权后，才允许新增并执行：

```bash
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare
```

计划沿用 `SW-EXP-002` 已收口的安全结构，但必须使用新的目录、label、evidence ID 和 lockfile：

1. 只复制固定输入到本轮私有 `.work/repo/`，仓库不得可写挂入容器；
2. 使用 fixed-digest Rust 1.96.1 Linux ARM64 image；记录 MSRV、host/daemon/container architecture 和工具链；
3. 只允许 crates.io registry；未知 registry、git source、path override、yanked crate 或 lockfile 漂移立即 `STOP`；
4. 生成新 lockfile 后固定 SHA-256，再运行 `cargo metadata --locked`、`cargo tree --locked --target all`、`cargo tree --locked --target all --edges features` 与 `cargo tree --locked --duplicates`；
5. 固定 `cargo-audit 0.22.2` 与 `cargo-deny 0.20.2`，保存 advisory DB revision、完整退出码和报告；
6. 对 `hpke-rs 0.7`、RustCrypto、bundled SQLite 与 proc-macro 的全部传递依赖逐项执行许可证、source 和 advisory 门；provider/storage 不继承主 `openmls` crate 的安全公告结论；
7. 初始 allowlist 仅为 `MIT`、`Apache-2.0`、`BSD-2-Clause`、`BSD-3-Clause`、`ISC`、`Unicode-3.0`、`Zlib`；SQLite public-domain 表达、`MPL-2.0`、未知或缺失许可证均进入人工复核，不自动放行；
8. schema 2 manifest 另记 direct dependency/features、resolved package 数量、SQLite source/version 和 storage codec；manifest 完成后再生成 checksum。

任一 advisory、许可证拒绝、未知来源、版本不兼容、证据缺失或工具失败均输出 `STOP`，不自动更换 provider、开启旧格式 feature、加入 ignore 或进入 Phase B。

### 预计影响

以下只是未来授权前的保守估计，不是已发生事实：

- 首次耗时约 15–45 分钟，取决于镜像、crates 和 advisory DB cache；
- 网络下载约 0.8–2.5 GiB；
- 忽略目录磁盘峰值不超过 5 GiB；
- 会编译审计工具与 bundled SQLite 的后续 Phase B 可能增加 CPU/磁盘占用；
- 不创建长期容器、Docker network、端口、服务，不访问项目远程或提交任何内容；
- fixed Rust image 和本轮 `.work` cache 默认保留，清理需要精确目标与独立授权。

## Phase B：无网络 Linux ARM64 最小实证

Phase B 只有在 Phase A 完整通过、许可证表达得到人工确认并由非实现者复核后，才能形成单独授权。计划覆盖：

| ID | 场景 | 必须成立 | 立即失败条件 |
| --- | --- | --- | --- |
| `N01` | provider/codec 启动 | 固定 suite、RustCrypto、JSON codec 与 SQLite provider 和 manifest 一致 | 运行时使用 MemoryStorage 或换 provider |
| `N02` | A 创建组，C 离线加入 | `KeyPackage` / `Welcome` 经不透明 B 转存 | B 获得私钥、group secret 或正文 |
| `N03` | A→B→C 私有消息 | C 验证并只交付一次，B 只见允许字段 | B 可解密、duplicate 再交付或 own-message 状态误判 |
| `N04` | SQLite 重启恢复 | A/C 独立进程恢复 group、epoch、去重与 deadline | 内存 snapshot 伪装持久化或状态分裂 |
| `N05` | 提交点崩溃 | 安全状态、消息记录和 evidence 要么都未推进，要么完整推进 | pending commit、secret tree、receipt 不一致 |
| `N06` | 不支持 suite/未知输入 | 高成本处理前显式拒绝，状态不变 | 深层失败、默认 fallback 或部分写入 |
| `N07` | 篡改、旧 epoch 与 fork | 使用已接受的 `SW-G3` profile，有界拒绝并保存失败证据 | 接受篡改、状态回退或静默合并 fork |
| `N08` | B 可见性盘点 | 只保留对象类型、大小、相对名和 SHA-256 | plaintext、credential 私钥、key package 私有部分或会话密钥出现 |

新建 JSON storage 的通过不证明 0.8.1 数据可迁移。若未来需要迁移，必须另设至少 `N09`，同时固定旧/新 crate 别名、export/import feature、源/目标 codec、合成旧数据库、失败回滚和双版本许可证/advisory 图；在该包接受前不实现。

## 证据、清理与授权单位

每轮证据固定在：

```text
artifacts/sw-g2-openmls-0.9/<run-id>/
├── Cargo.lock
├── manifest.json
├── generated-lock-sha256.txt
├── cargo-metadata.json
├── cargo-tree.txt
├── cargo-tree-features.txt
├── cargo-tree-duplicates.txt
├── cargo-deny-sources.txt
├── cargo-audit.json
├── cargo-deny.txt
├── audit-exit-codes.json
├── advisory-db-revision.txt
├── storage-baseline.json
├── checksums.sha256
└── run.log
```

授权必须拆分为：

1. **实施骨架**：按[精确授权包](sw-g2-openmls-0.9-phase-a-authorization.md)新增受限文件并执行无网络静态验证；
2. **Phase A**：骨架已提交且工作区干净后，另行授权一次依赖下载、lockfile 生成与审计；
3. **Phase B**：Phase A 通过后构建并运行无网络 Linux ARM64 新建状态场景；
4. **0.8.1→0.9.0 迁移包**：只有存在产品迁移需求时另行设计，不包含在前三项；
5. **移动/FFI 与其他 provider**：另建依赖图与平台授权；
6. **可选清理**：复核精确 run 目录、容器引用和镜像前置状态后另行授权。

当前静态门禁和精确方案已接受，实施单元 A 已完成。`SW-EXP-004` Phase A 尚未发生，不存在新 lockfile、依赖许可证结论、构建、运行、迁移或平台实证；L3 单元 B 与 Phase B 均未授权，`SW-G2` 继续保持未通过。
