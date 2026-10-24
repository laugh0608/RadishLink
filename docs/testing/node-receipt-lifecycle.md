# Node 证明生命周期与恢复边界验证

日期：2026-10-24。本文记录 [ADR 0005 D6—D10](../adr/0005-node-security-integration.md) 接受后的 Node 自有持久开发，承接[服务运行可靠性](node-service-reliability.md)。读者为实现与验收人员；本文不证明 MLS、签名、身份撤销或 Linux 平台能力。

## 范围

所有者要求先固化决策，再继续不受现行停止线阻塞的开发与验证。本批为 L2：只改 Node、ADR、安全/架构专题和状态索引；使用已有 Rust 1.97.1 与固定 Node 依赖，未安装工具或依赖，未修改 Go harness、密码 spike、旧 lock/profile、根入口或现行 gate。

新接口仍只用于内部持久集成，Service 不提供 receipt 写入口，生产 run 仍拒绝。所有证明、状态、正文和身份引用均为合成字节；本批没有签名器或验证器，没有调用候选 storage trait，也未实现联系人撤销、新活动恢复或可信平台时钟。D6—D9 的真实机制及负例在[安全接入设计](../security/node-security-integration.md)明确，不用自造密码接口替代实际候选。

## 已实现行为

| 环节 | 行为 |
| --- | --- |
| T-C | Receive.receipt_intent 替代预先生成的 evidence；安全状态、消息、历史、去重与未签署意图在同一事务提交。提交失败不能读取意图或形成待发证明 |
| 提交后准备 | receipt_intent 只返回已提交意图、core、原返回邻居和原 deadline；时间隔离或到期拒绝读取供签署的数据。该读取不代表已完成授权或可以发送 |
| 意图转换 | finalize_receipt 先比较尚存意图，再原子删除意图并插入 evidence queue。历史和安全状态不再次推进；真实签署、语义匹配和撤销检查是未来调用者前置 |
| 响应丢失/重复 | 转换已提交但响应丢失后，重开可查询待发事实；相同已入队 proof 的重复调用不改 retry，改变 proof 返回 Conflict。签名器若产生不同字节，不自动覆盖已有证明，应查询并复用已存责任 |
| 控制容量 | 每个意图按一个记录、4096 bytes 计入预留，足以转换为当前最大 proof；relay 的预留保持原机制。满额拒绝 T-C/T-B；转换不增加最终记录数，不依赖腾出另一个控制槽 |
| D10 | C→B 与 B→A 的新 proof queue 使用原消息 deadline；T-D 和转换在 deadline 到达时拒绝，retain_until 不参与发送许可。重开和调度拒绝超出消息 deadline 的 queue |
| 维护 | 每批各清理最多 256 条 payload、已到期 proof、已到期 intent、到期历史；时钟与所有清理共同提交，more_due 包含控制积压。即使清理未轮到某条，deadline 检查也禁止继续调度 |
| 目标端事实 | 目标端 T-C 后状态为 committed；payload 到期清理后为 delivered，保留同一已交付事实，不改成 expired。中继/发起端未收到证明时仍可 expired；去重记录与历史独立保留 |
| 冷启动 | 新 boot 的现有隔离覆盖意图读取、转换、T-D、到期写入和时钟推进；新时间值或改回旧 boot 输入不能解除当前实例隔离。只读历史不成为旧会话继续使用的许可 |

预留是事务最终逻辑容量保证，不是 journal/磁盘写前硬预留。意图上限和证明上限均为现有内部控制上限 4096 bytes，不是已冻结的 COSE wire 上限。retry 的首次计划时间在证明首次入队时固定，后续重复不重建；原消息 deadline 始终独立约束。

## schema v3 与兼容性

原 schema.sql v1 与 migration_v2.sql 不改。新建库在一笔初始化事务中依次应用 v1/v2/v3；v3 新增 receipt_intents、完整消息 deadline 索引，并修正旧目标端 expired 的事实表达。普通 open 遇到 v1/v2 均返回 MigrationRequired；显式 migrate_v1 执行 v1→v3，migrate_v2 只接受 v2→v3。错误来源、重复迁移和未知版本拒绝，不能靠回填版本号降级。

