# Node 第一批服务与事务基础实施

日期：2026-10-24。面向后续 Node 开发与评审，记录 [ADR 0004](../adr/0004-node-service-foundation.md) 接受后的首批离线实现、精确依赖与证据边界。不是安全候选 Phase B、正式三节点网络实验或部署授权。

## 授权与结果

所有者接受 D1—D5，并要求先更新方案/ADR、提交工作区文档，再推进第一批服务与事务基础。文档提交为 `5c46e6b`；随后新增 `node/` 代码、依赖锁及本记录。实现属于有持久化与失败恢复影响的 L2；本轮未安装依赖、修改系统、启动 VM/设备或监听服务，未使用真实身份、消息或密钥。

首批基础已实现并通过本机离线测试；生产入口仍拒绝业务运行。应用层只有状态/消息/动作/历史查询、平台时间推进与发送拒绝，不提供可绕过认证的写入入口。T-A/B/C/D 是真实 SQLite 事务上的内部原语，密码状态和 proof 仍为调用方前置条件；测试中的合成字节不能证明 E2EE 或安全库联合提交已完成。

## 文件与依赖差量

新增目录为 [`node/`](../../node/README.md)：一个 Cargo package，含 `config`、`error`、`model`、`retry`、`store`、`service`，两个 CLI，schema、配置示例、单元/CLI 测试及第三方记录。没有修改旧 Go harness、密码 spike manifest/lock、profile、CI、根入口约定或 I5 资源/运行合同。

