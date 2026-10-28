# Node D16 控制持久化与尝试预算

- 日期：2026-10-28
- 范围：已接受 ADR 0006/0007 下的 Node 自有持久化、逻辑预留、控制调度与显式迁移
- 面向：Node 存储、调度、安全接入与恢复验证协作者
- 授权：所有者本次明确要求实施 D16 控制状态持久化、容量预留、尝试预算，完成必要验证并同步文档；随后明确要求提交工作区更改，本批实现与文档随本次本地提交保存，不包含远程写入
- 风险：L2，涉及持久化版本、容量兼容性与安全状态基础；不开放现有生产入口

## 实际交付与接口前置

新增 `node/src/store/control_types.rs`、`control_state.rs`、`control_objects.rs`、`control_scheduling.rs`、`migration_v4.sql`，在现有 `Store`、单拥有者锁和 `atomic` 事务中实现。复用既有 `Batch::merge`、128 事件上限、时钟隔离、错误与提交故障机制；没有另建服务、runner 或数据库，也没有改动 I1 数据重试时槽。

`PreparedControl` 的解析字段、原始 payload、标准摘要引用与 COSE bytes 必须由未来严格解码、验签及授权层提供。存储层只验证有界性、绑定一致性、当前政策和持久责任，不计算摘要、不签验、不将合成字节变成认证结果。配对接口只供可信本机调用，不能把任意网络输入送进 Pending。所有新增写接口均未向 Service/CLI/网络暴露。

| 已实现边界 | 行为 |
| --- | --- |
| 活动 | 一个持久活动，最长 12 小时；deadline 只可缩短，停用保留 marker；错误 activity、到期、跨 boot 拒绝输出 |
| 绑定 | 最多五人；每人连续 1–4 个代数，每人至多一个 Pending；核验激活与封禁旧代同事务，旧代不复用、不删除后重占位 |
| 控制对象 | 原始 COSE/payload 各有界至 512 bytes，保留首个对象；退出按目标凭据、报告按 reporter participant 与目标凭据固定槽；同 operation 不同载荷冲突，换 operation/reason/报告者凭据不能新开已占槽 |
| 本机退出 | 先持久固定退出意图并置 Retiring；未来签署结果只能匹配该意图，随后原子写封禁、原始对象与邻居责任；失败保持 Retiring，已完成或被所有者封禁的意图不再作为待签工作返回 |
| 邻居责任 | 每对象最多四个 participant 槽；换凭据、地址、重复接纳或重新排队不替换槽或恢复次数；报告只能提示，不能封禁目标 |
| 尝试 | 八个既定时槽和两次间隔至少 60 秒的 Down→Up 恢复机会；每次先持久消费再返回决定，提交结果未知时不得输出，写失败不返还 |
| ACK | 当前活动内已存在的控制对象/邻居槽最多十次 ACK；未知对象不建状态；已认证持久 ACK 仅终结对应邻居责任，不能提升为全队撤销或目的端送达 |
| 外发额度 | kind 2/3 对象与其 ACK 共用 4 frames/s、8192 bytes/s 的逻辑桶，同值 burst；对象按完整上限 522 bytes、ACK 按 127 bytes 保守计费；首次活动及同 boot 重开从空桶开始，不补停机额度 |

本批只保存一个活动范围，不提供删除 marker 后重新使用活动 ID 的接口。停用后建立新活动、重新配对、历史保留与安全状态切换仍须后续完整生命周期接线；这不是修改已接受的重新配对方向。在本 D16 批次结束时，业务 `Message` 尚无 D15 完整身份映射；后续字段实施见[数据持久化记录](node-data-persistence.md)。同日后续[业务政策关联](node-business-policy.md)已接入 T-A/B/C/D 与证明的内部检查，实际 transport 统一授权门仍未接入，不能宣称已经实现产品撤销。

## 容量与 schema v4

默认总额仍是 8 MiB / 4096 控制记录。schema v4 在创建、迁移、重开和事务准入时固定扣除 **1 MiB / 576 记录**，即使尚无活动或实际记录很少也不外借；全局记录额度同时保留 576 槽。小于完整预留的 Limits 不能创建 v4 库，旧库不能通过迁移；config 仍为 v1，不静默提高配置值。

业务证明意图、中继预留和已入队 proof 均按每条 4096 bytes 收费。过去对已入队 proof 按实际 body 长度检查的路径已统一为责任计费，短 proof 转换不会释放可再承诺的控制额度。默认字节上限为 1792 条，其他既有限额仍可能先命中。

D16 实际使用按绑定 1024、对象 4096、邻居状态 512、辅助记录 4096 bytes 核算。当前辅助表只有活动和限速器两条记录，完整 51 个辅助槽及剩余逻辑余量继续保留。`Usage.security_control` 区分固定保留与已用；原 `reserved_control_*` 继续表示业务证明预留，`records` 包括两类实际记录。所有值均为应用逻辑责任，不证明 SQLite journal、索引页、文件系统或整机硬隔离。

原 v1/v2/v3 SQL 文件未改。新库依次初始化到 v4；普通 `open` 对 v1/v2/v3 返回 `MigrationRequired`，维护调用须按来源选择 `migrate_v1/v2/v3`，在同一事务迁移到 v4。v1/v2 的原有证明迁移语义保留。错误来源、重复迁移、未知版本、时钟隔离、损坏、空间不足及提交失败均拒绝；不删除旧责任凑空间，不手改版本号降级。容量不足的 v3 库保持原样，需在原兼容实现下正常终结责任后再评审迁移。

