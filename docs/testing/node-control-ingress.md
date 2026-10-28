# Node 控制入站准入与有界验签等待

- 日期：2026-10-28
- 范围：ADR 0007 D16 的 kind 2/3 入站限速、16 对象等待边界及验证结果接纳；L2 安全/资源边界
- 授权：所有者要求提交上一批并继续下一步；共享外发批次已提交为 `0a77399`，本批实现、验证和文档随后获所有者明确授权本地提交
- 面向：Node 状态拥有者、控制输入与安全接入协作者；不实现密码验证、严格解码、真实通道或网络接线

## 已实现边界

新增 `node/src/store/control_ingress.rs`，由已有 Store 唯一拥有。限速器、待验证队列和任务标识只在该拥有者内存中存在；不建立另一份身份库、线程/工作池、服务或持久表。schema 保持 v7，依赖/lock、活动预算及原试验停止线不变。

| 阶段 | 实际行为 |
| --- | --- |
| 入站身份 | 按当前可信 Store Clock 检查活动、普通本机 Active 权限和精确邻居 credential_ref；陌生、Pending、本机自己、封禁、错误活动、Retiring 或已到期输入先拒绝，不分配邻居桶/对象槽 |
| 有界字节 | 只接纳 1..512-byte 不透明 COSE 候选；不读取其中自报的身份、退出种类或 priority 来获得权限。完整 frame 组装及严格 envelope 路由仍是未来前置 |
| 限速 | 每邻居 participant 为 1 object/s、burst 2，全局 4 objects/s、burst 4；两个桶都足额才一起扣减，毫秒整数运算。最多四个邻居桶，不提供重连重置/淘汰接口，换凭据复用 participant 桶 |
| 初始/重开 | 桶从拥有者创建时的可信坐标空桶开始；未访问的合法邻居桶首次计算也以该坐标为起点，空闲期间只能积累到 burst。同 boot 重开以重开坐标重新空桶，不补旧进程停机时间；活动和持久尝试不重置 |
| 满额与重复 | 限流返回 RateLimited；足额输入先消费限速，再识别重复或满队列。QueueFull、重复合并、取消、验证失败均不返还 token；这些结果不自动发送回应 |
| 原字节缓存 | 仅用现有最多 100 个持久控制对象的原始 bytes 做完全相等比较；不采用网络自报 object_ref/hash。已有有效报告或保留的原始退出可返回 Known，不新建证明/转发/ACK 责任；失效报告 issuer 拒绝，仍已消费入站额度 |
| 等待/执行总数 | 未持久验证对象最多 16 个、原始对象合计最多 8192 bytes；等待和已交给验证方的任务共同占槽。相同通道/政策下的 byte-identical 待处理重复合并，但仍受限速；不同来源不偷换既有授权上下文 |
| 验证任务 | FIFO 分发，任务不支持 Clone/Debug/序列化；队列和任务使用同一不可变 Arc 字节分配。未验证数据不能自报退出优先级。等待项政策/期限失效时丢弃并返回带原因的 discarded 列表；已分发任务仍占槽，直到返回或显式取消 |
| 完成/取消 | 返回结果必须匹配该 Store 实例、任务序号、原始 bytes、活动、精确来源通道和捕获的政策修订。Rejected/取消只释放内存，不创建状态或 ACK。Verified 仍只是未来合格验证方的内部输入类型，不是本模块执行了验签 |
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

下一步准备新活动生命周期与重新配对的持久边界，保留旧活动身份/去重/历史，禁止旧消息、旧验证任务或旧权限在新活动复活。实际 framing→严格解析→认证通道→验证工作池→状态拥有者的接线，以及超 128 责任公平枚举、真实输出交接仍待其各自前置。

许可证/R2/Phase B、G1/G2、SW-G2、可信平台、I5、HW/RF 停止线保持；未启动网络、服务、VM、设备、密码候选或正式实验，未修改系统、依赖、远程状态。测试进程已结束，忽略目录保留构建缓存/日志，测试已清理自身临时库。
