# SW-G2 OpenMLS 0.8.1 受限 spike 执行授权包

- 状态：Phase A `STOP`（已生成并审计 lockfile；许可证与 RustSec 停止线触发；Phase B 禁止执行）
- 资料核对日期：2026-08-24
- 证据编号：`SW-EXP-002`（候选可行性，不是 `SW-V*`）
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)
- 目标读者：安全、协议、平台、测试与执行授权者

## 目的与非目标

本文把 `OpenMLS 0.8.1` 首轮 spike 收敛为两道可单独批准的 L3 操作：

1. Phase A 获取固定依赖、生成 lockfile，并执行许可证、来源和安全公告审计；
2. Phase B 只在 Phase A 复核通过后，于无网络 Linux ARM64 容器运行合成身份与不透明中继场景。

本文最初用于准备分段授权，现同时保留实际执行与停止证据。它不选择生产 E2EE 实现，不形成 ADR，不修改 `tools/t0/`，不运行 `SW-V*`，不使用真实身份、联系人、消息或设备密钥，也不涉及 VM、系统网络、HaLow、射频、采购、移动端或 `libsignal/mls-rs`。

`SW-EXP-002` 只回答候选能否在固定条件下进入正式验证设计。成功不能写成 RadishLink 已支持或已验证 E2EE。

## 固定上游与工具基线

### OpenMLS 直接依赖

本轮实施只允许在独立 crate `tools/spikes/sw-g2-openmls/` 声明下列直接依赖；不使用 git dependency、分支、`main`、通配主版本或 prerelease：

| crate | 固定版本 | 用途 |
| --- | --- | --- |
| `openmls` | `=0.8.1` | RFC 9420 状态机；只启用 `fork-resolution` |
| `openmls_traits` | `=0.5.0` | provider 接口 |
| `openmls_rust_crypto` | `=0.5.1` | RustCrypto provider |
| `openmls_basic_credential` | `=0.5.0` | 合成 `BasicCredential` 与签名 key pair |
| `openmls_sqlite_storage` | `=0.2.0` | 持久状态与重启边界 |
| `tls_codec` | `=0.4.2` | MLS 对象标准序列化 |
| `serde` | `=1.0.229` | spike 自有证据结构，只启用 `derive` |
| `serde_json` | `=1.0.151` | 证据与 SQLite codec |
| `tempfile` | `=3.27.0` | 仅 dev/test 临时目录 |

