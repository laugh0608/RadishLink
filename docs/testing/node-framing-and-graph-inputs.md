# Node 帧接收边界与新图离线输入验证

日期：2026-10-24。面向 Node 实现者与依赖评审者；记录接受 [ADR 0007](../adr/0007-node-envelope-and-control-budget.md) 后的有限离线开发。D15/D16 文档与 ADR 已提交为 `fdefa3b`；本批不改变设计、不安装依赖、不放行真实安全/平台/网络入口。

## 已实现的帧边界

本页保留 2026-10-24 帧与 G0 批次的版本/未实现结论；后续 D15/D16 及 D18/schema v9 自有边界以 [current](../status/current.md)为准。2026-11-02 的[外发拥有者工作包](../architecture/node-outbound-owner.md)已完成只读候选遍历和同步离线周期，仍没有将本页 framing 接到真实 Service/transport，也未取得严格解析/签验或工作池证据。

[`framing::Ingress`](../../node/src/framing.rs) 提供已有授权邻接的应用帧组装，沿用 Node `Clock` 与错误分类。四字节 u32be 前缀只接受 body 1..65532 bytes，完整 frame 最大 65536 bytes；先校验长度再申请 body 容量，最多四邻居，每邻居仅一个未完成或待消费 frame。容量统计包含 prefix 与 Vec capacity，最多 256 KiB；不是进程 RSS、allocator 或逐跳通道缓冲的硬内存证明。

从首个非空输入启动单帧 10000 ms 期限，零星字节、空输入和重复 open 均不延期。恰好到点拒绝并移除该流；维护返回需关闭的邻居集合。一次 push 只消费到首个完整帧，报告 consumed，剩余输入由调用者保留；已完成而未 take 时 Busy，不覆盖。take 转移 buffer 所有权，下游须有自己的容量准入；完成组装不会免除业务期限检查。

boot 改变、单调时钟回退或非法 Clock 会清空流并将此 Ingress 永久隔离。创建新实例不是解除 D9 平台隔离的途径。调用者必须验证邻居身份、供应可信时钟、周期调用 expire 并真正关闭被移除的 transport；空闲但尚无 frame 的流只受四邻居数量限制，未来承载须另管连接空闲期限。

模块没有 socket、CBOR/COSE、MLS、签验、哈希、custody 或数据库操作，也未接入 Service。D15 的完整结构与认证、UTC 区间，D16 的控制限流/持久预算/Retiring 状态机均尚未实现；现有 I1 重试算法和 schema v3 不变。下游接线前仍须检查授权、期限、身份和事务，不能直接向 CLI/网络暴露 Store。

## 新图 G0 输入准备

[`node_security_graph_inputs.py`](../../scripts/node_security_graph_inputs.py) 消费[新图评审包](node-security-graph-review-package.md)的精确输入，只提供 check/prepare/verify。它不引入运行器，既有采样 audit monitor 不能满足新包的硬写入要求；未生成真实 lock 或获取第三方源码。

prepare 在所有来源校验通过后创建唯一 bundle，最多 128 KiB 逻辑文件内容，结束标记也计费；两个目录和七个文件由精确清单约束。目录逐层 O_NOFOLLOW 打开，文件检查单链接/普通文件、大小及读取前后元数据；来源上限 256 KiB。短写循环有进展检查，异常保留未完成输入，不自动重试或覆盖。verify 根据已审阅常量和 TOML 重新构建字节预期，拒绝额外目录/文件、缺失标记、篡改及自洽重算摘要。以上不构成对 root/同用户任意并发写入的隔离保证，实际执行仍要受控只读输入及环境证据。

实际输入包为 `artifacts/node-security-graph-inputs/accepted-d15-d16-v1`，按下列命令生成和核验。它只保存 manifest、LICENSE、无功能 source stub、Cargo config、审阅计划、摘要和结束标记；无 Cargo.lock、registry、源码下载、target 或执行证据。路径已由仓库忽略规则覆盖，留存供后续审阅，不作为依赖安装或 G1 成功记录。

## 已执行验证

