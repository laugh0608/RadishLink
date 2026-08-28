# SW-EXP-004 OpenMLS 0.9.0 实施骨架与 Phase A 精确授权包

- 状态：Accepted（精确方案，2026-08-28；实施单元 A 已授权并完成；L3 执行单元 B 未授权、未执行，且须先关闭运行上限控制差距）
- 日期：2026-08-28
- 证据编号：`SW-EXP-004`
- 前置门禁：[OpenMLS 0.9.0 静态门禁](sw-g2-openmls-0.9-spike-authorization.md)已接受
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文把已接受的 OpenMLS 0.9.0 静态门禁转换为两个必须依次、分别授权的动作：

1. **实施单元 A**：新增只支持依赖解析的最小 crate 与受限 runner，执行无网络静态验证；
2. **L3 执行单元 B**：在 A 已提交、工作区干净且再次明确授权后，只运行一次 Phase A，生成新 lockfile 并执行来源、许可证和 advisory 门。

分段用于保证用户在任何联网、依赖下载、审计工具编译或 Docker 容器启动前，能够先审阅真实脚本。接受本文不授权 A 或 B；A 的授权不自动包含 B，B 的一次授权也不构成失败重试、Phase B、清理或其他候选的持续授权。

本包不选择 OpenMLS 作为产品实现，不构建或运行 OpenMLS 场景，不接入 `SW-V3/P0`，不迁移数据库，不修改 `SW-EXP-002`、`tools/t0/` 或任何产品协议，也不使用真实身份、联系人、消息、设备凭据或密钥。

## 固定基线

执行单元只能使用静态门禁已接受的基线：

- crate：`openmls =0.9.0`、`openmls_basic_credential =0.6.0`、`openmls_rust_crypto =0.6.0`、`openmls_sqlite_storage =0.3.0`、`openmls_traits =0.6.0`、`rusqlite =0.32.1`、`serde =1.0.229`、`serde_json =1.0.151`、`tls_codec =0.5.0` 与 dev dependency `tempfile =3.27.0`；
- 镜像：`rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`；
- 平台：`linux/arm64`，容器内必须为 Linux `aarch64`、`rustc 1.96.1`、`cargo 1.96.1`；
- 审计工具：`cargo-audit =0.22.2`、`cargo-deny =0.20.2`，均使用 `cargo install --locked` 安装到本轮 `.work`；
- 来源：候选和审计工具只允许 crates.io；RustSec advisory DB 只由固定审计工具获取；
- 许可证初始 allowlist：`MIT`、`Apache-2.0`、`BSD-2-Clause`、`BSD-3-Clause`、`ISC`、`Unicode-3.0`、`Zlib`。

任何版本、digest、平台、provider、feature、registry、审计工具或 allowlist 变化都会使本包失效。不得用 `cargo update`、手改 lockfile、advisory ignore、许可证例外、换 provider、换镜像 tag 或 prerelease 绕过停止线。

`Cargo.toml` 的包与依赖段必须逐字采用：

```toml
[package]
name = "radishlink-sw-g2-openmls-0-9-spike"
version = "0.0.0"
edition = "2021"
publish = false
license-file = "../../../LICENSE"

[dependencies]
openmls = { version = "=0.9.0", default-features = false, features = ["fork-resolution"] }
openmls_basic_credential = "=0.6.0"
openmls_rust_crypto = "=0.6.0"
openmls_sqlite_storage = "=0.3.0"
openmls_traits = "=0.6.0"
rusqlite = { version = "=0.32.1", features = ["bundled"] }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.151"
tls_codec = { version = "=0.5.0", features = ["derive", "serde", "mls"] }

[dev-dependencies]
tempfile = "=3.27.0"
```

`deny.toml` 必须逐字采用：

```toml
[graph]
targets = ["aarch64-unknown-linux-gnu"]

[advisories]
ignore = []

[licenses]
allow = [
  "Apache-2.0",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "ISC",
  "MIT",
  "Unicode-3.0",
  "Zlib",
]
confidence-threshold = 0.93
private = { ignore = true }

[bans]
multiple-versions = "warn"
wildcards = "deny"

[sources]
unknown-registry = "deny"
unknown-git = "deny"
```

