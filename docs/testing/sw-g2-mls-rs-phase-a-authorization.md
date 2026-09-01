# SW-EXP-003 mls-rs 0.56.0 实施与 Phase A 精确授权包

- 状态：Accepted（2026-09-01；精确包已接受，共享运行资源单元 A0 已离线实施并形成 clean revision；A1/C/D、Docker、Cargo、网络与候选运行均未授权）
- 日期：2026-09-01
- 证据编号：`SW-EXP-003`
- 前置门禁：[mls-rs 0.56.0 静态门禁](sw-g2-mls-rs-spike-authorization.md)已接受候选方向，执行就绪差异待本包关闭
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文把已接受的 mls-rs 0.56.0 静态候选方向转换为可审阅、可停止、逐单元授权的实施与 Phase A 方案。它只处理固定依赖图、来源、许可证、advisory、feature、Linux ARM64 工具链和证据合同，不选择 mls-rs 为产品实现，不构建或运行 MLS/AWS-LC/SQLite 候选，不接入 `SW-V3/P0`，也不使用真实身份、联系人、消息、设备凭据、数据库或密钥。

必须依次区分以下授权单位：

1. **共享运行资源单元 A0**：离线实现候选无关的运行 monitor、固定审计工具 bundle builder、独立 manifest filter 与 self-test；
2. **mls-rs Phase A 骨架单元 A1**：离线新增固定 crate 输入、拒绝 Phase B 的入口、受限 runner、候选 manifest filter 与 self-test；
3. **L3 通用审计工具 bundle 单元 C**：在 A0 clean revision 上构建一次固定 `cargo-audit` / `cargo-deny` bundle，并以无网络容器验证版本；
4. **L3 mls-rs Phase A 单元 D**：在 A1 clean revision 上只读消费一个精确、已复核的通用 bundle，生成独立 lockfile 并执行完整 gates；
5. **Phase B**：只有 D 完整 `PASS`、许可证人工复核与非实现者证据复核都通过后，才另建精确包；当前不存在实现或执行授权。

本文的接受只冻结精确方案，不自动授权任何实施单元。本次另行明确授权只覆盖 A0；A0 不包含 A1，A0/A1 不包含 commit，C 不包含 D，任一 L3 授权不包含失败重试、Phase B、清理、push 或其他候选。

## 固定基线

### 候选依赖

首轮只允许静态门禁已接受的精确直接依赖：

| crate | 固定版本 | 允许 feature |
| --- | --- | --- |
| `mls-rs` | `=0.56.0` | `default-features = false`；`std`、`private_message`、`out_of_order`、`prior_epoch`、`tree_index` |
| `mls-rs-crypto-awslc` | `=0.25.0` | `default-features = false`；`non-fips` |
| `mls-rs-provider-sqlite` | `=0.23.0` | `default-features = false`；`sqlite-bundled` |
| `mls-rs-codec` | `=0.7.0` | 无额外 feature |
| `serde` | `=1.0.229` | 无额外 feature；仅保留已接受的脱敏 evidence dependency |
| `serde_json` | `=1.0.151` | 无额外 feature |
| `tempfile` | `=3.27.0` | 仅 dev dependency |

不得启用 `rfc_compliant`、`fast_serialize`、`rayon`、`external_client`、`sqlcipher*`、`test_util`、`benchmark*`、`fuzz_util`、`post-quantum`、`fips`、FFI/UniFFI 或 `cfg(mls_build_async)`。不得在运行中放宽版本范围、运行 `cargo update`、换 provider、加入 prerelease 或用 feature fallback 猜测可用组合。

### 镜像、平台与审计工具

- image：`rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`；
- target：`linux/arm64`；容器内必须为 Linux `aarch64`、`rustc 1.96.1`、`cargo 1.96.1`；
- audit tools：`cargo-audit =0.22.2`、`cargo-deny =0.20.2`；
- candidate source：仅 crates.io registry；未知 registry、git/path source、patch/replace、yanked crate 或 lockfile 漂移立即 `STOP`；
- RustSec DB：只由固定审计工具在候选 Phase A 中获取并记录 revision；
- license allowlist：`MIT`、`Apache-2.0`、`BSD-2-Clause`、`BSD-3-Clause`、`ISC`、`Unicode-3.0`、`Zlib`。SQLite public-domain 表达、未知/缺失许可证和任何新表达均 `STOP`，不自动添加例外。

任何 crate 版本、feature、image digest、platform、Rust/Cargo、audit tool、registry、provider、allowlist 或证据合同变化都会使相应授权失效，必须先回到静态差异评审。