在既有 macOS ARM64 / Rust 1.97.1 与已有 Node 缓存上执行，未安装工具或新增 crate：

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
python3 -B -m unittest discover -s scripts -p test_node_security_graph_inputs.py -v
python3 -B scripts/node_security_graph_inputs.py check
python3 -B scripts/node_security_graph_inputs.py prepare accepted-d15-d16-v1
python3 -B scripts/node_security_graph_inputs.py verify accepted-d15-d16-v1
./scripts/check-repo.sh
git diff --check
```

结果：Node 73 项库测试及 2 项 CLI 测试通过，其中 framing 新增 12 项；Python 19 项通过；格式化、Clippy 与仓库检查通过。Node 包含既有合成进程退出/恢复测试，不代表真实掉电。帧测试覆盖分片、合并、最大/无效长度、四邻居满额、9999/10000/10001 ms、空输入/慢流不续期、跨 boot/回退及 i64 上界；输入工具测试覆盖基线漂移、链接/FIFO、总量/单文件上限、篡改重算摘要、额外产物、短写/中途失败和不支持的执行参数。所有测试均为合成或已有非敏感仓库输入。

新增输入包只返回 `INPUTS_VERIFIED`、`execution_ready: false`、`execution_authorized: false`。四个基线 manifest/lock、现有三个 SQL schema、AGENTS.md/CLAUDE.md 保持不变；没有新图解析、密码候选编译或签验、设备/VM/服务启动、远程修改。离线准备无需重判已接受 D11—D16，也不消耗或延续历史实验授权。

## 仍未关闭与集中确认事项

新图前置已补齐到**可复现输入**，尚未到可执行环境。缺少：专用硬写入域与路径约束、域名网络限制及 G2 禁网切换、整个进程组内存/PID/FD/CPU/时限与父退出终止、无凭据环境和固定工具绑定的真实验证，以及最终 clean revision 和当前单次授权。当前 Mac/UTM 资源事实不变；不重复盘点、不先搭建无环境依据的通用运行器，也不把 I5 的 NO-GO 改判。

本批没有新增产品选择需确认。后续集中处理两个事项：

1. **G1/G2 执行**：先取得合格承载和上述真实边界证据，再按评审包确认精确命令、目标、时限/预算、副作用和清理；G1 结果复核后绑定实际 lock 才能确认 G2。现阶段不请求预先放行未就绪环境，不把本机 G0 输入目录当执行环境。
2. **许可证与 R2**：所有者落实具资格的独立复核者及材料移交/留存范围，按已有 `debug_tree` / `r-efi` 处置路径处理；不会自动对外发送资料、联系上游或把新图/内部使用当专业意见。

这些确认边界来自 [AGENTS.md](../../AGENTS.md) 的 L3 与外部状态约束，以及现行安全/许可证停止线。无需重复确认 D15/D16；独立离线开发仍可推进，但真实安全接入、G1/G2、R2、Phase B、ARM64 台架和 I5-R 均未完成或放行。

## 有界入站离线验收（2026-11-08）

Store 在登记后通过 `open_inbound_stream` 打开帧槽，通过 `mark_inbound_ready` 复核原句柄及拥有者并合并就绪。`poll_inbound` 每步先检查时间、到期和权限，再按轮转选择一个实例，读取后复核新采样才交给 framing。正常读取保留就绪至 `WouldBlock`，届时等待下一次通知。即使无就绪，轮询仍处理半帧到期。开槽失败、读故障或失效会关闭逻辑准入，原登记等调用者确认关闭。全局停机直接释放帧槽和就绪标记。见 [离线接线](../../node/src/store/control_ingress/read.rs)和[两步关闭](node-control-ingress.md#实例两步关闭离线验收2026-11-08)。

每步前缀仅请求剩余字节，帧体按剩余量和 4096 bytes 的较小值请求。完整帧在该步按 backing capacity 请求下游预留。预留成功时移交原 backing，预留拒绝时返回 `Discarded` 并释放该帧。下一帧由后续轮转读取。这里用调用方提供的合成读取、时钟与预留回调验证顺序，真实 socket/TLS、可信时钟、严格解码与工作池另行验收。见 [接线合同](../architecture/node-bounded-ingress.md)。

九项合成用例覆盖最大帧的分片和粘包、下游满额后读取下一帧、`WouldBlock` 与 9999/10000/10001 ms 边界、EOF、超读、非法长度、四实例轮转及停机、开槽失败、撤销与读取期间到期、两步关闭后旧就绪、重开复用实例号和读后时钟回退。

本机使用已缓存的 Rust `1.97.1` 和既有 `Cargo.lock` 验证。`cargo test --offline --locked` 通过 295 项库测试和 2 项 CLI 测试，库测试耗时 162.70 秒。`cargo fmt --check`、离线锁定的全目标 Clippy（`-D warnings`）、`./scripts/check-repo.sh` 和 `git diff --check` 通过。

## 入站字节向量与离线分流（2026-11-08）

[34 个字节向量](../../node/tests/fixtures/inbound-wire-v1.json)沿用 D12、D15 和 D16。每个 `base_bodies` 项按顺序连接 hex 片段及重复段。向量可用 `splice` 在指定 body 偏移核对旧字节后替换，再以 `body_bytes` 核对长度并生成四字节大端前缀。`preserve` 给出原始 body 上的 `[偏移, 长度]`，供未来候选校验 core、MLSMessage、COSE、protected 与 payload 是否原样移交。

| 向量组 | 候选解码时的期望 |
| --- | --- |
| `DataFrameV1` / `CoreV1` | 最大 61,704-byte body 包含 216-byte core 与 61,440-byte MLSMessage。保留原始 core 和 MLSMessage。拒绝未知版本/类型、非最短整数、不定长/错误项数、尾随/截断、超长声明、非法 hop 和 core 截止计算溢出 |
| COSE 外层及 D12 profile | 外层 bstr 的 1 和 512 bytes 可通过外层长度检查，0 和 513 bytes 拒绝。三种内层类型各有结构样例，使用合成字段和全零签名字节。签验须另行验证。错误 tag、旧算法、protected 重复键和未知内层类型在 D12 层拒绝 |
| `LinkAckV1` | 两类 ACK 的 body 均恰好 123 bytes。拒绝未知 ACK 类型、非最短整数、错误凭据长度和尾随字节。实际来源授权另由原通道及 Store 判定 |

向量测试验证重建、前缀、分块组装及原始切片。`expect` 是供 D14 候选后续逐个验证的解码判定。见 [向量测试](../../node/tests/inbound_vectors.rs)。

[分流实现](../../node/src/store/control_ingress/read/dispatch.rs)先复核原拥有者和通道，再把只读原帧借给同步回调，取得合成解码结果后重新采样并核对当前活动及精确凭据。回执与数据各自提供可用字节，以原帧 backing capacity 计费，只有同步借用期间占用。拒绝、回调失败和正常返回都释放原帧。原始 core、MLSMessage 和 COSE 从同一 backing 取切片。未来如果复制、异步派发或保留解码 scratch，须取得各自额度。

退出和报告仍由原 16 槽、原每邻居和全局速率接纳，使用当前 Store 已公布的时钟。未公布新的采样时拒绝本次接纳。逐跳 ACK 按原实例比对活动、custodian 和凭据，使用原待提交终结槽。数据 ACK 的内部消息键由调用方解析，既有终结检查继续核对该键、原绑定和对应邻居责任。ACK 仍以已持久化的接纳为前置。若遇到已持久化的同一控制对象，是否补发 ACK 仍由原提交、来源和额度检查决定。

七项合成分流用例覆盖数据/回执各自满额与等额、原字节切片、控制 16 槽满额后仍扣限速、逐跳 ACK 两类终结及错误来源、非法分流后下一帧、解码期间到期、撤销、同凭据重连和重开复用实例号。真实传输、严格解码、签验、工作池与 Linux 承载继续按各自前置验收。

`cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings` 首次以 101 退出，报 `InboundReadProgress::Frame` 的 `large_enum_variant`。帧改为保留原拥有者标识、通道与采样，活动从仍有效的拥有者读取，复验通过。

最终在本机用已缓存的 Rust `1.97.1` 和现有锁文件验证。离线锁定的全量测试通过 302 项库测试、2 项 CLI 测试和 1 项字节向量测试，库测试耗时 161.95 秒。格式检查、全目标 Clippy、向量 JSON 校验、`./scripts/check-repo.sh` 和 `git diff --check` 通过。