## 实施单元 A：最小文件与职责

获得单元 A 的明确授权后，只允许新增：

```text
scripts/run-sw-g2-openmls-0.9-spike.sh
tools/spikes/sw-g2-openmls-0.9/
├── Cargo.toml
├── deny.toml
└── src/
    └── main.rs
```

`Cargo.lock` 不由 A 人工创建；它只能由获授权的单元 B 在隔离容器中使用 Cargo 首次生成。A 不修改其他脚本、已有 spike、根配置、CI、产品代码或历史 artifact。完成后只允许同步本文与 `docs/status/current.md` 的授权、验证和停止点，不借结果记录扩大实现范围。

### 文件职责

| 文件 | 只负责 | 明确不负责 |
| --- | --- | --- |
| `Cargo.toml` | 逐字声明固定直接版本和已接受 feature；`publish = false` | 版本范围、git/path override、迁移 feature、debug/test feature |
| `deny.toml` | 固定 target、来源拒绝、空 advisory ignore 和初始许可证 allowlist | 自动例外、许可证法律结论 |
| `main.rs` | 显式说明 Phase B 未实现并拒绝所有场景命令 | MLS 状态机、provider 初始化、身份、加密、SQLite 或网络 |
| runner | 参数门、隔离目录、镜像/平台核对、单次 Phase A、证据与精确残留处理 | Phase B、重试循环、容器网络/端口、主机 Cargo home、真实数据 |

runner 只接受一个参数 `prepare`；无参数、多参数、`run`、未知 action 都必须在 Docker、artifact 或网络访问前以退出码 `2` 拒绝。脚本使用 `set -euo pipefail`、`umask 077`，拒绝 symlink 输入、artifact root 偏移、run 目录碰撞和 label 不匹配的容器清理。

仓库根不得可写挂入容器。runner 只把 `LICENSE`、新 crate 的三个固定输入和可选的既有 `Cargo.lock` 复制到本轮 `artifacts/sw-g2-openmls-0.9/<run-id>/.work/repo/`，容器只写本轮 run 目录。

### A 的精确静态验证

单元 A 只允许运行：

```bash
bash -n scripts/run-sw-g2-openmls-0.9-spike.sh
./scripts/run-sw-g2-openmls-0.9-spike.sh
./scripts/run-sw-g2-openmls-0.9-spike.sh run
./scripts/check-repo.sh
git diff --check
```

前两个 runner 负例必须各自以退出码 `2` 结束，并且不创建 artifact、不访问 Docker 或网络。验证不运行 `cargo`、`rustc`、`docker`，不生成 lockfile，也不下载或安装任何内容。

A 完成后先审阅和提交新增文件，使 B 从 clean revision 运行；提交是独立 Git 动作，接受本文本身不授权 commit 或 push。若 A 证明必须新增、删除或修改清单外文件，停止并修订本包。

### 2026-08-28 单元 A 实施记录

- 用户明确授权提交本包并实施单元 A；新增文件与职责严格等于清单，没有生成 `Cargo.lock`，没有修改旧 spike、产品代码、CI 或历史 artifact；
- runner 使用 `umask 077`、唯一 run 目录、fixed digest、非 root 只读容器、capability/进程/CPU/内存限制、独立 Cargo cache、source/feature gate、原子 lockfile promotion、schema 2 manifest、checksum 与精确 label 清理；仅接受 `prepare`，没有 Phase B action；
- 首次负例在 shell 入口前以退出码 `126` 暴露 runner 未设置 executable mode；当时没有创建 artifact 或进入 Docker。将唯一脚本改为 `0755` 后，同一无参数与 `run` 负例均按设计以退出码 `2` 拒绝；
- `bash -n`、两个参数负例、feature-gate 合成正负例、仓库基线与 `git diff --check` 通过，且 `artifacts/sw-g2-openmls-0.9/` 不存在；
- 本轮没有执行 `prepare`、`docker`、`cargo` 或 `rustc`，没有联网、下载、安装、生成 lockfile、构建候选或产生 `SW-EXP-004` artifact；
- 单元 A 授权已消费完毕。下面的代码—授权包复核进一步收紧了停止点；当前下一步以复核后的运行上限控制要求为准。

