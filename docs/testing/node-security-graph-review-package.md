# Node 安全候选新依赖图精确评审包

日期：2026-10-24。状态：**评审输入与命令合同已编写；G1/G2 未授权、未执行，环境前置未通过**。目标读者为依赖、许可证与执行安全评审者。承接 [ADR 0006 D14](../adr/0006-node-identity-and-control-profile.md)，只准备新图、固定源码及差异证据；不构建/运行密码候选，不替代原 mls-rs R2 或 Phase B。

## 精确范围与基线

基线为接受 D11—D14 的提交 `5d2ebfc`；Node 依赖来自该提交的 `node/Cargo.toml`，旧安全图来自 `tools/spikes/sw-g2-mls-rs/Cargo.toml` / `Cargo.lock`。执行时必须记录包含本包的最终 clean commit、下列输入的 SHA-256，以及与该基线的范围差异；没有实际提交/hash 绑定不能运行。

本机已只读核对已有工具版本：Rust `1.97.1 (8bab26f4f 2026-07-14)`，完整 compiler commit `8bab26f4f68e0e26f0bb7960be334d5b520ea452`；Cargo `1.97.1 (c980f4866 2026-06-30)`；宿主 `aarch64-apple-darwin`。不安装 Rust、不添加 Linux target、不启动 Docker/UTM；metadata 准备不需要编译 Linux 标准库。实际 ARM64 Linux 编译仍是后续独立包。

旧图、旧 cache/evidence、Node manifest/lock 全部只读，不在它们所在目录运行 resolver。不修改旧 gate、source、allowlist、advisory ignore 或历史合同；不会以新图给旧 STOP 改判。

## 唯一候选 manifest 输入

以下内容是待执行工作区的 `input/Cargo.toml` 精确文本，当前只保存在文档中。它是为审查“Node 现有依赖 + D14 候选”的一次性输入，不是第二个产品配置入口。实施准备工具时须逐项对照上述基线并生成/核对，不能长期独立漂移。没有 root features、dev/build dependencies、patch、replace、git/path dependency 或额外 registry。

```toml
[package]
name = "radishlink-node-security-graph-review"
version = "0.0.0"
edition = "2024"
rust-version = "1.97"
publish = false
license-file = "LICENSE"

[workspace]
resolver = "3"

[lib]
path = "input.rs"

[dependencies]
rusqlite = { version = "=0.40.2", default-features = false, features = ["bundled"] }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.151"
mls-rs = { version = "=0.56.0", default-features = false, features = ["std", "private_message", "out_of_order", "prior_epoch", "tree_index"] }
mls-rs-crypto-awslc = { version = "=0.25.0", default-features = false, features = ["non-fips"] }
aws-lc-rs = { version = "=1.16.3", default-features = false, features = ["alloc", "aws-lc-sys"] }
coset = { version = "=0.4.2", default-features = false }
ciborium = "=0.2.2"
```

`input/LICENSE` 逐字复制仓库根 LICENSE；`input/input.rs` 仅含 `// Metadata-only review input; no runtime implementation.` 与末尾换行。它不实现功能，也不得编译或运行。输入使用的根原创许可不覆盖第三方依赖。

不直接增加 mls-rs-codec/core：固定 mls-rs 源码已 re-export codec 与 GroupStateStorage、IdentityProvider、KeyPackageStorage、PreSharedKeyStorage，先使用公开入口；实际接入若另需 direct dependency，作为新图差异重新审查。移除的是新候选图中的旧 SQLite provider，不触碰原 spike。AWS-LC 的直接 feature 选择对应固定 1.16.3 已有 `alloc/aws-lc-sys` 能力，不开启其 default、ring 兼容、FIPS、PQ 或 bindgen 开关。

本文 TOML fenced block 的内容按 UTF-8/LF、含末尾换行计算 SHA-256；实施工具必须消费相同字节或重新走输入审阅：

| 输入 | SHA-256 |
| --- | --- |
| 候选 manifest block | `afdea8deee4fa0cd4fbe8e5a0740e02384ce6e8d60135f791e4765cb9459ac22` |
| 下节 Cargo config block | `1e707d3933bf964411852e125ebfa28c0dfee5137c0cf2dc28df803f2f8360d3` |
| 基线 Node Cargo.toml | `53e49bb950e8749a8b0c3a662ffdf279294a83e9fc391d566daf43878ca8ce5e` |
| 基线 Node Cargo.lock | `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24` |
| 基线 mls-rs spike Cargo.toml | `82fa10b4985273e4edcd54451432144711981f599be0ec090496a898cfdc7fe0` |
| 基线 mls-rs spike Cargo.lock | `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7` |