迁移先核对已有 retry 格式及其原版本寿命边界，再共同提交可信时钟推进、schema、证明截止时间缩短和已到期证明清理。每条 retry 只取更早 deadline，保留 start、slot、recovery、link、phase 和最后批次；不退还预算、不重设起点。旧证据字节仅保持为旧内部数据，不因迁移获得真实性认证。时间隔离禁止迁移；损坏、SQL 错误或提交前故障不留半迁移状态。

新 MessageView 区分 receipt_intent_pending 与 evidence_pending，MaintenanceReport 增加两种控制清理计数。它们是未发布产品的进程内接口，未定义公共网络兼容协议。真实用户库迁移未执行；测试仅处理本轮新建的合成临时库。

## 验证结果与失败记录

环境：已有 Rust 1.97.1、bundled SQLite 3.53.2，本机 aarch64-apple-darwin。Node Cargo.lock SHA-256 仍为 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24`；没有依赖差量。

```bash
export RUSTUP_AUTO_INSTALL=0
export CARGO_TARGET_DIR="$PWD/.cache/node/target"
cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```

本批新增 16 项库测试，覆盖：

- 意图仅在 T-C 提交后可读、重复接收不增加历史、proof 转换不返还 retry、满控制/总记录预算转换最大证明。
- 安全状态写后、COMMIT 前/后故障；SQL 拒绝插入时意图删除回滚；实际子进程在 T-C、转换和 v2 迁移提交两侧退出。71/72 是预期故障退出，不是物理断电。
- deadline 前 1 ms、等于、后 1 ms；无维护调用时也拒绝转换/T-D；两条返回路径停止，256+1 清理积压不允许继续发送。
- 新 boot 不读取签署工作、不续传、不释放旧责任、不猜测删除历史；原时钟输入也不能解除隔离。
- v1/v2 显式迁移、重试预算保持、到期 proof 清理与目标端事实保持、迁移错误/跨 boot/损坏时旧 schema 保持、非法 queue deadline 与缺失意图拒绝重开。

开发中保留两次失败：首次编译退出 101，跨 store 子模块调用 insert_queue 的可见性不足，改为只对父模块可见的 pub(super)，未扩大公共入口；首次完整测试退出 101，58 项通过、1 项失败，迁移按新时钟清理了旧证明而责任检查仍使用旧持久时钟。修复为迁移事务先共同推进时钟，再检查责任，针对性复验通过。相应 SQL 故障现在发生在事务应用阶段并成功回滚，返回 StoreUnavailable，原测试对提交阶段 OutcomeUnknown 的预期同步修正。

修复后的完整测试 61 个库测试（含三个受控子进程入口）和 2 个 CLI 测试通过，共 63 项；无失败、忽略或筛选。Clippy `--all-targets -D warnings`、格式检查、仓库检查（264 个文件）和 `git diff --check` 全部退出 0。

## 未覆盖与接续

本批没有证明真实签名不可伪造、MLS 状态联合提交、撤销与网络输出竞争、物理掉电/防回滚或跨 boot 恢复。手动/合成 Clock 只证明给定坐标下的拒绝；实际签署、COMMIT 与输出跨 deadline 的时间竞态须在可信平台集成中再次验证。

本批无新增必须由所有者取舍的产品决定。本批之后已形成并接受 ADR 0006/0007 的身份、COSE、envelope 和控制预算，接续顺序见[日终事项](../status/2026-10-24-progress.md#接下来的事项)；实际候选接入前仍需许可证有效新证据、合格 R2 复核和精确功能试验授权，平台操作另行处理。这些证据缺口不通过新增合成测试或放宽入口消除。

本批实现与安全基线随后已提交为 `a5ef086`。没有 push 或其他远程写入，没有启动长期服务、VM 或实体设备。测试目录由测试清理，保留既有忽略目录 .cache/node/target；本页的 63 项结果是该批时点记录。
