# SW-EXP-004 OpenMLS 0.9.0 实施骨架与 Phase A 精确授权包

- 状态：A5 implemented / new L3 bundle pending（2026-08-30；首次单元 C 已构建固定二进制，但 evidence finalizer 失败，run 无效；A5 已离线修正，尚无成功 bundle，Phase A 未重跑，Phase B 禁止）
- 日期：2026-08-30
- 证据编号：`SW-EXP-004`
- 前置门禁：[OpenMLS 0.9.0 静态门禁](sw-g2-openmls-0.9-spike-authorization.md)已接受
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文把已接受的 OpenMLS 0.9.0 静态门禁转换为必须依次、分别授权的动作。前三个单元已经执行并保留为历史合同；A3 后 deadline 结果又形成 A4、独立 bundle 构建与新的 Phase A 单元：

1. **实施单元 A**：新增只支持依赖解析的最小 crate 与受限 runner，执行无网络静态验证；
2. **运行控制单元 A2**：在不执行 runner 的前提下补齐 45 分钟 deadline、5 GiB 定期监测、信号收口与停止证据；
3. **L3 执行单元 B**：在 A/A2 已提交、工作区干净且再次明确授权后，只运行一次 Phase A，生成新 lockfile 并执行来源、许可证和 advisory 门。
4. **运行资源单元 A4**：离线实现固定、可验证的审计工具 bundle，Phase A 只读消费精确 bundle ID，并在 deadline/signal 下回填已经落盘的 partial evidence；
5. **L3 审计工具 bundle 构建单元 C**：已获授权执行一次；固定二进制构建与无网络版本验证成功，但 evidence finalizer 失败，因此整体为 `INVALID`，不构成成功 bundle；
6. **证据终结单元 A5**：不重跑 bundle，离线修正 manifest/checksum 原子终结、失败传播和 `PASS` 时序；
7. **L3 Phase A 执行单元 D**：只有未来新 bundle `PASS`、人工复核且再次单独授权后，才以精确 bundle ID 重跑一次 Phase A。

分段用于保证用户在任何联网、依赖下载、审计工具编译或 Docker 容器启动前，能够先审阅真实脚本。接受本文不授权 A 或 B；A 的授权不自动包含 B，B 的一次授权也不构成失败重试、Phase B、清理或其他候选的持续授权。

本包不选择 OpenMLS 作为产品实现，不构建或运行 OpenMLS 场景，不接入 `SW-V3/P0`，不迁移数据库，不修改 `SW-EXP-002`、`tools/t0/` 或任何产品协议，也不使用真实身份、联系人、消息、设备凭据或密钥。

## 固定基线

执行单元只能使用静态门禁已接受的基线：

- crate：`openmls =0.9.0`、`openmls_basic_credential =0.6.0`、`openmls_rust_crypto =0.6.0`、`openmls_sqlite_storage =0.3.0`、`openmls_traits =0.6.0`、`rusqlite =0.37.0`、`serde =1.0.229`、`serde_json =1.0.151`、`tls_codec =0.5.0` 与 dev dependency `tempfile =3.27.0`；
- 镜像：`rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`；
- 平台：`linux/arm64`，容器内必须为 Linux `aarch64`、`rustc 1.96.1`、`cargo 1.96.1`；
- 审计工具：`cargo-audit =0.22.2`、`cargo-deny =0.20.2`；A4 后只能由独立单元 C 使用 `cargo install --locked` 构建固定 bundle，Phase A 不再安装工具，也不得挂载构建 bundle 的 `.work`；
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
rusqlite = { version = "=0.37.0", features = ["bundled"] }
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
| 运行控制 monitor | 45 分钟 deadline、5 GiB 本轮目录定期监测、触发原因与离线自检 | 文件系统 quota、Docker 域名 allowlist、依赖或场景执行 |
| audit tool bundle builder | 使用固定镜像构建、无网络运行验证、manifest/checksum、90 分钟与 5 GiB 用户态上限、精确残留处理 | Phase A、候选依赖、产品构建、自动重试、`.work` 复用 |
| runner | 参数门、bundle 合同核对、隔离目录、镜像/平台核对、单次 Phase A、证据与精确残留处理 | Phase B、工具安装、重试循环、容器网络/端口、主机 Cargo home、真实数据 |

