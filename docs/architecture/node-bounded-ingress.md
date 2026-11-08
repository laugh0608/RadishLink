# Node 有界输入与通道关闭接线评审

2026-11-08，接线前评审稿。供 Node 拥有者、逐跳传输和验证协作者评审，基于 `a02794a` 的[资源账本](node-owner-resource-ledger.md)和现有离线代码。范围从逐跳层提供已认证连接开始，到一帧交给有额度的下游、明确丢弃或原连接关闭为止。保留 D13–D18、既有 wire、配额和持久化语义；本稿不实现握手、密码、严格解码、工作池、custody 或生产 Service，也不授权平台操作。

## 连接身份和拥有者顺序

| 位置 | 接线合同 |
| --- | --- |
| 认证完成，尚未开放应用读取 | 逐跳适配层提供经过验证的活动、双方 participant 与精确凭据，并交付唯一的本地连接所有权。拥有者复核同一 boot/域、当前活动及原准入政策；地址、ready 事件、自报 ID 或成功读到帧都不能作为来源。认证前和认证完成待登记仍占传输侧的连接、任务和字节额度，不占用已认证 framing 槽兜底 |
| 同一拥有者内登记 | 复用 [`register_control_ingress_channel`](../../node/src/store/control_ingress.rs) 分配实例和原句柄，再用同一 participant 开启 [`Ingress`](../../node/src/framing.rs) 槽。两者均成功且关联完成后才把实例标为可读。任一步失败则保持不可读、撤下已建的 framing 槽并按原实例关闭；若已登记 Store 句柄，待实际关闭确认后再释放。仍是四个应用邻居槽；同 participant 的旧实例关闭未确认时，不开放替代实例 |
| 读取、移交及关闭 | 所有回调以拥有者、域和活动下的精确实例路由，不能只按 participant 或可复用 FD。进入 `push`、`take`、下游接纳前复核实例和当时适用的限制；失效或过期不再执行。已接受的本机停止、撤销、到期和通道失效先于随后开始的读取或移交。跨 boot 或时钟回退按原隔离规则使全部受影响实例不可读并进入关闭，不能重建 `Ingress` 恢复旧许可 |

就绪是同一实例上可合并的标记，每个已开放槽最多一个。适配层只通知，不在后台按事件读取帧；拥有者在槽间轮转，一次最多推进一个读取步骤并处理至多一个完整帧，随后回到本机控制与维护检查点。重复就绪不得堆成事件队列，旧实例通知不能抢占新实例槽位。无进展只等适配层下一次就绪，既不忙等也不漏掉仍有可读字节的实例；需要对适配层实际就绪语义验证这一点。停止闩锁、组装到期和关闭确认不依赖数据队列或诊断 sink 腾位。

## 单次读取额度与字节转移

