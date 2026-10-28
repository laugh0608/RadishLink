# Node 活动生命周期与有界归档

- 日期：2026-10-28
- 范围：ADR 0008 D17 的活动作用域、schema v8 显式迁移、同 boot 切换与离线恢复验证；L2 持久化/安全边界
- 授权：所有者审阅[生命周期方案](../architecture/node-activity-lifecycle.md)后明确“接受，实施”；本批按所有者要求提交为 `c7008eb`
- 面向：Node 存储、状态拥有者和恢复验证协作者；不作为真实配对或密码安全验收

## 实施结果与使用顺序

沿用一个 Store、一个 SQLite 数据库与一个提交者。`preflight_activity_switch` 只读返回旧活动/修订、归档代价、控制/全局余额及等待/在途任务数。调用者先 `stop_control_activity` 明确停用，再用既有 `next_control_verification` 丢弃失效等待项，收回或取消全部在途 job。`switch_control_activity` 复核旧活动 ID、政策修订、停用、任务已收束、新标识、期限及容量，在单事务中完成旧上下文归档、旧动作退休、新上下文/指针建立与输出空桶重建。提交成功后重建内存入站空桶和拥有者标识。

本机停用不依赖归档空间；新活动失败保留旧停用状态，不恢复 Active。COMMIT 前失败无部分归档；提交结果未知隔离 Store，重开后以 `activity_status(previous)` 的持久 successor 查询结果。重复切换、复用旧活动/参与者/凭据、错误修订、运行中切换和未收束任务均拒绝。新活动空绑定，可信调用方仍须重新准备并核验凭据；没有密码生成、自动信任或真实连接。

`renew_action_scope(scope, previous_generation)` 在新活动中显式更新已退休 scope 的代数和活动关联；也可创建全新 scope。旧 `(scope,generation,reference)` 动作事实保留，不在新代数下解析成旧请求。`retire_action_generation` 同样保留既有动作事实，由总记录上限约束，不自动删除旧动作腾空间。

## 精确持久结构与兼容

| 记录 | v8 规则 |
| --- | --- |
| `control_activity` / `meta.current_activity` | 活动 ID 唯一，内部 id 递增；meta 指向唯一当前上下文。归档保存 closed_ms、successor 与有界的最终速率/游标摘要，旧 boot 坐标不改写 |
| 绑定、控制对象、邻居责任 | 原表增加 activity 外键和活动索引，保留原字节、状态与次数；credential/object reference 继续全库唯一，参与者不能跨保留活动复用，没有第二套归档表或数据库 |
| `current_control_*` | 只读查询视图限定当前活动；写入仍直接操作原表并校验当前活动。触发器拒绝归档控制记录的修改/删除及向旧活动插入新控制记录 |
| `security_states` | 复合键 `(activity,session)`；新安全状态从当前已授权消息 core 的 activity 取得作用域，联合事务检查不变。旧 v7 session 缺可靠映射，以空 BLOB 活动标记隔离保留；不视为空活动、不猜归属、不继续更新 |
| `action_scopes/actions` | scope 持久活动关联与 retired 状态；旧版 scope 退休但保留动作记录。显式续代才能绑定新活动，旧 generation 永久失效；新 scope 不继承旧请求 |
| 历史业务关联 | 消息、core、密文、去重、原 retry/ACK 次数保持；历史校验查对应旧活动/绑定，运行准入只查当前活动。`policy_stopped` 不反转，原来的到期与证明清理仍按各自规则执行 |

`Store::create` 建立 v8；普通 open 对 v1..v7 返回 `MigrationRequired`。可信维护方按实际源版本调用 `migrate_v1`..`migrate_v7`。历史迁移 SQL 不改；更早版本在同一事务沿旧链到 v7 边界，再检查活动不存在或已停用后进入 v8。仍在运行的旧活动导致整笔拒绝，须用兼容旧版本的可信入口先明确停用，不能直接改数据库标记；新代码不自动结束它。迁移后的旧活动仍停用，通信须新活动和新会话。旧 session/scope 没有映射时保留为隔离事实，普通 open 不静默赋权。

迁移复制四个控制表、重建安全状态复合键并替换索引/视图，全部处于同一 SQLite 事务；维护时需要额外页面/journal 空间。本次只覆盖合成临时库，没有生产迁移、磁盘总包络或真实用户数据操作。未知/重复/错误来源版本、损坏关联、容量不足、跨 boot 与时间回退继续拒绝或只读隔离。