原单元 A runner 只接受一个参数 `prepare`。A4 后当前 runner 只接受 `prepare <audit-tool-bundle-id>`，bundle ID 必须是精确 run ID；无参数、缺失或多余参数、`run`、未知 action、未知 bundle 都必须在 Phase A artifact、Docker 或网络访问前以退出码 `2` 拒绝。A5 后 bundle builder 接受 `prepare` 与不触发 Docker/Cargo/网络的 `self-test`；其他参数均拒绝。两个脚本都使用 `set -euo pipefail`、`umask 077`，拒绝 symlink 输入、artifact root 偏移、run 目录碰撞和 label 不匹配的容器清理。

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

### 2026-08-30 运行控制实施单元 A2

用户在当前任务确认开始实施上一轮已经精确说明的无 Docker、无网络运行控制范围。A2 只修改或新增：

```text
scripts/run-sw-g2-openmls-0.9-spike.sh
scripts/monitor-sw-g2-openmls-0.9-run.py
docs/testing/sw-g2-openmls-0.9-phase-a-authorization.md
docs/testing/sw-g2-openmls-0.9-spike-authorization.md
docs/testing/sw-g2-openmls-spike-authorization.md
docs/security/e2ee-candidate-review.md
docs/security/e2ee-sw-g2-decision-package.md
docs/status/current.md
docs/status/d0-t0-p0-plan.md
docs/status/project-execution-plan.md
docs/README.md
```

- runner 固定 `2700 s` deadline 与 `5242880 KiB` 本轮目录预算；Python 标准库 monitor 每 `5 s` 统计一次 run 目录的 apparent size，达到任一边界先原子写入 `runtime-control-trigger.json`，再向父 runner 发送 `TERM`；
- 外部 Docker 查询、镜像拉取和容器运行改为受控子进程。runner 在 deadline、磁盘触发或外部信号后先终止当前受控子进程，最多等待 `5 s` 后使用 `KILL` 收口该精确子进程，再进入原有 label 核对、容器清理、残留盘点和 evidence finalizer；
- 5 GiB 是五秒周期监测和退出期 `du` 复核，不是文件系统 quota。单次采样间隔内可能短暂越过阈值，结论不得写成内核硬配额；达到或发现越界时本轮为 `STOP`，不得自动重试；
- schema 2 manifest 新增 `runtime_controls`，记录 timeout、disk budget、采样值、峰值、monitor 状态、信号、终止原因，以及 `docker-default-network-no-domain-allowlist`；monitor、snapshot 和可选 trigger 进入 checksum；
- 默认 Docker 出站网络仍没有域名 allowlist。A2 没有修改 Docker 网络、系统代理、防火墙或目标服务范围，只把该限制变成 manifest 和下一次 L3 授权的显式事实；
- 离线自检以临时合成目录和子进程覆盖 deadline 边界、磁盘边界、monitor 向父进程发 `TERM`、runner 主动停止 monitor 和无触发正常停止；不执行 `prepare`、Docker、Cargo、网络、依赖下载或 lockfile 生成；
- A2 已完成本地实现与离线验证，并与 runner、monitor 和状态文档一并形成 clean revision；未执行 push。单元 B 继续未授权。

A2 的精确离线验证入口为：

```bash
bash -n scripts/run-sw-g2-openmls-0.9-spike.sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/monitor-sw-g2-openmls-0.9-run.py self-test
./scripts/run-sw-g2-openmls-0.9-spike.sh
./scripts/run-sw-g2-openmls-0.9-spike.sh run
./scripts/check-repo.sh
git diff --check
```

2026-08-30 实际结果：Python 自检、runner shell 语法、合成 shell deadline/受控子进程收口、schema 2 manifest 离线渲染、两个参数负例、仓库基线与 diff 检查均通过；deadline shell 探针在 `SECONDS=2` 进入清理、`SECONDS=3` 完成受控子进程收口。`artifacts/sw-g2-openmls-0.9/` 不存在，未启动或调用 Docker、Cargo 与网络。

## 历史 L3 执行单元 B：一次 Phase A

本节记录 2026-08-30 已执行两次的历史合同，不再是当前可执行入口。A4 后 runner 已拒绝不带 bundle ID 的旧命令；新的 bundle 构建与 Phase A 分别以本文后续单元 C、D 为准，二者均未获 L3 执行授权。

### 前置条件