## 共享资源决策

OpenMLS 0.9.0 的成功 bundle `20260830-112214-39636.GpERrj` 包含正确的固定工具二进制，但其 evidence ID、路径、label、builder/filter 摘要和 `sw-exp-004-audit-tools-v2` contract 绑定 OpenMLS 历史单元。mls-rs 不直接消费、复制或改写该 bundle，也不复用其中 `.work`、cache 或运行授权。

A0 新建候选无关的 `sw-g2-rust-audit-tools-v1` contract。它沿用已经验证的安全性质与失败语义，但不修改 OpenMLS 历史脚本或 evidence：

- 固定工具版本、image/platform、独立 Cargo home/target；
- builder 使用 Docker 默认出站网络且无域名 allowlist，validation 使用 `--network none`；
- 非 root、只读根、drop capabilities、no-new-privileges、`pids-limit 512`，不挂载 Docker socket、真实 home、Git/SSH 凭据或用户数据；
- 独立 jq filter、原子 manifest、非空/有效 JSON、checksum 自校验、唯一 post-finalization `PASS`；
- 90 分钟 deadline、5 GiB 五秒周期 monitor、精确 label 清理与零残留复核；
- bundle 只包含两个 `0555` 二进制和可复核证据；consumer 只能按精确 bundle ID、contract、manifest/checksum、版本和 SHA-256 只读挂载。

该通用合同未来能否被其他候选消费，仍由每个候选的精确包单独授权；“通用”不等于持续运行授权。

## 单元 A0：共享运行资源离线实施

### 允许文件

| 路径 | 允许内容 |
| --- | --- |
| `scripts/monitor-sw-g2-dependency-audit-run.py` | 候选无关的 deadline、磁盘、父进程信号和 runtime-control JSON；含标准库 self-test |
| `scripts/run-sw-g2-rust-audit-tools.sh` | 仅 `prepare` 与离线 `self-test`；固定工具 bundle builder、精确清理与证据终结 |
| `scripts/sw-g2-rust-audit-tools-manifest.jq` | `sw-g2-rust-audit-tools-v1` 独立 manifest renderer |
| `scripts/check-sw-g2-rust-audit-tools.sh` | 无 Docker/Cargo/网络的语法、合同、失败传播与 finalizer 检查 |
| 本文及索引/状态文档 | 同步 A0 设计与验证事实 |

不得修改、删除或包装现有 OpenMLS runner、monitor、bundle builder、filter、Cargo inputs 或历史 evidence；不得为了“复用”改变已接受的 OpenMLS 证据摘要。A0 不创建 bundle，不查询 Docker，不调用 Cargo，不访问网络。

### A0 离线验证

```bash
bash -n scripts/run-sw-g2-rust-audit-tools.sh
bash -n scripts/check-sw-g2-rust-audit-tools.sh
python3 scripts/monitor-sw-g2-dependency-audit-run.py self-test
./scripts/run-sw-g2-rust-audit-tools.sh self-test
./scripts/check-sw-g2-rust-audit-tools.sh
./scripts/check-repo.sh
git diff --check
```

无参数、未知 action 和 `run` 必须在 artifact、Docker、Cargo 与网络前以 `2` 拒绝。renderer 失败、空/无效 JSON、既有 final/tmp 路径、checksum 自校验失败或提前 `PASS` 必须由 self-test 覆盖。

### A0 实施结果

2026-09-01 已按单次明确授权完成 A0：新增候选无关 monitor、通用 audit bundle builder、schema 1 renderer 与综合离线 checker。实现固定 `rust:1.96.1-bookworm` 完整 digest、`linux/arm64`、Rust/Cargo 1.96.1、`cargo-audit 0.22.2`、`cargo-deny 0.20.2`、90 分钟/5 GiB/五秒运行控制、精确 label、构建默认出站网络和两处无网络验证；通用成功合同为 `sw-g2-rust-audit-tools-v1`，payload 仅允许两个 `0555` 二进制。

离线验证覆盖 deadline、磁盘边界、父进程信号、正常停止、无参数/未知 action/`run` 的退出码 `2` 与零副作用、renderer 失败、空/无效 JSON、既有 final/tmp 拒绝、checksum 篡改检测、唯一 post-finalization `PASS`、容器限制和 OpenMLS 历史脚本摘要不变。A0 没有执行 `prepare`，没有创建 `artifacts/sw-g2-rust-audit-tools/`，没有查询 Docker、调用 Cargo/网络、修改历史 evidence、构建 bundle、提交或 push。

