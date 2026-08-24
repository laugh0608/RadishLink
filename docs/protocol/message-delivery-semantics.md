# RadishLink 覆盖层消息交付语义

- 状态：Draft，待 `SW-G1` 评审
- 版本：0.1
- 日期：2026-08-24
- 适用范围：D0/P0 一对一文字消息、最多一个中继的存储转发语义

## 目的

本文冻结实现前必须一致的消息语义和状态不变量，使 Ethernet、2.4 GHz 或未来 HaLow 承载可以替换而不改变“消息何时被接受、转发、送达、删除或拒绝”的含义。

本文是[D0/P0 软件工作计划](../status/d0-t0-p0-plan.md)的 `SW-G1` 候选产物。文档获评审前不得据此扩展 `tools/t0/` 或重新运行三节点场景；即使 `SW-G1` 通过，也仍需完成 `SW-G2/SW-G3` 并获得 `SW-G4` 实现授权。

## 范围与非目标

本文负责：

- 消息身份、版本、origin/destination、lifetime、hop budget 和优先级的语义；
- destination delivery、relay custody、read receipt 与删除提示的区别；
- 去重、重放、乱序、重试、配额、淘汰和失败状态；
- 持久化提交边界、崩溃恢复不变量和拒绝路径；
- A—B—C 中 A 与 C 不可直连、B 为唯一中继时的正负场景。

本文不冻结：

- 二进制或 JSON 线格式、字段编号、序列化库、生产语言或数据库；
- Signal、MLS、签名算法、密码套件、密钥长度或实现库；
- 邻居发现、路径算法、802.11s、EasyMesh、L3 路由或承载分片；
- 群组、多设备合并、附件、实时媒体或超过一个中继的优化；
- 具体超时、重试次数、时钟容差、队列字节数和故障 profile；这些数值由 `SW-G3` 的 manifest 冻结。

`tools/t0/` 的 JSON `version: 0`、摘要 ACK 和 snapshot 状态不构成本设计的兼容输入。

## 信任与故障模型

- 无线或有线承载可能丢包、重复、乱序、延迟、断开和重新连接；
- 任一节点可能在任一持久化步骤前后崩溃或掉电，磁盘可能只读、满或损坏；
- 墙上时钟可能未同步、跳变或回拨，单调时钟会在重启后失去连续性；
- 中继 B 不可信，可以丢弃、延迟、重复或篡改数据，但不得因此获得正文或伪造目的端送达；
- P0 不承诺对抗阻断通信的恶意中继，也不能证明恶意中继真实消耗了多少时间或跳数；
- 身份认证、E2EE 和状态安全由 `SW-G2` 选择成熟协议与实现。`SW-G1` 只规定必须被认证绑定的语义。

## 术语

| 术语 | 含义 |
| --- | --- |
| message | 用户提交的一次逻辑文字发送；承载分片、重传和多路径副本仍属于同一 message |
| message key | 标识同一逻辑消息并驱动去重的复合键，不等同于数据库主键或线格式 |
| origin | 创建消息的逻辑发送端；P0 映射到一个已验证设备身份 |
| destination | 负责最终验证、持久提交和用户交付的逻辑接收端 |
| custodian | 已经把密文及必要元数据持久提交，并承担有界保留和重试责任的节点 |
| relay | 不是 destination、只处理最小路由元数据和密文的转发节点 |
| delivery evidence | destination 在完成验证和原子提交后产生的、可验证且绑定 message key 的送达证据 |
| tombstone | 删除 payload 后保留的有界去重/终态记录，防止旧副本再次交付 |

“接收”“custody”“destination delivery”和“read”是四个不同事件，日志、API 和 UI 不得复用一个模糊的 `ACK` 表达它们。

## 消息身份与语义字段

### Message key

message key 在语义上至少绑定：

1. 协议主版本；
2. origin 设备身份或由安全层导出的不可混淆 origin scope；
3. 会话/安全 epoch 对应的 replay scope；
4. origin 生成的 message ID。