B 只有在以下条件全部成立并获得当前任务明确授权后才可执行：

1. 单元 A 与运行控制单元 A2 已通过上述离线验证并提交，工作区干净，runner、monitor 与新 crate 位于同一 HEAD；
2. 新候选目录首次执行前不存在 `Cargo.lock`；若未来已存在，runner 只能重生成并逐字比较，不得更新；
3. `SW-EXP-002` 的源码、lockfile、artifact、`.work` cache、advisory DB 和授权均不复用；
4. Docker daemon 可用，artifact root、输入和目标 lockfile 均不是 symlink；
5. 没有相同精确 run label 的残留；磁盘可用量不少于 5 GiB，且 45 分钟总时限与 5 GiB 运行期预算已具备经复核的强制或监控机制；
6. 用户已看到并接受本节的网络、代码执行、磁盘、Docker 与保留副作用。

### 唯一执行入口

```bash
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare
```

该历史命令现在会在 artifact、Docker 和网络前以退出码 `2` 拒绝，不得作为新执行授权引用。

一次授权只覆盖一次上述入口。外部服务失败、digest 不符、工具安装失败、解析漂移、许可证/advisory/source 拒绝或证据不完整都立即 `STOP`；不得自动重试。

### 固定动作顺序

runner 必须按顺序执行：

1. 创建唯一私有 run 目录，启动固定 45 分钟与 5 GiB 定期 monitor，记录 HEAD、clean 状态、host/daemon architecture、磁盘前置和 fixed image 是否已存在；
2. 若 exact-digest 镜像存在，只用 `docker image inspect` 保存 image ID、`RepoDigests` 与平台；不存在时先用 `docker buildx imagetools inspect` 核对 index digest，再执行一次固定的 `docker pull --platform linux/arm64`；
3. 在 `--network none --read-only` 的短生命周期容器内保存 `uname -sm`、`rustc -vV` 与 `cargo -vV`；任一平台或版本不符立即停止；
4. 在新的联网容器和本轮专用 `CARGO_HOME` / `CARGO_TARGET_DIR` 中运行 `cargo generate-lockfile`、`cargo fetch --locked --target aarch64-unknown-linux-gnu`，并把实际 `Cargo.lock` 与 SHA-256 保存到 artifact；
5. 安装固定审计工具，生成 `cargo metadata --locked --format-version 1`、普通 tree、feature tree 与 duplicate tree；显式核对 `hpke-rs 0.7.*` 解析节点包含 `experimental` feature；
6. 分别运行 source gate、`cargo audit --json` 与许可证/advisory gate，保存每个命令的退出码；主 `openmls` crate、crypto provider 与 storage backend 分别保留结论，不相互继承；
7. 只有 source gate 与固定 feature gate 均为零、输入和 HEAD 未变且目标不是 symlink 时，才把 Cargo 生成的 lockfile 原子写入 `tools/spikes/sw-g2-openmls-0.9/Cargo.lock`；写入后要求工作区只出现这一个预期路径。许可证或 advisory 拒绝时仍保留这份真实负向图，但不得进入 Phase B；
8. 删除本轮精确容器，停止 monitor，以退出期 `du` 再复核本轮目录，生成包含运行控制事实的 schema 2 manifest，再为所有已完成的固定输入与证据生成 checksum；报告 outcome、stage、退出码和残留，不执行任何场景。

若仓库已有 `Cargo.lock`，第 4 步必须在隔离副本重新生成并与其 SHA-256 完全一致；漂移立即停止且不得覆盖。runner 不执行 `cargo build`、`cargo test`、候选 build script、SQLite 构建或 OpenMLS 二进制；编译执行的第三方代码仅限固定 `cargo-audit` / `cargo-deny` 及其工具依赖，并被限制在容器和本轮 `.work`。

### Docker 与网络限制

- 工具链核对容器使用 `--network none`；依赖与审计容器只使用 Docker 默认出站网络，不创建 named network、不映射端口；
- 两类容器均使用 `--read-only`、宿主非 root UID/GID、`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit 512` 和专用 tmpfs；
- 依赖与审计容器上限为 4 CPU、4 GiB 内存；不挂载 Docker socket、SSH agent、真实 home、主机 Cargo cache、Git credential 或系统密钥目录；
- 预期访问仅为 Docker Hub（只在 exact image 缺失时）、crates.io index/download 与 GitHub RustSec advisory DB；当前 Docker 默认出站网络不实施域名 allowlist，这一限制必须在执行授权中明确接受；runner 不主动访问项目 Git remote，不 push，不创建 PR、Release 或部署；
- 不使用 `--privileged`、host network、`NET_ADMIN`、系统代理修改、VM、长期服务或后台守护进程。