A0 已随本批次提交形成 C 要求的 clean revision；没有 push。A1、C、D 与 Phase B 继续保持未授权。

## 单元 A1：mls-rs Phase A 骨架离线实施

### 允许文件

| 路径 | 允许内容 |
| --- | --- |
| `tools/spikes/sw-g2-mls-rs/Cargo.toml` | 仅固定直接依赖、package metadata 与 dev dependency |
| `tools/spikes/sw-g2-mls-rs/deny.toml` | 固定 source、license 与 advisory 停止线，不含 allow/ignore 例外 |
| `tools/spikes/sw-g2-mls-rs/src/main.rs` | 明示 Phase B 未实现并拒绝所有场景命令；不初始化 MLS/provider/storage |
| `scripts/run-sw-g2-mls-rs-spike.sh` | 仅 `prepare <bundle-id>`；clean preflight、隔离 Phase A、完整 evidence 与精确清理 |
| `scripts/sw-g2-mls-rs-phase-a-manifest.jq` | `sw-g2-candidate-phase-a-v1` 独立 manifest renderer |
| `scripts/check-sw-g2-mls-rs-phase-a.sh` | 无 Docker/Cargo/网络的参数、合同、feature/source、finalizer 与负例检查 |
| 本文及索引/状态文档 | 同步 A1 设计与验证事实 |

A1 不新增 `Cargo.lock`；它只能由获授权的 D 使用 Cargo 生成。A1 不复制 OpenMLS crate、runner、filter 或 candidate cache，不包含 MLS 场景、AWS-LC/SQLite 编译、身份、密钥、迁移、FFI 或产品代码。

### A1 离线验证

```bash
bash -n scripts/run-sw-g2-mls-rs-spike.sh
bash -n scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-repo.sh
git diff --check
```

runner 无参数、缺 bundle ID、未知 action、`run`、`phase-b`、latest/路径型 bundle selector 均必须在 artifact、Docker、Cargo 与网络前以 `2` 拒绝。A1 通过后须独立审阅并形成 clean revision；commit 是独立 Git 动作，不由 A1 实施授权自动包含。

## 单元 C：通用固定审计工具 bundle

只有 A0 clean revision、离线 self-test 与仓库门禁通过，并再次说明 L3 影响后，才可单独申请执行一次：

```bash
./scripts/run-sw-g2-rust-audit-tools.sh prepare
```

### C 的影响与停止线

- 预计 20–90 分钟，目录预算 5 GiB；Docker 容器限制 `4 CPU/4 GiB`，monitor 每五秒检查 deadline 与 apparent size。这是用户态监测，不是内核硬 quota；
- fixed image 已存在时只核对，缺失时可能访问 Docker Hub；工具构建使用 Docker 默认出站网络且无域名 allowlist，预期访问 crates.io index/download；不映射端口；
- 使用独立 Cargo home/target，以 `cargo install --locked` 构建固定工具；validation 容器使用同一 digest、`--network none` 和只读 bundle mount；
- 不下载 mls-rs/AWS-LC/SQLite 候选，不生成候选 lockfile，不运行 candidate gates 或 Phase B；
- fixed image、成功或负向 evidence、`.work`/cache 与 bundle 默认保留；trap 只清理名称和精确 run label 同时匹配的本轮容器，不做全局 Docker 清理；
- 任一网络、deadline、磁盘、版本、digest、platform、binary permission、manifest/checksum 或零残留失败都 `STOP`，不自动重试。

C 成功后必须记录唯一 bundle ID，并在工作区保持干净的情况下独立复核 contract、工具版本、二进制 SHA-256、manifest、checksum、运行控制与残留。C 的一次授权不包含 D。

## 单元 D：mls-rs Phase A

D 只有在以下值全部实际存在并写入当次授权说明后才能申请：

- A1 clean revision 的完整 commit；
- C 的精确 bundle ID、`sw-g2-rust-audit-tools-v1` manifest SHA-256、两个工具版本与二进制 SHA-256；
- clean worktree、固定 image/platform 与输入摘要；
- 唯一命令中的真实 `<bundle-id>`，不得使用 placeholder、latest、其他路径或自动发现。

未来唯一命令形态为：

```bash
./scripts/run-sw-g2-mls-rs-spike.sh prepare <bundle-id>
```

本文当前仍含 placeholder，因此不能据此执行 D。

### D 的动作

