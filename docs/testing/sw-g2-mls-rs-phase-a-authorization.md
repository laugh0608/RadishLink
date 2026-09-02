# SW-EXP-003 mls-rs 0.56.0 实施与 Phase A 精确授权包

- 状态：Accepted（2026-09-02；A0/A1/A2 已分别形成 clean revision，单元 C 已复核 `PASS`；单元 D 在旧 transitive feature gate 正式 `STOP`；A3、D2 与 Phase B 均未授权）
- 日期：2026-09-02
- 证据编号：`SW-EXP-003`
- 前置门禁：[mls-rs 0.56.0 静态门禁](sw-g2-mls-rs-spike-authorization.md)已接受候选方向，执行就绪差异待本包关闭
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文把已接受的 mls-rs 0.56.0 静态候选方向转换为可审阅、可停止、逐单元授权的实施与 Phase A 方案。它只处理固定依赖图、来源、许可证、advisory、feature、Linux ARM64 工具链和证据合同，不选择 mls-rs 为产品实现，不构建或运行 MLS/AWS-LC/SQLite 候选，不接入 `SW-V3/P0`，也不使用真实身份、联系人、消息、设备凭据、数据库或密钥。

必须依次区分以下授权单位：

1. **共享运行资源单元 A0**：离线实现候选无关的运行 monitor、固定审计工具 bundle builder、独立 manifest filter 与 self-test；
2. **mls-rs Phase A 骨架单元 A1**：离线新增固定 crate 输入、拒绝 Phase B 的入口、受限 runner、候选 manifest filter 与 self-test；
3. **mls-rs 包限定 feature gate 单元 A2**：依据 D 的保留 metadata 与 crate source，离线把按 feature 名称全局拒绝改为固定 package/版本、解析集合、alias 展开和 provider 依赖边联合判定；
4. **D2 固定图消费合同单元 A3（Proposed）**：离线实现只读验证 D 最终 evidence、以其 `Cargo.lock` 固定新 run 图、升级 manifest 合同与负例；当前未授权；
5. **L3 通用审计工具 bundle 单元 C**：在 A0 clean revision 上构建一次固定 `cargo-audit` / `cargo-deny` bundle，并以无网络容器验证版本；
6. **L3 mls-rs Phase A 单元 D**：在 A1 clean revision 上只读消费一个精确、已复核的通用 bundle，生成独立 lockfile 并执行完整 gates；
7. **L3 mls-rs 固定图复核单元 D2（Proposed）**：A3 clean revision 后只运行一次新 evidence，重新执行当前 source/audit/deny/feature gates；当前未授权；
8. **Phase B**：只有未来获授权的 Phase A 完整 `PASS`、许可证人工复核与非实现者证据复核都通过后，才另建精确包；当前不存在实现或执行授权。

本文的接受只冻结精确方案，不自动授权任何实施单元。A0、A1 与 A2 已分别获得一次明确授权并离线实施；A2 不重写 D 的历史 `STOP`，也不包含 D2、Cargo、Docker、网络、lockfile 提升、commit 或 Phase B。C 不包含 D，任一 L3 授权不包含失败重试、Phase B、清理、push 或其他候选。

## 固定基线

### 候选依赖

首轮只允许静态门禁已接受的精确直接依赖：

| crate | 固定版本 | 允许 feature |
| --- | --- | --- |
| `mls-rs` | `=0.56.0` | `default-features = false`；`std`、`private_message`、`out_of_order`、`prior_epoch`、`tree_index` |
| `mls-rs-crypto-awslc` | `=0.25.0` | `default-features = false`；`non-fips` |
| `mls-rs-provider-sqlite` | `=0.23.0` | `default-features = false`；`sqlite-bundled` |
| `mls-rs-codec` | `=0.7.0` | 无显式 feature；保留 crate 默认，解析必须精确为 `default/std/preallocate` |
| `serde` | `=1.0.229` | 无额外 feature；仅保留已接受的脱敏 evidence dependency |
| `serde_json` | `=1.0.151` | 无额外 feature |
| `tempfile` | `=3.27.0` | 仅 dev dependency |