message ID 必须在对应 origin 与 replay scope 内具有不可预测且可忽略碰撞的唯一性，但精确位数和编码等待 `SW-G2`。重试必须复用原 message key；生成新 ID 表示新的用户消息，不能被实现当作普通重传。

同一 message key 还必须绑定不可变消息核心的认证摘要。相同 key、相同摘要是 duplicate；相同 key、不同摘要是 conflict，必须拒绝且不能覆盖已存副本。

### 语义字段

| 字段 | 语义要求 |
| --- | --- |
| protocol version | 区分消息语义主版本；不支持的主版本不得进入 custody |
| origin/destination | 绑定逻辑端点身份；中继可见的路由 hint 不得被当作用户身份 |
| replay scope | 将去重与安全会话/epoch 关联的无歧义 scope；不得用联系人显示名代替 |
| message ID | 标识一次逻辑发送；所有重传、分片和路径副本保持不变 |
| payload authenticator | 绑定认证密文及不可变语义，供 conflict、篡改和送达证据校验 |
| priority class | origin 声明的业务类别；每个节点按本地策略限幅，不能由中继提升 |
| originated at | origin 的墙上时间声明，只用于显示、诊断和 lifetime 计算，不单独作为可信新鲜度证明 |
| lifetime | 从 origin 创建开始的最大逻辑寿命；重试、转存和重启不得续期 |
| initial hop budget | origin 允许的最大覆盖层传输边数，受每个节点的本地上限约束 |
| remaining hop budget | 当前副本尚可使用的传输边数；每跨一个覆盖层邻接只减不增 |
| ciphertext length | 认证密文的有界长度；分配或落盘前检查，P0 文字正文仍受 16 KiB 产品上限约束 |

### 保护与可见性

语义上分为三层，具体封装等待 `SW-G2`：

1. **端到端认证的不可变核心**：message key、逻辑 origin/destination、lifetime、initial hop budget、priority class 和 payload authenticator 必须防止中继静默改写；
2. **中继可见的有界转发元数据**：路由 hint、remaining hop budget、密文长度和逐跳 custody 关联值只暴露转发所需最小信息，变化需要可验证且不能超过不可变核心的上限；
3. **端到端密文**：正文、附件密钥和会话秘密对中继始终不透明。

完整稳定节点 ID、联系人名称和会话显示信息不得为了路由方便直接写入中继日志。是否使用短期路由别名由 `SW-G2` 的元数据评审决定。

## Lifetime 语义

### 基本规则

- lifetime 从 origin 首次创建消息开始，不从任一中继首次看到消息开始；
- origin、relay 和 destination 都必须执行“截止点不会变晚”的规则；重试、重启、重新入队和路径变化不得重置 lifetime；
- origin 的 `originated at + lifetime` 构成逻辑 not-after；每个节点还施加不大于它的本地保留上限；
- 到期消息不得新进入 custody、不得转发、不得产生 destination delivery evidence；已有 payload 转为到期终态并按策略清理；
- lifetime 是资源与产品语义边界，不是对恶意中继延迟行为的密码学证明。安全重放仍由 message key、epoch 和认证状态共同处理。

### 时钟与重启

节点在接受消息时计算本地 deadline，并以单调计时驱动本次启动内的倒计时。持久状态至少记录逻辑 not-after、本地接受时刻、已观察寿命和时钟置信状态。

- 墙上时间在允许偏差内时，使用逻辑 not-after 与本地保留上限中较早者；
- `originated at` 明显位于未来、wall clock 回拨或持久时钟锚点不一致时，不得延长 deadline；节点应拒绝新 custody，或把既有项置为 `TIME_UNCERTAIN` 并采用更早的保守截止点；
- 重启后无法证明剩余寿命时，必须到期或进入显式隔离状态，不能重新获得完整 lifetime；
- 精确时钟偏差、锚点格式和 `TIME_UNCERTAIN` 观察窗由 `SW-G3` 冻结。

## Hop budget 语义