## 工作区、环境与不可继承项

每个单元只消费一个明确工作区，运行根由已审阅 supervisor 在专用可写域内创建，记为 `review_root`。以下相对布局固定：

```text
input/             # 本文 manifest、input.rs、LICENSE；G1 可写入 Cargo.lock
cargo-home/        # 全新 registry/config/cache/src；不复用用户缓存
tmp/               # 进程临时写入
target/            # 应为空；出现编译产物即停止
evidence/          # 命令、版本、exit code、lock、metadata、tree、摘要与门结论
```

G2 必须在新的运行根只读验证并复制 G1 成功证据的输入/lock/registry snapshot；不修改 G1 证据。复制内容纳入 G2 总预算，不能使用符号链接绕过写入域。每个运行根禁止已存在路径复用、symlink 和宽泛选择器；最终 evidence 终结后不可写。

launcher 使用显式环境 allowlist：保留经核对的系统运行所需 PATH/locale/证书只读输入；设置专属 `CARGO_HOME`、`CARGO_TARGET_DIR`、`TMPDIR`、`RUSTC`（固定已安装编译器路径）、`RUSTUP_AUTO_INSTALL=0`、`CARGO_TERM_COLOR=never`、`CARGO_NET_RETRY=0`、`CARGO_HTTP_TIMEOUT=30`。不重新定义用户 HOME，不复制其 Cargo/Git/SSH 凭据，不继承 registry token、proxy、RUSTFLAGS、RUSTC_WRAPPER 或 source 替换配置。

