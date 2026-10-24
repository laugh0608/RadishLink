# Node 帧接收边界与新图离线输入验证

日期：2026-10-24。面向 Node 实现者与依赖评审者；记录接受 [ADR 0007](../adr/0007-node-envelope-and-control-budget.md) 后的有限离线开发。D15/D16 文档与 ADR 已提交为 `fdefa3b`；本批不改变设计、不安装依赖、不放行真实安全/平台/网络入口。

## 已实现的帧边界

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