- 每一次从一个覆盖层节点向另一个覆盖层节点的逻辑传输消耗一个 hop；A→B→C 因而需要 initial hop budget 至少为 2；
- 节点创建发往下一邻居的副本前将 remaining hop budget 减 1；同一邻接上的包级重传复用减值后的同一副本，不重复消耗 hop；
- destination 可以接收 remaining hop budget 为 0 的到达副本；非 destination 在 0 时不得继续转发；
- remaining 值不得大于 initial 值，也不得大于该节点首次接受同一副本时观察到的值；违反时按篡改或 conflict 拒绝；
- 多下一跳复制必须受扇出与配额限制，每个外发副本使用相同的减值结果，不能借复制增加预算；
- hop budget 用于限制正常节点的环路和资源消耗，不能阻止恶意中继复制或重新封装密文。destination 仍依赖认证核心与去重拒绝重复交付。

## Custody 语义

节点只有在以下条件全部满足后才能接受 custody：

1. 支持协议版本，结构与长度在界限内；
2. message key、不可变摘要和必要认证可验证，或处于 `SW-G2` 前明确标记的合成测试模式；
3. 消息未到期，hop budget 允许本节点成为 destination 或继续转发；
4. origin、邻居、replay scope、priority 和全局队列配额均允许；
5. 已预留空间，并把 payload、状态、deadline、去重键和恢复信息原子持久提交。

custody evidence 只能在第 5 步成功之后产生。只进入内存、开始写文件、返回网络响应或准备转发都不构成 custody。

custody evidence 至少认证绑定协议版本、message key、payload authenticator、custodian 身份和 receipt 类型；本地 deadline 可以作为诊断信息，但不能把已缩短的 lifetime 重新延长。精确凭据关系由 `SW-G2` 决定。

custody 表示节点承担“在 lifetime、hop budget、配额和本地健康边界内保留并重试”的责任。它不表示 destination 已收到或用户已读，也不允许 origin 或上游 relay 仅凭 custody evidence 删除其唯一 payload 副本。P0 的 relay payload 只因可验证 delivery evidence、本地到期或显式配额淘汰而释放。

## Destination delivery 与 read receipt

### Destination delivery

destination 只有在一次原子事务中完成以下操作后，才能产生 delivery evidence：

1. 验证 destination、message key、不可变核心和安全层认证；
2. 检查同 key conflict、重放和 lifetime；
3. 持久提交密文/本地受保护消息记录；
4. 持久提交去重 marker，确保恢复后不会再次产生用户交付；
5. 提交可重建或已持久化的 delivery evidence 状态。

delivery evidence 至少认证绑定协议版本、message key、payload authenticator、destination 身份和 receipt 类型。时间戳可用于诊断，但不得成为唯一真实性依据。精确凭据、签名或 MAC 关系由 `SW-G2` 决定。

证据丢失时 destination 必须能对 duplicate 幂等重发同等语义的 evidence，不得再次创建用户消息。relay 或 origin 只有验证 evidence 后，才能进入 `DESTINATION_DELIVERED` 并释放 payload；无法验证、字段不匹配或来自错误身份的证据按伪造处理。

### Read receipt

read receipt 是 destination 用户界面确认内容已展示或打开后的独立、可选端到端事件：

- 必须发生在 destination delivery 之后；
- 不得由 relay 产生，也不得从 delivery 自动推导；
- 不影响 relay 的 payload 删除、custody 或重试；
- 用户隐私设置可以完全禁止发送，发送失败不撤销 delivery。

### 删除提示

删除提示不是第四种送达证明，只是携带或引用有效 delivery evidence 的清理通知。任何节点都可以转发提示，但接收者必须独立验证 evidence。提示丢失只会延迟释放空间，不能让未送达消息被误删。

删除 payload 后必须保留 tombstone，直到去重窗口安全结束；删除提示本身不得删除 tombstone。

## 去重、重放、乱序与重试

### Duplicate 与 conflict