顶层 `mls-rs 0.56.0` 仍不得启用 `rfc_compliant`、`fast_serialize`、`rayon`、`external_client`、`test_util`、`benchmark*` 或 `fuzz_util`；AWS-LC provider 自身只允许 `non-fips`，不得解析出 `default`、`fips` 或 `post-quantum`；SQLite provider 自身只允许 `sqlite/sqlite-bundled`，不得解析出 `default` 或 `sqlcipher*`。FFI/UniFFI 与 `cfg(mls_build_async)` 继续禁止。

固定传递图只包限定接受以下集合与展开，不构成同名 feature 的通用 allowlist：

- `mls-rs-core 0.27.0` 解析 feature 必须精确为 `default/std/rfc_compliant/fast_serialize/x509`；其 `default` 必须仍精确展开为 `std/rfc_compliant/fast_serialize`，`rfc_compliant` 只能展开为 `x509`，`fast_serialize` 只能展开为 `mls-rs-codec/preallocate`；
- `mls-rs-codec 0.7.0` 必须精确为 `default/std/preallocate`；`mls-rs-identity-x509 0.21.0` 必须精确为 `default/std`；
- AWS-LC 与 SQLite 对 core 的 normal dependency 必须继续使用 core defaults；AWS-LC 对 `mls-rs-identity-x509` 的 normal dependency 必须继续使用该 crate defaults，identity crate 对 core 必须继续以 `default-features = false` 只启用 `x509`；
- 任何上述固定 package/version、解析集合、alias、provider dependency edge、provider、source 或禁止 feature 变化都 `STOP`。不得在运行中放宽版本范围、运行 `cargo update`、换 provider、加入 prerelease 或用 feature fallback 猜测可用组合。

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

A0 已随独立批次提交形成 C 要求的 clean revision；没有 push。A1 随后另行授权实施；C、D 与 Phase B 继续保持未授权。

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

### A1 实施结果

2026-09-01 已按单次明确授权完成 A1：新增精确 crate manifest、无 advisory/license/source 例外的 `deny.toml`、始终以 `2` 拒绝场景命令的 `main.rs`、只允许 `prepare <bundle-id>` 的 Phase A runner、schema 1 / `sw-g2-candidate-phase-a-v1` renderer 与综合离线 checker。

runner 固定只读消费 `sw-g2-rust-audit-tools-v1`，在当时 D 与未来另获授权的 D2 中只允许生成/下载/审计依赖图，不编译或运行 MLS/AWS-LC/SQLite；source 与 feature 均为零后才原子提升 lockfile，任何 gate、运行控制、finalizer 或精确残留异常都保留真实 `STOP/INVALID`。A1 离线 checker 当时已覆盖精确 TOML/feature/allowlist、唯一文件集、Phase B 硬拒绝、bundle contract、容器限制、manifest renderer、参数/selector，以及 `fips`、第二 crypto provider、git source 负例；A2 在此基础上扩充包限定解析图负例。

A1 没有新增 `Cargo.lock`，没有执行 runner `prepare`，没有创建 `artifacts/sw-g2-mls-rs/`，没有调用 Docker、Cargo 或网络，也没有构建/运行候选或修改 OpenMLS 历史实现。A1 实施授权本身不包含 commit；提交动作随后另获明确授权并形成 D 要求的 A1 clean revision，没有 push。

## 单元 A2：包限定 feature gate 离线修订

### 决策依据

D 的保留 metadata、feature tree 与 crates.io source 证明，旧 gate 按 feature 名称扫描全部 `mls-rs*` package，混淆了顶层聚合 feature 与 core 同名 alias：

