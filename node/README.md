# RadishLink Node

Rust 服务与事务基础，依据 [ADR 0004](../docs/adr/0004-node-service-foundation.md)。当前可验证单写者应用入口、SQLite 联合事务、恢复与调度；尚不能部署为聊天服务。实施范围、容量边界及测试结果见[第一批记录](../docs/testing/node-service-foundation.md)。

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
- `store`：schema v1、单拥有者、T-A/B/C/D 持久操作、查询、时间隔离、配额与历史清理。
- `service`：容量 32 的命令队列与专属状态线程；查询已提交事实，业务发送明确拒绝，关闭时等待线程退出。
- `error`：稳定错误分类与受控诊断原因；默认 Display/Debug 不回显底层输入。

`Store` 写方法是内部集成基础：其调用者将来必须先完成授权、消息认证、proof 验证和安全状态准备。当前测试直接提供不透明合成字节；这些字节没有密码学意义。不能将这些方法直接暴露给 CLI、HTTP 或网络，也不能将 `core_binding` 当作本模块计算/验证的哈希。

`Store::create` 只允许全新目录，`Store::open` 不创建或重置缺失/损坏的库。目录必须为 canonical 0700，状态/锁文件为单链接 0600；这些检查不证明卷已加密或能够抵抗同用户/root 的并发路径替换。平台接入仍须验证受控父目录、用户身份、解锁和锁定生命周期。

schema/config/retry 持久版本当前均为 1，未知版本拒绝。没有旧产品库迁移；后续 schema 变更须显式 migration、版本和失败测试，不能在现有 v1 库上静默重建。版本化记录与动作 generation 不是可信硬件抗回滚机制。

历史默认 7 天，由受信平台时钟推进；服务启动和 Clock 命令负责到期删除。平台时钟源及定时驱动尚未接入。不同 boot、单调时钟回退或已持久可信墙钟回退进入 `TIME_UNCERTAIN`，保留可读状态并拒绝写入，不能通过新的时间值自动解除隔离。提交结果不确定时停止查询/写入，须重开并按动作键查询，不自动重发。

依赖固定图、许可追溯及更新责任见 [THIRD_PARTY.md](THIRD_PARTY.md)。未接入 Tokio、HTTP/TLS、mls-rs、加密卷或 systemd，未修改原有 Go harness、密码 spike 或 I5 运行入口。