- 同 message key、同 payload authenticator：作为 duplicate 接受观察，不再次用户交付、不延长 lifetime、不提升 priority、不增加 hop budget；可以幂等重发已有 custody 或 delivery evidence；
- 同 message key、不同 payload authenticator 或不可变核心：作为 conflict 拒绝、保留原记录、记录脱敏安全事件；
- destination 的 inbox 提交与去重 marker 必须原子完成，提供去重窗口内的 effectively-once 用户交付；项目不宣称在 tombstone 丢失或窗口外实现数学意义上的永久 exactly-once；
- relay 在落盘前检查活动记录和 tombstone，防止 duplicate 重复占用完整 payload 配额。
- delivered tombstone 至少保留到原消息逻辑 not-after 加 `SW-G3` 冻结的 replay margin，或者直到安全层能够证明对应 epoch 永久拒绝旧消息；资源压力不得静默缩短该窗口。

### Replay 与乱序

message key、replay scope、安全 epoch、lifetime 和 tombstone 共同区分允许的乱序与拒绝的历史重放。仍在安全层允许窗口内、尚未见过的旧序消息可以乱序交付；已经终结或超出 epoch/窗口的消息不得因“ID 未见过”而自动接受。

安全层 skipped-key/epoch 窗口必须有界；窗口耗尽属于显式安全或资源错误，不能静默扩大。精确窗口由 `SW-G2/SW-G3` 冻结。

### Retry

- retry 复用相同 message key、不可变核心、payload 和原始 lifetime；
- 同一邻接的 retry 不再次消耗 hop，改走新的覆盖层邻接仍从当前节点剩余预算创建减值副本；
- retry 必须使用有界退避、抖动、次数或截止点，具体 profile 由 `SW-G3` 冻结；
- custody evidence 只允许 origin 降低发送频率，不能把 UI 标成“已送达”；
- delivery evidence 丢失导致的 duplicate 必须返回既有 evidence，而不是再次用户交付。

## 配额与淘汰

### 配额维度

每个节点至少按以下维度施加独立且有界的资源策略：

- 邻居与可验证 origin scope；
- replay scope/会话；
- priority class；
- 单消息密文长度；
- 未确认消息数量与字节数；
- tombstone、receipt 和错误响应数量；
- 节点全局磁盘、内存、CPU 与发送速率。

控制和 receipt 使用独立的小型保留配额，但也必须限速；高 priority 不能绕过身份、长度、寿命或全局安全上限。中继只能保持或降低 origin 声明的 priority，不能提升。

### 接受与淘汰顺序

节点必须先做廉价的版本、长度、基本结构和配额检查，再执行高成本认证、分配或写盘。无法预留完整事务空间时拒绝 custody，由上游保留责任。

需要回收空间时，按以下顺序处理：

1. 已到期 payload；
2. 已有有效 delivery evidence、可转为 tombstone 的 payload；
3. 低优先级、体积较大的未确认附件或媒体（超出 P0 范围）；
4. 最后才是未确认文字。

淘汰未确认文字必须写入显式 `EVICTED` 终态和原因，保留足以防止立即重收的 tombstone，并在安全可行时向上游发出 authenticated custody-failure notice。该 notice 不是 destination delivery；上游若仍有 payload 可以继续尝试其他路径。

系统不得通过删除去重 marker、receipt 状态或事务日志来制造可用空间，也不得在配额不足时返回成功。

## 状态机

### Origin

| 状态/事实 | 进入条件 | 允许后续 |
| --- | --- | --- |
| `QUEUED` | message key、不可变核心和 payload 已原子持久提交 | retry、观察 custody、delivery、到期或显式失败 |
| `CUSTODY_OBSERVED` | 验证某 relay 的 custody evidence | 仍保留 payload；继续等待 delivery、到期或改路 |
| `DESTINATION_DELIVERED` | 验证 destination delivery evidence | 释放 payload、保留 tombstone、可等待 read |
| `READ_OBSERVED` | 验证可选 read receipt | 只更新用户状态，不改变 delivery 事实 |
| `EXPIRED` / `FAILED` | lifetime 到期或本地不可恢复失败 | 不再自动 retry；不伪造 delivery |

`CUSTODY_OBSERVED` 和 `READ_OBSERVED` 是附加事实，不得覆盖更重要的 payload/交付终态。

### Relay