| 项目 | 本批固定输入 |
| --- | --- |
| Rust / Cargo | 1.97.1；edition 2024，MSRV 声明 1.97；本机已有工具链，禁止自动安装 |
| rusqlite | 0.40.2，关闭 default features，启用 bundled |
| serde / serde_json | 1.0.229（derive）/ 1.0.151 |
| SQLite native | libsqlite3-sys 0.38.2 / SQLite 3.53.2，使用缓存内 bundled 源码 |
| Cargo.lock | 22 个第三方 package；SHA-256 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24` |
| 宿主 | `aarch64-apple-darwin`，rustc `8bab26f4f`；Apple clang 21.0.0（clang-2100.3.34.2） |
| 构建输出 | 仓库忽略目录 `.cache/node/target`，不是 I5 运行环境或预算的一部分 |

选择这些缓存版本用于独立 Node 图，避免为首批基础安装新包；此前 spike 中的 rusqlite 0.37.0 并未修改。未来接入 mls-rs 时须重新解决 native SQLite 的整图兼容，不把当前选择强行带入已冻结密码图。包来源、许可证文件与摘要、SQLite public-domain 声明和更新责任见 [第三方记录](../../node/THIRD_PARTY.md)；未执行联网 advisory 扫描，不声称完成独立供应链/法律审查。

锁文件由 `cargo +1.97.1 generate-lockfile --offline --manifest-path node/Cargo.toml` 生成。没有手改解析图、安装依赖或下载新工具链。

## 已实现的事务与恢复

| 边界 | 已实现行为 |
| --- | --- |
| 单拥有者与持久格式 | canonical 0700 目录、0600 单链接文件、非阻塞文件锁、SQLite application_id/schema v1；缺库/未知版本/损坏/第二拥有者拒绝；新建与重开分离 |
| SQLite 提交 | DELETE journal、EXTRA synchronous、4096 page size 启动读回；macOS fullfsync；BEGIN IMMEDIATE 联合修改，失败回滚；提交不确定隔离直到重开查询 |
| T-A | 安全状态 revision、历史、原始消息、outbox、作用域内 action binding 同事务；重复动作返回旧事实，不再推进安全状态；generation 退休后拒绝复用 |
| T-B / T-C | 中继只存不透明载荷及来源，不接受端点明文/安全状态；目的端联合安全状态、历史、消息及证据返回队列；去重不重复历史，来源/core/寿命冲突拒绝 |
| T-D | 中继先在同事务保存向持久上游的证据责任，再删除数据副本；错误上游、proof core 不一致、控制容量不足均不清理；原点依据已验证 proof 的调用前提改变状态 |
| 调度 | 移植 I1 的 0/250/750/1750/3750 ms 与一次恢复机会；迟到只发一个机会、消费已错过额度；Stop/Pause 优先、同一时刻冲突拒绝；决定仅在持久消费成功后返回 |
| hop / custody | 中继下一跳副本一次扣减 hop，重复调度不补额度；custody 只暂停重试，不上报 delivered、不删除载荷 |
| 时间与历史 | 提交保存 boot/单调及可信墙钟下界；不同 boot/回退隔离写入；历史 7 天到期清理与传输/动作/证据责任分离；时间不确定时保留历史 |
| 生命周期与错误 | 容量 32 的串行状态线程，显式停止/Join；安全能力缺失返回 SecurityUnavailable；底层错误保留 source，默认输出只含分类与操作上下文 |

I1 移植核对了旧 Go 分支顺序并测试关键向量；本批未执行跨语言全量差分测试。I1 的 `Attempt`/`MissedSlots` 观测字段没有迁入当前 `Decision`，本批不生成 I4/I5 evidence。调用者必须汇总同一时刻的重试事件，不能在相同坐标先推进再提交不同 Pause batch。

## 容量与不覆盖的边界

以下是第一批应用层上限，不是生产容量或整机硬资源承诺；配置可缩小，已有库须与持久 limits 一致，变更需要显式迁移。

| 对象 | 上限 |
| --- | --- |
| 传输载荷 | 2048 条 / 16 MiB；单条 64 KiB |
| 用户历史 | 10000 条 / 64 MiB；单条有效 UTF-8 4096 bytes |
| 返回证据 | 4096 条 / 8 MiB；单条 4096 bytes |
| 消息/动作/队列/作用域/安全状态总记录 | 16384 条；安全状态总字节 8 MiB、单条 64 KiB |
| 单来源 / 单邻居数据队列 | 512 条及 4 MiB / 256 条及 2 MiB；来源真实性由未来认证层保证 |
| SQLite 主数据库 | 32768 页 × 4096 bytes = 128 MiB；journal 不在此数内 |
| 配置 / 历史单页查询 | 16 KiB / 100 条 |

逻辑配额在同一事务提交前检查，超额整笔回滚；目的端返回责任不能入库时不提交交付，中继不能保存返回责任时保留数据。当前是**提交前拒绝**，没有完成磁盘写入前覆盖主库、journal、文件系统开销、构建/日志和系统写入的硬预留。SQLite 页数限制也不能证明 journal、进程内存、整机或 I5 的硬边界；真实入口仍需部署环境预算与物理拒绝测试。

尚无去重 marker/证据责任的安全窗口回收；达到上限会明确拒绝，不静默提前删除。没有可信时间源/定时器，历史到期由服务启动和平台 Clock 命令驱动。不同 boot 后尚无恢复解除流程；不能据此宣称设备重启后能继续转发。数据库完整性与 retry v1 检查不等于抗恶意旧镜像回滚或全域语义证明。

## 离线验证

在仓库根执行，使用已安装工具链与缓存；精确命令：

```bash
export RUSTUP_AUTO_INSTALL=0
export CARGO_TARGET_DIR="$PWD/.cache/node/target"
cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```

测试当前覆盖 28 项：26 个库测试（含 crash 子进程入口）及 2 个 CLI 测试。主要证据包括：

- 安全状态写后/COMMIT 前失败整笔回滚，COMMIT 后丢响应隔离，重开按 action 查询；受控子进程实际在 COMMIT 前/后以 71/72 退出，重开分别得到全旧/全新状态。
- T-B/T-C 写失败、T-D 提交两侧故障、真实 SQLite query_only 与页容量不足、逻辑历史/载荷/控制容量拒绝。
- 动作幂等与内容冲突、generation 退休、目的端一次历史、单跳预算消费、重试消费跨重开不返还、来源冲突与上游返回目标恢复。
- 三个独立 SQLite store 的 A/B/C 职责流转，采用直接构造的合成记录，没有网络、认证、真实密码或实体三节点。
- schema/损坏/符号链接/第二拥有者拒绝，时钟不确定隔离、历史 7 天边界及服务时间推进，配置歧义/超长拒绝，敏感字段不进入默认错误输出。
- CLI 配置检查不代表 ready；`run` 退出 2；控制 CLI 能力报告不打开数据库。

最终结果：上述五条检查全部退出 0；Rust 26 个库测试和 2 个 CLI 测试通过，Clippy `--all-targets -D warnings` 无告警，格式检查通过，仓库检查覆盖 252 个文件，`git diff --check` 通过。受控 71/72 和 CLI 2 是断言要求的负向退出，不是漏报的验证失败。本轮未出现失败后靠重跑掩盖的测试结果。

## 下一批前置

首批离线基础不替代 R2、SW-G2、安全候选 Phase B 或 I5-R。后续应先证明安全库 storage 接口能加入同一个 SQLite 事务、proof 与撤销/重放边界及可信时间恢复；本机/手机 API、有线 TLS、加密卷/锁屏、systemd 和 ARM64 实测仍按后续批次推进。

未执行真实密码适配、HTTPS/CA、LUKS、ARM64 构建/运行、物理掉电、SD 卡耐久与备份恢复、真实设备或网络实验；没有新增后台常驻进程或远程写入。保留 `.cache/node/target` 编译缓存，测试临时目录由测试析构清理。