### 2026-08-28 代码—授权包一致性复核

- 固定依赖、镜像 digest、平台、CPU/内存/PID/capability 限制、私有 `.work`、source/feature gate、lockfile 原子写入、schema 2 manifest、checksum 和精确 label 清理均已落实到 runner；
- runner 在启动前要求 artifact 所在卷至少有 5 GiB 可用空间，但当前没有运行期 `du`/quota 监测，因此“最多 5 GiB”仍是人工停止线，不是脚本内硬上限；
- runner 当前没有内建 45 分钟总超时；`INT`/`TERM` 可进入精确清理，但达到时限仍依赖外部监督触发；
- 依赖与审计容器使用 Docker 默认出站网络，不映射端口，但不提供域名 allowlist；Docker Hub、crates.io 与 GitHub RustSec 是预期访问范围，不是由 runner 技术强制的唯一目的地；
- 因此单元 B 在 2026-08-28 收口时继续保持未授权、未执行。明日优先形成一个无 Docker/无网络的最小实施单元，为 45 分钟和 5 GiB 提供可验证的强制或监控机制，并把默认网络边界写入下一次 L3 授权；完成并提交 clean revision 前不申请或执行 B。

## L3 执行单元 B：一次 Phase A

### 前置条件

B 只有在以下条件全部成立并获得当前任务明确授权后才可执行：

1. 单元 A 已通过上述静态验证并提交，工作区干净，runner 与新 crate 位于同一 HEAD；
2. 新候选目录首次执行前不存在 `Cargo.lock`；若未来已存在，runner 只能重生成并逐字比较，不得更新；
3. `SW-EXP-002` 的源码、lockfile、artifact、`.work` cache、advisory DB 和授权均不复用；
4. Docker daemon 可用，artifact root、输入和目标 lockfile 均不是 symlink；
5. 没有相同精确 run label 的残留；磁盘可用量不少于 5 GiB，且 45 分钟总时限与 5 GiB 运行期预算已具备经复核的强制或监控机制；
6. 用户已看到并接受本节的网络、代码执行、磁盘、Docker 与保留副作用。

### 唯一执行入口

```bash
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare
```

一次授权只覆盖一次上述入口。外部服务失败、digest 不符、工具安装失败、解析漂移、许可证/advisory/source 拒绝或证据不完整都立即 `STOP`；不得自动重试。

### 固定动作顺序

runner 必须按顺序执行：

1. 创建唯一私有 run 目录，记录 HEAD、clean 状态、host/daemon architecture、磁盘前置和 fixed image 是否已存在；
2. 若 exact-digest 镜像存在，只用 `docker image inspect` 保存 image ID、`RepoDigests` 与平台；不存在时先用 `docker buildx imagetools inspect` 核对 index digest，再执行一次固定的 `docker pull --platform linux/arm64`；
3. 在 `--network none --read-only` 的短生命周期容器内保存 `uname -sm`、`rustc -vV` 与 `cargo -vV`；任一平台或版本不符立即停止；
4. 在新的联网容器和本轮专用 `CARGO_HOME` / `CARGO_TARGET_DIR` 中运行 `cargo generate-lockfile`、`cargo fetch --locked --target aarch64-unknown-linux-gnu`，并把实际 `Cargo.lock` 与 SHA-256 保存到 artifact；
5. 安装固定审计工具，生成 `cargo metadata --locked --format-version 1`、普通 tree、feature tree 与 duplicate tree；显式核对 `hpke-rs 0.7.*` 解析节点包含 `experimental` feature；
6. 分别运行 source gate、`cargo audit --json` 与许可证/advisory gate，保存每个命令的退出码；主 `openmls` crate、crypto provider 与 storage backend 分别保留结论，不相互继承；
7. 只有 source gate 与固定 feature gate 均为零、输入和 HEAD 未变且目标不是 symlink 时，才把 Cargo 生成的 lockfile 原子写入 `tools/spikes/sw-g2-openmls-0.9/Cargo.lock`；写入后要求工作区只出现这一个预期路径。许可证或 advisory 拒绝时仍保留这份真实负向图，但不得进入 Phase B；
8. 删除本轮精确容器，生成 schema 2 manifest，再为所有已完成的固定输入与证据生成 checksum；报告 outcome、stage、退出码和残留，不执行任何场景。

