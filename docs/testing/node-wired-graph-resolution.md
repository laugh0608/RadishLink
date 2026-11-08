# Node 有线传输候选锁解析评审

2026-11-08。基线为 `fabdec617b323fa4a5b6a4601e50d9f0c0181628`。本包准备一次隔离的 Cargo 解析，把 [Tokio/rustls 候选](../architecture/node-bounded-ingress.md#有线传输依赖候选)加入 Node 现有依赖，取得可与产品锁对照的候选 `Cargo.lock`。固定输入已静态核验。本机合成探针已执行，运行环境准入仍待验证，候选锁待生成。D14 G1/G2 使用各自的输入、证据和授权。见 [D14 新图评审包](node-security-graph-review-package.md)。

## 固定输入

在专用运行根中生成 `input/Cargo.toml`，使用下面的完整文本。`input/LICENSE` 逐字复制基线的根许可，`input/input.rs` 仅含 `// Metadata-only review input; no runtime implementation.` 和末尾换行。产品 `node/Cargo.lock` 只用于解析后的差异比较。新根从空锁起步，解析可能改变传递版本，任何差量都应显式记录并评审。Cargo 对已有锁调用 `generate-lockfile` 也会重建锁。见 [Cargo generate-lockfile](https://doc.rust-lang.org/cargo/commands/cargo-generate-lockfile.html)。

```toml
[package]
name = "radishlink-node-wired-graph-review"
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
tokio = { version = "=1.54.1", default-features = false, features = ["net", "rt", "time"] }
rustls = { version = "=0.23.46", default-features = false, features = ["std", "ring"] }
```

独立 `cargo-home/config.toml` 使用 [D14 工作区章节](node-security-graph-review-package.md#工作区环境与不可继承项)的同一段配置，仅复用配置文本。配置采用 crates.io sparse、零重试、30 秒 HTTP timeout 和 Rust 版本不兼容时的 `fallback`。整个进程的实际期限及出站约束由外层监督执行。解析前用 UTF-8/LF 原始字节复算下列摘要，检查独立 workspace、精确直接依赖及初始空 `Cargo.lock` 状态（路径不存在）。摘要、范围或文件类型不符时停止。

| 输入 | SHA-256 |
| --- | --- |
| `input/Cargo.toml`（上面的完整代码块，含末尾换行） | `2096329567ad7bc4a19fca7dfd172c5011156e228e9ef369fa119c6fc378de72` |
| `input/input.rs` | `0c148b350a7e280e5f74ca8220d14ae07f2a597c0d71de75f25d5ba77cb24bb5` |
| `cargo-home/config.toml`（引用的代码块，含末尾换行） | `1e707d3933bf964411852e125ebfa28c0dfee5137c0cf2dc28df803f2f8360d3` |
| 基线 `node/Cargo.toml` | `53e49bb950e8749a8b0c3a662ffdf279294a83e9fc391d566daf43878ca8ce5e` |
| 基线 `node/Cargo.lock`（格式 4，含根共 23 条） | `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24` |
| 基线根 `LICENSE` 及复制后的 `input/LICENSE` | `74cc49765a69e5bef2f533b59a39e3d29dea30f4bb2d7e7693846f3867709e01` |

## 一次解析的执行条件

实际运行前绑定包含本包的干净 Git revision、唯一新运行根、宿主与 supervisor 版本、Cargo/rustc `1.97.1` 的实际绝对路径及摘要。`aarch64-unknown-linux-gnu` 是后续取证目标，解析宿主可以不同，须如实登记。运行根固定包含 `input/`、`cargo-home/`、`tmp/`、`target/`、`evidence/`，仅允许已审阅的输入文件进入新根。基线产品锁可在解析结束后由评审者只读核对。用显式环境设置 `CARGO_HOME`、`CARGO_TARGET_DIR`、`TMPDIR`、`RUSTC` 和必要的系统路径/信任根，直接调用已安装的工具链二进制。核对运行根及祖先的 `.cargo/config*`，拒绝额外配置、用户缓存、代理、凭据、wrapper 和共享写入位置。见 [Cargo 配置查找规则](https://doc.rust-lang.org/cargo/reference/config.html#hierarchical-structure)。

| 边界 | 建议上限及运行前须提供的证据 |
| --- | --- |
| 写入与留证 | 总运行根硬上限 64 MiB，其中证据域最多 8 MiB，其余写入最多 56 MiB，均计入对应的文件系统开销。用合成写入证明超额和写域外会被拒绝，证据区仍能写入终止原因。根及其可写子目录拒绝旧路径、链接和其他写入者。 |
| 网络 | Cargo 仅能通过 HTTPS 向 `index.crates.io` 请求 sparse 配置和索引条目；DNS/TLS 基础设施流量由宿主边界另管。验证允许的请求、禁止其他目的地及重定向，证明结束后网络资格撤回。`static.crates.io`、归档下载和备用 registry 留待后续独立评审。 |
| 进程和时长 | 候选进程组总内存 512 MiB、最多 16 个任务、每进程 128 个 FD、总 CPU 配额 2 核。预计 1–3 分钟，绝对上限 300 秒，含终止和收束；执行前绑定停止动作和留给收束的时间。用无依赖合成进程验证超限、超时及父进程退出时子进程和网络的收束。 |

上述是待验证的执行上限，沿用既有静态解析包的量级。实际环境须给出所用机制与拒绝证据，目录大小采样和 Cargo 超时设置只能作为观测。若 64 MiB 放不下实时索引，保留失败证据后回到范围评审。当前工作区尚无满足这些条件的已核验运行根。

运行条件证实并获得单次授权后，supervisor 从 `review_root` 执行下面的唯一 Cargo 命令。初始 `input/Cargo.lock` 必须不存在，退出后关闭本次网络资格，再离线复核。命令产生索引缓存和候选锁，`target/` 应为空。若退出失败、证据截断或发现源码归档、解包、编译产物，立即结束该次运行并保留原因。见 [Cargo sparse 协议](https://doc.rust-lang.org/cargo/reference/registry-index.html#sparse-protocol)。

```bash
"$cargo_bin" generate-lockfile --manifest-path "$review_root/input/Cargo.toml"
```

## 候选锁与失败证据

1. 终结记录包含运行根标识、Git revision、输入和工具摘要、实际 argv、起止时间和退出码、受限日志、资源峰值及拒绝事件、进程与网络收束情况。保留候选锁原始字节、SHA-256 及已消费索引的可复核版本记录。在证据受限或输出不完整时保留失败状态，候选锁不得进入下一阶段。
2. 只接受格式 4、唯一无 source 的评审根和五个精确直接依赖。对全部外部包按 `(name, version, source)` 核对唯一性、标准 crates.io source（`registry+https://github.com/rust-lang/crates.io-index`）、64 位十六进制 SHA-256 及该次 sparse 索引中的对应版本/撤回状态。异常 source、yanked、预发布、缺失索引或摘要差异均停在评审。
3. 用基线锁的外部包生成增删和版本差量，单列同版本的校验和或依赖边变化。核对 Tokio、rustls、`ring 0.17.14` 和 `rustls-webpki 0.103.16` 的登记值。后者在 `0.103` 系列低于 `0.103.16` 时拒绝，任一预期版本漂移或既有 Node 包版本变化均须显式复核。AWS-LC、`tokio-rustls`、MLS/COSE 进入候选锁也停在差异评审。版本与摘要见 [候选版本证据](../architecture/node-bounded-ingress.md#版本证据与完整图准入)。
4. 完整保留输入、候选锁、索引记录与错误证据，结束后封存。清理仅在后续授权中指定的新运行根及临时对象内进行。候选锁经复核后再单独准备固定锁的归档与来源取证，分别取得 Linux ARM64、实际宿主的依赖路径和有效 features。Cargo 锁中的包列表不能证明实际目标的 feature 或原生链接结果。见 [Cargo metadata](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html#options)和 [台架准入](node-security-integration-acceptance.md#linux-arm64-接线准入)。

输入准备时用标准库对照基线和提交记录核验候选 TOML、配置、占位源码及基线 SHA-256。许可证、来源归档、advisory 全图复核及真实台架证据各有独立验收。

## 本机合成探针结果

macOS `27.0.1`（Darwin `27.0.0`、arm64），使用现有 Python `3.14.5` 的 `-I -B` 和标准库。文件探针只写入 `/private/tmp` 下本次新建的专用目录，进程与通信探针仅使用合成子进程、管道和 `AF_UNIX` socketpair。候选锁解析仍停在环境准入。

| 边界 | 合成输入和实测结果 | 准入缺口 |
| --- | --- | --- |
| 总写入与路径 | `RLIMIT_FSIZE=32768`，忽略 `SIGXFSZ` 后顺序写入两个新文件。第一个文件满 32768 bytes 后追加 1 byte 返回 `EFBIG`，第二个文件仍写满，总计 65536 bytes。另在专用临时目录内通过 `job/../outside/canary` 写入自有兄弟目录成功。 | 需要真实的 56 MiB 工作域和 8 MiB 证据域的硬写入控制及独立路径约束。单文件限制和当前工作区权限均允许上述越过任务边界的合成写入。 |
| FD 与进程时限 | `RLIMIT_NOFILE=128`，保留 3 个标准 FD，再打开 125 个 `/dev/null` 后下一次返回 `EMFILE`。同组 leader/worker 超过 200 ms，忽略 `SIGTERM` 100 ms 后由探针向该组发送 `SIGKILL`。leader 退出 `-9`，worker 管道 EOF，进程组消失。 | 单进程 FD 限制与同组超时回收已有证据。512 MiB、16 个任务、2 核及含回收的 300 秒整组上限待在目标环境验证。 |
| 父退出和脱离进程组 | 父进程主动退出 `79` 后，同组 worker 仍能通过管道回应。另一用例使 worker 创建新 session，原 leader 的进程组在 `SIGKILL` 后消失，worker 仍可在原先传入的本地 socket 上回应。两条用例的 worker 都按探针协议退出，随后已不可见。 | 需要独立于 worker 与执行父进程的监督，覆盖脱离进程组和已打开的连接，证明实际成员归零以及网络资格回收。 |
| 网络策略 | 本机 `sandbox-exec` 的进程内限制探针在应用策略时退出 `71`，stderr 为 `sandbox-exec: sandbox_apply: Operation not permitted`。目标程序尚未启动，未获得域名、重定向或真实连接撤回证据。 | `index.crates.io` 的出站正例、其他目标及重定向负例、收束后网络禁用均待在具备隔离的宿主验证。 |

上述网络探针只尝试在启动 `/usr/bin/true` 前应用进程内策略。

```bash
/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' /usr/bin/true
```

合成进程已全部退出，探针临时目录已清理。后续优先核对可用原生 Linux 宿主，在同一个获审运行根完成以下验收。

1. 回读工作域与证据域的实际硬边界。用普通文件、并发写入和已打开后删除的文件压满工作域，验证下一次写入被拒绝，并确认兄弟路径写入、链接及重命名逃逸被拒绝。工作域满后验证监督者仍可写入有界错误证据。
2. 在可由独立监督者回收的任务域验证 FD、内存、任务数、CPU 和总截止。包含 leader 超时、创建新 session、父进程异常退出和日志满额。若用 Linux cgroup v2，读取实际限制与事件并验证子任务无法迁出，任务域 `populated=0` 后再认定收束。见 [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)。
3. 先以隔离测试端点验证允许目的地、拒绝目的地、重定向和断网后的行为。测试包括已建立连接及新的请求。之后由宿主提供实际索引域控制与证书验证证据，逐项复核本包网络边界。

本机 `sandbox-exec` 失败与合成探针只覆盖当前 macOS 执行环境。当前候选锁解析缺少已验证的运行根，取得上述证据后再按本包评审单次运行。I5 的宿主与整批预算另行验收。