Cargo 可读取当前目录及父目录的 `.cargo/config*`；所以只改 CARGO_HOME 不足以隔离。launcher 必须核对全部祖先配置并拒绝额外配置，固定工作目录为该运行根；从只读工具链直接调用 cargo/rustc，禁止 rustup 自动安装路径。[Cargo 配置层级](https://doc.rust-lang.org/cargo/reference/config.html#hierarchical-structure)。

独立 `cargo-home/config.toml` 固定为：

```toml
[registries.crates-io]
protocol = "sparse"

[net]
retry = 0

[http]
timeout = 30
check-revoke = true

[resolver]
incompatible-rust-versions = "fallback"
```

配置不是网络隔离。网络控制必须只允许 HTTPS `index.crates.io`（G1/G2），以及 `static.crates.io`（仅 G2）；DNS/TLS 验证基础设施流量单独受系统网络边界控制，禁止对其他站点重定向、git、代理或私人 registry。拿不到域名级实际控制/证据就停止，不能把这段配置写成已实施 allowlist。禁止关闭证书验证。

## G1：仅生成一次新 lock

前置：本包输入审阅、真实写入/网络/时长限制验证、工具路径与版本/hash 固定、当前任务单次 L3 授权。操作目标只为新 input 目录；预计 1–3 分钟，绝对上限 **300 秒**；整个运行根硬上限 **64 MiB**，其中 evidence 最多 8 MiB。只有 crates.io sparse 索引网络，不下载 `.crate`，不运行 build.rs 或 proc macro。

supervisor 在上述环境中执行唯一 resolver 命令（`cargo_bin` 是已复核固定二进制，`review_root` 是已创建的精确根）：

```bash
"$cargo_bin" generate-lockfile --manifest-path "$review_root/input/Cargo.toml"
```

初始目录必须无 Cargo.lock；不加 `--locked` 假装已有锁，不复制旧锁来掩盖新版直接依赖。generate-lockfile 对已有 lock 会重建，因此失败不在同一目录重跑，不调用 cargo update。[Cargo generate-lockfile](https://doc.rust-lang.org/cargo/commands/cargo-generate-lockfile.html)。

结束后以只读标准库工具记录并检查：八个直接依赖精确版本、全部 lock package/source/checksum、包数、输入文件不漂移、无编译产物、无 `.crate`/解包源码、锁文件版本与退出码。lock 每个外部 package 仅允许 crates.io registry，禁止未知 source、缺 checksum、预发布或无法匹配直接声明；仓库自身 metadata-only 根例外单独列明。

对照旧 mls-rs 图和 Node 图分别列新增、删除、版本改变；**所有传递版本变化必须列出，不静默继承旧评审**。G1 只得到可审阅候选锁；即使退出 0，也不能称来源/漏洞/许可证 PASS。不再自动进入 G2；先复核差异并绑定该 lock hash。

## G2：固定锁的来源与图取证

前置：一个明确且通过结构/差异复核的 G1 evidence ID、lock SHA-256、独立环境和单次 L3 授权。预计 3–10 分钟，绝对上限 **900 秒**；整个运行根硬上限 **512 MiB**，其中 evidence 最多 32 MiB，metadata 单文件最多 8 MiB。容量不足则 STOP，不能扩大或借用户全局 cache。这里的容量是允许消费的上限，不保证新闭包能装下。

顺序执行以下命令；每项 stdout/stderr 由 supervisor 写入表中证据名，写前限额并保留退出码。网络只在第一项允许，其余项操作系统侧禁网且使用 `--frozen`；不允许通过缺缓存时补网来“修复”取证。

| 顺序 | 命令 | 输出 |
| --- | --- | --- |
| 1 | `"$cargo_bin" fetch --locked --manifest-path "$review_root/input/Cargo.toml"` | `fetch.stdout` / `fetch.stderr` |
| 2 | `"$cargo_bin" metadata --frozen --format-version 1 --manifest-path "$review_root/input/Cargo.toml"` | `metadata-all.json` |
| 3 | `"$cargo_bin" metadata --frozen --format-version 1 --filter-platform aarch64-unknown-linux-gnu --manifest-path "$review_root/input/Cargo.toml"` | `metadata-linux-arm64.json` |
| 4 | `"$cargo_bin" metadata --frozen --format-version 1 --filter-platform aarch64-apple-darwin --manifest-path "$review_root/input/Cargo.toml"` | `metadata-macos-arm64.json` |
| 5 | `"$cargo_bin" tree --frozen --target all --edges normal,build,dev,features --format '{p} {f}' --manifest-path "$review_root/input/Cargo.toml"` | `tree-all.txt` |
| 6 | `"$cargo_bin" tree --frozen --target aarch64-unknown-linux-gnu --edges normal,build,dev,features --format '{p} {f}' --manifest-path "$review_root/input/Cargo.toml"` | `tree-linux-arm64.txt` |
| 7 | `"$cargo_bin" tree --frozen --target aarch64-apple-darwin --edges normal,build,dev,features --format '{p} {f}' --manifest-path "$review_root/input/Cargo.toml"` | `tree-macos-arm64.txt` |

fetch 不加 target，明确取得整个 lock 的所有平台依赖，避免把未下载材料默认为已审查；这增加来源/许可证审阅范围。metadata 的 platform filter 只过滤 resolve，packages 仍可能包含其他平台包；必须分别记录完整材料集与目标可达集合，不能按 packages 列表判定目标实际链接。[Cargo fetch](https://doc.rust-lang.org/cargo/commands/cargo-fetch.html)、[Cargo metadata](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html)、[Cargo tree](https://doc.rust-lang.org/cargo/commands/cargo-tree.html)。

上述命令不编译依赖；也不能证明未来编译的 host/target unit feature 组合完全相同。实际 resolver v3 的构建单元、proc macro 与 native ABI 仍须在获准编译包中验证，不使用 nightly unit-graph 绕过当前范围。

对每个 `.crate` 用锁中 checksum 校验原始归档；留存 archive hash、实际解包文件清单、manifest/许可证/NOTICE/holder 的来源映射，检查未知 source/yanked 状态。注册表 checksum 与 HTTPS 是来源一致性输入，不是上游作者签名证明。归档缺失、manifest/lock 不一致、解包结果越界、证据截断、任何 lock 改变均 STOP，保留失败原件。

## 新图评审判定表

| 项目 | 必须输出的可审阅证据 | 停止条件 |
| --- | --- | --- |
| Node 原依赖 | rusqlite/serde/serde_json 的精确版本、feature 差异与 normal/build/dev 路径 | 版本漂移、出现未批准直接依赖或启用非预期能力 |
| MLS | mls-rs 0.56.0 的 root features 和 package 限定展开、core/codec/x509 实际边 | 新顶层 rfc_compliant、rayon、external_client、test/fuzz/benchmark、FFI/async 等未经评审能力 |
| AWS-LC | provider non-fips、aws-lc-rs alloc/aws-lc-sys、native sys 精确版本与构建工具边 | FIPS/PQ/bindgen/兼容 feature 意外开启、native links 冲突；不按 feature 名称全局误判 |
| SQLite | 只由 Node rusqlite 承载，libsqlite3-sys 唯一 links 与实际 features | 旧 mls-rs-provider-sqlite 重入图，重复 native links 或 SQLCipher 路径 |
| COSE/CBOR | coset/ciborium/所有传递版本、维护/来源/许可证与资源行为输入 | 用宽松 Value 解码替代分配前限制、无法保留原始字节、缺完整正文/归属 |
| 源码和产物范围 | registry snapshot、全部归档/解包 source、工具和 evidence 的实际复制/留存清单 | 忽略非目标源码、私有凭据进入输入、未经授权发送给第三方 |
| advisory / 许可证 | 后续独立审计的工具/数据库 revision、逐包正文与人工意见 | 不把旧 D2 PASS/内部使用或无已知告警当作新图许可或安全通过 |

G2 输出只允许 `EVIDENCE_COMPLETE`、`STOP` 或 `INVALID`，不输出“Phase A PASS”。现有 `debug_tree` / `r-efi` 处置与 R2 前置仍需合格复核；实际新图是否仍含它们以锁/来源为准，删除某个依赖也不能改写历史材料的复制义务。后续审计工具运行另有精确合同，不自动复用旧 bundle 的执行授权。

## 真实资源前置与清理合同

本轮只确认已有 macOS 工具链，**没有验证专用写入域硬容量、进程写路径约束、域名网络控制、硬时限 supervisor 或无凭据环境**。G1/G2 因这些前置及缺少执行授权保持 STOP。不能用定期 `du`、采样告警、命令 timeout 参数或可扩展目录冒充总量硬界限；现有 I5 不合格宿主结论不因这是静态依赖操作而改判。

两单元共同要求进程组（含子进程）内存硬上限 512 MiB、最多 16 个进程、每进程最多 128 个文件描述符、最多 2 个 CPU 的总计算配额；硬写入域之外不产生任务 cache/temp/log。具体机制需实际验证，不把 macOS 上未生效的资源参数写成限制成功。工具自身只读版本/cfg 查询允许，任何候选源码编译、build script、proc macro 执行均禁止。

准备实现时优先复用现有 audit monitor 的退出码/证据终结语义，但必须承认其采样磁盘监控不满足本包硬写入域要求；不通过包装旧 runner 自动获得新图资格。需先交付可验证的 launcher/监督与环境绑定，再请求 G1 或 G2 单次实际执行；本包没有授权创建磁盘镜像、修改挂载/系统网络规则或另装隔离工具。

每次允许启动的子进程必须属于独立进程组；时限/配额/输入错误先停止该组，保留已产生证据和真实退出状态，不能静默重试。父进程退出也必须关闭子进程与网络资格。清理仅限该精确运行根的 tmp/不再需要的 cache/source，保留输入、lock、checksum 与错误证据；先核对 canonical 根、对象清单和目录归属，不清理旧 evidence 或用户缓存。删除第三方材料前先按审查留存要求决定保留范围，不能为了“零残留”丢失失败证据。

成功/失败均报告实际耗时、工作区与网络/进程终止状态。运行后的锁不会自动复制回 Node；产品 manifest/lock 提升、候选构建/签验、真实 trait 接入、ARM64 运行、任何远程写入均不属于 G1/G2。

## 本轮已完成与仍需输入

已完成：精确候选 manifest/config、两单元命令/输出/来源/资源/错误合同、基线差异与审查清单；对文档内 TOML 做标准库语法及固定依赖检查，读取已有工具版本并核对本机源码的 feature/re-export 入口。没有调用 generate-lockfile/fetch/metadata/tree，没有生成新锁、下载归档、安装或运行候选。

需要的真实输入是：环境硬边界验证与 launcher 实施证据、最终 clean revision/input hash、G1 单次明确授权；G1 产生真实 lock 后才能固定 G2 的 evidence ID/hash 和单次授权。专业审查者及材料移交范围另行落实，不能通过“接受 D14”替代。当前不请求立即运行尚未就绪的命令，也不重复请求已接受的候选方向。