- `mls-rs-core 0.27.0/rfc_compliant` 只展开为 `x509`，不是顶层 `mls-rs 0.56.0/rfc_compliant` 对 `private_message/custom_proposal/out_of_order/psk/x509/prior_epoch/by_ref_proposal` 的聚合；
- `mls-rs-core 0.27.0/fast_serialize` 只展开为 `mls-rs-codec/preallocate`；直接依赖 `mls-rs-codec =0.7.0` 已通过 crate 默认 feature 启用同一叶子；
- AWS-LC 无条件依赖 `mls-rs-identity-x509`，后者已显式启用 `mls-rs-core/x509`。只禁止 core alias 不会从固定图移除 X.509 叶子或 AWS-LC 的 X.509 源码面。

因此，A2 接受的是固定 package/version 下的精确 alias 与已存在叶子，不接受顶层同名 feature，不接受 provider 自身 defaults，也不把“RFC compliant”名称升级为完整互操作或安全结论。若未来要求最终二进制不含 X.509 面，或拒绝 codec 预分配路径，必须另行评审 provider/manifest/source；不得借 A2 推导。

语义与风险边界同时冻结：core `fast_serialize` 只是映射 codec `preallocate`；它让 `mls_encode_to_vec` 按 `mls_encoded_len` 预分配，并让 collection 迭代编码先计算长度、写长度前缀、`reserve` 后直接编码，以避免中间 buffer。在所有 `MlsSize` 实现正确时线格式不变，但自定义实现的长度不一致会让长度前缀与实际编码不一致，整数边界、容量溢出和输入驱动分配仍需负例/资源测试；现有证据不能把它写成已证明安全或已知漏洞。core `rfc_compliant` 只是编译 X.509 credential 支持；它不会替应用选择 credential、完成 Authentication Service 绑定或证明跨实现互操作，自定义 `IdentityProvider` 仍须拒绝未批准的 X.509。精确 alias gate 会在上游 feature/依赖边重构时 fail closed，维护代价是每次版本变化都重新核对 source 与固定图，而不是沿用名称放行。

### 允许范围

| 路径 | 允许内容 |
| --- | --- |
| `scripts/run-sw-g2-mls-rs-spike.sh` | 将 feature gate 改为固定 package/version、解析集合、alias 展开与 provider dependency edge 联合判定 |
| `scripts/check-sw-g2-mls-rs-phase-a.sh` | 扩充真实结构 fixture 与顶层同名 feature、core 意外 feature/alias、provider dependency edge、provider default、FIPS/PQ/SQLCipher、FFI、第二 provider、path/git source 负例 |
| mls-rs 两份授权包、安全候选/决策包、状态/计划与文档索引 | 同步 A2 结论、历史 D 边界与 D2/Phase B 停止线 |

A2 不修改 `tools/spikes/sw-g2-mls-rs/Cargo.toml`、`deny.toml`、manifest schema/filter、版本、provider、source、allowlist 或历史 evidence；不生成或提升 `Cargo.lock`，不调用 Docker/Cargo/网络，不重跑 D，不进入 Phase B，也不 commit 或 push。

### A2 离线验证

```bash
bash -n scripts/run-sw-g2-mls-rs-spike.sh
bash -n scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-repo.sh
git diff --check
```

另以同一抽取 gate 对 D 保留的 `cargo-metadata.json` 做一次只读回归；该回归只证明新谓词识别既有固定图，不改变 D 的 manifest、checksum、退出码或历史 `STOP`。

### A2 实施结果

2026-09-02 已按单次明确授权完成 A2。runner 现在只对固定 package/version 接受上述 core/codec/X.509 alias 与解析集合，并同时冻结 AWS-LC/SQLite provider 自身解析集合、core/X.509 normal dependency edge、唯一 provider、唯一 root path source、其余全 crates.io source 和 FFI 禁止线；顶层同名 feature、provider default、FIPS、post-quantum、SQLCipher、额外 core feature、alias/依赖边漂移、第二 provider 与额外 path/git source 负例继续拒绝。

两个 shell 语法检查、综合离线 checker、D 保留 metadata 的只读 gate 回归、仓库门禁与 diff 检查均通过。没有调用 Docker、Cargo 或网络，没有修改历史 evidence、crate manifest、版本、provider、source、allowlist 或 manifest schema，没有生成/提升 lockfile、重跑 D、进入 Phase B、commit 或 push。