## 预计副作用与上限

- 原预计持续 15–45 分钟；A3 后实测在 45 分钟内仍未完成固定审计工具准备，因此该估计已失效。monitor 当前仍从 runner 启动时累计耗时，每 5 秒复核并在达到 45 分钟时写入触发证据、终止受控子进程并进入精确清理，不自动重试。它是用户态 deadline 与信号收口，不是操作系统作业调度硬时限；
- 网络下载约 0.8–2.5 GiB，包含可能缺失的固定 Rust image、候选 crates、固定审计工具和当次 advisory DB；
- `artifacts/sw-g2-openmls-0.9/<run-id>/.work/` 与证据磁盘预算为 5 GiB。runner 继续要求启动前至少有 5 GiB 可用空间，并每 5 秒统计本轮目录 apparent size、在退出期以 `du` 复核；达到阈值即 `STOP`。该机制不是文件系统 quota，采样间隔内可能短暂越界；
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
├── runtime-control.json
├── runtime-control-trigger.json    # 仅 deadline、磁盘或 monitor 错误触发时存在
├── checksums.sha256
├── run.log
└── .work/
```

schema 2 manifest 至少记录 evidence/run ID、开始/结束时间、HEAD、前置 dirty、固定输入哈希、镜像 index digest 与本地 platform image ID、host/daemon/container architecture、Rust/Cargo 版本、直接依赖与 feature、resolved package 数量、lockfile SHA-256、advisory DB revision、各门退出码、运行 deadline、磁盘预算/当前值/峰值、monitor 状态、终止原因、默认网络不具备域名 allowlist、stage、outcome、总退出码、lockfile 是否写入仓库和精确残留。

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

## 2026-08-30 Phase A 执行结果

用户在获知唯一命令、Docker/网络、预计时长与下载、用户态 deadline、磁盘监测、默认保留和清理边界后，明确授权执行一次单元 B。

- 首次启动在任何 Docker、Cargo 或网络操作前因受限执行环境拒绝 Bash `/dev/fd` process substitution，以 `STOP/preflight`、退出码 `1` 结束；证据目录为 `20260830-085136-79099.fY2Gf7`。它只证明该受限环境不支持 runner 的日志重定向，不是候选依赖证据；
- 随后经当前任务明确批准在沙箱外重试同一唯一命令。clean revision 为 `af14ef970f9343e6dd25e5c20e7e3ee0c746ad33`，有效证据目录为 `20260830-085316-79789.Pc2ZKb`；
- fixed image 已存在，index digest 与本地 platform image ID 均为 `sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`；host、daemon 与容器分别为 `arm64`、`aarch64`、`aarch64`，容器内为 `rustc/cargo 1.96.1`；
- Cargo 更新 crates.io index 后在生成 lockfile 前退出 `101`。`openmls_sqlite_storage =0.3.0` 需要 `rusqlite ^0.37`，解析到 `rusqlite 0.37.0` / `libsqlite3-sys ^0.35.0`；本包另行固定的 `rusqlite =0.32.1` 引入 `libsqlite3-sys 0.30.1`。Cargo 禁止同一图同时包含两个 `links = "sqlite3"` 实现，因此该固定依赖基线不可解析；
- 最终 manifest 为 `STOP/dependency-audit`，退出码 `101`；未生成或写入 `Cargo.lock`，source、license/advisory、feature 四类门均未开始，advisory DB revision 不可用，不得推导任何许可证或安全结论；
- monitor 正常停止，耗时 `15029 ms`，本轮目录峰值 `4428 KiB`，未触发 45 分钟或 5 GiB 边界；checksum 全部通过，精确容器残留为 `0`，fixed image 和两份 ignored evidence 按约定保留；
- 本次不构建或运行 OpenMLS 候选，不进入 Phase B，不修改产品代码，不生成迁移证据，不重跑。修订 `rusqlite` 固定版本或移除直接依赖都会改变已接受基线，必须先形成新的静态差异评审和精确授权，不能在本包内直接修补。

## 2026-08-30 A3 固定 SQLite 依赖静态修订

用户明确授权继续执行无 Docker、无网络的静态修订单元。A3 的证据与边界为：

- 有效 Phase A 获取的 crates.io sparse index metadata 显示，`openmls_sqlite_storage 0.3.0`（checksum `e7a48acaffbed1bbed61c5030193e374ff4914331ed5f4a604bd5a4692c0a713`）直接要求 `rusqlite ^0.37`、启用 `bundled`，MSRV 为 Rust 1.91；
- `rusqlite 0.37.0`（checksum `165ca6e57b20e1351573e3729b958bc62f0e48025386970b6e4d29e7a7e71f3f`）要求 `libsqlite3-sys ^0.35.0`；其 `bundled` feature 继续映射到 `libsqlite3-sys/bundled` 与 `modern_sqlite`；
- spike 源码当前不直接调用 `rusqlite` API。保留直接依赖不是为了建立第二套 SQLite 入口，而是把 storage backend 的关键 native 依赖精确钉在 `=0.37.0`，并在 manifest 中显式记录 `bundled` 来源边界；
- A3 只把 `tools/spikes/sw-g2-openmls-0.9/Cargo.toml` 与 runner manifest 的 `rusqlite` 从 `=0.32.1` 对齐为 `=0.37.0`，同步当前专题与状态文档；不修改其他 crate、provider、feature、allowlist、镜像、审计工具、运行控制或 Phase B 拒绝入口；
- A3 不调用 Docker、Cargo 或网络，不生成 lockfile，不下载或安装依赖，不证明完整解析图可生成，也不形成许可证、advisory、构建、运行、迁移或产品能力结论；
- 再次执行 Phase A 仍是新的 L3 单元，必须基于 A3 clean revision 重新说明唯一命令、默认网络无域名 allowlist、预计时长/下载、45 分钟 deadline、5 GiB 定期监测、保留与精确清理，并取得当次明确授权。

## 2026-08-30 A3 后 Phase A 执行结果

用户在获知 A3 clean revision `851f3bb8e9c7e844d9f2c1c84abf64dfcf092388`、唯一命令、Docker/网络、预计资源、deadline、磁盘监测、保留和清理边界后，明确授权执行一次新的 Phase A。有效 run ID 为 `20260830-091344-87309.iyw1Dm`。

- fixed image 已存在，host、daemon 与容器架构分别为 `arm64`、`aarch64`、`aarch64`，容器内为 `rustc/cargo 1.96.1`；运行前工作区干净，仓库没有候选 `Cargo.lock`；
- Cargo 已成功锁定候选解析图。partial metadata 包含 264 个 package（含 workspace root），evidence `Cargo.lock` SHA-256 为 `850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49`；图中只有 `rusqlite 0.37.0` 与 `libsqlite3-sys 0.35.0`，并显式启用 `bundled`，因此 A3 已关闭此前的双 `links = "sqlite3"` 解析冲突；
- 该 lockfile 只存在于 ignored evidence，未原子写入仓库。runner 在受控容器返回前没有取得 `resolved_package_count` 或 `cargo_lock_sha256` shell 状态，因此 manifest 对应字段仍为 `null` / `unavailable`；checksum 已覆盖实际 evidence lock、metadata 和三份 tree 文件，不能把 manifest 缺省值误写成“没有生成 partial graph”；
- `cargo-audit 0.22.2` 已开始下载和安装，但 crates.io 传输多次出现 OpenSSL EOF / send failure，并由同一 Cargo 命令使用默认内部重试；runner 没有重启本轮。`cargo-deny 0.20.2` 尚未开始，RustSec advisory DB revision 不可用；
- source、audit、deny、feature 四个正式门均未返回退出码，不得推导来源、许可证、advisory 或 feature 通过；没有候选构建、运行、迁移或产品能力证据；
- monitor 在 `2704774 ms` 触发 `deadline_exceeded`，runner 收到 `TERM`、终止受控子进程并完成精确清理；最终为 `STOP/runtime-deadline`、退出码 `124`，结束时间距开始约 45 分 11 秒；
- monitor 记录的最终目录峰值为 `337380 KiB`，低于 5 GiB 预算；checksum 全部通过，精确容器残留为 `0`。仓库 `Cargo.lock` 仍不存在，工作区保持干净；fixed image 与三份 `SW-EXP-004` ignored evidence 按约定保留；
- 本次授权已经消耗，不自动重试。再次执行前必须先评审 45 分钟内安装固定审计工具的可行方式、受控复用/固定工具产物的证据边界，或重新论证 deadline；不得直接复用未校验 `.work`、放宽工具版本、跳过审计门或仅延长时限掩盖根因。

## 2026-08-30 运行资源单元 A4

用户在获知 A4 只实施和离线验证、不会调用 Docker/Cargo/网络、不会构建 bundle 或重跑 Phase A 后明确授权。A4 选择“独立固定二进制 bundle”，不直接复用上一轮 `.work`，也不延长 Phase A 的 45 分钟 deadline。

### 固定 bundle 合同

新增入口：

```bash
./scripts/run-sw-g2-openmls-0.9-audit-tools.sh prepare
```

该命令在 A4 时定义首次 L3 单元 C；该次授权已经执行并因 evidence finalizer 失败而消费完毕。未来相同入口只可在 A5 clean revision 上作为新的 L3 单元 C 另行授权。脚本在固定 Linux ARM64 Rust image 中以 `cargo install --locked` 构建 `cargo-audit 0.22.2` 与 `cargo-deny 0.20.2`，再于同一 fixed image 的 `--network none` 容器中执行两个 `--version`。构建单元使用独立 label、独立 Cargo home/target、4 CPU、4 GiB 内存、90 分钟 deadline 和 5 GiB 五秒周期目录监测；构建使用 Docker 默认出站网络且没有域名 allowlist，不映射端口。它不下载候选 crate、不生成候选 lockfile、不运行候选审计或 Phase B。

成功 bundle 固定保留：

```text
artifacts/sw-g2-openmls-0.9-audit-tools/<bundle-id>/
├── bundle/bin/
│   ├── cargo-audit
│   └── cargo-deny
├── cargo-audit-version.txt
├── cargo-deny-version.txt
├── container-toolchain.txt
├── git-status-before.txt
├── git-status-after.txt
├── image-index.txt
├── image-inspect.json
├── manifest.json
├── runtime-control.json
├── checksums.sha256
├── run.log
└── .work/                    # 仅保留，不是 bundle 信任或消费边界
```

A4 原定的 schema 1 / `sw-exp-004-audit-tools-v1` 没有产生任何有效 bundle。A5 新增 consumer 必需的 manifest filter 摘要，因此未来成功证据显式升级为 schema 2 / `sw-exp-004-audit-tools-v2`，不以同一版本静默收紧旧格式。v2 manifest 固定 image/index/platform、Rust/Cargo、请求与实报工具版本、二进制 SHA-256、builder、runtime monitor 与 manifest filter SHA-256、运行控制、工作区和精确残留。`PASS` 只在两个二进制为唯一 `bundle/bin` 项、无 symlink、无网络运行验证成功、输入未变、工作区前后干净、残留为零，并且非空有效 manifest 与精确 checksum 集已经重新验证后成立；finalizer 将二进制权限收紧为 `0555`。checksum 精确覆盖两个被消费的二进制和九个固定公共证据文件；不覆盖 `.work`、自身或持续写入的 `run.log`。

### Phase A 只读消费与 partial evidence

当前 Phase A 唯一入口变更为：

```bash
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare <bundle-id>
```

runner 在创建 Phase A artifact、查询 Docker 或访问网络前完成下列核对：精确 ID 格式和路径、无 symlink payload、`bundle/bin` 只有两个不可写可执行文件、manifest 为固定 contract 的 `PASS`、image/platform/Rust/Cargo/工具版本/90 分钟 bundle 上限/5 GiB 上限/网络口径/clean 状态/残留均匹配、checksum 路径集合完全一致且全部通过、manifest 中的二进制摘要与实际文件一致。不得自动选择 `latest`、模糊匹配或降级到上一轮 `.work`。

通过后，Phase A 只把 `bundle/bin` 挂载到 `/audit-tools/bin` 且为 `readonly`，以绝对路径执行两个工具；候选容器不再运行 `cargo install`，也不挂载 bundle `.work`。Phase A 自身仍保持 45 分钟与 5 GiB 监测、fixed image、默认出站网络无域名 allowlist、无端口、非 root、只读根文件系统和原有 source/license/advisory/feature 停止线。schema 3 Phase A manifest 新增 bundle contract、ID、manifest SHA-256、两个工具版本和二进制 SHA-256。

此前 signal/deadline 在受控 Docker 子进程返回前会跳过 shell 后处理，使实际存在的 evidence lock 与 metadata 在 manifest 中显示为 `unavailable`。A4 cleanup 现在只回填已经安全落盘的 lock SHA-256、resolved package 数量、advisory DB revision 和已有 gate 退出码；不会在异常路径补跑 feature gate、伪造未执行门或提升仓库 lockfile。正常路径仍显式执行 feature gate 并写入统一退出码文件。

### A4 验证与未执行边界

A4 的离线验证入口为：

```bash
bash -n scripts/run-sw-g2-openmls-0.9-audit-tools.sh
bash -n scripts/run-sw-g2-openmls-0.9-spike.sh
./scripts/run-sw-g2-openmls-0.9-audit-tools.sh
./scripts/run-sw-g2-openmls-0.9-audit-tools.sh run
./scripts/run-sw-g2-openmls-0.9-spike.sh
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare
./scripts/run-sw-g2-openmls-0.9-spike.sh prepare invalid-bundle
PYTHONDONTWRITEBYTECODE=1 python3 scripts/monitor-sw-g2-openmls-0.9-run.py self-test
./scripts/check-repo.sh
git diff --check
```

这些负例必须在 artifact、Docker、Cargo 和网络前以退出码 `2` 拒绝。A4 不创建成功 bundle、不执行 Phase A、不修改仓库 `Cargo.lock`、不安装或下载任何内容、不访问远程、不 push；只证明静态合同和离线收口已实现，不能证明工具二进制实际可构建或 Phase A 可通过。

2026-08-30 实际结果：两个 shell 语法检查通过；builder 的无参数/`run` 与 Phase A 的无参数/缺 bundle/非法 bundle/格式正确但不存在的 bundle 共六个负例均返回 `2`，`artifacts/sw-g2-openmls-0.9-audit-tools/` 未创建；monitor 标准库自检通过。对既有 deadline evidence 的只读 partial-state 探针恢复出 lock SHA-256 `850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49` 和 `264` 个 package，与实际文件一致；同一 metadata 上的 feature 表达式离线返回零，但它只是 A4 逻辑探针，不追记为历史 Phase A 的正式 feature gate。仓库基线与 `git diff --check` 通过；未调用 Docker/Cargo/网络。

## 2026-08-30 L3 单元 C 结果与 evidence finalizer 单元 A5

用户在 A4 clean revision `39641eb` 上明确授权执行一次单元 C。唯一 run `20260830-103454-21213.oL36gJ` 复核了固定 image/platform 与 Rust/Cargo `1.96.1`，成功构建并在 `--network none` 容器中验证 `cargo-audit 0.22.2`、`cargo-deny 0.20.2`；二进制 SHA-256 分别为 `3f1eec4519d67df8d48c02ff366528155a664702b360388a69ae484549b6cb87` 与 `9ea2b1019a52961af71fcd589a8dd5e640169b8c02a9ab1d3d44d7ac0204fd45`，权限为 `0555`。monitor 在 `1472554 ms` 由 runner 正常停止，记录峰值 `1358445 KiB`；工作区前后干净，精确容器残留为零。

该 run 不能接受为 bundle。A4 的内联 jq program 受 shell 双引号展开破坏，jq 编译失败并留下 `0` 字节 `manifest.json`；随后的 `mv` 错误地遮蔽 jq 非零状态，cleanup 继续生成了包含空 manifest 摘要的 checksum，脚本还在 evidence finalizer 前过早打印 `PASS` 并最终错误返回 `0`。Phase A consumer 对该精确 ID 的离线前置校验以退出码 `2` 拒绝固定 manifest contract。run 原样保留为无效历史证据；其二进制、`.work`、checksum 和日志均不得被 Phase A 消费，也不得因二进制实际生成而改写为部分成功 bundle。

用户随后明确授权实施并提交 A5，同时禁止 Docker、Cargo、网络和 bundle 重跑。A5 把 jq program 移入独立固定 filter 文件并记录其 SHA-256；因该字段成为 consumer 必需合同，未来 manifest 升级为 schema 2 / `sw-exp-004-audit-tools-v2`，无效 v1 不具兼容资格。manifest 只有在 renderer 成功、输出非空、JSON 有效且核心合同字段匹配后才原子提升。checksum 拒绝空或无效 manifest；任何 manifest/checksum/PASS contract 失败都传播非零状态，移除同一 run 的不完整 finalizer 输出，并至多尝试生成显式 `STOP/evidence-finalize` 证据。成功消息只在 manifest、精确 checksum 集和摘要全部复核后打印；Phase A consumer 还要求 v2 与 A5 manifest filter 摘要字段存在。

A5 新增 `./scripts/run-sw-g2-openmls-0.9-audit-tools.sh self-test`，只在系统临时目录使用合成状态，覆盖有效 manifest/checksum、固定字符串与 null/boolean、renderer 失败不留 final/tmp、空 manifest 和无效 JSON 均拒绝 checksum。shell 语法、独立 jq filter 渲染、自检、既有无效 run 前后文件大小/mtime 比对、仓库基线和 `git diff --check` 均通过；未调用 Docker/Cargo/网络，未创建或重跑 bundle，未修改历史 artifact。

未来新的单元 C 仍须基于 A5 clean revision 重新说明并获得一次精确 L3 授权：唯一命令、Docker 默认出站网络无域名 allowlist、最多 90 分钟、5 GiB 五秒周期监测、4 CPU/4 GiB、可能复用 fixed image 并重新下载/编译工具 crate、保留新 bundle/`.work`，以及只清理精确 label 容器的方式。此前授权已经消费，失败不自动重试，无效 run 的 `.work` 不成为可信输入，也不自动进入单元 D。

单元 D 只有在某个 bundle `PASS` 且 manifest/checksum 人工复核后才可提出。授权必须写出精确 `<bundle-id>` 和唯一 Phase A 命令，并重新说明候选 crates/RustSec 网络、45 分钟、5 GiB、可能写入仓库 lockfile、证据与清理。D 不包含 bundle 重建、自动重试、Phase B、commit、push 或清理历史 evidence。

## 当前停止点与未来授权措辞

本文历史 Phase A 已执行；A3 关闭了已知 SQLite 解析冲突，A4 已离线实现固定审计工具 bundle 与 partial evidence 收口。首次单元 C 的工具二进制构建成功但证据终结失败，整体 run 无效；A5 已离线修正根因，但没有重跑。当前仍无成功 bundle；存在三份 Phase A `SW-EXP-004` ignored evidence、一份无效 bundle run 和一份仅位于最新 Phase A evidence 的 partial lockfile，仓库没有候选 `Cargo.lock`，也没有来源、许可证/advisory、feature、候选构建或场景实证。Phase A 单元 D 与 Phase B 禁止。

未来授权必须明确指出授权单元：

- 单元 A：按本文文件清单实施最小骨架并运行列出的无网络静态验证；
- 运行控制单元 A2：按本节文件清单实现并离线验证 deadline、磁盘 monitor、信号收口和证据；不包含 `prepare`、commit 或外部运行；
- 静态修订单元 A3：把直接 `rusqlite` 精确对齐为 `=0.37.0`、保留 `bundled` 并同步证据口径；不包含 lockfile、Docker、Cargo、网络或外部运行；
- 运行资源单元 A4：实现独立固定 bundle、精确校验与只读消费、partial evidence 回填；不包含 Docker/Cargo/网络、bundle 构建、Phase A 或 Phase B；
- 首次 L3 单元 C：已经消费的一次固定 bundle 构建授权；结果无效，不包含候选 Phase A、失败重试或 `.work` 复用；
- 证据终结单元 A5：离线修正 finalizer 并提交；不包含 Docker/Cargo/网络、bundle 重跑或历史 artifact 修补；
- 新 L3 单元 C：在 A5 clean revision 上重新构建一次固定 bundle；必须另行授权，不包含候选 Phase A、自动重试或旧 `.work` 复用；
- L3 单元 D：以一个已经复核的精确 bundle ID 执行一次 Phase A；不包含 bundle 重建、失败重试或 Phase B。

任何只写“接受文档”“继续下一步”或此前授权都不自动授权新的 C/D。此前 C 授权不构成重试授权，新 C 的授权不包含 D，D 的授权不包含失败重试。Phase A 即使 `PASS`，Phase B 仍必须重新形成精确包并另行授权；`SW-G2` 继续保持未通过。