若仓库已有 `Cargo.lock`，第 4 步必须在隔离副本重新生成并与其 SHA-256 完全一致；漂移立即停止且不得覆盖。runner 不执行 `cargo build`、`cargo test`、候选 build script、SQLite 构建或 OpenMLS 二进制；编译执行的第三方代码仅限固定 `cargo-audit` / `cargo-deny` 及其工具依赖，并被限制在容器和本轮 `.work`。

### Docker 与网络限制

- 工具链核对容器使用 `--network none`；依赖与审计容器只使用 Docker 默认出站网络，不创建 named network、不映射端口；
- 两类容器均使用 `--read-only`、宿主非 root UID/GID、`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit 512` 和专用 tmpfs；
- 依赖与审计容器上限为 4 CPU、4 GiB 内存；不挂载 Docker socket、SSH agent、真实 home、主机 Cargo cache、Git credential 或系统密钥目录；
- 预期访问仅为 Docker Hub（只在 exact image 缺失时）、crates.io index/download 与 GitHub RustSec advisory DB；当前 Docker 默认出站网络不实施域名 allowlist，这一限制必须在执行授权中明确接受；runner 不主动访问项目 Git remote，不 push，不创建 PR、Release 或部署；
- 不使用 `--privileged`、host network、`NET_ADMIN`、系统代理修改、VM、长期服务或后台守护进程。

## 预计副作用与上限

- 预计持续 15–45 分钟；达到 45 分钟仍未完成时中断同一次进程并保留 `STOP` 证据，不自动重试。当前 runner 没有内建总超时，须在 B 前补齐经复核的强制或监控机制；
- 网络下载约 0.8–2.5 GiB，包含可能缺失的固定 Rust image、候选 crates、固定审计工具和当次 advisory DB；
- `artifacts/sw-g2-openmls-0.9/<run-id>/.work/` 与证据磁盘预算不超过 5 GiB。当前 runner 只验证启动前至少有 5 GiB 可用空间，不实施运行期硬配额，须在 B 前补齐经复核的强制或监控机制；
- 可能新增由 Cargo 生成的 `tools/spikes/sw-g2-openmls-0.9/Cargo.lock`，但只在 source gate 通过后发生；不自动 `git add`、commit 或 push；
- fixed Rust image、本轮 crates/audit cache 和 evidence 默认保留；不清理 Docker 全局 cache；
- 不创建 Docker network、volume、端口、长期容器或服务，不修改系统配置，不读取真实用户数据。

上述数字是单次首次运行的保守计划值，不是已发生测量。网络量、磁盘量、时长或资源类型超出上限时停止并重新授权。

## 停止线与判定

以下任一情况均为 `STOP`：

- HEAD 或固定输入在运行中变化，工作区前置不干净，目标 lockfile 已存在但重生成不一致；
- 镜像 digest、image ID 关联、OS/architecture、Rust/Cargo 版本不符；
- 出现 git/path dependency、未知 registry、未知 source、yanked crate 或无法解释的重复关键版本；
- `hpke-rs 0.7.*` feature 解析不包含已知 `experimental`，或出现未接受的 OpenMLS/debug/migration feature；
- 任一未解释 advisory、许可证拒绝/未知/缺失、工具失败、证据缺失或 checksum 失败；
- 容器名称相同但 label 不匹配、精确残留无法清理或资源上限被突破。