## 单元 A3：D2 固定图消费合同（Proposed，未授权）

### 路径选择

D2 推荐**只读消费 D 的最终 `Cargo.lock` 作为固定图种子，不重新解析版本**。理由是 D 的 94-package 图已经完成 source/audit/deny，唯一停止原因是旧 feature gate；重新运行 `cargo generate-lockfile` 会把 crates.io index 与传递版本漂移混入 A2 复核，无法再把结果归因于 gate 修订，也会构成新的版本选择。

固定种子只来自 `artifacts/sw-g2-mls-rs/20260901-135918-13430.mvBCS2/` 的 final evidence，不读取或复用其 `.work`、Cargo home、target、advisory DB 或其他可变 cache：

| 输入 | 固定值 |
| --- | --- |
| D clean revision | `36765755154dc88f8bd21605cbc25f5abf6bb828` |
| D outcome/stage | `STOP` / `feature-gate` |
| D final manifest SHA-256 | `704e439e66103d7c8ff0f92231be8589a802a7b5f4ba834086aaafec9f8c701a` |
| D checksums SHA-256 | `aeb904e2656cc6458125017edd84fd6732fbd658c793b77c6d0c230b7feac481` |
| D `Cargo.lock` SHA-256 | `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7` |
| D metadata SHA-256 | `632a9bca905426b32a36e08aac8ebdecb04f60ca598d629a99157d2c59c409f8` |
| D gate JSON SHA-256 | `64526a2beb6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| D package/gates | `94`；source/audit/deny `0`，历史 feature `1` |

`checksums.sha256` 同时覆盖当时的仓库输入；A2 已合法改变 runner/checker，因此 A3 不用当前工作区对整份历史 checksum 清单执行无差别 `-c`。它必须先固定清单文件本身的上述 SHA-256，再逐项核对 final manifest、lock、metadata 与 gate JSON 的清单记录、实际摘要及 manifest 字段，避免把预期的输入修订误报为 evidence 损坏。

### A3 精确实施范围

| 路径 | Proposed 变更 |
| --- | --- |
| `scripts/run-sw-g2-mls-rs-spike.sh` | 在创建新 artifact、查询 Docker 或访问网络前验证固定 seed 路径/非 symlink/摘要/manifest 字段；仓库无 lockfile 时只读复制 seed lock 到新隔离 repo，删除 `cargo generate-lockfile`，改用 `cargo fetch --locked`；禁止读取 D `.work` |
| `scripts/sw-g2-mls-rs-phase-a-manifest.jq` | 升级为 schema 2 / `sw-g2-candidate-phase-a-v2`，新增 `dependency_graph_seed`、`lockfile_seeded` 与 `mutable_cache_reused: false` |
| `scripts/check-sw-g2-mls-rs-phase-a.sh` | 固定上述 ID/摘要/字段；新增 seed 缺失、symlink、清单/manifest/lock/metadata/gate 摘要篡改、历史 gate 字段漂移、读取 `.work`、重新解析版本、schema 1 假通过等离线负例 |
| 本包与当前状态 | 同步 A3/D2 授权边界；不改历史 D 结论 |

A3 不修改 `Cargo.toml`、`deny.toml`、版本、provider、feature gate、source/allowlist 或任何历史 evidence；不生成仓库 `Cargo.lock`，不调用 Docker/Cargo/网络，不创建 D2 artifact，不重跑 Phase A，不进入 Phase B，也不 commit 或 push。A3 实施完成、离线门禁通过并另获 commit 授权形成 clean revision 后，才可申请 D2。

### A3 离线验证

```bash
bash -n scripts/run-sw-g2-mls-rs-spike.sh
bash -n scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-sw-g2-mls-rs-phase-a.sh
./scripts/check-repo.sh
git diff --check
```

checker 还必须证明 A3 只读验证 final seed files、拒绝 D `.work`，并继续用同一抽取 gate 对固定 metadata 返回零。接受本节只冻结方案，不授权 A3 实施。

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

### C 执行结果

2026-09-01 在 clean revision `c6e3a43a530f4af18cef9ab26a925a241649a16f` 上消费一次独立 L3 授权，唯一命令 `./scripts/run-sw-g2-rust-audit-tools.sh prepare` 返回 `0`，没有重试。run `20260901-134500-6665.ARcd4F` 形成 schema 1 / `sw-g2-rust-audit-tools-v1` `PASS` bundle；manifest SHA-256 为 `79bdf71ba29632fb05a1097431f4c1a2a2c7fbd2f183f3685e808de143dbcad5`，11 项 checksum 已从仓库根全部复核。

固定镜像此前已存在，身份仍为 `rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663` / `linux/arm64`。构建容器通过默认出站网络访问 crates.io；无网络验证确认 `cargo-audit 0.22.2` 与 `cargo-deny 0.20.2`。两个 `0555` 非 symlink 二进制 SHA-256 分别为 `3f1eec4519d67df8d48c02ff366528155a664702b360388a69ae484549b6cb87` 与 `9ea2b1019a52961af71fcd589a8dd5e640169b8c02a9ab1d3d44d7ac0204fd45`。

monitor 记录 `206562 ms`、峰值 `1358459 KiB`，未触发 90 分钟或 5 GiB 停止线；原始 runtime control 以父进程正常请求停止记录 `runner_requested_stop`，成功 finalizer 在 manifest 中登记 `completed`。工作区前后干净，精确 run label 的独立查询残留为零。约 `1337960 KiB` evidence、`.work`/cache 与 fixed image 默认保留；没有下载 mls-rs/AWS-LC/SQLite 候选、生成候选 lockfile、执行 D/Phase B、commit、push 或清理。

## 单元 D：mls-rs Phase A（历史授权与结果）

D 的原授权只有在以下值全部实际存在并写入当次授权说明后才能申请：

- A1 clean revision 的完整 commit；
- C 的精确 bundle ID、`sw-g2-rust-audit-tools-v1` manifest SHA-256、两个工具版本与二进制 SHA-256；
- clean worktree、固定 image/platform 与输入摘要；
- 唯一命令中的真实 `<bundle-id>`，不得使用 placeholder、latest、其他路径或自动发现。

D 当时冻结的唯一命令形态为：

```bash
./scripts/run-sw-g2-mls-rs-spike.sh prepare <bundle-id>
```

真实 bundle ID 已在 D 的单独执行授权中给出并消费；本节只保留历史合同，不构成 D2 或任何重跑授权。

### D 的动作

1. 在创建 candidate artifact、查询 Docker 或访问网络前，拒绝 dirty worktree，复核精确 bundle contract/ID/path、无 symlink payload、manifest/checksum、工具版本/摘要、bundle clean revision 与零残留；
2. 创建私有 `artifacts/sw-g2-mls-rs/<run-id>/`，启动 45 分钟、5 GiB、五秒周期 monitor；记录输入 SHA、HEAD、工作区、磁盘、Docker daemon、image 和精确 label pre-state；
3. 无网络工具链容器以 `1 CPU/512 MiB` 验证 Linux `aarch64` 与 Rust/Cargo；候选容器以 `4 CPU/4 GiB`、Docker 默认出站网络且无域名 allowlist访问 crates.io 与 GitHub RustSec，不映射端口；
4. 使用本轮全新 Cargo home/target 生成 lockfile，保存 `cargo metadata --locked`、普通/feature/duplicate tree；不读取主机 Cargo home，不复用任何 OpenMLS `.work`；
5. 只读挂载固定 bundle，执行 `cargo-deny check sources`、`cargo-audit audit --json`、`cargo-deny check advisories licenses` 与固定 feature gate；
6. feature gate 至少证明直接版本/feature 精确匹配、禁用列表未出现、AWS-LC `non-fips` 与 SQLite `sqlite-bundled` 路径唯一、没有其他 crypto/storage provider、没有 git/path/patch source；
7. source 与 feature 为零、输入/HEAD 未变且目标安全时，才原子新增 `tools/spikes/sw-g2-mls-rs/Cargo.lock`。许可证/advisory `STOP` 时仍保留已复核负向图；runner 不自动暂存、提交或 push；
8. 任何 gate 非零、tool/runtime/finalizer 异常或残留都终结为真实 `STOP`/`INVALID`，保留 partial evidence，不补跑、换版本/provider、放宽 allowlist、添加 ignore 或进入 Phase B。

### D 执行结果

2026-09-01 在 clean revision `36765755154dc88f8bd21605cbc25f5abf6bb828` 上消费一次独立 L3 授权，唯一命令使用 bundle `20260901-134500-6665.ARcd4F`；run `20260901-135918-13430.mvBCS2` 在第 6/8 步以 `STOP/feature-gate`、退出码 `24` 终止，没有重试。固定图共 94 个 package，evidence lock SHA-256 为 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`；仓库 lockfile 未写入。

