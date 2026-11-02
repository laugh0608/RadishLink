# Node 服务运行可靠性与安全接入准备

日期：2026-10-24。本文面向 Node 开发与评审，记录[首批基础](node-service-foundation.md)之后的持续开发任务，覆盖状态拥有者、存储演进、资源责任、时间维护与调度。安全接入源码核对放在[安全决策专题](../security/e2ee-sw-g2-decision-package.md#node-联合事务接入源码核对2026-10-24)，不在本文重复密码方案。

本文记录提交 `dd43b7e` 时的 schema v2 与 47 项测试事实；后续 D6—D10 和 schema v3、证明截止时间及意图开发见[证明生命周期记录](node-receipt-lifecycle.md)，后者取代本页相关当前行为描述。

## 范围与开发基线

所有者要求先提交工作区，再按整体开发计划继续。初始 24 文件更改已提交为 `2936c6e feat(node): 建立服务与 SQLite 事务基础`；提交前 28 项测试、仓库检查和 diff 检查通过。本任务在 `dev` 连续开发，未创建分支、worktree 或远程对象。

本批仍为 L2 本机离线实现，沿用原工具链与 Node Cargo.lock；未新增依赖或安装工具，未运行安全候选、VM、网络服务或实体设备。提交/迁移/维护的故障测试只使用本轮测试创建的临时合成库。实际平台时钟、加密卷与安全机制没有因库接口增加而自动可用。

## 行为与兼容性

| 内容 | 已实现行为与边界 |
| --- | --- |
| 应用生命周期 | `Service` 持有唯一状态线程，`Client` 是可克隆命令入口；数据库不交给客户端。32 个排队命令之外返回 Busy；引用、分页、Clock 的基础边界在入队前检查 |
| 停止协调 | 同一 admission gate 关闭新请求，已接纳命令先于 Stop 执行；显式 stop 和 Drop 都 Join。线程 panic 关闭入口并由 Join 报错；gate poison 仍先停止/Join 再返回错误，不遗留脱离监督的线程 |
| 可观测状态 | 正常仍为 SecurityUnavailable；时间隔离、提交隔离、维护失败分别报告。诊断保留最近维护计数与错误分类，不回显原始底层输入；没有虚构 READY、LOCKED 或已解锁状态 |
| 周期维护 | `start_with_clock` 接收明确平台 `ClockSource`，周期限定 100 ms–60 s；每轮命令前检查到期，持续请求不能饿死维护。自动驱动时拒绝另一个手动时钟写入口；无源模式只使用平台 Clock 命令 |
| 原子维护 | 时钟下界推进、到期 payload 清理、相关 data queue/预留释放及历史清理在同一事务；每批最多 256 条 payload 与 256 条历史，返回 more_due。保留去重/动作/证据责任 |
| 历史可见性 | 受信时间已到期的历史立即从查询过滤，即使有分批物理清理积压；时间不确定时保留原有只读历史，不猜测到期 |
| 批量调度 | 同一坐标最多 128 个输入事件，先按消息/队列类型/邻居合并，再推进重试。Stop 优先于 Pause，拒绝优先于 Allow，矛盾链路事件拒绝；所有队列消费、时钟与维护共同提交后才返回决定 |
| 容量诊断 | 返回 payload、历史、已存证据、预留控制条目/字节、总记录和 SQLite 主库字节数；不暴露正文。数据库字节不包含 journal、文件系统或进程内存 |

`ClockSource` 必须由可信平台集成提供、有界且不阻塞；本轮定时测试提供合成源，未实现 Linux 启动身份、可信墙钟或休眠恢复后端。维护周期不是设备性能或耐久建议，真实周期须结合闪存写放大与功耗测量确定。关闭可以排空有界队列，但无法对阻塞的 VFS、硬件或违约时钟源承诺硬时限；最终进程监督仍属部署工作。

用户命令没有权限输入 Clock、执行迁移、访问原始 SQL 或使用内部调度写方法。生产 `run` 仍退出 2；没有网络发送器，持久调度决定不是已发送事实，也不是通用的跨线程发送授权。

## schema v2 与控制责任预留

schema v1 源文件保持原样，新建库在初始化事务内顺序应用 v1 与 `migration_v2.sql`。v2 新增 `control_reservations` 和 payload 到期索引。普通 `Store::open` 遇到 v1 返回 MigrationRequired，只有显式 `Store::migrate_v1` 执行 v1→v2；未知版本和不匹配来源拒绝。v1 程序不支持 v2，不能靠回填 user_version 降级。

迁移先检查路径、锁、配置 limits、SQLite 完整性、外键与已有 retry 记录，再在同一事务中补齐仍持有载荷的中继预留、创建索引并更新版本。已有数据需要的预留超出配置时整笔回滚，既不降低保证，也不静默删除记录。时钟隔离中的库不执行迁移。没有 limits 变更迁移或自动容量扩张。

每条接纳的中继消息预留一个控制记录及 4096 bytes，覆盖当前允许的最大返回证据。预留与消息同时提交，计入控制条目、控制字节和总记录预算；满额则 T-B 拒绝。T-D 将预留转换为实际证据队列，并在同一事务删除 payload/data queue；错误或提交前失败仍保留载荷和预留。payload 到期终结后释放未消费预留，已形成的返回证据责任继续保存。

这是逻辑责任容量保障。接收者不会因其他合法入库操作把已有预留占走；但物理磁盘耗尽或硬件错误仍可能使事务失败。未完成主库、journal、备份/维护、文件系统与整机写入的硬预留，不宣称满足 I5 预算。旧 marker、证据队列和安全状态的最终回收窗口尚未接受，当前保留并在上限明确拒绝新请求。

## 验证与失败记录

使用已有 Rust 1.97.1 / bundled SQLite 3.53.2，本机 `aarch64-apple-darwin`；Node lock SHA-256 保持 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24`。完整命令与首批一致：

```bash
export RUSTUP_AUTO_INSTALL=0
export CARGO_TARGET_DIR="$PWD/.cache/node/target"
cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```

本批新增验收覆盖：

- 队列满额与停止竞争、已接纳查询排空、客户端仍存活时服务 Drop、线程 panic、gate poison 与 Join、响应接收者断开后的维护提交。
- 无 UI Clock 命令的周期维护、时钟源报错与恢复、boot 改变后的隔离、历史删除积压期间的到期过滤。
- v1 显式迁移、错误来源/未知版本拒绝、迁移容量不足和 SQL 错误回滚；实际子进程在迁移 COMMIT 前/后退出，分别保留完整 v1/v2。71/72 是预期故障退出，不是物理掉电。
- 控制预留跨重开保持、预留阻止新接收、T-D 失败恢复、总记录满额时预留转换仍可完成、缺失预留拒绝恢复。
- 同坐标事件合并、矛盾事件拒绝、整批重试消费失败回滚、重开不返还额度、维护最多 256 条与后续继续清理。

开发中两次失败均已保留原因：首次新增代码编译退出 101，rusqlite 不提供直接 `u64 FromSql` / `usize ToSql`，改为读取有符号 SQLite INTEGER 后受检转换，并固定 SQL batch 参数为 i64；之后的 257 条历史积压测试退出 101，旧测试 fixture 将 revision 转为 u8 再加一导致溢出，改为完整 i64 编码，精准复验通过。没有修改产品逻辑来绕过上述测试，也不把它们解释为环境不稳定。

最终全量结果：45 个库测试（含两个受控 crash 子进程入口）及 2 个 CLI 测试通过，共 47 项；Clippy `--all-targets -D warnings`、格式检查、仓库检查（258 个文件）与 `git diff --check` 全部退出 0。失败原因修正后重新执行完整测试，没有保留已知失败或跳过用例。

## 后续工程顺序

本批已将普通请求、维护与持久责任的协调实现到库内；接下来围绕[源码核对结论](../security/e2ee-sw-g2-decision-package.md#node-联合事务接入源码核对2026-10-24)评审正式 storage trait 适配、proof 与撤销映射，以及跨 boot 恢复所需可信基座。真实安全功能仍须完成许可证/R2/Phase B 前置；不能以新增合成测试代替它们。

跨 boot 暂不自动续传。可继续读取原有历史，但截止点只有旧坐标，数据库内墙钟下界也不能证明停机上界和防回滚；后续须先明确时间源可信性、停机误差界、库状态反回滚证据及显式责任终结规则，再设计持久字段和恢复事务。本批没有改变这项安全决定。

本机/手机接口、有线 TLS、Linux ARM64、解锁/锁定与进程监督按后续批次接入。没有启动 VM/设备/网络服务，没有新采购、签名、部署或远程写入。测试临时目录由测试清理，仅保留仓库忽略的 `.cache/node/target` 编译缓存。

## Store 锁并发诊断（2026-11-02）

- 范围：所有者要求按计划推进跨 boot 设计及 Store 锁异常诊断；本节记录工程诊断，不授权修改锁行为或接受跨 boot 新语义。
- 基线：`ee20ab3`，Node 实现为 `c7008eb` / schema v8；macOS 27.0.1（26A434）、aarch64-apple-darwin、Rust 1.97.1（8bab26f4f）。
- 结论：**已定位并复现“并发启动子进程暂时持有继承锁”的机制；历史两次个例没有逐次时序证据，修复尚未实施。** 本次未修改任何 Node 源码、测试、manifest 或 lockfile。

### 失败来源与排查

历史 `.cache/node/outbound-full.log` 保存 D15 重开用例 `reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision` 的 `Busy: store owner lock`；D16 另记录证明事务用例 `intent_and_conversion_failures_never_publish_partial_work` 的相同错误。本次保留原日志及历史失败，不以新运行通过覆盖。

`store/mod.rs::lock()` 将 `File::try_lock()` 的失败映射为该操作名，发生在打开 SQLite 之前；该错误不等同于 SQLite 事务 Busy。已核对：失败用例先显式 drop Store 再 open；Workspace 路径由 PID 加进程内原子计数分配；Store 没有复制 owner 文件句柄，字段顺序为连接先释放、锁文件后释放；套件的多个 COMMIT 故障用例会同时通过 `Command::status()` 创建测试子进程。代码核对没有发现两个用例主动使用同一路径的证据。

[Rust File 文档](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock)说明 Unix 当前使用 flock，依赖所有复制/继承句柄关闭或显式 unlock 才释放；[Apple flock 手册](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html)说明 fork/dup 的描述符引用同一把锁。[Rust CommandExt 文档](https://doc.rust-lang.org/std/os/unix/process/trait.CommandExt.html#tymethod.pre_exec)区分 fork 后的 pre_exec 与 exec 时关闭 CLOEXEC 描述符。因此仅在父线程 drop 文件，并不证明并发创建子进程的窗口中已经没有该锁的引用。文档提供机制依据，具体本机行为由下列探针验证；不从文档推断历史每次失败的精确调度。

### 本次实际执行与结果

先执行一次未修改代码的默认并行库套件；未通过串行化、更改重试或吞错处理 Busy。之后用无依赖的 File 探针及链接当前未修改 Node 库的 Store 探针分离变量；所有记录仅含合成状态。

| 项目 | 实际结果 / 退出码 | 覆盖与限制 |
| --- | --- | --- |
| 默认并行 `cargo test --lib` | 172/172 通过，86.80 秒，退出 0 | 两个历史失败用例均通过；一次成功不能关闭不稳定风险，未重跑 CLI 或正式实验 |
| File，无子进程 | 50000 次，Busy=0，最终可加锁，退出 0 | 同一合成文件反复 open/try_lock/drop 的对照 |
| File，并发普通 spawn | 4 线程各 64 次 `/usr/bin/true`；50000 次加锁中 Busy=104，最终可加锁，退出 0 | 无 pre_exec hook 的普通 `Command::status()` 已复现窗口；计数不是稳定概率或产品性能 |
| File，受控 fork 窗口 | 父进程 drop 后返回 WouldBlock；释放子进程进入 exec 后成功，退出 0 | 用匿名本机 IPC 暂停 pre_exec；只在诊断探针使用 async-signal-safe read/write/_exit，未引入产品 unsafe |
| Store，无子进程 | 500 次 open，Busy=0，最终可 open，退出 0 | 当前产品库的空合成数据库，无密码/网络或实际用户数据 |
| Store，并发普通 spawn | 4 线程各 128 次 `/usr/bin/true`；500 次 open 中 Busy=8，最终可 open，退出 0 | 未修改 `Store::open`，复现完全相同的 `Busy: store owner lock` 路径 |
| Store，受控 fork 窗口 | drop 后为 `Some(Busy: store owner lock)`；子进程 exec/退出后 open 成功，退出 0 | 确认 Store RAII drop 与继承锁窗口的因果关系；没有重新接纳真实业务或释放产品锁 |

源代码核对与实际 Store 探针共同支持该机制可以造成此类错误。历史失败没有记录 fork/close/exec 的完整时序，仍不能逐次断言全部由它引起；本次没有证据表明 SQLite 损坏、消息丢失或错误接受第二拥有者。Linux 行为和真实部署尚未验证。

实际命令（均使用已有工具链与缓存，顺序执行）：

```bash
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml --lib
RUSTUP_AUTO_INSTALL=0 rustc +1.97.1 --edition=2024 .cache/node/2026-11-02/owner_lock_probe.rs -o .cache/node/2026-11-02/owner-lock-probe
.cache/node/2026-11-02/owner-lock-probe no-spawn "$PWD/.cache/node/2026-11-02/no-spawn.lock"
.cache/node/2026-11-02/owner-lock-probe spawn-overlap "$PWD/.cache/node/2026-11-02/spawn-overlap.lock"
.cache/node/2026-11-02/owner-lock-probe fork-window "$PWD/.cache/node/2026-11-02/fork-window.lock"
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 build --offline --locked --manifest-path node/Cargo.toml --lib
RUSTUP_AUTO_INSTALL=0 rustc +1.97.1 --edition=2024 .cache/node/2026-11-02/store_lock_probe.rs --extern radishlink_node=.cache/node/target/debug/deps/libradishlink_node-9a35482a649e9e5a.rlib -L dependency=.cache/node/target/debug/deps -o .cache/node/2026-11-02/store-lock-probe
.cache/node/2026-11-02/store-lock-probe no-spawn "$PWD/.cache/node/2026-11-02/store-no-spawn"
.cache/node/2026-11-02/store-lock-probe spawn-overlap "$PWD/.cache/node/2026-11-02/store-spawn-overlap"
.cache/node/2026-11-02/store-lock-probe fork-window "$PWD/.cache/node/2026-11-02/store-fork-window"
```

探针使用 create_new / Store::create，精确路径已消费，不可直接覆盖重跑；复验须选择新的任务专用路径。两个探针源码、构建输出及逐项日志保留于忽略目录 `.cache/node/2026-11-02/`，不加入产品入口或 CI。匿名 IPC 的读等待设置 5 秒超时，子进程全部等待回收；合成锁文件/数据库保留，没有清理历史证据。诊断程序的采样循环用于观测，不是产品的锁重试方案。

| 固定输入 | SHA-256 |
| --- | --- |
| `node/Cargo.lock` | `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24` |
| `owner_lock_probe.rs` | `5a87231b5fa168d0f88c55cd92f2ef5e524015ab0a44da7344c80c591c4b029e` |
| `store_lock_probe.rs` | `15283cea8a64d00de85cec69aa26b2e103faa6136afd64653a2ec65a7a27fa40` |

### 修复建议与关闭条件

下一批可评审在连接关闭且拥有者工作已停止后显式释放 owner 锁，保留释放错误及上下文，并保证析构/异常路径的顺序；不在连接仍可写时提前解锁，也不由继承句柄的子进程替父进程解锁。本轮只完成诊断，尚未实施该生命周期调整。新增依赖、改锁协议、全局串行测试或加延时/重试均不作为默认方案。

修复验收须同时证明：真实第二拥有者仍立即 Busy；连接/工作尚存时不能释放所有权；受控继承窗口和普通并发 spawn 不再阻止合法重开；失败/异常退出和原 COMMIT 故障恢复仍成立。随后运行对应精准回归、默认并行全量、fmt/Clippy 与仓库检查。历史个例仍保留其当时不确定性，不将新修复追溯写成旧运行已稳定；Linux 部署证据另验。

本轮文档同步后执行 `./scripts/check-repo.sh`（309 文件）与 `git diff --check`，均退出 0；独立核对新增相对链接/锚点及草案逻辑计费计算通过。Node 源码未变，未另跑 fmt/Clippy、CLI、正式实验或真实环境验收。六份文档留在 `dev` 工作区待审阅，未提交/push，未改变远程状态；本任务测试与诊断子进程均已结束，无新增后台服务。
