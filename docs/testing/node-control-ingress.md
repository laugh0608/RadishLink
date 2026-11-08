# Node 控制入站准入与有界验签等待

- 日期：2026-10-28
- 范围：ADR 0007 D16 的 kind 2/3 入站限速、16 对象等待边界及验证结果接纳；L2 安全/资源边界
- 授权：所有者要求提交上一批并继续下一步；共享外发批次已提交为 `0a77399`，本批实现、验证和文档随后获所有者明确授权本地提交
- 面向：Node 状态拥有者、控制输入与安全接入协作者；不实现密码验证、严格解码、真实通道或网络接线

截至 2026-10-28 日终，当前实现已推进至 [schema v8 活动生命周期](node-activity-lifecycle.md)。本页版本、迁移与测试数字保留该批次时点；该批迁移须旧活动已停用，旧 session/动作隔离，不沿用本页早期版本可继续旧活动的行为。完整接续见[当天回顾](../status/2026-10-28-progress.md)。

## 已实现边界

以下版本与测试数字保留 2026-10-28 批次时点；D18/schema v9 与当前责任遍历见 [current](../status/current.md)及[外发拥有者工作包](../architecture/node-outbound-owner.md)。候选位置复用本 Store 的运行者身份，但没有新增实际验证 worker 或改变本页 16 槽、限速及结果复核语义。

新增 `node/src/store/control_ingress.rs`，由已有 Store 唯一拥有。限速器、待验证队列和任务标识只在该拥有者内存中存在；不建立另一份身份库、线程/工作池、服务或持久表。schema 保持 v7，依赖/lock、活动预算及原试验停止线不变。