1. 在创建 candidate artifact、查询 Docker 或访问网络前，拒绝 dirty worktree，复核精确 bundle contract/ID/path、无 symlink payload、manifest/checksum、工具版本/摘要、bundle clean revision 与零残留；
2. 创建私有 `artifacts/sw-g2-mls-rs/<run-id>/`，启动 45 分钟、5 GiB、五秒周期 monitor；记录输入 SHA、HEAD、工作区、磁盘、Docker daemon、image 和精确 label pre-state；
3. 无网络工具链容器以 `1 CPU/512 MiB` 验证 Linux `aarch64` 与 Rust/Cargo；候选容器以 `4 CPU/4 GiB`、Docker 默认出站网络且无域名 allowlist访问 crates.io 与 GitHub RustSec，不映射端口；
4. 使用本轮全新 Cargo home/target 生成 lockfile，保存 `cargo metadata --locked`、普通/feature/duplicate tree；不读取主机 Cargo home，不复用任何 OpenMLS `.work`；
5. 只读挂载固定 bundle，执行 `cargo-deny check sources`、`cargo-audit audit --json`、`cargo-deny check advisories licenses` 与固定 feature gate；
6. feature gate 至少证明直接版本/feature 精确匹配、禁用列表未出现、AWS-LC `non-fips` 与 SQLite `sqlite-bundled` 路径唯一、没有其他 crypto/storage provider、没有 git/path/patch source；
7. source 与 feature 为零、输入/HEAD 未变且目标安全时，才原子新增 `tools/spikes/sw-g2-mls-rs/Cargo.lock`。许可证/advisory `STOP` 时仍保留已复核负向图；runner 不自动暂存、提交或 push；
8. 任何 gate 非零、tool/runtime/finalizer 异常或残留都终结为真实 `STOP`/`INVALID`，保留 partial evidence，不补跑、换版本/provider、放宽 allowlist、添加 ignore 或进入 Phase B。

### D 的预计影响

- 预计 15–45 分钟，45 分钟与 5 GiB 由五秒用户态 monitor 执行；网络量取决于固定候选 crates 与当次 RustSec DB；
- Phase A 只解析、下载和审计，不编译或运行 mls-rs、AWS-LC、SQLite，也不创建真实/合成密钥和数据库；
- fixed image、bundle、本轮 evidence、候选 `.work`/cache 与可能新增的仓库 lockfile 默认保留；精确容器清理后必须复核残留为零；
- 不访问远程 Git，不修改系统配置，不启动 VM/长期服务，不操作硬件或射频。

## 证据合同

### 通用 bundle

bundle evidence 位于：

```text
artifacts/sw-g2-rust-audit-tools/<run-id>/
```

成功 manifest 使用 schema 1 / `sw-g2-rust-audit-tools-v1`，至少记录 image/platform/toolchain、两个工具版本与二进制 SHA-256、builder/monitor/filter 摘要、runtime controls、网络边界、clean revision、零残留和退出码。checksum 必须覆盖所有 final evidence 与 bundle payload，并从仓库根自校验。

### mls-rs Phase A

candidate evidence 位于：

```text
artifacts/sw-g2-mls-rs/<run-id>/
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
├── container-toolchain.txt
├── git-status-before.txt
├── git-status-after.txt
├── runtime-control.json
├── checksums.sha256
└── run.log
```

manifest 使用 schema 1 / `sw-g2-candidate-phase-a-v1`，至少记录：candidate/evidence/scenario/run、outcome/stage、clean revision、fixed image/platform/toolchain、精确 bundle contract/ID/manifest/binary 摘要与只读挂载、direct dependencies/features、resolved package count、lock SHA、gate exit codes、RustSec revision、输入摘要、runtime controls、网络边界、lockfile preexisting/written、零残留和 runner exit code。

只有四个 gate 全部为零、manifest 非空有效、输入/HEAD/工作区未变、runtime 正常、零残留、checksum 完整自校验，才能打印唯一 `PASS`。零 vulnerability 只覆盖固定 lockfile 与记录的 RustSec revision，不构成第三方安全审计或 `SW-G2` 通过。

## 当前停止点与后续授权

精确包已接受，A0 已完成离线实施并形成 clean revision；尚未调用 Docker/Cargo/网络，未构建通用 bundle，未创建 mls-rs crate 或 lockfile，也未执行 Phase A/Phase B。

下一步是独立评审并明确授权 `mls-rs Phase A 骨架单元 A1`。C/D 在执行前必须重新展示唯一命令、A0/A1 clean revision、真实 bundle ID、网络、资源、保留与清理边界并逐次授权。

笼统的“继续”“按计划做”或接受本文不授权 A1/C/D。Phase B、失败重试、清理、commit、push、版本/provider/allowlist 变化和其他候选始终是独立动作。
