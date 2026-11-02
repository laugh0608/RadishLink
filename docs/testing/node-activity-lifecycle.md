# Node 活动生命周期与有界归档

- 日期：2026-10-28
- 范围：ADR 0008 D17 的活动作用域、schema v8 显式迁移、同 boot 切换与离线恢复验证；L2 持久化/安全边界
- 授权：所有者审阅[生命周期方案](../architecture/node-activity-lifecycle.md)后明确“接受，实施”；本批按所有者要求提交为 `c7008eb`
- 面向：Node 存储、状态拥有者和恢复验证协作者；不作为真实配对或密码安全验收

以下至 D18 章节前保留 2026-10-28 D17 的实施与失败记录；当前 schema v9 和跨 boot 结果见 [D18 接续](#d18-跨-boot-时钟域与-schema-v92026-11-02)，不把旧批次的 v8/未实现结论当作当前状态。

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

## D18 跨 boot 时钟域与 schema v9（2026-11-02）

- 接受与授权：所有者明确接受单库时钟域、两步转换、每域计费及显式 v9 迁移，并授权 Node 自有边界与合成离线验证，见 [ADR 0009](../adr/0009-node-clock-domains.md)。不包含本批 Git 提交/push 或真实运行。
- 基线：`9a57466`，沿用现有 macOS ARM64 / Rust 1.97.1 / 本地缓存；不改 manifest/lock、原 SQL、资源总额或实际密码前置。
- 结论范围：新 schema、维护事务、业务/历史/控制查询及故障恢复的内部边界；不是可信 boot/UTC、真实重配、MLS/COSE、物理掉电或产品 E2EE 验收。

### 结构与调用顺序

| 结构 / 接口 | 实际行为 |
| --- | --- |
| `clock_domains` / `meta.current_domain` | 初始域 ID 为全零 32 bytes，仅作本库关联；sequence 从 1 受检递增。域保存唯一权威 boot/单调/UTC 坐标，meta 不再保存时钟副本，`current_clock` 是当前域只读视图 |
| 域状态与请求 | frozen 域坐标与隔离事实不可变；isolation JSON ≤1024 bytes，transition JSON ≤2048 bytes，严格拒绝未知字段；boot 沿用 Clock 的 64-byte 限制，请求引用为有界 ASCII、≤256 bytes。各操作的引用在保留域中唯一，完整参数改变拒绝，重复结果只返回事实 |
| 活动 / 消息 | 活动、messages、message_data 显式关联域；跨 boot 归档使用 closed_kind=cross_boot、closed_ms=NULL，保留原期限和次数。消息域使用真实 FK、回填、insert/update 必填触发器与全库校验，兼容 SQLite 对非空表增加 REFERENCES 列的限制 |
| `preflight_clock_domain` | 只读返回源域、可空旧活动、净归档成本及控制/全局余额；无旧活动只计域 4096 bytes / 1 记录，有空活动再计 4096 / 1，不造免费域或假活动 |
| `isolate_clock_domain` | 不要求可信新 UTC、归档余额或新身份；在同一事务冻结原坐标、停用旧当前活动、退休动作、单向停止源域业务政策。不会伪造签名退出或改写旧 payload/期限 |
| `establish_clock_domain` | 核对隔离结果、完整请求、可信新采样、UTC 端点不回退、新 ID/sequence、任务数及容量；一次事务建立新域/空活动、归档原上下文、写后继/指针及空桶。没有真实绑定时业务仍拒绝 |
| 兼容迁移 | 普通 open 对 v1..v8 返回 MigrationRequired。migrate_v8 要求同 boot 且旧活动已停用；migrate_v8_isolated 将 v8 结构映射、原坐标校验与冻结共同提交，只返回隔离库。旧 migrate_v1..v7 沿原停用/同 boot 前置和未改 SQL 链到 v8，再到 v9 |

v1..v4 没有 D15 UTC 上界，只有已通过原前置的同 boot 迁移使用当前可信采样补齐区间后再映射。冷启动 v8 路径不构造旧 Clock，也不推进原坐标。中途失败整体回滚源版本；提交结果未知隔离拥有者，重开后查询持久后继，不重复建域或发放额度。

新域成功后 `time_uncertain` 仅对新写域解除，旧会话和责任仍隔离。新活动可使用全新核验绑定与动作代数提交合成业务；旧凭据、session、动作、job 和输出不能继承。验证 job 额外保存域关联，owner/domain 任一不匹配拒绝；实际 worker 停止/Join 仍由未来调用方负责。

### 查询、计费与恢复核对

`constrain_data_clock`、deadline 维护及 more_due 限定当前域，旧消息按所属域的冻结坐标校验；不把新 boot 较大/较小的单调数值当成旧消息到期证据。同域的旧活动继续沿已有到期清理规则处理。原逐行队列/业务/数据完整性及逻辑配额仍覆盖全库，避免只看当前活动漏掉旧责任或损坏；后继域必须保留可信 UTC 区间且端点不早于前域，重开校验也拒绝缺失或回退。旧政策停止的证明清理及 D5 的 UTC 下界历史清理分别保留。

当前域按 4096 bytes / 1 记录计入原固定预留；归档域进入原业务控制余额及全局记录计数，当前预留不外借，总额不增加。SQL view 从原表直接计费，共享域仅计一次，域数不超过活动数加 1。满额拒绝建立新上下文，隔离仍可提交；未新增自动控制归档、payload、marker、session 或域回收。逻辑计费不证明 SQLite/journal/内存或物理硬隔离。

新增 20 项测试（含受控子进程入口），覆盖新 boot 内部业务提交、重新绑定/动作与同名 session 零起点；旧原字节/payload/期限/预留/历史保持；无旧活动/空活动计费；完整重复与参数/来源重放拒绝；UTC 缺失/回退、旧 ID、sequence 超限、旧 job；新旧单调坐标小于/等于/大于；两个以上域及两步间再次 boot；字节/控制记录/全局记录恰好满足或少 1；十个事务写点失败；COMMIT 未知及隔离/建立/冷迁移两侧的六次实际子进程退出；冻结事实不可改、旧记录损坏全库拒绝、历史 UTC 到期不删除旧 payload/动作事实。旧 v1..v8 fixture 从原 SQL 重建，未修改历史迁移脚本。

### 实际验证与失败保留

所有日志保存在忽略目录 `.cache/node/2026-11-02/`，只使用合成临时库和受控子进程。初期失败继续保留：

| 阶段 / 退出码 | 结果与处置 |
| --- | --- |
| 首轮编译 / 101 | StoredData 新增 domain 字段未填，补齐查询映射；未用默认域掩盖缺失 |
| 首轮新域扩展定向 / 101 | 15/17；SQLite 不允许对非空表直接添加带非 NULL default 的 REFERENCES 列；改为显式回填加 FK/必填触发器及全库校验。一项损坏 fixture 被新 SQL CHECK 提前拒绝，改用仍能进入实际恢复校验的损坏字段 |
| 首轮兼容全量 / 101 | 158/181；包含上述迁移限制、旧版本/空库记录断言及旧字段触发器位置不匹配，分别修正实现或 fixture，不放宽产品限额 |
| 第二轮兼容全量 / 101 | 183/196；余下 13 项由 v1..v4 缺 UTC 上界导致区间检查失败，保留 source 诊断，按原同 boot 许可补齐；定向复验通过 |
| 新域定向复验 / 0 | 17/17，通过后补三项跨来源请求引用、旧 job 及单调坐标用例，并将恢复用例按职责拆分 |
| 首轮最终全量 / 101 | 197/199；两项旧控制 fixture 未计当前域记录/未填消息域，按实际 schema v9 修正；控制套件定向 22/22 通过 |
| 首轮 Clippy / 101 | 新 job 拒绝测试漏传 neighbors 参数，补齐真实接口参数；最终 all-targets `-D warnings` 通过 |

修正两项控制 fixture 后，第二轮默认并行全量退出 0：199 项库测试 + 2 项 CLI 测试通过（库测试 145.30 秒）。收尾自审又补齐后继域 UTC 缺失/回退的恢复不变量与损坏库用例，定向复验通过；最终默认并行全量再次退出 0：**199 项库测试 + 2 项 CLI 测试通过**（库测试 129.84 秒，`domain-full-final-3.log`），未出现 owner lock Busy。fmt、all-targets Clippy `-D warnings`、仓库检查（316 文件）、53 个本地 Markdown 锚点与 `git diff --check` 均通过。此前失败日志保留，不据两次通过推导 Linux 或所有锁行为已验证。

本批 manifest/lock、初始 schema、历史 migration SQL 与根入口未变；`Cargo.lock` SHA-256 仍为 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24`。收尾时 `dev` 相对本地 origin/dev 仍 ahead 2，D18 文件未暂存/提交；本次没有 fetch/push 或其他远程修改。测试及子进程均已退出，日志保留在上述忽略目录，无本任务后台进程。正式 SW/I5 实验、真实安全/平台/设备入口及真实数据迁移均未执行。

执行入口：

2026-11-02 上述交接后，所有者明确要求提交工作区并继续下一步；D18 本地提交由此另行授权，不扩大原实施或外部运行范围。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```
