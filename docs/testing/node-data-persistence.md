# Node D15 数据持久化与保守时间

- 日期：2026-10-28
- 范围：ADR 0007 已接受的 D15 自有字段、持久映射、时间运算与离线恢复验证
- 面向：Node 存储、协议接入与恢复验证协作者
- 授权：所有者要求继续推进当前下一步；按当前优先级实施 D15 离线批次并同步文档，随后明确要求提交该批次；本次本地提交不包含远程写入或真实运行
- 风险：L2，涉及 schema、内部调用兼容和安全时间边界；不改变已接受线格式，不开放生产入口

## 实际交付

`node/src/data.rs` 提供 `PreparedCore`、完整复合身份和可信 UTC 区间的有界运算；`store/data.rs` 将其接入既有 T-A/B/C、重复接收、T-D、证明意图及队列检查，`migration_v5.sql` 显式升级持久结构。没有另建服务或数据库，没有增加依赖、CBOR 编解码、摘要算法或签验器。

`PreparedCore` 的原始字节和解析字段必须由未来严格解码/认证层一致提供。当前只检查字段边界、持久一致性和时间预算，不证明原始 core 可合法解码，不验证 MLS sender/group/epoch/AAD，也不验证 `core_binding` 的摘要值。所有测试字节均为合成输入，Service/CLI 的业务发送仍拒绝。

| 边界 | 当前行为 |
| --- | --- |
| 原始 core | 原样保存 1..512 bytes；同时保存活动、两端 ID/凭据、message ID、group、epoch、创建时间、寿命和 initial_hops；类型固定为 CoreV1 的版本/种类 1、priority 0、content_type 1 |
| 完整身份 | `(activity_id, origin_id, origin_credential_ref, message_id)` 设唯一约束；同身份换内部 key 拒绝，同 key 改 core 任一字段拒绝；已有 payload 时还逐字比较完整 MLS bytes |
| 内部 key/配额 | 继续沿用有界内部引用；建议的 SHA-256/CBOR key 尚未计算。保留完整身份防止别名重复准入，`origin_ref` 从凭据引用生成 64 位小写十六进制，调用者不能任意更换别名拆分来源配额 |
| epoch | 固定 8-byte big-endian BLOB，Rust 边界为 u64；0、i64::MAX、i64::MAX+1、u64::MAX 均无损往返；不进行 signed INTEGER 强转或自动 epoch 推进 |
| 消息边界 | 新记录 binding 必须 32 bytes、MLSMessage 1..61440 bytes，寿命 1..3600000 ms、initial_hops 1/2；接纳的待发/收到副本已消费首跳，remaining_hops 小于 initial_hops；relay 新准入仍要求有剩余 hop |
| 时间映射 | `Clock.trusted_utc` 保存 `[L,U]`，宽度最多 2000 ms；`N=originated_at+lifetime` 和新 deadline 运算检查溢出，要求 `originated_at<=U<N`，使用 `min(N-U, received_remaining, local_cap)` 映射同 boot deadline |
| 重复与重开 | 保存首次原始 core/准入区间、boot、deadline 上界；重复消息只取更早 deadline/更小 hop，原队列同步缩短；保留 retain_until、retry 起算点、时槽与消费状态，不重新加密或补次数 |
| 输出与证明 | 每次内部队列决定、转发建队、T-D、证明意图读取和转换复核 UTC 上界与同 boot deadline；单调时间未到但 UTC 已到仍拒绝。决定仍不是可重放的网络发送许可 |
| 历史 | 新历史的七天窗口以准入 UTC 上界起算，删除/过滤使用可信下界；避免因区间不确定性提前删除。去重与动作记录不随 payload 清理 |

控制/数据事务仍共用原 Store 状态拥有者、原子提交、配额和故障处理。时间推进会保守收紧已存数据与队列 deadline；较晚或更宽的副本不能恢复期限。UTC 两端或 BOOTTIME 回退、已知来源消失和 boot 改变进入当前实例时间隔离；超宽/非法区间也由拥有者观察并隔离，后续时间值不能解除。重开比较持久时钟边界，跨 boot 保持只读；没有新增可信恢复/解锁机制。

`Message` 与 `Clock` 是未公开的集成基础类型，本批更改其字段，现有合成调用点已同步。准入与输出检查使用调用者交付的可信采样；采样新鲜性、漂移、检查至实际外部效果的最大间隔和真实 BOOTTIME 来源没有实现，不能用普通系统墙钟填值后运行。