| 状态/事实 | 进入条件 | 允许后续 |
| --- | --- | --- |
| `STORED` | custody 原子提交完成 | 产生 custody evidence、forward、到期或淘汰 |
| `FORWARDED` | 已向下一 hop 创建合法减值副本 | payload 仍保留并可有界 retry |
| `DESTINATION_DELIVERED` | 验证 destination delivery evidence | 删除 payload 并写 tombstone |
| `EXPIRED` | 本地 deadline 到达 | 删除 payload、写到期 tombstone，不产生 delivery |
| `EVICTED` | 配额策略最后手段淘汰 | 记录原因、写 tombstone、可通知上游，不产生 delivery |
| `QUARANTINED` | 状态损坏、时间不确定或认证状态不可恢复 | 不转发、不确认，等待显式恢复或安全清理 |

`FORWARDED` 不代表下游 custody 或 destination delivery，不能作为删除依据。

### Destination

| 状态/事实 | 进入条件 | 允许后续 |
| --- | --- | --- |
| `RECEIVED_UNCOMMITTED` | 网络层收到有界候选 | 验证后提交或拒绝；崩溃后不算送达 |
| `COMMITTED` | 安全验证、消息记录与去重 marker 原子提交 | 产生/重建 delivery evidence、用户展示 |
| `DELIVERY_EVIDENCE_READY` | evidence 状态已持久化或可由 committed 状态确定性重建 | 幂等发送 evidence |
| `READ` | 用户界面完成定义的阅读动作 | 可选产生 read receipt |
| `REJECTED` | conflict、过期、版本、认证、配额或安全窗口失败 | 不产生 delivery evidence |

## 持久化与崩溃恢复不变量

实现选型前必须保持以下不变量：

1. custody evidence 不能早于 relay 的 payload、deadline、去重键和恢复状态提交；
2. delivery evidence 不能早于 destination 的安全验证、消息记录和去重 marker 原子提交；
3. payload 删除不能早于 delivery evidence 验证结果或显式到期/淘汰终态提交；
4. receipt 发送与重发必须幂等，崩溃恢复不得再次触发用户交付；
5. 同 key conflict 永远不能覆盖先前已提交的 payload、tombstone 或 evidence；
6. lifetime、remaining hop budget 和安全 epoch 在恢复后不得回退到更宽松状态；
7. 存储错误、部分写入、校验失败或迁移未知时 fail closed，进入 `QUARANTINED` 或拒绝启动相关队列；
8. 只读或满盘状态不得返回 custody/delivery 成功；
9. schema version、未知字段、升级、降级拒绝、迁移和回滚必须在选择存储实现时显式设计；
10. 日志只记录合成或截断标识、状态、原因码和时间线，不记录正文、密钥、完整身份或精确位置。

## 版本与未知输入

- 不支持的协议主版本、未知 critical extension 或无法理解的认证语义：拒绝且不接受 custody；
- 已知主版本的 unknown non-critical extension：只有被发送端明确标记可忽略且能够原样保留时才可转发；
- 节点不得静默降级、猜测字段含义、重编码未知认证字段或把新版消息转换成旧版；
- 超长字段、整数溢出、重复关键字段、非规范编码和截断 payload 在高成本处理前拒绝；
- 错误响应必须有界、限速且不回显敏感或大体积输入。

## 关键拒绝与结果语义

| 条件 | 结果 |
| --- | --- |
| unsupported version / critical extension | `REJECTED_UNSUPPORTED`，不 custody、不转发 |
| expired / time cannot be bounded safely | `REJECTED_EXPIRED` 或 `TIME_UNCERTAIN`，不产生 delivery |
| remaining hop budget 为 0 且本节点不是 destination | `REJECTED_HOP_EXHAUSTED` |
| 同 key 不同认证摘要 | `REJECTED_CONFLICT`，保留原记录 |
| 认证、destination 或 receipt issuer 不匹配 | `REJECTED_AUTH`，不改变既有状态 |
| 无路由但可接受 custody | 保持 `STORED` 并有界等待；不是 delivery |
| 无空间或配额不足 | `REJECTED_QUOTA`；若已 custody 后被迫淘汰则为 `EVICTED` |
| 存储只读、部分写入或损坏 | fail closed；不返回 custody/delivery 成功 |
| duplicate 且原消息已 delivered | 不再次交付，幂等返回既有 delivery evidence |