Store 的离线入站轮转按当前帧读取，每步使用一块 **4096-byte 明文暂存区**。`Ingress` 给出当前前缀或帧体的剩余字节数，继续负责前缀验证、容量与组装时钟。真实适配层还须证明按调用方给出的 slice 做有界非阻塞读取，并给出实际单步时限。见 [有界入站离线验收](../testing/node-framing-and-graph-inputs.md#有界入站离线验收2026-11-08)。

| 组装位置 | 本次最多申请的应用明文字节 |
| --- | --- |
| 4-byte 前缀尚未收齐 | `4 - prefix_len`。完成前缀后由原 framing 检查 `1..=65532`；非法前缀在分配 body 前拒绝并关闭，首步不越过前缀读取 body |
| 已有合法长度，body 尚未收齐 | `min(4096, expected_body_len - received_body_len)`。适配层只能返回本次实际得到的 `n <= credit`，随后仅把这 `n` bytes 交给同一实例的 `push`；正常结果应全部消费，无应用层帧尾积压 |
| 完整帧、关闭中、失效或未登记 | `0`。先执行同一轮移交、丢弃或关闭，不请求零字节读取，也不读取下一帧 |

额度由拥有者在执行前按当前实例计算并即时使用，不作为可排队的异步许可。一次成功的非零读取即交给原 framing；上层适配器若报告越界、进度不一致或未知消费位置，保留原因并关闭该实例，不尝试重新对齐。短读按实际进度计，`WouldBlock` 不改变进度或开始新期限；真正 EOF 或致命错误使连接不可继续。EOF 带来的截断帧不得移交；若完整帧已在更早的拥有者步骤合法移交，随后 EOF 不回滚已明确提交的事实。

现有组装期限从第一次非空 `push` 起算，前缀与 body 共用 10 秒，恰好到期拒绝。接线在读取前检查已有期限，在 `push` 前复核新采样，覆盖读取期间跨过截止的情况。使用可信同 boot 坐标，证明首个应用字节交付到首次采样的间隔有界；前置的握手、密文/明文滞留和连接空闲另有限制。短读、空读、重新通知均不能重置期限。用到期检查驱动不再可读的半帧，即使没有新的数据事件也能关闭原实例。完整帧在本轮转移或丢弃，`Ingress::expire` 不负责回收完整帧。

这段接口最多持有四个 framing 槽，原逻辑容量至多 `4 × 65,536 = 262,144 bytes`；读暂存单独计 4096 bytes，两者可同时存在。`take` 移交原 body backing，直到目的段释放；重填原槽或产生解码/验签副本之前须为重叠占用计费。此方案只消除适配层交付到 framing 之间的帧后缀：后续帧可能仍在传输库或内核。TLS 明文/密文缓冲、握手、socket、分配器和时钟检查的真实硬限制仍需单列；不能把 266,240 bytes 当作进程或网络接收总上限。

## 下游拒绝和实例关闭

完整帧只说明长度边界有效。移交前先确认精确实例仍有效并为一次解码的槽位、帧体及 scratch 预留额度，再调用 `take`。若无额度，本轮取出原 backing 并直接释放，不执行解码、不复制、不回 ACK；当前实例本轮不再读取，后续由正常轮转与可用额度重新评估，不为该帧排队重试。若有解码额度而具体下游满，仍在本轮释放，保持帧边界。下游仅能在各自已封账时接纳，不能用排队发送动作占住拥有者。

分类保留[原数据格式](../protocol/node-data-envelope.md#线格式与界限)和[控制格式](../protocol/node-control-propagation.md#逐跳确认与消息类型)：外层 `kind=1` 是数据，`kind=2` 是 COSE 容器，`kind=3` 是 `LinkAckV1`。未严格解码的字节不给退出优先级；COSE 内层 `kind=2/3` 沿原有 16 槽和限速入口，内层 `kind=1` 回执、数据和逐跳 ACK 不借用这 16 槽。格式无效或无权限按原边界拒绝。framing、移交、排入验证及 `Known` / `AlreadyPending` 均不构成持久接纳；此片不新增回 ACK 条件。

离线分流消费原帧。原帧携带拥有者和实例，读取后的采样记入同一拥有者的运行期时钟下限。分流核对原实例，把原帧借给同步解码回调，再取新采样复核时限、当前活动和凭据。现用回调返回合成结果，实际 COSE 内层类型由未来严格解码器确定。数据和回执在单次同步借用内按原帧 backing capacity 各自检查可用字节。逐跳 ACK 的活动、custodian 和凭据与原实例一致后，才交给既有终结槽。控制候选按解码后采样使用现有限速和队列。入站和外发共同校验运行期时钟下限，验证后的控制接纳随原事务持久化适用的时钟。见 [分流实现](../../node/src/store/control_ingress/read/dispatch.rs)和[时钟衔接验收](../testing/node-control-ingress.md#入站时钟与控制限速衔接2026-11-08)。

关闭采用先失效、后确认的两步。`begin_control_ingress_channel_close` 按精确实例撤下帧槽和就绪标记、待发 ACK 和外发交接，拒绝该实例的新读取、入站接纳、派发与写入。原等待项在验签轮询中丢弃，已派发租约继续占额度，迟到结果只归还原租约。拥有者接线时须在同一有序步骤通知传输层中止短写及丢弃未发送应用输出。见 [两步关闭离线验收](../testing/node-control-ingress.md#实例两步关闭离线验收2026-11-08)。

待适配层确认原连接不再持有可读写的本地传输句柄、其 I/O 回调已收束且不会产生新字节效果，才用原句柄调用 `close_control_ingress_channel` 并释放登记额度。收到 EOF、发出关闭命令、移除 framing 或超时都不是这一确认。重复或迟到的确认只核对原实例，不影响复用相同 FD、participant 或凭据的新实例。关闭不确定时保留原因、实例和未归还额度，拒绝替代连接；全局停机仍按 [`finish_owner_shutdown`](../../node/src/store/owner_shutdown.rs) 要求检查所有通道、短写、租约与真实 worker Join，再关闭 SQLite 和释放锁。已经由底层接纳的字节可能稍后到达对端；本地关闭证据证明的是不再提交新字节。

## 验收输入和平台前置

| 待验收场景 | 应取得的结果 |
| --- | --- |
| 分片前缀、两帧拼接、最大帧；前缀 0 / 65533 | 记录每次 credit 与消费量；已读第一帧时下一帧仍在适配层。四槽满时第五个实例不能开放读入，非法前缀不分配 body；失败不留未归属的 Store 登记或 framing 槽 |
| 半帧沉默、`WouldBlock`、EOF、适配层报告超读；9999 / 10000 / 10001 ms | 无进展不延期，不忙等；到期可在没有新数据时被观察。EOF 截断和超读关闭原实例，不产生移交或 ACK。验证停止与维护在连续可读的四实例下仍可达 |
| 解码满、下游满及接收方慢 | 一帧只转移一次或在本轮释放，下一帧不被提前读出；满额无旁路积压或 ACK，保留停止和归还所需的额度。验证充满下游后仍能区分已持久接纳与从未接纳 |
| 读取前后撤销、旧回调与同凭据重连、关闭失败、时钟失信 | 观察是否发生下游接纳、应用写入和 ACK；旧实例永不影响新实例。未确认时登记及未归还资源仍计费；确认后才可替换；回退/跨 boot 不恢复旧权限。停机不依赖远程事件再到达 |

平台依据沿用[服务架构](node-service-design.md)的 Linux ARM64、有线 TCP + TLS 1.3 双向邻居认证方向，以及 [HW1 的 BSP 预检](../hardware/hardware-validation-plan.md#镜像与接口版本证据2026-10-24)：Radxa ZERO 3E 2GB、Bookworm KDE `rsdk-b1` 和 `6.1.84-10-rk2410-nocsf` 是文档中已有的候选证据，镜像本体未验签、板未采购，KDE 镜像不作为生产 headless 结论。本稿没有刷新版本、批准候选或以 Mac/UTM 替代目标平台。

| 前置 | 目前有的依据 | 继续评审所需材料 |
| --- | --- | --- |
| 镜像与进程边界 | HW1 有候选资产、内核包和源码定位；服务方向为 Linux ARM64、普通非 root 进程 | 绑定可用目标、镜像来源/校验与维护范围、实际内核配置、进程身份；确认是合格台架而非 I5 宿主替代方案 |
| 逐跳适配层与字节 | 有应用前缀、read credit 方案、双向认证方向；逐跳库未冻结 | 固定库/版本和接入 API，证明一次读取不会隐藏无界网络/密码工作；列出握手和认证队列、内核 socket、明文/密文缓冲、任务/FD 的限制执行点与满额结果 |
| 可信时间与关闭 | 现有 `Ingress`、Store 登记和停止闩锁只提供逻辑证据 | 给出时钟来源、轮转/维护最长单步、局部关闭与全局 Join 的界限及观测点；计划如何验证持续可读下停止、满额拒绝、局部关闭失败与资源归还 |

2026-11-08 接续按上表只读复核。既有 BSP 记录可以定位镜像和内核，缺可用台架、镜像本体来源核验及运行配置。Node manifest/lock 未接入拟议的 Tokio/rustls，仍无实际逐跳适配接口可核对握手、缓冲、限额执行和原连接关闭。可信时间源、读取及关停时限也没有运行证据。真实入口继续停止，T-B 只消费已准备好的合成输入验证持久事务。见[中继接纳验收](../testing/node-outbound-scheduling.md#中继接纳转发与重开2026-11-08)。

## Tokio/rustls 候选接入评审（2026-11-08）

优先评审由拥有者分步驱动 `Tokio TcpStream` 和 `rustls ConnectionCommon` 的方案。源码对照版本为 Tokio `1.54.1`、rustls `0.23.46`、tokio-rustls `0.26.6`，用于固定本次观察。依赖版本、features、密码 provider、完整依赖图和接入接口仍待决策。

`tokio-rustls` 的 `poll_read` 在按调用方 slice 拷贝明文前可以多次从底层读入并处理 TLS 记录，握手也在一次推进中循环读写。`poll_write` 返回的进度可能只到 rustls 缓冲。当前缺少把这些循环直接映射到拥有者单步额度的依据。rustls `set_buffer_limit` 只约束经 `writer()` 写入的应用数据，接收侧和 TLS 自身生成的握手、告警输出须单独封账。Tokio `timeout` 无法抢占未让出执行权的调用，必须单列 TLS 解析与密码调用的工作量。见 [tokio-rustls 读取与握手源码](https://github.com/rustls/tokio-rustls/blob/v/0.26.6/src/common/mod.rs)、[写入与刷新语义](https://docs.rs/tokio-rustls/0.26.6/tokio_rustls/#why-do-i-need-to-call-poll_flush)、[rustls 缓冲配置](https://docs.rs/rustls/0.23.46/rustls/struct.ConnectionCommon.html#method.set_buffer_limit)和 [Tokio timeout](https://docs.rs/tokio/latest/tokio/time/fn.timeout.html)。

### 接口与额度检查点

| 边界 | 执行点与满额行为 |
| --- | --- |
| 接受连接与认证 | 在进入 TLS 前为未认证连接预留 FD、握手状态、任务和字节额度，设独立的绝对截止。预留失败时拒绝，内核监听 backlog 另计。禁用 0-RTT，核对 TLS 1.3 双向认证结果与当前活动、participant、原准入政策和精确凭据。恢复会话若纳入设计，须证明当前政策仍被复核。`is_handshaking()` 转为 `false` 后仍可能有握手记录待发送，须用实际待写状态决定后续调度。完成原 Store 登记和 framing 开槽后才允许交付应用明文。 |
| 传输单步与就绪 | 分别限制每轮 socket 调用次数、密文读写字节和 TLS 状态推进次数。用显式限额的 `Read` / `Write` 适配器调用 `read_tls` / `write_tls`，再分步调用 `process_new_packets`、`reader()` / `writer()`。额度为零时不发起 socket 调用，不向 rustls 伪造 EOF，不把额度耗尽当作内核 `WouldBlock` 清除就绪。真实 `WouldBlock` 等待对应 socket 就绪。已缓冲的 TLS 明文在获得新额度后仍须能被轮转，无需新 socket 事件；每实例保留至多一个待处理标记。见 [Tokio TcpStream 就绪语义](https://docs.rs/tokio/latest/tokio/net/struct.TcpStream.html#method.try_io)和 [rustls I/O](https://docs.rs/rustls/0.23.46/rustls/struct.ConnectionCommon.html#method.read_tls)。 |
| 缓冲与截止 | 分别核算 socket 收发缓冲、TLS 密文与明文滞留、握手证书链及待发记录、应用暂存与 framing、下游和分配器开销。在各自可分配或接纳的入口执行上限，无法证明上限的部分保留接线停止。握手、TLS 滞留和空闲分别定界；保留首个非空 `push` 后 10 秒的 framing 截止。拥有者每步前后检查适用期限；用连续可读和复杂握手负载测量最大单步和维护延迟，结合源码与配置证明硬界限。 |
| 应用输出与关闭 | 区分应用写入 TLS 的明文偏移、密文提交 socket 的进度和已提交的协议事实；前两者均不生成逐跳 ACK 或接纳事实。撤销、过期、停止或失败使精确实例进入关闭中，丢弃用户态未发送的应用输出。常规 TLS 告警或 `close_notify` 只可在能证明限时且不会刷新已撤回应用输出的路径发送。TLS 截断、正常 EOF 与 socket 错误分别保留原因，均进入原实例收束。 |
| 本地关闭确认 | 候选为单一所有者持有完整 socket 与 TLS 状态，读写任务和业务 worker 不持有可独立存活的句柄。关闭时撤下就绪，确认最后一个本地 I/O 所有者已退出并释放 socket，若有 I/O 任务则实际 Join 后才确认原实例。`abort()` 发出取消请求，丢弃 `JoinHandle` 会分离任务。Linux 中关闭 FD 后阻塞调用仍可能完成，FD 也可能被复用，故所有确认按精确实例归属。超时仍保留关闭中和原额度，禁止替代登记。见 [Tokio JoinHandle](https://docs.rs/tokio/latest/tokio/task/struct.JoinHandle.html)和 [Linux close(2)](https://man7.org/linux/man-pages/man2/close.2.html#CAVEATS)。 |

### 故障注入与证据

用合成身份和流量记录精确实例、阶段、单调时刻、额度与实际字节数、拒绝原因、socket 释放和任务 Join 顺序。分别记录应用偏移和密文字节计数；由 Store 核对接纳、ACK、租约归还和同 boot 重开后的事实。运行资源需记录配置上限、实际分配峰值、FD/任务数和最长单步；测得峰值仅适用于对应平台和负载。握手/关闭期限和各层传输额度待以目标平台和选定依赖图定值。

| 注入方式 | 验收观测 | 既有离线证据 |
| --- | --- | --- |
| 握手停在首段，占满握手槽后再连；另用错误、过期或撤销凭据，以及 0-RTT 数据 | 超额连接在分配 TLS 状态前拒绝，停滞连接按原截止退出。无提前应用读取、framing 槽、提交或 ACK；原资源收束后新连接才能使用腾出的额度。 | Store 拒绝未知或不适用身份、活动及过期工作；实际握手、0-RTT、backlog 与回收待测。 |
| 逐字节给前缀并拼接下一帧；半帧分别在 9999、10000、10001 ms 尝试完成，再单测全程无就绪、TLS 截断和适配器报告超读 | 9999 ms 仍可按当前额度尝试完成，10000 ms 起拒绝；无新事件也按原截止维护。拼接不越过当前帧，截断或超读不移交、不确认。记录首次明文字节到首次 `push` 的间隔。 | framing 覆盖分片、拼接、精确到期和维护。socket/TLS 定时、截断和超读联动待测。 |
| 四个应用实例持续可读，另连第五个；填满下游和 TLS 各向缓冲，让接收方停止读取并注入假就绪 | 按层记录拒绝和内存，轮转仍能执行维护及停止。`WouldBlock` 不推进偏移、不延长原期限；额度恢复后已缓冲明文可继续。不为满额帧增加副本、队列或 ACK。 | 四个 framing 槽和 16 个控制验签等待/租约槽的满额行为已覆盖；传输缓冲、就绪恢复和实际轮转延迟待测。 |
| 应用短写后撤销或关停，延迟 I/O Join，同时让原实例的验证结果到达 | 关闭中停止新 socket 写入、入站派发和旧结果提交。超时仍保留原实例；迟到结果只归还旧租约。取得 socket 释放和 Join 证据后才确认原实例。同 boot 重开对照提交事实，未接纳的输入不得产生 ACK。 | 短写、撤销、原租约和逻辑停机有离线证据；关闭中接线、TLS 用户态待发丢弃和实际 Join 待测。 |
| 关闭确认前后各用同凭据重连，向新实例投递旧就绪、重复关闭确认和旧验证回调，另覆盖 FD 复用 | 确认前拒绝替代实例；确认后只允许新实例的合法工作提交，旧通知不抢占新槽，旧回调不改写新实例或归还新额度。 | Store 覆盖同凭据重连、旧结果释放和旧等待项清理；真实 FD 复用及 I/O 回调次序待测。 |

本次以 Rust `1.97.1` 对 `node/Cargo.toml` 运行 `cargo test --offline --locked --lib` 的四组筛选，`framing::tests` 12 项、`store::control_ingress_tests` 18 项、`store::outbound_handoff_tests` 14 项、`store::owner_shutdown_tests` 2 项均通过。真实接线仍需要已审查的依赖图、可用 Linux ARM64 台架、可信时间和上述传输观测。HW1 当前优先评审的 Armbian 镜像及其信任缺口以[首轮评审记录](../hardware/hardware-validation-plan.md#首轮范围与镜像信任评审2026-11-08)为准。

## 有线传输依赖候选

2026-11-08，基于 `61dcb75` 的接入方案，首选评审 **Tokio `1.54.1` + rustls `0.23.46`，逐跳 TLS 使用 `ring` provider**。范围是单一拥有者驱动的有线 TCP/TLS 1.3 双向认证，当前已有 [Node 依赖](../../node/Cargo.toml)作为比较基线。下列 TOML 仅固定候选直接依赖，实际接入须通过完整图与[台架准入](../testing/node-security-integration-acceptance.md#linux-arm64-接线准入)。

```toml
[dependencies]
tokio = { version = "=1.54.1", default-features = false, features = ["net", "rt", "time"] }
rustls = { version = "=0.23.46", default-features = false, features = ["std", "ring"] }
```

| 候选 feature | 本入口用途与裁剪 |
| --- | --- |
| Tokio `net` | `TcpListener` / `TcpStream`、就绪及 `try_read` / `try_write`。Linux 上声明边包括 `mio`、`socket2`、`libc`，实际版本由整图确认。使用固定 slice 和标准库 `Read` / `Write` 适配器，省去 `io-util`。 |
| Tokio `rt`、`time` | 用 `Builder::new_current_thread()` 显式启用 I/O 与计时驱动，唤醒握手截止、半帧维护和关闭检查。`time` 用于唤醒，授权期限仍由拥有者复核可信时钟。候选省去 `rt-multi-thread`、`macros`、`sync`、`signal`、`test-util` 和 `full`，实际若需扩大再核对整图。 |
| rustls `std`、`ring` | `std` 提供本入口所用的同步 I/O 接口，`ring` 同时选入 `rustls-webpki/ring`。显式关闭默认 features，使 `tls12`、`logging`、`aws_lc_rs`、`prefer-post-quantum` 不随默认配置开启。`brotli`、`zlib`、`fips` 和 `custom-provider` 也不纳入。首轮直接驱动 rustls 的 I/O 原语，`tokio-rustls 0.26.6` 只作上节源码对照。 |

这些是按接口用途推导的直接 features。将来须分目标和宿主查看实际合并结果，确认间接边没有重新打开默认或额外 features。见 [Tokio 固定 manifest](https://github.com/tokio-rs/tokio/blob/tokio-1.54.1/tokio/Cargo.toml)和 [rustls 固定 manifest](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/Cargo.toml)。

### Provider 与认证配置

- 用 `rustls::crypto::ring::default_provider()` 的同一实例配置 `ClientConfig`、`ServerConfig` 和双方 WebPKI verifier 的 `builder_with_provider`，协议版本显式限于 `TLS13`。证书验证使用活动对应的受控信任材料，服务端要求客户端证书。拥有者另按当前活动、participant 和精确凭据复核登记，证书链通过只满足其中一项。实际证书用途、命名与凭据映射待接线评审确认。见 [CryptoProvider 固定源码](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/crypto/mod.rs)和 [客户端证书验证器](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/webpki/client_verifier.rs)。
- 首轮拟禁用会话恢复和 0-RTT，每次重连走完整双向握手。客户端用 `Resumption::disabled()` 并关闭 `enable_early_data`，服务端 `send_tls13_tickets = 0`、不保留恢复状态且 `max_early_data_size = 0`。rustls `TimeProvider` 接受单个 `UnixTime`，可信 UTC 区间及其与证书有效期、D15 原截止的保守判断须由接线合同分别处理，时间失信则拒绝。见 [客户端配置](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/client/client_conn.rs)、[服务端配置](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/server/server_conn.rs)和 [TimeProvider](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/time_provider.rs)。
- 选择 `ring` 优先评审的依据是 TLS 1.3 所需能力可从固定源码定位，crates.io 包的 ARM64 路径用 `cc` 构建 C 和随包汇编，发布包已有生成产物。需审查本机目标 C 工具链、汇编/链接器、系统头和 glibc ABI、随机源及随包原生代码。rustls 到 `ring` 的依赖边开启 `ring` 的默认 features，须把 `alloc` 和 `dev_urandom_fallback` 的实际生效范围列入审阅。见 [ring provider 源码](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/crypto/ring/mod.rs)、[ring 固定构建说明](https://github.com/briansmith/ring/blob/2723abbca9e83347d82b056d5b239c6604f786df/BUILDING.md)和 [ring 发布索引](https://index.crates.io/ri/ng/ring)。
- rustls 和候选 `rustls-webpki` 的 AWS-LC 路径要求 `aws-lc-rs ^1.18`。现有 D14/MLS 图输入精确固定 `=1.16.3`，复用其版本不可行。AWS-LC 路径需另外评审实际 `aws-lc-sys`、native 链接和版本差量。当前 `ring` 仅用于逐跳候选，未来与 MLS 同进程时须重新评审整图和两套原生代码的链接及资源成本。见 [rustls 发布索引](https://index.crates.io/ru/st/rustls)、[rustls-webpki 发布索引](https://index.crates.io/ru/st/rustls-webpki)和 [D14 固定图](../testing/node-security-graph-review-package.md#唯一候选-manifest-输入)。

### 版本证据与完整图准入

2026-11-08 对照 crates.io API 与稀疏索引，以下版本当时均未 yanked。校验和是登记值，归档本体及其中的许可、归属与原生源码须在后续精确输入中核对。

| 包 / 用途 | 声明许可 / Rust 最低版本 | crates.io 登记 SHA-256 |
| --- | --- | --- |
| [Tokio `1.54.1`](https://crates.io/crates/tokio/1.54.1)（直接） | MIT / `1.85` | `b52fd3255258d26fac7264ab5a76b53c13367136dc011d3d6ad4f8ed070396a3` |
| [rustls `0.23.46`](https://crates.io/crates/rustls/0.23.46)（直接） | Apache-2.0 OR ISC OR MIT / `1.71` | `48e13bd8c0e9365c43cfa5c9e8f9ad49d3c8444926c9aac819e0e4dc503c8fdf` |
| [ring `0.17.14`](https://crates.io/crates/ring/0.17.14)（预期传递版本） | Apache-2.0 AND ISC / `1.66.0` | `a4689e6c2294d81e88dc6261c768b63bc4fcdb852be6d1352498b114f61383b7` |
| [rustls-webpki `0.103.16`](https://crates.io/crates/rustls-webpki/0.103.16)（预期传递版本） | ISC / `1.71` | `4443b1b6d39d7c663139942cc4558262562d2c84123bb6282ef177009ca8b281` |

Tokio `1.54.1` 覆盖 `Interval` 竞态的修复并处于 `AsyncFd` 公告给出的已修复版本范围，候选接口使用 `TcpStream`。rustls `0.23.46` 覆盖 TLS 1.3 记录边界公告的修复，也覆盖 10 月发布的四条 rustls 公告所列修复。见 [Tokio 竞态](https://rustsec.org/advisories/RUSTSEC-2026-0384.html)、[AsyncFd](https://rustsec.org/advisories/RUSTSEC-2026-0386.html)、[TLS 1.3 记录边界](https://rustsec.org/advisories/RUSTSEC-2026-0285.html)和 [rustls 公告](https://rustsec.org/packages/rustls.html)。

rustls 声明 `rustls-webpki ^0.103.14`，该范围可解析到证书验证公告影响的版本。后续候选锁须至少达到该 `0.103` 系列的修复版 `0.103.16`，漂移时复核公告和整图。`ring 0.17.14` 处于 AES 公告的修复范围，也不属于旧系列未维护公告的范围。见 [证书验证公告](https://rustsec.org/advisories/RUSTSEC-2026-0382.html)、[ring AES 公告](https://rustsec.org/advisories/RUSTSEC-2025-0009.html)和 [ring 维护公告](https://rustsec.org/advisories/RUSTSEC-2025-0010.html)。

后续先审定隔离解析输入，以 Node 基线加上述两条直接依赖，与现有锁比较新增、删减和版本变动。分别保留 Linux `aarch64-unknown-linux-gnu` 运行图、实际准备宿主的 build/宏依赖和测试图，核对原生 `links`、系统库、归档校验和、实际 feature 并集、许可正文及随包归属。逐包公告审查须绑定数据源 revision 和日期，维护责任须覆盖传递包及原生代码。两项预期传递版本用于核对候选锁，当前不增加直接依赖来强制求解。范围漂移或证据缺失须回到评审。此次只读元数据及源码，完整依赖图、来源和采用仍待评审，D14 的 G1/G2 与许可证/R2/Phase B 各有独立范围。