## schema v5 与兼容

新库初始化到 v5；普通 open 对 v1..v4 返回 `MigrationRequired`，维护调用按实际源版本选择 `migrate_v1/v2/v3/v4`，在一个事务中升级到 v5。原 v1..v4 SQL 保持不变；旧版中继预留、证明期限和目标端事实修正沿用原迁移顺序。

v4 及更早消息没有完整 D15 字段，迁移不能推导或补造认证内容：旧消息标为 `data_version=0`，保留原消息、历史、动作、证明责任和预算供查询/到期维护；对其转发、队列输出、T-D、签署意图读取/转换返回 `UnsupportedVersion`。不提供把旧记录原地补成 D15 的接口。新消息为 `data_version=1`，在同库一对一的 `message_data` 表保存完整字段，缺失/错配元数据或未知版本拒绝；旧记录不能靠新收到的帧恢复输出。

元数据属于一个逻辑消息记录，不新增可独立创建的责任槽；受原 16384 总记录上限和每条固定长度/512-byte 原始 core 上限约束。`Usage.records` 继续计逻辑责任，payload_bytes 继续计 MLS payload，新增元数据/索引的物理页由原 SQLite 128 MiB 主文件上限约束，journal 和文件系统仍不在这一硬界限内。D16 的 1 MiB/576 记录预留不变；这不是完整物理资源隔离证明。

错误源版本、重复迁移、未知 schema、跨 boot、存储失败或不满足原容量边界均拒绝。COMMIT 前失败回滚全部变更；提交结果未知仍隔离，重开按实际持久结果查询。不得手改版本号降级；真正 v1..v4 实例仅在合成临时目录重构用于测试，本批未操作真实用户库。

## 验证与失败记录

环境：既有 macOS ARM64、Rust 1.97.1 与本地依赖缓存；使用 `--offline --locked`，无下载或 manifest/lock 变更。最终全量 109 项库测试（含新增 13 项 D15 存储/时间用例和 1 项 Service 时间隔离用例）、2 项 CLI 测试通过；fmt、Clippy、`./scripts/check-repo.sh`（289 文件）与 `git diff --check` 均通过。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```

新增验证覆盖 epoch 四个边界、完整身份冲突/不同作用域、原始字节保留、字段/长度/hop/时间拒绝、N-1/N/N+1 与 1999/2000/2001 ms、加法溢出、重复期限收紧与队列不返还、UTC 提前到期、历史保守保留、同单调坐标重开的新 UTC 样本、旧库全输出拒绝及可读事实、损坏拒绝。COMMIT 前后子进程退出覆盖 v4→v5、T-C 元数据/安全状态/历史/意图联合写入和重复期限收紧；不是物理掉电或 Linux 实测。

| 开发命令 / 阶段 | 失败与处置 |
| --- | --- |
| 初次 fmt，退出 1 | 新测试模块文件尚未创建，创建后完成格式化 |
| 首次 `cargo test --no-run`，退出 101 | SQLite 长度读取误用不支持的 usize；改为受界 u32。测试比较 Vec 与引用的类型错误同步修正 |
| 首轮串行全量，退出 101，80/100 通过 | 维护查询错误传入第三个参数；修正为 SQL 的两个参数。旧迁移断言仍期待 v4 或允许旧记录输出，以及无 UTC 时准入旧合成行为，按显式 v5 兼容合同更新；未放宽生产检查 |
| 首次 Clippy，退出 101 | 嵌套条件 lint；改为 match，保留非到期错误原始上下文 |
| 增强持久采样一致性时 Clippy，退出 101 | 元数据查询未同步增加局部变量；补齐明确列读取，随后 Clippy 通过 |

以上失败保留；此前 D16 批次的瞬态文件锁 Busy 记录仍有效，本批通过不证明其根因已经修复。

## 接续与停止线

下一批可对照完整活动/端点凭据把 D16 控制政策关联到业务、证明和输出责任，再处理共享控制外发、入站限速/公平调度及新活动生命周期。真实严格解码、MLS/COSE、标准摘要、认证映射、可信平台和 transport 尚未接入；不把 PreparedCore 或合成测试称为已验证 E2EE。

未运行 G1/G2、R2/Phase B、正式 harness/I5-R、网络、VM、设备或射频，没有依赖安装、采购、push 或远程修改；所有者随后授权本批本地提交。原安全、许可证、资源与 HW/RF 停止线保持。