顶层 `mls-rs 0.56.0` 的 `std/private_message/out_of_order/prior_epoch/tree_index`、AWS-LC `non-fips`、SQLite `sqlite-bundled`、唯一 provider 与 crates.io source 均匹配。失败来自 transitive `mls-rs-core 0.27.0`：其默认 feature 为 `std/rfc_compliant/fast_serialize`，而 `mls-rs-crypto-awslc 0.25.0` 与 `mls-rs-provider-sqlite 0.23.0` 都以默认 feature 依赖该 core，实际图因此启用已接受 gate 明确禁止的 `rfc_compliant` 和 `fast_serialize`。这不是网络、工具或重复 provider 故障，不得通过自动放宽 gate、patch/fork 或换 provider 处理。

source/audit/deny exit code 均为 `0`；`cargo-audit 0.22.2` 基于 RustSec revision `72f8b23d78ea6c4c9ded301a4c6ec4260e8b4c27` 未发现 vulnerability 或 warning。`cargo-deny` 报告 sources/advisories/licenses `ok`，只有 allowlist 中 `BSD-2-Clause` 未在本图遇到的信息 warning。manifest SHA-256 为 `704e439e66103d7c8ff0f92231be8589a802a7b5f4ba834086aaafec9f8c701a`，25 项 checksum 已从仓库根全部复核。