[`openmls-v0.8.1` workspace](https://raw.githubusercontent.com/openmls/openmls/openmls-v0.8.1/Cargo.toml)固定了 OpenMLS 各 crate 的对应版本；[`openmls 0.8.1` manifest](https://raw.githubusercontent.com/openmls/openmls/openmls-v0.8.1/openmls/Cargo.toml)显示 MIT 许可证及危险的 `content-debug/crypto-debug` feature。spike 明确禁止后两者，也不启用 extensions、libcrux、Wasm 或 test utility feature。

上表不是完整依赖清单。Phase A 必须由 Cargo 生成并保存 `Cargo.lock`，再以 lockfile 中的实际传递图作许可证和安全判断；人工不得编造或手改解析结果。

### Linux ARM64 执行镜像

- 镜像：Docker Official Image `rust:1.96.1-bookworm`
- 固定 multi-platform index digest：`sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`
- 目标：`linux/arm64` / `aarch64-unknown-linux-gnu`
- 容器内预期版本：`rustc/cargo 1.96.1`

[Docker Hub 固定镜像页](https://hub.docker.com/layers/library/rust/1.96.1-bookworm/images/sha256-7113930bd9ec13edc2103de1c875f326b87a682eff63f3970968e2e6884afcf7)记录上述 index digest 和 ARM64 构建输入。固定镜像不存在时保存 `docker buildx imagetools inspect` 后 pull；本地已存在 exact-digest 镜像时，保存 `docker image inspect` 的 image ID、`RepoDigests` 和 OS/architecture 并要求 `RepoDigests` 含同一 digest，不再为形式核对重复访问 registry。两条路径都必须在无网络只读容器保存 `uname -m`、`rustc -vV`、`cargo -vV`；任一结果不是固定 digest、`aarch64 Linux` 或 `rustc/cargo 1.96.1` 即停止。

OpenMLS 0.8.1 的[发布版 README](https://raw.githubusercontent.com/openmls/openmls/openmls-v0.8.1/README.md)只把 `aarch64-unknown-linux-gnu` 列为 CI 构建但未测试目标，因此交叉编译成功不能替代容器内实际运行。

### 审计工具

审计工具只安装在本轮忽略目录，不写入主机 Cargo home：

| 工具 | 固定版本 | 用途 |
| --- | --- | --- |
| `cargo-audit` | `=0.22.2` | 以当次 RustSec advisory DB 审计 `Cargo.lock` |
| `cargo-deny` | `=0.20.2` | 检查许可证、registry/source 与 advisory |

[`cargo-audit 0.22.2`](https://github.com/rustsec/rustsec/releases/tag/cargo-audit%2Fv0.22.2)和[`cargo-deny 0.20.2`](https://github.com/EmbarkStudios/cargo-deny/releases/tag/0.20.2)是本轮固定工具版本。工具自身只属于审计环境，不进入 RadishLink 产品依赖。

## 已实施的受限骨架

实施范围限定为：

```text
tools/spikes/sw-g2-openmls/
├── Cargo.toml
├── Cargo.lock
├── deny.toml
└── src/
    ├── evidence.rs
    ├── main.rs
    ├── scenario.rs
    └── store.rs
scripts/run-sw-g2-openmls-spike.sh
```

- `main.rs` 当前只提供 `phase-a-info`，并保留 `init`、`key-package`、`create-group`、`join`、`encrypt`、`decrypt`、`process-commit` 和 `inspect` 名称用于显式拒绝 Phase B；没有实现 MLS 场景，也未新增 CLI framework。
- `scenario.rs` 当前只维护 Phase B 命令清单与统一 `BLOCKED` 门禁，不编排场景、不复刻 MLS 状态机或密码原语。
- `store.rs` 当前只验证 artifact 相对路径不能绝对化或穿越；没有连接 OpenMLS SQLite provider，也没有创建覆盖层队列、去重或证据表。
- `evidence.rs` 当前只输出 Phase A 信息和 Phase B 阻断证据；未来即使获准扩展，也不得输出 plaintext、credential 私钥、key package 私有部分、会话密钥或数据库正文。
- `deny.toml` 只允许 crates.io registry；初始许可证 allowlist 为 `MIT`、`Apache-2.0`、`BSD-2-Clause`、`BSD-3-Clause`、`ISC`、`Unicode-3.0`、`Zlib`。出现其他表达式、未知来源或缺失许可证即停止，由人工复核，不自动加入例外。
- `run-sw-g2-openmls-spike.sh` 使用 `mktemp -d` 在固定 artifact root 下创建带时间戳、PID 与随机后缀的唯一 run 目录，并以 `umask 077` 收紧新建目录和证据文件；artifact 路径、所列源码输入和清理容器都拒绝符号链接或 label 不匹配。脚本不开放端口，不使用 `--privileged`、`NET_ADMIN`、host network、真实 home 或主机 Cargo cache。
- 仓库不再以可写方式挂入容器。脚本把固定输入复制到本轮 `.work/repo/`，仅挂载本轮 run 目录；容器在隔离副本中重新生成 `Cargo.lock` 并与待评审 lockfile 的 SHA-256 比较，任何漂移以退出码 `21` 停止，运行后宿主 lockfile 变化以退出码 `22` 停止。
- 未来 run 使用 manifest schema 2，记录开始/结束时间、最终退出码、container architecture、Rust/Cargo 版本、advisory DB revision、镜像 index digest 与本地平台 image ID；`checksums.sha256` 在 manifest 之后生成并包含 manifest、固定输入与实际存在的证据文件。

这些文件已在 Phase A 获明确授权后实施。当前实现仍硬阻断 Phase B；Phase A 审计 `STOP` 后不得为继续运行而添加 advisory ignore、放宽许可证 allowlist、更新传递依赖或改用 prerelease。

## Phase A：依赖获取与停止门

### 精确入口

已实施的唯一入口为：

```bash
./scripts/run-sw-g2-openmls-spike.sh prepare
```

脚本执行以下固定动作：

1. 只读检查 Git 工作区、Docker daemon、host/daemon architecture 和固定镜像是否已存在；
2. 若 exact-digest 镜像已存在，以 `docker image inspect` 核对 image ID、`RepoDigests` 和平台；否则运行 `docker buildx imagetools inspect` 核对 index digest；
3. 只在 exact-digest 镜像不存在时运行 `docker pull --platform linux/arm64`；本地复用与新拉取均再次保存并核对 image inspect；
4. 把已评审的 manifest、lockfile、deny 配置和源码复制到本轮忽略目录；在 `linux/arm64` 容器内以独立 `CARGO_HOME` / `CARGO_TARGET_DIR` 对隔离副本运行 `cargo generate-lockfile`，要求结果与仓库 lockfile 哈希完全一致，再运行 `cargo fetch --locked`；
5. 在同一隔离 cache 内运行 `cargo install cargo-audit --version 0.22.2 --locked` 与 `cargo install cargo-deny --version 0.20.2 --locked`；
6. 保存 `cargo metadata --locked --format-version 1`、`cargo tree --locked --target all`、`cargo audit --json` 和 `cargo deny check advisories licenses sources` 的完整退出码与脱敏输出；
7. 先生成 schema 2 manifest，再计算 `LICENSE`、spike 输入、manifest、metadata、tree 和审计报告的 SHA-256；然后停止，不自动进入 Phase B。

Phase A 允许容器访问 Docker Hub、crates.io index/download 和 GitHub RustSec advisory DB，不访问项目远程、不 push、不创建 PR 或 Release。外部服务不可达、镜像 digest 不符、lockfile 漂移、yanked crate、任何未解释 advisory、未知 registry/git source、未知或未许可许可证均为 `STOP`，不能通过 ignore、更新候选版本或添加例外继续。

### Phase A 预计影响

- 首次耗时约 15–40 分钟，取决于镜像和 crates 下载；
- 网络下载预估 0.8–2.0 GiB；
- 临时磁盘峰值预估不超过 4 GiB；
- 首次已授权 Phase A 会生成待评审的 `tools/spikes/sw-g2-openmls/Cargo.lock`；收口后的脚本要求该 lockfile 已存在，只在忽略的隔离副本中重新生成并比较，不再写入仓库；
- 会在 `artifacts/sw-g2-openmls/<run-id>/` 生成忽略的 metadata、审计与日志；
- Docker 全局状态会保留固定 Rust 镜像；无长期容器、端口或后台服务。

### 2026-08-24 Phase A 执行记录

- 授权范围：实施所列隔离 spike 骨架并执行 `./scripts/run-sw-g2-openmls-spike.sh prepare`；
- run ID：`20260824-200047-57540`；
- 已完成：仓库/Docker 只读预检，固定 multi-platform index digest 核对通过；
- `STOP` 位置：拉取固定 `linux/arm64` Rust 镜像；
- 原始错误：目标 layer 预期 `180206809` bytes，仅收到 `16909044` bytes，Docker 返回 `short read` / `unexpected EOF`；
- 未进入：镜像内架构/Rust 复核、Cargo 依赖解析、`Cargo.lock` 生成、审计工具安装、许可证/source/advisory 检查；
- 残留复核：没有本轮容器，固定镜像未完整存在；只保留忽略的失败日志、index 证据和 `STOP` manifest；
- 实现修正：prepare 脚本现保证在镜像拉取等早期阶段失败时也生成带 stage 与退出码的 manifest。

该失败只说明本次 Docker Hub 数据传输未完成，不证明固定镜像或 OpenMLS 候选不可用。按既定停止线不自动重试、不换 tag、不改 digest；再次执行同一 Phase A 仍需用户重新明确授权。

### 2026-08-24 Phase A 第二次执行记录

- 重新授权范围：再次执行相同固定 digest 的 `./scripts/run-sw-g2-openmls-spike.sh prepare`，不改变来源、版本、网络或停止线；
- run ID：`20260824-201212-60799`；
- 已完成：固定 index digest 再次核对通过；多个镜像 layer 下载完成，其中三个 layer 已完成 pull；
- `STOP` 位置：固定 `linux/arm64` 镜像仍未完成，达到授权包 40 分钟计划上限后，以 `INT` 终止同一进程，退出码 `130`；
- 未进入：镜像内架构/Rust 复核、Cargo 依赖解析、`Cargo.lock` 生成、审计工具安装、许可证/source/advisory 检查；
- 残留复核：没有本轮容器，固定镜像仍不能通过完整 digest inspect；Docker 内部可能保留已完成 layer，未获授权清理；只保留 24 KiB 忽略证据；
- manifest：自动记录 `outcome: STOP`、`stage: image-pull` 和 `exit_code: 130`，验证了早期失败证据修正。

两次结果共同说明当前 Docker Hub 固定镜像获取路径不稳定，但仍不能外推为镜像、OpenMLS 或 Linux ARM64 不可用。不得直接进入 Phase B。下一次操作应先评审继续复用 Docker layer cache，或改为另一个精确、可审计且单独授权的 ARM64 获取路径；任一路径都不能静默换源或放松 digest。

### 2026-08-24 固定镜像复用与 Phase A 审计记录

- 用户手动完成同一 exact-digest 镜像拉取；只读复核得到 image ID `sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663`、同值 `RepoDigests` 与 `linux/arm64`。
- run `20260824-214344-85824` 在工具链复核时暴露 login shell 覆盖官方 Rust `PATH` 的执行器缺陷；改为非 login shell 后，`rustc/cargo 1.96.1` 均可核对。run `20260824-214619-87761` 与 `20260824-214902-88874` 又分别在冗余 registry pull 和 OAuth token 请求遇到 `EOF`；脚本随后改为只有本地 exact digest 缺失时才访问 Docker Hub，并保留 digest-bound inspect 与容器内复核。
- 最终审计 run：`20260824-215104-90006`；固定镜像、Linux ARM64 和工具链复核通过，解析 229 个 crates.io package，生成 `Cargo.lock`，SHA-256 为 `274105e0173f675ebddff18b6f0f32e1bfed7bb2a7029d62b03f6284d3b47c98`。
- 来源检查通过：229 个上游 package 均来自 crates.io registry，没有 git dependency 或未知 source。
- 许可证检查失败：实际检查图中的 `hpke-rs 0.6.1`、`hpke-rs-crypto 0.6.1`、`hpke-rs-rust-crypto 0.6.1` 为 `MPL-2.0`，不在初始 allowlist；不得自动添加例外，仍需独立许可证复核。
- advisory 检查失败：`cargo-deny` 的检查图命中 `RUSTSEC-2026-0212`（`libcrux-secrets 0.0.5`，AArch64 constant-time swap/select）、`RUSTSEC-2026-0207` 与 `RUSTSEC-2026-0208`（`libcrux-sha3 0.0.8`）；`cargo-audit` 对完整 lockfile 共报告 6 个 vulnerability，另含 `libcrux-aesgcm 0.0.7` 与 `libcrux-chacha20poly1305 0.0.7` 条目。
- 当前固定图不能靠普通传递更新消除活跃停止项：`hpke-rs 0.6.1` 要求 `libcrux-sha3 ^0.0.8`，`libcrux-traits 0.0.6` 精确要求 `libcrux-secrets =0.0.5`。
- RustSec 数据库 revision：`851b9c93dc25a711144b70a007b5f3a4bd50e2e9`；审计退出码为 `cargo-audit=1`、`cargo-deny=5`，脚本按约定以 `20` 停止。
- 该 run 的原始 manifest 因生成顺序把 `stage` 记为 `evidence-finalize`，但 `prepare_exit_code=20`、审计退出码和报告内容完整；不回写原 artifact，脚本已修正为后续审计失败明确记录 `dependency-audit`。
- 所有登记在 `checksums.sha256` 的 manifest、lockfile、metadata、tree 和审计报告均复核通过；没有残留容器或后台进程。固定镜像保留；忽略目录保留约 1.5 GiB 的审计工具/cache 与证据，未获清理授权不删除。

以上结果是 `OpenMLS 0.8.1 + openmls_rust_crypto 0.5.1` 固定候选图的负向 Phase A 证据。它不证明 MLS 路线整体不可用，但明确禁止以该 prepared run 进入 Phase B。`mls-rs 0.56.0` 与[OpenMLS 0.9.0](sw-g2-openmls-0.9-spike-authorization.md)静态门禁均已于 2026-08-28 接受；OpenMLS 0.9.0 的[Phase A](sw-g2-openmls-0.9-phase-a-authorization.md)在 A3 后已生成可解析 partial graph，但在审计工具安装期间 deadline `STOP`。A4 已离线实现其独立固定工具 bundle，bundle 和新 Phase A 尚未执行，仍没有可复用的仓库 lockfile 或许可证/advisory 结论。不得直接复用任一 prepared run、采用未经审计的候选、手改 lockfile 或绕过 advisory/许可证停止线。

### 2026-08-28 实现静态收口

- 未重跑 Phase A、未构建 OpenMLS、未安装依赖，也未修改历史 artifact；最终 run `20260824-215104-90006` 的原始 manifest 和 checksum 继续按生成时状态保留；
- 脚本已关闭 run 目录碰撞、artifact/source 符号链接、默认权限、全仓库可写挂载和 lockfile 静默漂移路径；
- 新 manifest schema 2 与 checksum 顺序已覆盖本节上方列出的缺口，Phase B 仍在参数解析阶段硬阻断；
- 静态验证只覆盖 shell 语法、格式、文本门禁和未授权 action 的退出行为，不证明新 evidence finalizer 已在 Docker/Linux ARM64 中实际运行；任何新的 Phase A 仍需单独说明并授权。

## Phase B：无网络 Linux ARM64 可行性运行

Phase A 的 lockfile、许可证、来源和 advisory 结果必须先由非实现者复核；复核通过后仍需对 Phase B 单独授权。当前 Phase A 已因许可证与 advisory 停止，而且脚本只接受 `prepare`，所以下列原设计入口尚未实现并禁止执行：

```bash
./scripts/run-sw-g2-openmls-spike.sh run --prepared-run <run-id>
```

Phase B 的所有容器使用 `--platform linux/arm64 --network none --read-only`，只挂载对应节点状态、只读源码、准备 cache 和专用 tmpfs。每次 A/C 命令都是独立进程，A 不能挂载 C 状态，C 不能挂载 A 状态；B 只持有公开 `KeyPackage` 和不透明传输对象。

### 场景与判定

| ID | 场景 | 必须证明 | 失败条件 |
| --- | --- | --- | --- |
| `O01` | 平台与构建 | 容器为 Linux ARM64；`cargo test --locked --all-targets` 通过 | 只完成 cross-build、架构不符或 lockfile 变化 |
| `O02` | 离线首次联系 | C 生成 `KeyPackage`，A 经 B 获得并生成 `Welcome`，C 以重启后的独立进程加入两成员组 | A/C 需要直接共享私有状态，或 B 获得 KeyPackage 私有部分 |
| `O03` | 不透明消息 | A 的固定合成 sentinel 经 B 到 C，C 解密后哈希匹配；B 只记录对象 ID、大小、版本和哈希 | B 文件或日志出现 sentinel、密钥、credential 私有材料 |
| `O04` | 重启、重复与篡改 | A/C 跨进程恢复；重复密文不重复交付；bit flip、旧 epoch、错误 credential 被拒绝 | 静默接受、重复用户交付、错误被归为成功 |
| `O05` | 乱序与并发 | 有界乱序按候选能力处理；同时建组、并发 commit 和 fork 给出确定结果 | 结果依赖非记录时序，或状态无诊断地分叉 |
| `O06` | 应用提交边界 | 在 enqueue、process、receipt 前后触发固定 failpoint 并重启，不提前确认、不复活第二次交付 | key/nonce 重用迹象、确认先于状态落盘、回滚后接受重放 |
| `O07` | 中继删除接口 | 记录 OpenMLS 是否能支撑 origin-verifiable receipt 与最小 relay-clear proof 的身份绑定 | 为通过测试自造签名/MAC，或让 B 获得 read 状态/正文 |

`O07` 只形成接口可行性结论，不实现自制 relay-clear proof。若 OpenMLS 与选定 credential 无法安全提供所需验证面，结论是候选缺口，不以临时密码 helper 绕过。

故障注入只发生在 spike 自有应用提交点，不声称覆盖 OpenMLS/SQLite 内部每条写路径。Phase B 通过仍需 `SW-G3` 冻结的正式矩阵验证。

### Phase B 预计影响

- 预计耗时 5–15 分钟；场景阶段无互联网访问；
- CPU 峰值不超过本机可用核数的 50%，容器内存总上限 2 GiB；
- 创建若干带 `org.radishlink.sw-g2-openmls.run=<run-id>` label 的短生命周期容器；不创建 Docker network，不映射端口；
- 合成 identity/key/state 仅存在专用临时目录，结束时删除；
- 只保留脱敏 manifest、summary、日志校验值与 B 可见字段清单。

## 证据与数据边界

每轮保留：

```text
artifacts/sw-g2-openmls/<run-id>/
├── manifest.json
├── generated-lock-sha256.txt
├── container-toolchain.txt
├── advisory-db-revision.txt
├── audit-exit-codes.json
├── cargo-audit.json
├── cargo-deny.txt
├── cargo-metadata.json
├── cargo-tree.txt
├── checksums.sha256
└── run.log
```

以上是 Phase A 最小证据；`scenario-summary.json` 与 `b-visible-inventory.json` 只属于未来另行授权的 Phase B，不由 Phase A 占位生成。

schema 2 `manifest.json` 至少记录 Git revision、dirty 状态、镜像 index digest 与本地平台 image ID、host/daemon/container architecture、Rust/Cargo 版本、`Cargo.lock` 哈希、advisory DB revision、场景 ID、开始/结束时间和最终退出码。早期失败无法取得的字段使用 `null` 或明确的 `unavailable`，不能伪造默认值。

不得保留或提交 endpoint SQLite、私钥、完整 credential、随机种子原值、合成 plaintext、core dump 或包含敏感 feature 的日志。B inventory 只列相对对象名、类型、字节数和 SHA-256；日志中的合成节点 ID 固定为 A/B/C。

## 清理、恢复与残留复核

- 脚本 trap 只按本轮精确 container name 和 label 删除容器；不存在的目标不扩大匹配范围。
- 临时 cache/state 固定在 `artifacts/sw-g2-openmls/<run-id>/.work/`。删除前必须解析真实路径并确认它严格位于该 run 目录下；证据文件不随 `.work` 删除。
- `SIGKILL` 后先用以下只读命令定位残留，不自动删除其他项目资源：

```bash
docker ps -a --filter label=org.radishlink.sw-g2-openmls.run
docker image inspect rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663
```

- 固定 Rust 镜像默认保留并在交接中报告。只有确认它在 Phase A 前不存在、没有容器引用且用户授权清理时，才按完整 digest 删除；不清理 Docker 全局 cache。
- `Cargo.lock`、源码或 `deny.toml` 发生异常变化时保留 diff 和退出码，不 reset、checkout 或重新生成来掩盖差异。

## 授权单位与当前停止点

授权必须分别覆盖：

1. **实施 + Phase A**：新增所列 spike 文件，拉取固定镜像和 crates，生成 lockfile 并审计；
2. **Phase B**：在 Phase A 人工复核通过后，运行无网络 Linux ARM64 场景；
3. **可选清理镜像**：只在满足精确前置条件时执行，不包含在前两项默认授权中。

隔离 spike 骨架与 lockfile 已形成；Phase A 最终在许可证和 advisory 门 `STOP`，来源检查通过但安全与许可证条件未关闭。Phase B 不再是“待授权即可执行”，而是被本轮负向证据阻断；镜像与 1.5 GiB 忽略 cache 的清理也未授权。OpenMLS 0.9.0 A3 后的独立 Phase A 已生成 partial graph，但在审计工具安装期间 deadline `STOP`；首次固定工具构建因 evidence finalizer 失败而无效，A5 已离线修正但尚无新 bundle，仍不得复用任一 prepared run 进入场景。
