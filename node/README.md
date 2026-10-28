# RadishLink Node

Rust 服务与事务基础，依据 [ADR 0004](../docs/adr/0004-node-service-foundation.md) 和 [ADR 0005](../docs/adr/0005-node-security-integration.md)。当前可验证单写者应用入口、SQLite 联合事务、恢复与调度；尚不能部署为聊天服务。首批范围见[第一批记录](../docs/testing/node-service-foundation.md)，生命周期、维护与调度见[运行可靠性记录](../docs/testing/node-service-reliability.md)；证明意图见[证明生命周期记录](../docs/testing/node-receipt-lifecycle.md)，当前 schema v4 与 D16 控制持久边界见[控制持久化记录](../docs/testing/node-control-persistence.md)。

## 开发验证

在仓库根使用已有 Rust 1.97.1、Clippy、rustfmt 和本地依赖缓存运行：

```bash
export RUSTUP_AUTO_INSTALL=0
export CARGO_TARGET_DIR="$PWD/.cache/node/target"
cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
```

缺少工具或缓存时命令应失败；不自动下载、安装或更换 lock。测试只用临时目录内的合成内容，并清理自己创建的目录。受控子进程在 COMMIT 前/后退出，用于验证重开恢复，不是物理掉电试验。

`radishlink-node check-config PATH` 只校验严格 JSON，不创建状态目录。`radishlink-node run` 以退出码 2 拒绝运行，报告安全与平台解锁尚未接入。`radishlinkctl capabilities` 只报告本构建能力；尚未连接常驻服务，不直接开库。

## 结构与调用边界

- `config`：配置 v1、16 KiB 输入上限、显式容量与路径校验。
- `model`、`retry`：进程内记录及 I1 重试规则移植，不是产品 wire 或认证结果。
- `framing`：ADR 0007 的 u32be 前缀、每邻居一个 ≤64 KiB frame、最多四邻居和固定 10 秒组装期限；仅内部缓冲边界，尚未接入 transport/Service，详见[离线验证记录](../docs/testing/node-framing-and-graph-inputs.md)。
- `store`：schema v4、显式 v1/v2/v3 迁移、单拥有者、T-A/B/C/D 持久操作、证明意图/容量预留、有界维护与事件批调度。
- `service`：容量 32 的命令队列、可克隆 Client、专属状态线程；支持平台时钟源周期维护，查询已提交事实；关闭接纳后排空已接纳命令并 Join，业务发送仍拒绝。
- `error`：稳定错误分类与受控诊断原因；默认 Display/Debug 不回显底层输入。

`Store` 写方法是内部集成基础：其调用者将来必须先完成授权、消息认证、proof 验证和安全状态准备。当前测试直接提供不透明合成字节；这些字节没有密码学意义。不能将这些方法直接暴露给 CLI、HTTP 或网络，也不能将 `core_binding` 当作本模块计算/验证的哈希。

`Store::create` 只允许全新目录，`Store::open` 不创建或重置缺失/损坏的库。目录必须为 canonical 0700，状态/锁文件为单链接 0600；这些检查不证明卷已加密或能够抵抗同用户/root 的并发路径替换。平台接入仍须验证受控父目录、用户身份、解锁和锁定生命周期。

schema 当前为 4，config/retry 仍为 1，未知版本拒绝。普通 open 遇到 v1/v2/v3 返回 MigrationRequired，须按实际来源显式调用 `Store::migrate_v1`、`Store::migrate_v2` 或 `Store::migrate_v3` 到当前版本。迁移为旧中继补预留、缩短旧 proof queue 至原消息 deadline、终结已到期证明并保留目标端交付事实；不重置 retry 预算。容量不足整笔拒绝，已有 v4 不重复执行，不能通过改版本号降级或静默重建。版本化记录与动作 generation 不是可信硬件抗回滚机制。

历史默认 7 天，由受信平台时钟推进；启动/Clock 命令和可选周期维护将时钟推进与有界清理一起提交，到期内容立即从查询过滤。`Service::start_with_clock` 的周期为 100 ms–60 s，平台必须提供可信且有界的 `ClockSource`；现有测试用合成源，Linux 时钟信任与休眠恢复后端尚未接入。不同 boot、单调时钟回退或已持久可信墙钟回退进入 `TIME_UNCERTAIN`，保留可读状态并拒绝写入，不能通过新的时间值自动解除隔离。提交结果不确定时停止查询/写入，须重开并按动作键查询，不自动重发。

依赖固定图、许可追溯及更新责任见 [THIRD_PARTY.md](THIRD_PARTY.md)。未接入 Tokio、HTTP/TLS、mls-rs、加密卷或 systemd，未修改原有 Go harness、密码 spike 或 I5 运行入口。

同一时刻的队列观察用 `Store::process_queue_batch` 一次提交，最多 128 个输入事件；同队列事件先合并，矛盾链路观察拒绝，整个批次提交后才返回决定。内部写方法仍要求已认证输入，不能接到公共 API。`usage` 的控制容量包含每条 live relay 预留的一个记录和 4096 bytes；这是逻辑责任容量，不是物理磁盘硬预留。

T-C 只保存 `Receive.receipt_intent`，不接收预生成的送达签名；提交后可用内部 `receipt_intent` 读取，再由 `finalize_receipt` 原子转换成待发证明。这些接口没有签验或身份授权能力，不暴露给 Service/CLI/网络。意图与中继预留都按一个控制记录及 4096 bytes 计费；转换失败保留意图，重复转换不重置队列。两条 proof 返回路径均使用原消息 deadline，到期维护各批最多清理 256 个 intent 和 256 个 proof，保留历史与去重。目标端 committed 表示 T-C 已提交，payload 到期后转为 delivered，仍表示已交付，不能因证明未返回而改成 expired。

D16 在原 8 MiB / 4096 控制总额度内固定保留 1 MiB / 576 记录，全局记录额度也预留 576 槽；业务 proof 按完整 4096-byte 责任计费，默认字节维度上限为 1792 条。迁移空间不足保留旧库；不通过删除 custody 或增大配置放行。`Usage.security_control` 报告专用预留和实际使用，`records` 包括两类实际记录，`reserved_control_*` 仍为业务证明预留。这些不是物理磁盘硬边界。

内部控制接口保存当前活动、五人四代绑定、退出/报告固定槽、Retiring 意图和邻居责任。`process_control_batch` 复用 Batch 合并和原子提交边界，消费八个 D16 时槽与两次有间隔恢复机会，已错过时槽跳过；每邻居最多十次尝试/控制 ACK。同 boot 重开从空桶开始且不返还持久次数；新 boot 拒绝输出。没有公开的新活动重配/清理接口，不删除旧活动 marker 恢复额度。真实签验、业务身份关联、入站限速与传输统一授权门仍待接入；详见控制持久化记录及其中保留的测试失败。