| 阶段 | 实际行为 |
| --- | --- |
| 入站身份 | 按当前可信 Store Clock 检查活动、普通本机 Active 权限和精确邻居 credential_ref；陌生、Pending、本机自己、封禁、错误活动、Retiring 或已到期输入先拒绝，不分配邻居桶/对象槽 |
| 有界字节 | 只接纳 1..512-byte 不透明 COSE 候选；不读取其中自报的身份、退出种类或 priority 来获得权限。完整 frame 组装及严格 envelope 路由仍是未来前置 |
| 限速 | 每邻居 participant 为 1 object/s、burst 2，全局 4 objects/s、burst 4；两个桶都足额才一起扣减，毫秒整数运算。最多四个邻居桶，不提供重连重置/淘汰接口，换凭据复用 participant 桶 |
| 初始/重开 | 桶从拥有者创建时的可信坐标空桶开始；未访问的合法邻居桶首次计算也以该坐标为起点，空闲期间只能积累到 burst。同 boot 重开以重开坐标重新空桶，不补旧进程停机时间；活动和持久尝试不重置 |
| 满额与重复 | 限流返回 RateLimited；足额输入先消费限速，再识别重复或满队列。QueueFull、重复合并、取消、验证失败均不返还 token；这些结果不自动发送回应 |
| 原字节缓存 | 仅用现有最多 100 个持久控制对象的原始 bytes 做完全相等比较；不采用网络自报 object_ref/hash。已有有效报告或保留的原始退出可返回 Known，不新建证明/转发/ACK 责任；失效报告 issuer 拒绝，仍已消费入站额度 |
| 等待/执行总数 | 未持久验证对象最多 16 个，原始对象合计最多 8192 bytes。等待和已交给验证方的任务共同占槽。相同活动、邻居凭据和政策下的 byte-identical 待处理重复合并，仍受限速 |
| 验证任务 | FIFO 分发，任务不支持 Clone/Debug/序列化；队列和任务使用同一不可变 Arc 字节分配。未验证数据不能自报退出优先级。等待项政策/期限失效时丢弃并返回带原因的 discarded 列表；已分发任务仍占槽，直到返回或显式取消 |
| 完成/取消 | 返回结果必须匹配该 Store 实例、域、任务序号、原始 bytes、活动、来源邻居凭据及捕获的政策修订。Rejected/取消释放任务槽，不创建状态或 ACK。Verified 由未来合格验证方提供。当时入口只绑定凭据，精确通道实例见[离线接续](#通道实例绑定离线接续2026-11-08) |
| 原子接纳 | 验证后的当前权限复核和现有 control object/封禁/传播责任接纳处于同一 `policy_atomic` 事务；不在 SQL 事务里等待验证。写失败/提交未知隔离拥有者，不能报告已接纳；新退出保留既有原子业务停止效果 |

本机所有者封禁和退出意图不经过这条远程队列，队列满时仍可执行。完整已验证退出的结果应由未来状态线程优先提交，再处理受影响业务；本批未实现网络/验证工作池的事件优先级，也不能对未验证输入提供退出特权。

## 生命周期与调用合同

状态拥有者先通过既有可信时钟入口推进 Clock，再调用 `queue_control_candidate`；该准入函数只执行有界查询和内存操作，不自行写 SQLite、落盘/记录未验证字节或输出 ACK。`control_ingress_usage` 只报告数量、原始对象字节和桶数，不暴露正文或凭据。

未来验证方从 `next_control_verification` 获取任务，严格解码、签验并核对全部关联字段后，调用 `complete_control_verification`；必须检查分发返回的 discarded 原因。结果提交前重新核对所有权限，政策变化即使与该对象无直接关联也保守拒绝旧准备结果；没有后台自动重试或静默补验。

任务 handle 私有的拥有者身份与单调序号防止旧实例/其他 Store 的结果误配到新槽；计数溢出拒绝而不回绕。正常 worker 应消费结果或取消任务；丢弃任务 handle 不自动放开仍可能运行的任务额度，可能使容量耗尽，但不会无限创建新任务。取消调用消耗 handle，调用者还须确保实际 worker 停止；未来拥有者重开/关闭必须停止并 Join 所有旧 worker。当前未启动 worker，Arc 原始字节界限不是第三方解码器内存、外部复制、allocator/RSS 或跨旧进程任务总量的硬隔离证明。

进程退出丢弃全部未验证队列，不产生 custody 或恢复任务；发送方只能依照原有有界责任再次输入。重开限速器空桶，原持久控制对象、活动与次数照常恢复。`accept_control` 保留为既有可信本机/验证后底层原语；网络接入必须经新的准入/任务路径，不能直接调用该原语跳过限速。

本批只覆盖 kind 2/3 候选路径；data、receipt 和 ACK 的实际解析/通道认证仍未接入。外层 framing 仍独立于此入口，没有通过手写 CBOR/COSE 或假验签放行真实服务。

## 验证

既有 macOS ARM64、Rust 1.97.1、本地缓存、合成输入，无安装或下载。新增 14 项测试（含受控子进程入口），覆盖：

- 空桶、999/1000 ms、邻居 burst 2、全局 burst 4 与 249/250 ms refill；错误身份不占桶、换键不返还额度。
- 16 个等待/执行槽和 8192-byte 原始对象上限；全部已分发时第 17 个仍拒绝，取消不返还已消费额度，满队列不阻止本机封禁。
- 0/512/513-byte 边界；入队前后数据库 bytes/revision 不变，没有持久对象、交付证明或 ACK。
- 同来源重复合并、不同来源独立上下文、精确持久 bytes 缓存仍限速、修改一个字节必须重新验证、已撤销报告拒绝。
- FIFO、验证拒绝、不同 bytes/activity 拒绝、等待及在途任务的政策/到期/Retiring 检查、时钟回退/跨 boot 隔离。
- 重开空桶、旧实例任务与复用序号隔离；返回正常已验证退出时对象/封禁/业务停止共同提交，未自行发送 ACK。
- 提交前/后故障以及进程在仅持有未验证任务、COMMIT 前、COMMIT 后退出；核对对象、封禁、传播槽、政策修订、空队列和空桶。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::control_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::control_ingress_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml -- --test-threads=1
./scripts/check-repo.sh
git diff --check
```

早期控制回归 22 项及当时新增定向 12 项均通过。清理事务 helper 的局部变量别名时遗漏一处跨行 `s`，Clippy 与全量编译退出 101；修复引用后 Clippy 又报告结果枚举的 large-enum-variant，改为 Box 承载已验证结果，未抑制 lint。最终串行全量退出 0：**154 项库测试 + 2 项 CLI 测试通过**；fmt、Clippy、仓库卫生与 diff 检查通过。没有为既有并行 `store owner lock` Busy 增加重试、延时或吞错；本批最终全量采用串行，不能宣称既有并行风险已修复。故障进程不等于物理掉电或 Linux 验证。

## 接续与停止线

同日随后已完成 D17 同 boot 新活动持久边界，保留旧活动身份/去重/历史并拒绝旧权限复活；接续设计跨 boot 新写域与长期归档回收。实际 framing→严格解析→认证通道→验证工作池→状态拥有者的接线，以及超 128 责任公平枚举、真实输出交接仍待其各自前置。

许可证/R2/Phase B、G1/G2、SW-G2、可信平台、I5、HW/RF 停止线保持；未启动网络、服务、VM、设备、密码候选或正式实验，未修改系统、依赖、远程状态。测试进程已结束，忽略目录保留构建缓存/日志，测试已清理自身临时库。

## 通道实例绑定离线接续（2026-11-08）

Store 在原 `ControlIngress` 内维护最多四个已登记实例，每个 participant 同时一个，实例号在当前 owner 内递增，溢出拒绝。`register_control_ingress_channel` 复核当前活动及两端精确的 Active 凭据，并返回绑定 owner 的不透明句柄。`close_control_ingress_channel` 只移除精确匹配的登记，不提前释放验签任务。调用方负责实际通道的关闭确认。

`queue_control_candidate_on_channel` 在原槽保存绑定，重复合并仍受原限速，且要求同一实例。登记和关闭不重置 participant 桶。`next_control_verification` 丢弃过期实例的等待项并保留拒绝原因。`complete_control_verification` 收回旧实例的对应租约，拒绝其 Verified 结果进入提交事务。当前实例仍复核原始字节、域、活动、凭据及政策修订，再沿原事务接纳。既有凭据入口继续服务已有内部调用，共用同一 FIFO、16 槽、8192 bytes 原对象和原限速，无新增持久行、schema 或依赖。

五项新增离线用例覆盖同凭据重连后旧 close/queue/完成拒绝、当前实例原子提交已验证退出、旧等待项丢弃、重连占槽与不退限速额度、重开时相同实例编号的旧 owner 拒绝，以及同 boot 活动切换必须关闭登记。验证正例确认封禁、业务停止和邻居传播责任一并提交，ACK 次数保持为零。真实 framing 回调、签验、通道关闭与 worker Join 待后续接线和验证。

使用既有 Rust 1.97.1 工具链和离线锁定依赖，定向 `store::control_ingress_tests` 18/18 通过，活动切换新增用例单独通过。默认并行全量 239 项库测试和 2 项 CLI 测试通过，库测试耗时 151.35 秒。fmt、Clippy `--all-targets -- -D warnings`、仓库检查和 `git diff --check` 通过。测试及故障子进程均已退出，改动留在工作区，未暂存、提交或推送。

上述实例绑定代码、用例与文档随后按所有者要求本地提交为 `5f4f9a7`。

## 实例两步关闭离线验收（2026-11-08）

拥有者调用 `begin_control_ingress_channel_close` 后，原实例进入关闭中并保留登记名额。该步骤可重复调用，撤回同一实例的待发 ACK、未消费交接和短写续段。未派发的候选由原轮询丢弃并报告关闭原因，已派发的候选在结果返回或取消前继续占原槽。已接纳的限制性 ACK 终结仍按原复核提交。已经写入的持久事实、原限速和已扣发送额度沿用现有规则。

确认使用原句柄调用 `close_control_ingress_channel`。调用方已取得真实关闭确认时可沿用直接确认入口。关闭中的登记仍由活动切换和全局停机计入，旧 owner 或旧实例确认被拒绝。Store 签发的实例号使用保留范围，外发绑定与写入均复核登记。调用方自行分配的合成实例号使用低半区，继续由现有调用约定约束。实体连接、framing 的实例路由和 I/O worker 收束待接线。见 [有界输入与实例关闭](../architecture/node-bounded-ingress.md#下游拒绝和实例关闭)。

合成验收覆盖关闭中的 T-C 拒绝、待发 ACK 撤回及已提交接纳保留，16 个在途租约和四个通道槽满额时开始关闭，迟到结果归还、同凭据重连前后、短写撤回且其他通道继续交接，以及局部关闭与活动切换和全局停机交叠。首轮 `cargo test --offline --locked --manifest-path node/Cargo.toml --lib closing` 退出 101，测试对已有调度顺序的假设错误。按实际 ACK 优先顺序改正测试后，三项定向用例通过。

Rust `1.97.1` 下默认并行全量离线回归通过，包含 286 项库测试和 2 项 CLI 测试，库测试用时 172.42 秒。最终 `closing` 筛选通过 4 项。fmt、Clippy、仓库检查与 diff 检查均通过。

## 入站时钟与控制限速衔接（2026-11-08）

Store 把帧读取、解码后和外发交接的有效采样记在同一个运行期时钟下限。校验同时覆盖同 boot 单调坐标及可信 UTC 区间端点。旧采样锁存原有时间隔离。帧的原拥有者和实例仍在解码前校验，时钟、活动、凭据在分流前复核。见 [时钟推进](../../node/src/store/maintenance.rs)和[分流](../../node/src/store/control_ingress/read/dispatch.rs)。

控制候选入队使用解码后的采样。凭据兼容入口、原通道入口、已知对象的 ACK 资格和验证派发共用当前有效时钟以及原限速桶。限速拒绝、已满、重复和候选入队仍是有界查询与内存操作，Store 修订和持久时钟由实际提交推进。

验证结果归还后按最新有效时钟复核活动和政策。通过时，控制对象、邻居转发责任和需要推进的时钟同事务提交。确认提交后才更新内存中的持久坐标并按原条件排入 ACK。确定回滚和提交结果未知沿用既有隔离及重开规则。显式同 boot 活动切换以最新有效坐标开始新活动，空限速桶从该坐标计时。见 [控制对象事务](../../node/src/store/control_objects.rs)和[同 boot 活动切换](../../node/src/store/activity.rs)。

离线验收覆盖读取发生在 999 ms、解码后采样 1000 ms 时获得首个 token，兼容入口不能再消费同一个 token，旧坐标 999 ms 无法推进持久时钟。四邻居填满 16 槽及满后耗额期间，持久坐标和修订保持原值。另覆盖未落盘的到期采样拒绝等待和已派发对象，提交故障前后时钟与控制效果一起回滚或一起保留，以及切换后新活动不继承旧活动已流逝的时间。真实 Linux 时间源、严格解码和工作池仍需各自验收。

实施中，`cargo test --offline --locked --manifest-path node/Cargo.toml --lib control_ingress` 首次以 101 退出，原测试仍预期未提前写入时钟时返回 `Busy`，新实现按限速返回 `RateLimited`。用例已改为检查限速结果和无逐帧持久写入。`cargo clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings` 首次以 101 退出并报 `E0609`，同 boot 测试访问了 `ActivityStatus` 未提供的字段。测试改为直接核对已持久化的起点。

最终使用缓存的 Rust `1.97.1` 和现有锁文件完成离线全量回归，304 项库测试、2 项 CLI 测试和 1 项字节向量测试通过，库测试耗时 166.16 秒。格式、全目标 Clippy、仓库检查和 `git diff --check` 通过。

## 验证派发与结果归还（2026-11-08）

拥有者按原 FIFO 及授权检查派发，任务连同唯一发送端一起交给验证方。Store 在原租约内保留一个容量为 1 的结果位置。一次非阻塞归还独立于入站队列、Service 邮箱和停止闩锁。等待、已派发以及已返回但尚未收取的任务共用原 16 槽。旧调用方的手动租约继续使用原入口。见 [派发与结果收取](../../node/src/store/control_ingress/verification_dispatch.rs)。

返回前释放任务对原始字节的引用。结果内 `cose` 和 `fields.payload` 的 Vec 容量各限 512 bytes，越界时用错误占该结果位置，拥有者收取后释放原租约。全部 16 个位置中这两块可变数据的合计容量至多 16,384 bytes。实际接线时还需计入结果结构、通道元数据、分配器和验证期间的临时空间。

拥有者每步收取至多一个结果，沿原通道、活动、政策和事务路径处理。旧实例的结果收回原租约，当前实例的有效结果沿原提交条件生成 ACK。发送端断开时，仍可先收取其他已就绪的结果。缺结果的租约保留到停机并取得 Join 成功，停机期间已送达的结果仍可收取。Join 失败保留原因及租约，仍连接且无结果的发送端继续占槽。见 [停机收尾](../../node/src/store/owner_shutdown.rs)。

三项合成用例覆盖原 16 槽均在途时的跨线程归还、超额结果释放、同凭据重连及新实例提交、停机后迟到结果、发送端断开、Join 失败与仍连接的空结果位。实际验证工作池、签验和部署时的资源上限仍待验收。

使用缓存的 Rust `1.97.1` 和现有锁文件运行离线全量回归，307 项库测试、2 项 CLI 测试和 1 项字节向量测试通过，库测试用时 185.27 秒。格式、全目标 Clippy、仓库检查和 `git diff --check` 通过。