monitor 记录 `55761 ms`、峰值 `228844 KiB`，工作区前后干净且精确 run label 的独立查询残留为零。约 `254512 KiB` evidence/`.work`/cache、固定镜像与通用 bundle 默认保留；没有编译/运行候选、生成密钥/数据库、提升仓库 lockfile、执行 Phase B、push 或清理。结果文档随后另获 commit 授权并形成 clean revision。

### D 的预计影响

- 预计 15–45 分钟，45 分钟与 5 GiB 由五秒用户态 monitor 执行；网络量取决于固定候选 crates 与当次 RustSec DB；
- Phase A 只解析、下载和审计，不编译或运行 mls-rs、AWS-LC、SQLite，也不创建真实/合成密钥和数据库；
- fixed image、bundle、本轮 evidence、候选 `.work`/cache 与可能新增的仓库 lockfile 默认保留；精确容器清理后必须复核残留为零；
- 不访问远程 Git，不修改系统配置，不启动 VM/长期服务，不操作硬件或射频。

## 单元 D2：固定 94-package 图 Phase A 复核（Proposed，未授权）

D2 只有在 A3 已形成 clean revision、仓库仍无 mls-rs `Cargo.lock`、固定 seed 与通用工具 bundle 再次只读复核通过时，才可申请一次 L3 授权。唯一命令保持：

```bash
./scripts/run-sw-g2-mls-rs-spike.sh prepare 20260901-134500-6665.ARcd4F
```