## 容量、时间与真实接线限制

当前活动保留原 1 MiB / 576 记录。归档按上下文 4096、绑定 1024、对象 4096、邻居 512 bytes 计费；`activity_archive_usage` 从原表计算，加入业务控制字节/记录及全局 record_count。`Usage.archived_control_*` 单独报告归档占用，`Usage.records` 包含归档实占，`reserved_control_*` 仍表示业务证明预留。

保守单活动组合为 `4096 + 25×1024 + 100×4096 + 400×512 = 644096 bytes`、`1+25+100+400 = 526` 记录，不宣称此组合可同时达到。原控制余额 7340032 bytes，空归档也占 4096 bytes；证明理论容量相应降为 1791，保守满额归档降为 1634。实测用例覆盖空活动、多次切换、已有业务责任、控制字节/控制记录/全局记录刚好满足及少 1 的拒绝，不用伪造超出 D16 可达状态的“满活动”声称实测。

旧控制记录无自动回收；限额耗尽时拒绝新活动，不能抬高预算或先删除唯一 payload/历史/去重。逻辑计费不等于 SQLite 文件、journal、内存或宿主物理硬隔离。跨 boot 仍只读隔离，没有 ignore/reset/unlock；原 D9 的跨 boot 新活动与长期回收另行设计。

内部 job 计数清零不能证明外部线程/通道已关闭。真实 worker 的停止/Join、UI 撤销、framing/传输交接、严格签验和首次配对仍未接入；生产 run 继续拒绝。实际密码库、可信平台、许可证/R2/Phase B、新图 G1/G2、I5、HW/RF 停止线不变。

## 验证记录

环境为既有 macOS ARM64、Rust 1.97.1 和本地依赖缓存。仅合成临时数据库与受控测试子进程，未下载依赖、修改 manifest/lock、安装工具、启动服务/VM/设备或进行远程写入。

新增 18 项生命周期测试（含子进程入口）覆盖：历史/core/payload/去重关联保留；同名 session 新作用域零起点；旧动作退休/显式续代；旧 ID/凭据/政策拒绝；无新绑定不得通信；等待/leased job 收束与旧 owner 结果拒绝；入站/外发空桶；原控制对象/次数/ACK 保留；归档三类容量边界、空归档累积与业务预留不被抢占；每个切换写点失败；提交响应未知；切换和迁移的 COMMIT 前/后受控进程退出；v7 显式停用前置、空源与隔离迁移；归档关联/摘要损坏拒绝；跨 boot 与回拨不解锁。既有 v1..v6 迁移测试同步验证 v8 结果和新隔离契约。

执行命令：

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::activity_tests -- --test-threads=1
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml -- --test-threads=1
./scripts/check-repo.sh
git diff --check
```

开发中的失败保留，不以最终通过覆盖：

| 阶段 / 退出码 | 结果与处置 |
| --- | --- |
| 编译 / 101 | SQLite 计数误用不支持的 `u64: FromSql`，改为 i64 读入并检查转换；测试断言要求敏感 PreparedCore 实现 Debug，改用不打印内容的等值断言 |
| 首轮生命周期 / 101 | 6/9 通过；旧版合成 fixture 未先移除新 trigger；旧凭据缺失被映射为存储失败而隔离 owner。修正 fixture 顺序及明确 Conflict 拒绝，随后 9/9、扩展后 15/15 通过 |
| 首轮串行全量 / 101 | 149/163 通过；14 项旧版本数字、旧动作/旧活动继续可用假设与一项直接清表 fixture 不匹配新约束，按 v8 和隔离契约更新，不放宽产品逻辑 |
| Clippy / 101 | 一个测试使用 bool 等值断言，改为直接布尔断言，随后 Clippy 通过 |
| 第二轮串行全量 / 101 | 171/172 通过；普通维护用例的旧动作查询断言被批量替换误改，恢复原断言；18 项生命周期用例均通过 |

最终串行全量退出 0：**172 项库测试 + 2 项 CLI 测试通过**；fmt、Clippy、仓库与 diff 检查通过。既有并行测试 `store owner lock` Busy 根因未定位；串行成功不证明该风险已消除，也不证明真实 E2EE、网络、物理资源或安全平台验收通过。