只有 source、许可证和 advisory 命令全部返回零，固定 feature/平台检查通过，证据与 checksum 完整，manifest 才可记为 Phase A `PASS`。这仍只表示候选图通过本轮自动门；必须由非实现者人工复核 lockfile、provider/storage 独立公告范围、许可证表达和证据后，才能设计 Phase B。

## 证据格式

每次有效 `prepare` 尝试固定保留：

```text
artifacts/sw-g2-openmls-0.9/<run-id>/
├── Cargo.lock
├── manifest.json
├── generated-lock-sha256.txt
├── git-status-before.txt
├── git-status-after.txt
├── image-index.txt
├── image-inspect.json
├── container-toolchain.txt
├── cargo-metadata.json
├── cargo-tree.txt
├── cargo-tree-features.txt
├── cargo-tree-duplicates.txt
├── cargo-deny-sources.txt
├── cargo-audit.json
├── cargo-deny.txt
├── audit-exit-codes.json
├── advisory-db-revision.txt
├── checksums.sha256
├── run.log
└── .work/
```

schema 2 manifest 至少记录 evidence/run ID、开始/结束时间、HEAD、前置 dirty、固定输入哈希、镜像 index digest 与本地 platform image ID、host/daemon/container architecture、Rust/Cargo 版本、直接依赖与 feature、resolved package 数量、lockfile SHA-256、advisory DB revision、各门退出码、stage、outcome、总退出码、lockfile 是否写入仓库和精确残留。

`checksums.sha256` 覆盖所有已完成且不会再变化的固定输入与证据；它不包含自身和持续写入的 `run.log`。早期失败无法取得的 manifest 字段使用 `null` 或明确 `unavailable`，不得填默认成功值。证据不得包含 token、credential、私钥、完整 host 路径、真实身份/消息、endpoint database 或环境变量转储。

## 清理与恢复

- trap 只删除名称与 `org.radishlink.sw-g2-openmls-0.9.run=<run-id>` label 同时匹配的本轮容器；label 不匹配时不删除并将 run 判为 `STOP`；
- 正常退出后必须以精确 label 复核容器残留为零；不创建 network/volume，因此不得运行对应批量清理；
- `SIGKILL` 或执行器中断后只读盘点：

```bash
docker ps -a --filter label=org.radishlink.sw-g2-openmls-0.9.run
docker image inspect rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663
```

- fixed image、artifact、`.work` cache 与 source gate 通过后生成的仓库 `Cargo.lock` 默认保留；删除或回滚任何一项都需要复核精确目标并另行授权；
- 不运行 `docker system prune`、`docker image prune`、宽泛 label 删除、递归 artifact 清理、`git reset`、`git checkout` 或手工 lockfile 修复。

## 当前停止点与未来授权措辞

本文精确方案已接受，单元 A 已完成。当前没有执行 Docker，没有网络访问、依赖下载、lockfile、审计结果或 `SW-EXP-004` artifact；单元 B 仍未授权，且在 45 分钟总时限与 5 GiB 运行期预算的控制机制关闭前不申请执行。

未来授权必须明确指出授权单元：

- 单元 A：按本文文件清单实施最小骨架并运行列出的无网络静态验证；
- 单元 B：在 A 与运行上限控制改进均已提交、工作区干净后，执行一次 `./scripts/run-sw-g2-openmls-0.9-spike.sh prepare`，接受本文列出的 Docker、默认出站网络不具备域名 allowlist、第三方审计工具编译、最多 5 GiB 保留数据、可能新增 Cargo 生成的 lockfile，以及 45 分钟上限。

任何只写“接受文档”“继续下一步”或此前只授权 A 的表述都不自动授权 B。Phase A 即使 `PASS`，Phase B 仍必须重新形成精确包并另行授权；`SW-G2` 继续保持未通过。