重开活动库时，空桶重建与当前可信时间坐标一起提交；原始接纳时间、邻居起算点、时槽、恢复机会、ACK 和尝试计数不变。跨 boot 只保留只读事实，不执行该写入或恢复输出。

## 调度与结论边界

`process_control_batch` 在现有状态拥有者内合并同坐标事件并原子提交，冲突链路观察拒绝整批。退出先于报告处理；不同业务/证明/ACK 的轮转公平与实际发包还未接线。常规时槽使用既定毫秒坐标，已错过的槽直接消费，不增加宽限或迟到补发；正常槽与恢复机会同批至多返回一次输出。配额拒绝、断链和重复事件均不能返还已消费机会。

返回 `send=true` 只表示本次内部预算已提交，不是可重放的网络发送令牌。未来传输必须在同一串行授权门复核当前通道凭据、活动/时间、撤销状态，并防止一次决定被重复使用。真实签验、严格 CBOR、可信时钟、物理限额、入站速率/16 对象验签队列、业务 receipt/数据 ACK 的共享外发计费以及公平调度都没有被本批证明。

## 验证

使用既有 macOS ARM64、Rust 1.97.1 与本地缓存，无新增依赖、下载或 lock 变化。运行入口仍拒绝，测试数据全部合成。最终 95 项库测试（含 22 项 D16 用例）及 2 项 CLI 测试通过；受控子进程只验证 COMMIT 前后进程退出，不替代物理掉电或 Linux 实测。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml -- --test-threads=1
./scripts/check-repo.sh
git diff --check
```

覆盖：

- 20 绑定及额外成员/第五代拒绝，Pending 冲突、错误核验和旧代拒绝复活；80 报告满额后新 operation 合并，报告者换键不扩容，陌生目标拒绝。
- 575/576 保留记录、1 MiB 前后和 577 总控制记录的一条证明准入；4095/4096 业务余量、短 proof 仍计满责任；1792 条业务责任与 80 报告同时占满后自身退出及本机封禁仍可处理。
- 四邻居槽、全部十次尝试、迟到/断链、两次恢复间隔、同批合并、冲突整批回滚、单邻居 ACK 终结、未知 ACK 不建库、十次 ACK 上限及重开空桶。
- 重复/乱序/字段冲突、512/513-byte 对象边界、活动提前截止/停用、跨 boot、整数时间上界、Retiring 失败及原始退出对象保留。
- v1/v2 既有迁移回归、显式 v3→v4、容量不足与故障时源库保持、控制状态/时间篡改拒绝重开；新迁移、退出意图、退出完成、尝试消费分别覆盖提交前后子进程退出。

20 个退出、100 个对象与 400 个邻居是由绑定/固定槽及显式上限共同约束的保守容量。测试实际填满 80 报告，并验证其不能挤占退出；未把任意构造的 20 个退出或 576 个实际记录写成可达的真实活动/网络场景。

### 开发失败与复验

| 命令 / 阶段 | 失败与处置 |
| --- | --- |
| 首次上述 `cargo test`，退出 101 | `u64: FromSql` 不满足；SQLite 计数改读受界 u32 后无损转 u64 |
| 首轮全量，退出 101，79/80 库测试通过 | 既有 `intent_and_conversion_failures_never_publish_partial_work` 在重开时出现 `Busy: store owner lock`；精确单测复验退出 0。后续完整并行套件通过，但该次瞬态锁失败根因未确认，不能写成稳定性问题已修复；未添加锁重试或吞错 |
| 定向 `cargo test ... store::control_tests -- --test-threads=1`，退出 101 | 满额 fixture 先缺中继 source_neighbor，后触发每 origin 512 条上限；补正确来源并分配四个合成 origin，不放宽产品检查 |
| 首次上述 Clippy，退出 101 | 三个长 tuple 的 type-complexity；改为明确的活动、控制对象和邻居记录结构，没有抑制 lint |
| 增强持久一致性检查后的定向测试，退出 101 | 四个恢复用例发现重开空桶坐标领先 meta；空桶重建与活动首次建立先在同一事务写时钟，再校验，不放宽检查 |
| 增加时间上界测试，退出 101 | 既有测试 `clock(now)` 的 `100000 + now` 在合成极值溢出；该用例改用显式独立 UTC/单调坐标，生产代码未为 fixture 放宽边界 |

以上失败保留。最终验证只说明当前代码在所列离线条件通过；首次并行锁失败仍是待定位的测试稳定性风险。

## 接续与停止线

本批之后于同日完成 [schema v5 / D15 字段与时间迁移](node-data-persistence.md)，原始 core、复合身份、uint64 epoch 和 UTC 区间/同 boot deadline 已有有限离线验证；随后完成[业务政策关联](node-business-policy.md)的内部检查与持久停止。同日又完成[共享外发额度/责任轮转](node-outbound-scheduling.md)的 schema v7 内部接线。新活动重新配对、真实签验/联合事务、完整控制入口与真实传输公平仍须在各自前置范围内接续，不通过增加合成 helper 冒充安全闭环。

本批没有修改 manifest/lock、固定密码图、历史实验合同、I5 入口、公共 Service 发送能力或根协作规则；没有运行 G1/G2、Phase B、正式矩阵、设备/VM/网络、采购或射频操作。许可证/R2、可信平台、I5 资源、HW/RF 停止线保持。