固定工具与运行边界不变：bundle manifest SHA-256 为 `79bdf71ba29632fb05a1097431f4c1a2a2c7fbd2f183f3685e808de143dbcad5`，`cargo-audit 0.22.2` / `cargo-deny 0.20.2` 二进制 SHA-256 分别为 `3f1eec4519d67df8d48c02ff366528155a664702b360388a69ae484549b6cb87` 与 `9ea2b1019a52961af71fcd589a8dd5e640169b8c02a9ab1d3d44d7ac0204fd45`；镜像仍为 Rust 1.96.1 的固定 Linux ARM64 digest。候选容器使用默认出站网络且无域名 allowlist，只下载 seed lock 指定 crates 和当次 RustSec DB；新 run 使用全新 Cargo home/target，不编译或运行候选。

D2 预计 15–45 分钟，五秒用户态 monitor 执行 45 分钟/5 GiB 停止线；候选容器为 4 CPU/4 GiB，工具链无网络验证为 1 CPU/512 MiB。新 evidence、`.work`/cache、fixed image、bundle 与可能提升的仓库 lockfile 默认保留；只清理名称和精确 run label 同时匹配的本轮容器并复核零残留，不做全局 Docker 清理。

判定顺序固定：

1. seed、A3 clean revision、输入、bundle、image、空间、Docker 与零残留任一前置失败即 `STOP/INVALID`，不访问候选网络；
2. 新 evidence `Cargo.lock` 必须逐字等于 seed，SHA-256 必须仍为 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`，解析 package 数必须仍为 `94`；任一漂移 `STOP`；
3. source 与 package-qualified feature 均为零时，才允许按既有原子路径提升该固定 lockfile；即使当前 audit/deny 随 RustSec 或许可证结果变为非零，也保留固定负向图但 D2 为 `STOP`；
4. source/audit/deny/feature 全部为零、schema 2/v2 manifest、checksum、输入不变、运行控制与零残留全部通过时，D2 才为 `PASS`；
5. 任一失败保留 partial/final evidence，不自动重试、不换版本/provider/source、不重新解析、不放宽 gate/allowlist、不清理、不 commit/push，也不进入 Phase B。

D2 `PASS` 仍只证明该固定图在记录的 RustSec revision 与门禁下通过 Phase A。人工许可证复核与非实现者 evidence 复核完成后，才可另行设计 Phase B；本节不构成 A3、D2 或 Phase B 授权。

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

历史 D manifest 使用 schema 1 / `sw-g2-candidate-phase-a-v1`。Proposed D2 升级为 schema 2 / `sw-g2-candidate-phase-a-v2`，除既有 candidate/evidence/scenario/run、outcome/stage、clean revision、fixed image/platform/toolchain、精确 bundle contract/ID/manifest/binary 摘要与只读挂载、direct dependencies/features、resolved package count、lock SHA、gate exit codes、RustSec revision、输入摘要、runtime controls、网络边界、lockfile preexisting/written、零残留和 runner exit code 外，还必须记录固定 seed contract/run/revision/final 文件摘要、只读消费、`lockfile_seeded: true` 与 `mutable_cache_reused: false`。

只有四个 gate 全部为零、manifest 非空有效、输入/HEAD/工作区未变、runtime 正常、零残留、checksum 完整自校验，才能打印唯一 `PASS`。零 vulnerability 只覆盖固定 lockfile 与记录的 RustSec revision，不构成第三方安全审计或 `SW-G2` 通过。

## 当前停止点与后续授权

精确包已执行到 D；固定 94-package 图已形成完整 source/audit/deny 结果和正式历史 `STOP/feature-gate`。A2 只修正未来 gate 的包限定语义，不改写 D 的 manifest、checksum、退出码或结论。仓库 mls-rs lockfile 未生成，Phase B 未执行且继续禁止。

推荐保留 `mls-rs 0.56.0 + AWS-LC 0.25.0 + SQLite 0.23.0` 候选，不 patch/fork 或更换 provider。D2 已选择只读消费 D final lock、拒绝重新解析和旧 mutable cache 的路径；下一个最小授权单元是上述 A3 离线实施，不是 D2 运行。A3 尚未授权，D2 也不得执行。

笼统的“继续”“按计划做”或接受本文不授权 D2、Phase B、失败重试、清理、commit、push、gate/版本/provider/source/allowlist 变化和其他候选；这些始终是独立动作。
