# SW-G4 合成验证准备：持久文字路径单元 I3

- 状态：有限范围 Accepted；十文件实施与离线验证通过
- 日期：2026-09-26
- 基线：`3b5bf8f`，I1 重试/长度与 I2 frame codec 均已提交
- 目标读者：消息、存储与验证实现者
- 产物：有界输入 → A 入队 → B custody → C 提交 → evidence 返回 → 进程重开的完整离线合成路径
- 非目标：生产协议/数据库、真实身份/密码、正式 profile schema 2、Docker/网络或实体三节点验收

## 范围与关键选择

本包承接[文字切片的队列与事务设计](../architecture/minimal-text-slice.md#队列与事务的接入设计)，将下一次实现按完整路径组织，不再逐个批准 codec、队列、存储 helper。新代码仍在既有 Go module，使用标准库，复用 I1/I2；没有新增依赖或命令入口。

包 `internal/synthetic` 明确承载合成消息测试模型，依赖 `internal/delivery` 和 harness 的 frame codec；不把此模型当生产消息模块。测试使用三个独立 store 目录与 A/B/C 实例、内存字节流和注入逻辑时钟，无 socket。进程恢复用短命的 Go 测试子进程验证，不能称为物理掉电或正式三节点网络证据。

2026-09-26 所有者以“接受，继续推进”接受本包的 L2 选择及离线执行范围：测试 envelope v1、store v1、四消息容量/速率预算、单写者文件提交及恢复限制。它们不接受整体 SW-G3 修订，不冻结生产格式，不覆盖真实用户数据。已接受的 I1/I2 行为、V0 profile 与旧 t0node 格式保持原样。

## 输入与版本合同

### 外层与编码

- 用 `ReadSyntheticFrameWithLimit(..., delivery.MaxFrameBodyBytes)` 接收 body，最多 32768 B；数据 payload `1..16384 B`，控制 body 最多 2048 B。写出使用相同限额，4-byte 外层前缀单独计入发送速率。
- 只接收下述字段顺序的紧凑 JSON：Go 标准 `json.Marshal` 对显式 wire struct 的结果，无尾部换行，禁用 `omitempty`，不用 map 决定字段顺序。先有界解码、严格未知字段拒绝和语义检查，再重新编码并要求逐字节相等；任何 error 均丢弃整个候选对象。
- 因而拒绝缺失/null/重复/大小写别名字段、未知字段、额外 JSON 值、空白或其他非规范表示；不把“JSON 合法”当“本测试格式合法”。整数使用 int64，拒绝浮点、指数、字符串数字及溢出；所有标识使用下述 ASCII 限制。payload 不在 JSON 字符串内直接传正文。
- base64 使用带 padding 的标准字母表；先按声明及编码字符数检查，再严格解码，要求重新编码相等且实际字节数等于声明。不接受 CR/LF、无 padding、非零尾部填充位或 URL 字母表。原始长度最大 16384 B 对应编码最大 21848 字符；仍独立检查完整 frame。
- schema 不设透传扩展袋；增加/改变字段必须新版本并增加拒绝/兼容测试。`envelope_version`、`store_version`、未来 profile/evidence schema 版本各自独立。I3 decoder 不接受 t0node version 0 或生产密文；V0 decoder 不作放宽。

严格重编码使用固定测试向量验证，不新增一套泛用 JSON scanner。默认 Go JSON 对重复 key、大小写和部分非法 Unicode 有宽松行为，不能只靠 `Unmarshal` 判断合同成立；依据为 [Go 1.26.3 encoding/json 文档](https://pkg.go.dev/encoding/json@go1.26.3#Unmarshal)。此约束仅为合成格式，不是密码学 canonicalization 或签名方案。

### 完整 envelope 字段

下表顺序为 wire 顺序。三个类型各用自己的显式 struct；不适用字段必须不存在，不以空字符串或 null 占位。`run_id` 为测试隔离值，不是 SW-G1 message key 的替代。

| 类型 | 字段（依次）与边界 |
| --- | --- |
| 所有类型的公共头 | `envelope_version`=1；`security_mode`=`synthetic`；`kind`=`data`/`custody`/`delivery`；`run_id`=32 位小写 hex；`origin`=`A`；`replay_scope`=1..64 字节 `[a-z0-9_-]`；`message_id`=32 位小写 hex；`destination`=`C` |
| data 后续字段 | `originated_ms`=0..60000；`lifetime_ms`=1..30000；`initial_hops`=2；`remaining_hops`=0..2；`priority`=`normal`；`payload_kind`=`synthetic_opaque`；`payload_bytes`=1..16384；`payload_b64`=上节编码；`core_sha256`=64 位小写 hex |
| custody 后续字段 | `core_sha256`；`issuer`=`B`；`recipient`=`A` |
| delivery 后续字段 | `core_sha256`；`issuer`=`C`；`recipient`=`A`（经 B 返回） |

本包只支持固定 A—B—C、一个 run 与一个 replay scope、normal 文字类，最多四个本地动作。新 scope、额外节点、反向 C→A 数据和多路由均显式拒绝，而非动态创建无界 map；后续另版扩展。message key 为 `(envelope_version, origin, replay_scope, message_id)`，store/验证上下文另绑定 run。

schema 通过后还须校验接入上下文：B 只接受 A 传来的 remaining_hops=1 数据，C 只接受 B 传来的 remaining_hops=0 数据；未来 originated_ms、非本 run/scope 及非该路径的 custody/delivery 均拒绝。schema 中允许的数值范围不是转发授权。

`core_sha256` 是标准 SHA-256 对按表中顺序编码的公共头及 data 字段计算的**合成一致性指纹**，计算输入排除 `remaining_hops` 和 `core_sha256` 本身，保留其他 data 字段。B/C 必须重算 data 指纹；相同 key 不同指纹为 conflict。它不认证身份、不可变核心或证据，不提供防恶意篡改保证；不得把摘要匹配直接当作送达。

### 合成判定与本地动作

构造 Node 必须提供显式的合成判定来源，nil/未知判定拒绝。每次判定绑定接收节点、实际相邻节点、完整 frame 指纹、message key 和请求用途（admission、destination、custody、delivery、relay-clear）；测试来源只接受预登记的合成上下文。线上 envelope 不携带 `verified`、`authenticated` 或任意成功布尔值。

data 的准入、C 接收、A custody、A delivery、B relay-clear 分别消费相应判定；B clear 接受不替代 A delivery 接受。错误判定不得推进状态。所有成功事件均带 `security_mode=synthetic`，测试名称不得写真实认证通过。该测试来源是注入的分支 oracle，不是安全实现或新的凭据格式。

本地 `Submit` 输入为 run/Node scope、`action_ref`（1..64 字节 `[a-z0-9_-]`）、固定 fixture message ID、合成字节和 now。同动作同 key/核心查询原结果；同动作不同 key/核心拒绝，原绑定不变。一个 run 最多 4 个动作绑定，保留至 run 结束，不静默删除后重新发送；没有 Web 会话、真实配对或随机 ID 安全结论。

## 队列、预算与事务合同

### 固定资源配置 `i3-small4-v1`

| 对象 | 限额与计费 |
| --- | --- |
| 活动传输 payload | 每节点最多 4 条/65536 原始字节；A/C 历史保留另计，不以释放传输标记删除历史 |
| 消息元数据/去重/终态 | 每节点最多 128 条；每条固定预留 2048 B，覆盖无 payload 的核心、事实与 tombstone；实际序列化超额拒绝 |
| 调度责任 | 数据/控制共享最多 128 个已创建或预留槽；每槽固定预留 8192 B，含最多 64 个 RetryBatch；实际序列化超额拒绝 |
| 动作引用 / 历史 | 动作最多 4 个，每个 512 B；A/C 历史最多 4 条/65536 原始字节，正文在消息记录中单份存储，以标记区分传输与历史计费 |
| 控制与元数据总额 | 上述元数据、责任、动作及 bucket（每个预留 512 B）合计最多 128 objects / 262144 B；预留槽也计数，不把数据队列元数据当免费空间 |
| 整个状态文件 | 编码后最多 1048576 B；单次事务旧文件与临时新文件共最多 2097152 B，另有有界的目录/小元数据开销；不是磁盘或 RSS 硬 quota |

以上为小范围离线配置，不替换 SW-G3 的 2048-message 正常队列或 1000-message flood 参数。因只允许一个 origin/scope/priority，其各维度受同一总上限；每个邻接仍显式计数，不能借新邻接逃逸。全量编码用有界 buffer，读取先限制文件大小并最多读上限加一字节；对象/数组数量独立验证，不能仅限制 JSON 文件大小。

T-A 预留消息元数据、动作、数据责任；T-B 预留消息元数据、数据责任、custody 返回及未来 delivery 返回责任；T-C 预留消息元数据、历史容量及 delivery 返回责任。预留未启用的队列槽只计资源，不启动定时。tombstone 空间包含于消息元数据，不能在到期时才发现无处记录终态。B 的 delivery 材料随 T-D 填入已预留槽；超限/失败时不回收数据。所有预留和事实随同一事务提交。

### 发送速率与有限调度

- 每 Node 总 bucket：65536 B/s，burst 32772 B；每邻接 data bucket 同值，每邻接控制 bucket 为 4096 B/s、burst 4096 B。初始 token 均为 0，从测试 epoch 的 now=0 累积；重开不补满。
- 速率计费使用编码后 body 加 4 B 前缀，发送必须同时取得总 bucket 和对应邻接类别 bucket 的额度；控制先处理但也受两层额度限制。所有 bucket 使用整数千分之一字节，`rate * elapsed_ms` 加入额度并 clamp 至 burst，减去 `wire_bytes * 1000`；溢出、负数、回拨拒绝。
- 这里发现了原 SW-G3 burst=16384 B 小于最大 base64 frame 的问题，因此提出上述**仅 I3 的新测试值**，不能静默修改历史 profile。最大 data 帧需能积攒足够 token；初始 slot 因零 token 被拒绝仍消耗 I1 次数，不能阻塞等待后偷偷补发。
- 每条队列独立调用 I1：固定五个槽及一次恢复额度，传入 `RejectQuota`/`RejectHop` 也消费对应机会。准入通过才扣 bucket；link down 不扣 token；状态、预算及 token 扣减须先提交，实际写失败不退款。
- 同刻多项按 stop → pause → 控制发送 → 数据发送排列；同类别按 message key、邻接排序。每个 queue 同一逻辑时刻只调用一次 Advance；输入事件批次由调用者先收齐。已发包后到达的新事件不得倒填相同时刻。

custody 也使用有界控制责任：B 首次 T-B 建立 B→A custody 队列，duplicate 仅利用原预算；B 验证 delivery 后停止该 custody 队列，再启动独立 delivery 返回队列。同刻两者以 delivery 优先。无 ACK-of-ACK；控制写成功不取消余下的有限发送，预算耗尽不伪造送达。

四消息容量不等于四个最大 frame 同刻入队都能送达：零初始 token、单次 burst 和固定重试槽可能使后序消息耗尽预算。正常闭环分别以单条 1024 B 和单条 16384 B 测试；四消息用例验证容量/计费与有限失败，不允许为制造全送达而补次数或提升速率。

### 重试状态重建

不修改 I1 私有字段/算法或引入其持久化 ABI。每个已启用队列保存 `start_ms`、冻结 `deadline_ms`、`initial_link` 及按时间严格递增的 `batches`；每个批次保存 I1 的 now/link/signal/admission 四个显式字段，最多 64 条。

持久批次的字段顺序为 `now_ms`（0..100000）、`link`（unchanged/became_up/became_down）、`signal`（continue/pause/stop）、`admission`（admit/reject_quota/reject_hop），分别显式映射 I1 enum。不能将 Go enum 的整数顺序隐式当作 store 协议。

恢复时 `NewRetryState` 后顺序重放 `Advance`，校验所有错误和队列事实；**丢弃全部重放 Send 决定**。后续只能用剩余额度处理新批次。相同已处理批次的重复不追加记录；等时不同内容拒绝。第 65 个新批次拒绝并把该队列置为 `schedule_limit`，此本地状态必须提交，既有 payload 责任不丢失；不得截掉历史、重建新预算或以有界账本限制为由报告送达。

可重建的调度记录不是安全日志；任何旧状态恢复都另受下面的 generation/时钟条件约束。

### 一条消息的提交与副作用

1. T-A：原子写入动作绑定、消息核心/合成 body、`queued` 事实、数据责任及 `synthetic_send_steps + 1`。该计数只是模拟联合状态推进，不能称为密码状态。
2. A 发往 B 的副本 remaining_hops=1；B 接收后冻结本地 deadline，T-B 写 `custody_held`、body、去重和责任预留。先提交，再返回 custody 或转发。B 发往 C 的副本 remaining_hops=0；同邻接重试不再次减值。
3. A 接受 custody 后暂停 A→B 数据调度但保留 body；B 仍负责 B→C。未匹配邻接、key、核心或判定用途的控制输入拒绝。
4. T-C：确认未到期与正确目标后，原子写 `committed`、单条历史、去重、可重建 delivery 返回责任与 `synthetic_receive_steps + 1`。重复 data 不重复历史或计数。
5. B 的 T-D：relay-clear 合成判定接受后，原子写 `destination_delivered`、tombstone、B→A delivery 返回材料、停止 data/custody 并删除 B 的 body；返回责任不随 body 删除。A 的 T-D 另行接受 delivery 后写送达事实、停止传输并保留自己的历史。
6. 到期、排程耗尽和拒绝分别记录：`expired` 是到期事实，`schedule_limit` 是本地排程资源失败，timed slots exhausted 是调度结果；后三者都不能替代 delivery。I3 不自动淘汰未到期消息来接受新输入。

应用 API 返回副作用只能来自已确认提交；调用方在实际写前再检查 now < deadline 及队列仍允许发送。提交后写前退出可丢一次机会，不能重开后立即重发同一个已消费决定。失败响应不创建未限速的网络控制消息，只返回本地结构化错误。

消息到期由 Node 独立处理，包括已经 custody 暂停或 schedule_limit 的队列，不能等待 I1 返回 expired（I1 的 pause 本身会阻止普通调度）。到期事务同时停止全部外发责任、记录 expired/tombstone、释放传输标记与 B 的 body，A/C 历史按独立保留规则保持；已经 destination_delivered/committed 的历史不降级为未送达。此路径不生成 delivery，提交失败保留旧记录但外发仍被时间门禁止。

本地错误类别固定为 `REJECT_FRAME`、`REJECT_VERSION`、`REJECT_STRUCTURE`、`REJECT_CONTEXT`、`REJECT_VERDICT`、`CONFLICT`、`EXPIRED`、`REJECT_HOP`、`REJECT_QUOTA`、`SCHEDULE_LIMIT`、`TIME_UNCERTAIN`、`STORE_INVALID`、`STORE_NOT_COMMITTED`、`STORE_OUTCOME_UNKNOWN`；分类不替代带阶段的底层 error。错误不记录 body、凭据或合成判定来源的内部材料，且不允许以记录诊断失败为由回成功。

## Store v1 与恢复合同

### 完整持久字段与不变量

采用同一节点全状态的有界 JSON 替换，仅服务上述小测试容量。不是提升 t0node 的 version 0 snapshot；两种目录与格式互不识别，不提供隐式迁移。生产数据库及密码状态协调保持未选定。

状态按以下顺序编码，所有字段显式存在；数组按唯一键排序，空数组使用 `[]`，不用 null。嵌套结构同样严格解码/重编码比较。

| 记录 | 字段与限制 |
| --- | --- |
| 顶层 | `store_version`=1、`limits_id`=`i3-small4-v1`、`run_id`、`node`（A/B/C）、`generation`（非负 int64，提交加一）、`clock_epoch`（32 位小写 hex）、`last_now_ms`（0..100000）、`synthetic_send_steps`、`synthetic_receive_steps`（非负且最多 4）、`messages`、`actions`、`queues`、`buckets`、`checksum_sha256` |
| message | `key`（版本/origin/scope/id 四字段）、`core`（data 不可变字段，不含 payload_b64 或重复 key）、`core_sha256`、`body_b64`（释放后空字符串）、`accepted_deadline_ms`、`state`（queued/custody_held/committed/destination_delivered/expired）、`custody_seen`、`transport_retained`、`history_retained`、`tombstone_until_ms`（无终态时为 0） |
| action | `action_ref`、`key`、`core_sha256`；scope 由顶层 run/node 与 key 共同约束；同 ref 唯一 |
| queue | `key`、`kind`（data/custody/delivery）、`neighbor`、`status`（reserved/active/paused/stopped/expired/schedule_limit）、`remaining_hops`（data 为已减值副本，控制为 0）、`start_ms`、`deadline_ms`、`initial_link`（up/down）、`batches`（now_ms/link/signal/admission） |
| bucket | `neighbor`（总 bucket 使用 node）、`class`（total/data/control）、`credit_millibytes`、`last_refill_ms`；rate/burst 从 limits_id 派生，不重复存放可篡改配置 |

reserved queue 的 start/deadline 为 0、initial_link=down、batches=[]；首次启用时在同一事务固定真实起点和 deadline。状态 enum 在 wire/store 使用表中小写字符串，与 I1 enum 显式映射，未知值拒绝。

delivery/custody envelope 由消息引用/指纹、固定 issuer/recipient 和 queue kind 重建，不能依赖已删除的 payload。message.core 完整保存 data 中除 payload_b64、core_sha256、remaining_hops 及 key 内字段外的公共头/不可变字段；`payload_bytes` 在释放 body 后仍为原始声明，空 body 只允许对应已释放记录。body 尚在时必须验证解码长度与核心指纹。

校验还须覆盖引用完整性、重复 key、角色可用状态、histories/counters 一致性、未到期数据责任与 body 的对应关系、queue deadline 不晚于消息 accepted deadline、bucket 范围、终态保留窗口与资源重算。checksum 是对顶层除 checksum 本身外字段的规范编码计算的 SHA-256，只检测意外损坏，不证明来源或防旧库回滚。

### 时钟与终态保留

- I3 全节点使用同一个由测试驱动器持有的逻辑 clock_epoch；origin deadline=originated_ms+lifetime_ms，节点只能采用相同或更早值。所有加法须检查，now >= deadline 不产生新交付/证据或外发。
- tombstone 保留到 accepted deadline + 10000 ms，时间上限 100000 足以覆盖本包最大 origin 时间及寿命/余量；无空间时拒绝新消息，不能删未到期 marker。历史/动作在整个 run 内保持，跨 run 不导入旧状态。
- Open 必须获得驱动器提供的 `(clock_epoch, now_ms, minimum_generation)`；epoch 匹配、now 不早于保存时刻、generation 不小于已确认外部下限才能恢复。缺失或不可信时返回明确 `TIME_UNCERTAIN`/恢复错误，禁止发送、清理和自动建空库。
- minimum_generation 由仍存活的测试监督端保存；子进程重启不能代替它。整个监督端/机器重启后的防回滚和真实时钟恢复不在 I3 证据中。文件内 generation/checksum 无法自行证明没有被整体回滚。

### 文件提交与失败分类

只接受测试建立的独占空子目录，目录 0700，文件 0600，固定文件名 `state.json` / `state.next`。Init 与 Open 分开：Init 必须显式创建 generation=0；Open 遇到缺失、空、截断、未知版本或损坏立即失败，不回退为空状态。单 Node 对象串行写；同目录不并行打开两个 writer，此包不宣称跨进程锁。

每次 Save 校验前代 generation 和完整候选状态，编码至有界 buffer；以 O_EXCL 创建 state.next，检查完整写入，Sync 文件，检查 Close，Rename 到同目录 state.json，Sync 目录并检查 Close，最后才发布成功和副作用。原文件和 next 不接受符号链接或非普通文件；没有通用路径/自动探测旧库功能。

| 故障区间 | 调用者和恢复行为 |
| --- | --- |
| 创建/写入/文件 Sync/Close 在 Rename 之前明确失败 | `STORE_NOT_COMMITTED`；旧 generation 保留，无副作用，保留根因；不得发布候选内存状态 |
| Rename 返回错误，或 Rename 后目录 Sync/Close 失败 | 保守记 `STORE_OUTCOME_UNKNOWN`，停止该 Node，禁止立即重试/发包；重开完整校验后只接受完整旧态或完整新态 |
| 目录同步成功后、返回/外发前进程退出 | 重开读到新态及已消费预算；不重复用户交付或把发送机会退回 |
| state.next 遗留 | 只从 state.json 恢复，绝不提升 next；先验证已提交状态与精确 next 普通文件，才允许移除该已知临时文件并同步目录；失败则停止，不递归清理 |
| state.json 缺失/损坏但 next 有效 | 仍拒绝；不能猜测 next 已提交或重建空库 |

这是测试文件协议，而非掉电保证。[Go os.Rename](https://pkg.go.dev/os#Rename)明确存在平台限制，[File.Sync](https://pkg.go.dev/os#File.Sync)描述同步内容语义；这些 API 本身不证明目录、文件系统和设备在真实断电下的组合行为。I3 首轮只在现有 macOS 本地临时目录验证进程退出/重开和注入 I/O 错误；不把 Darwin 成功外推 Linux、Windows 或设备掉电。无法满足目录同步时报告限制，不吞错改成成功。

## 精确实施清单

新建同 module 的 `tools/t0/internal/synthetic/`，以下 10 个文件作为一个实施包：

| 文件 | 职责 |
| --- | --- |
| `envelope.go` / `envelope_test.go` | 三类合成 envelope、规范编码、长度/版本/字段拒绝，复用 I2 frame 入口 |
| `state.go` / `state_test.go` | 明确的 store 记录类型、资源预留/计费、bucket、I1 有界事件重放与全状态不变量 |
| `store.go` / `store_test.go` | 有界文件存储、提交结果分类、故障点与子进程退出/重开；不依赖探索性 store |
| `node.go` / `node_test.go` | Submit/接收/批次处理/查询，T-A/B/C/D 与提交后副作用，显式合成判定依赖 |
| `flow_test.go` / `recovery_test.go` | A/B/C 完整路径、单故障、边界与恢复验收矩阵；共用已有类型，不建新 runner |

新目录用于隔离合成 Node/存储职责，不复制 I1、I2、harness profile 或 t0node 协议。同步本文、文字切片、状态/两份计划和索引；不修改 I1/I2 源码、V0、go.mod、CI、密码依赖或历史 evidence。若确实需要超出十文件的职责调整，先说明差异，不临时扩展公共接口或运行范围。

## 验收与执行包

| 验收组 | 必须观察到的结果 |
| --- | --- |
| 正常纵向路径 | 同一个 action/query 入口：A 入队一次、B custody、C history 一条、A 最终送达、B body 已回收但 delivery 队列仍有责任；三目录重新 Open 后状态保持 |
| 单段 evidence 丢失 | C→B 首个 delivery 丢失与 B→A 首个 delivery 丢失分开测试；有限剩余预算最终返回；没有 ACK-of-ACK 或 C 重复 history |
| 断链/批次 | AB/BC 5 s 断链分别测试；deadline 边界、迟到调度、same-time conflict、恢复耗尽、64/65 批次上限不增加预算 |
| identity/duplicate/conflict | 合成 oracle 拒绝、错误用途/邻接/run/key、同 key 不同核心不推进；同 action/同 data/同 evidence 幂等；声明 synthetic 不等于自动接受 |
| 资源 | 四条 16 KiB 后第五条拒绝；控制预留不足、history/action 满、state 超限均不部分提交；最大编码 frame 在 bucket 中可发送，控制不能绕过总限额 |
| 编码 | 手工固定 data/custody/delivery 向量；未知版本/字段、重复 key、大小写、null/缺字段、非规范 JSON/base64、长度/指纹错和超深输入拒绝，无部分对象或 custody |
| 各提交点 | T-A、T-B、T-C、A/B 的 T-D、调度预算提交分别覆盖写前、写中/短写、Sync、Rename、目录 Sync、提交后副作用前的错误或退出；完整旧态/新态，不出现分裂状态 |
| 恢复 | 子进程退出后从实际文件 Open；无文件、坏 checksum、未知 store 版本、孤立 next、旧 generation、缺少时钟上下文、epoch 不同和时间回拨均明确拒绝；不重放 Send |

I/O 错误注入通过私有文件操作边界覆盖 EROFS/ENOSPC/短写等，不实际填满宿主磁盘或更改挂载权限。测试结果必须标成注入错误，不能写真实只读介质/满盘已验证。子进程只执行当前 Go 测试二进制的专用 helper（由唯一 test 名与环境标志双重约束），在指定故障点退出，父进程用 context 限制每个 child 最长 5 s 并 Wait 回收；不得启动任意 shell、服务或访问测试目录外的数据。

本次接受一次覆盖十文件实现、文档同步、以下离线验证与本范围修复后复验。仓库根执行十文件 `gofmt -w`；`tools/t0` 内执行：

```bash
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./internal/synthetic
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./...
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./...
```

仓库根执行 `./scripts/check-repo.sh`、`git diff --check`、链接/时态与范围复核。预期实现和验证需数十分钟；每条测试命令受 120 s 上限约束，总活动测试目录预算 32 MiB，串行执行存储/子进程用例，用例结束即清理其临时目录。不下载工具链或依赖，不运行正式脚本、Docker、监听器或射频；Go cache 保留，测试子进程和文件均须回收。沙盒失败保留原命令/错误，只在同范围获准后复验。

## 设计轮记录与接受边界

设计轮提交 I2 后完成上述候选合同；核对了 SW-G1、SW-G3 原参数、I1/I2 及 t0node 存储实现。发现并显式处理：encoded frame 大于旧 burst、I1 缺少恢复格式、控制返回义务需预留空间、Rename/Sync 结果不确定不能当明确失败重发、持久 generation 无法独立防回滚。

按本页 ASCII 字段和紧凑 JSON 做了临时容量核算：16384 B payload、64 字符 scope 及本包最大时刻组成的 data body 为 22369 B（含前缀 22373 B），delivery body 为 383 B，64 条最长批次的 queue 为 5826 B，分别小于 32768/2048/8192 B 边界。核算使用 Python 标准库，不是 Go 编码器测试或合法事件序列；实现仍须独立固定向量、完整资源账本和拒绝测试。

设计轮没有创建 synthetic 源码、执行上述 Go 命令或产生场景结果；实施轮结果见下节。接受 I3 仅冻结本页合成测试格式、资源/存储选择及离线执行包；不接受生产身份、密码、公共协议、完整 SW-G3/schema 2 或正式运行。后续正式实验须将这些真实实现映射到 profile/evidence 消费链并另列运行包；真实 E2EE 继续受 SW-G2、许可证和 R2/Phase B 条件约束。

设计轮检查：`./scripts/check-repo.sh` 覆盖 124 文件、`git diff --check`、6 份变更文档的 120 个相对链接及文本检查均通过。结果只证明本轮文档与仓库约束，不证明所述存储/消息算法成立。

## 2026-09-26 实施与离线验证记录

十文件均已实现，入口为 `InitNode` / `OpenNode`、`Submit` / `Query` / `History`、`Step` 及 `ReadInput` / `Transmission.Write`。三个目录中的真实文件提交与 I2 字节流组成离线闭环，未新增 CLI、依赖或正式 profile。A 历史、B custody/清理责任、C 单次 history 与返回证据随各自状态事务提交。

实现补充了调用边界：`Step` 要求严格递增的节点批次时刻；发送句柄绑定当前已提交 generation 和节点内唯一机会，复制句柄也不能重复发送，旧句柄不能消耗新机会。输入结构或判定拒绝时，不提交任何部分输入；已发生的本地到期清理可独立提交并仍返回原输入错误。失败的存储停止该 Node 的查询和写入，避免显示不确定结果；Open 校验后同步目录才返回。历史/动作保留整个 run，B 的终态记录也不自动回收，资源满后明确拒绝。

| 已执行验证 | 实际结果与边界 |
| --- | --- |
| 独立编码向量与拒绝测试 | data/custody/delivery、1/16384 B、规范 JSON/base64、版本/字段/指纹及分配前长度拒绝通过 |
| 六组 A/B/C 路径 | 1 KiB、16 KiB、C→B/B→A 首个 delivery 丢失、AB/BC 约 5 s 断链均通过；C history 一条，A 最终送达，B 删除 body 后保留返回责任，重开保持 |
| 身份/批次/资源 | oracle 拒绝、重复与冲突、四消息上限、控制预留不足、64/65 批次、整数 bucket、custody 暂停到期、坏输入到期清理及发送句柄复制/过期通过 |
| 60 个事务 I/O 故障用例 | T-A/B/C、A/B 的 T-D、调度预算共六类，各覆盖创建前、写前、短写、文件 Sync/Close、Rename 前后、目录 Sync/Close、提交后通知十点；返回错误、无副作用，恢复完整旧态或新态 |
| 48 个受控进程退出用例 | 同六类事务各覆盖八个退出点，包含真实部分写入后 `os.Exit`；当前测试二进制短命子进程退出后，由存活监督端重开，不重复消费历史发送决定 |
| 恢复拒绝 | 缺失/截断/损坏、未知版本、checksum、孤立 next、符号链接、epoch/时间/旧 generation 拒绝；无自动建空库或提升 next |
| 格式化、精准与全量 Go 验证 | 十文件 gofmt 完成；精准 `go test -count=1 -timeout=120s ./internal/synthetic` 通过；全量 `go vet ./...` 和 `go test -count=1 -timeout=120s ./...` 经下述同命令复验通过 |
| 文档与仓库检查 | `./scripts/check-repo.sh` 覆盖 134 文件；`git diff --check`、六份文档的 120 个相对链接目标检查及新增 Go 文本检查通过 |

开发阶段失败保留：首次从 module 目录运行带 `tools/t0/` 前缀的 gofmt 报路径不存在，首次编译报 `node.go:57:10: undefined: delivery`（退出码 1）；已修正命令工作目录和遗漏的 import。首次 Node 测试使用 `t.TempDir()` 本身，因目录权限不满足 0700 而报 `STORE_INVALID: exclusive directory`（退出码 1）；改为测试显式创建 0700 子目录，未放宽实现限制。之后精准测试通过。

全量 vet/test 首次均退出 1：`pattern ./...: open .../Library/Caches/go-build/75/75361adce43fd4367a09dd1539d5fa93b411dd3ea0528507328a7f8b2a866cf4-d: operation not permitted`；test 即使打印部分包通过，整体仍记失败。获准沙盒外复验相同离线命令后均退出 0，synthetic 全量用例耗时约 4.6 s；没有换缓存路径、下载依赖或忽略错误。

测试子进程已 Wait 回收，测试临时目录按用例清理，Go cache 保留。结果只覆盖 macOS 本地临时文件、注入 I/O 错误和监督端仍存活的进程恢复；未执行 Docker/网络正式实验、物理掉电、Linux/Windows 存储验证、真实安全适配或射频。下一步应先设计正式 profile/evidence 与 I3 真实入口的映射及运行包，不把本轮测试转换为 SW-V1/V2/V3 或 P0 通过。