原因码名称是语义标签，不冻结线格式枚举值。

## SW-G1 评审场景

以下场景用于评审语义是否闭合，不授权执行：

1. A 原子入队，经 B custody 后到 C；C 提交并产生 delivery evidence，B/A 验证后释放 payload 并保留 tombstone；
2. A→B、B→C 或 evidence 回程任意重复，C 用户交付计数始终为 1；
3. delivery evidence 丢失后 C 对 duplicate 幂等重发，不能再次生成用户消息；
4. B 伪造 custody、delivery、read 或删除提示时，A/C 不进入错误终态；
5. 同 message key 携带不同 payload authenticator 时，所有节点保留先到记录并拒绝 conflict；
6. hop budget 在 B 耗尽时 C 不收到；到达 C 时恰为 0 仍可由 C 接受；
7. 消息在 A、B 或 C 重启期间到期，不得因重启重新获得完整 lifetime；
8. wall clock 回拨、跳到未来或 origin 时间超前时，deadline 不变晚；
9. B 在 custody 提交的每个崩溃点恢复后，要么没有 custody，要么 payload 与责任完整存在；
10. C 在消息记录、去重 marker 和 evidence 提交的每个崩溃点恢复后，不重复用户交付、不提前确认；
11. B 满盘、只读、状态损坏或配额耗尽时 fail closed，上游不会收到虚假成功；
12. 未知版本、critical extension、超长字段和同 key conflict 被有界拒绝，不挤占控制/receipt 配额；
13. custody evidence 只降低上游重试压力，不把 UI 标为 destination delivered；
14. read receipt 禁用、丢失或晚到不影响 delivery 与 relay 清理。

## SW-G1 接受条件

评审者需要逐项确认：

- message key、duplicate、conflict 与 replay scope 没有歧义；
- lifetime 在重试、转存、时钟异常和重启后只会缩短或保持，不会延长；
- hop budget 对逻辑邻接、重传和 destination 为 0 的含义明确；
- custody、destination delivery、read 与删除提示各有独立权限和持久化前置条件；
- relay 无法仅凭本地行为伪造 destination delivery，密码绑定要求已交给 `SW-G2`；
- destination 用户交付与去重 marker 原子，receipt 可幂等重建；
- 配额、淘汰、未知版本、存储失败和崩溃路径不会默认成功或静默丢失责任；
- 所有数值 profile、密码选择、线格式与存储实现仍在正确的后续 gate；
- 本文没有把 Docker、Ethernet、HaLow、生产技术栈或 P0 能力写成已验证。

`SW-G1` 通过后，本文状态改为 Accepted；若上述任一语义仍存在会实质改变安全、兼容、持久化或用户状态的选择，则保持 Draft，不进入实现。

## 后续依赖

1. `SW-G2` 为不可变核心、message key、replay scope、custody/delivery/read evidence 选择成熟的身份与 E2EE 绑定方式；
2. `SW-G3` 冻结字段上限、clock skew、deadline、重试、配额、tombstone window、故障点、指标和 evidence manifest；
3. `SW-G4` 根据已接受的 `SW-G1..G3` 提交精确实现清单、命令、副作用、时长和清理方式；
4. `SW-G5` 才能根据代码审查、负例、三节点矩阵和证据判断软件模拟结论。

## 相关文档

- [项目执行计划](../status/project-execution-plan.md)
- [D0/P0 软件工作计划](../status/d0-t0-p0-plan.md)
- [网络与路由](../architecture/network-and-routing.md)
- [安全架构](../security/security-architecture.md)
- [端到端加密候选评审](../security/e2ee-candidate-review.md)
- [三节点软件探索与验证规范](../testing/t0-p0-software-validation.md)
- [ADR 0002：分离无线承载层与 RadishLink 覆盖层](../adr/0002-underlay-overlay-separation.md)
