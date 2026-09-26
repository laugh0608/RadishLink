# SW-G4 合成验证准备：有界 frame 读写单元 I2

- 状态：Accepted（2026-09-26 所有者授权）；I2 已实施，离线验证通过
- 日期：2026-09-26
- 设计基线：`0eb4885`，I1 离线重试与长度算法已提交
- 目标读者：harness 与消息输入边界的实现、验证协作者
- 产物：复用既有 length-prefixed codec 的可配置限额及错误路径
- 非目标：完整消息 schema、队列/持久化、安全适配、CLI/容器运行和正式 SW-V1/V2 结果

## 选择依据与当前差距

I1 的 `CheckLength` 只检查数值。I2 实施前，`internal/harness/proxy.go` 的 `ReadSyntheticFrame` 已在分配前检查 **65536 B**，但不能选择后续消息候选的 **32768 B** 边界；在读取结束后补一次 I1 检查不等于分配前拒绝。原 writer 检查 `Write` 的 error，却未检查返回的字节数，短写可能被当成完整成功。下文记录本次修复与验证。

I2 复用并参数化这两个现有函数，不新建第二套 framing、runner 或通用 transport 包。调用方根据已接受的具体用途选择限额；新消息路径将显式传入 `delivery.MaxFrameBodyBytes`，V0 原调用继续使用原默认值。队列、提交次序及剩余 schema/存储缺口见[接入设计](../architecture/minimal-text-slice.md#队列与事务的接入设计)。

## 精确实施范围

| 文件 | 允许修改 |
| --- | --- |
| `tools/t0/internal/harness/proxy.go` | 增加 `ReadSyntheticFrameWithLimit(reader io.Reader, maxBodyBytes int64)`、`WriteSyntheticFrameWithLimit(writer io.Writer, payload []byte, maxBodyBytes int64)`；既有无 limit 函数委托同一实现，默认常量不变；仅修改 codec 区域 |
| `tools/t0/internal/harness/proxy_test.go` | 内存流与受控 Reader/Writer 的边界、兼容、错误和短写回归；测试调用 I1 的 frame 上限常量进行衔接，生产代码不增加 harness → delivery 依赖 |
| 本文件、当前状态与两个计划、文档索引 | 记录实际结果和剩余缺口，不升级正式场景状态 |

预期仅两个 Go 文件，不修改 `go.mod`、I1 算法、profile/schema、proxy 故障策略、TCP 入口/超时、CLI、Docker、CI 或历史证据。既有 V0 合法输入的线格式、上限与成功结果不变；原先误报成功的短写改为错误。实现范围为 L1 工具边界；若需要改公共协议、持久化或正式实验合同，应停止扩张并重新说明。

## 读写合同

### 共用上限与兼容

- 上限参数为 `int64`，仅允许 `1..65536`；零、负数、超过既有 transport 总上限的值在任何 I/O 前拒绝。不接受零表示默认、不向上截取/取整。
- frame body 必须 `1..maxBodyBytes`；保留外层 **4-byte big-endian uint32** 长度前缀，上限不包含该前缀。不引入新 wire version，因为帧编码没有变化。
- 既有 `ReadSyntheticFrame` / `WriteSyntheticFrame` 继续以 `MaxSyntheticFrameBytes` 为默认上限；`SyntheticProxy.Process` 的总上限保持 65536 B。本包通过 codec 显式参数证明 32768 B 边界，不声称旧网络入口已经切换到新边界。
- body 是不透明字节。codec 不验证正文、UTF-8、base64、JSON、身份、message key 或认证结果；内层 16384 B 限额留给后续 envelope decoder。在读取前无法验证内层长度，不能因 frame 合法就报告“消息有效”。

### 读取

1. 校验限额后，用局部固定 4-byte 数组及 `io.ReadFull` 读取前缀；不以编译器是否把该数组放入栈作为安全保证。
2. 以宽整数比较声明长度与限额；空、超限直接返回 `nil, error`，不分配 body、不读 body、不试图跳过超长数据继续解析。
3. 通过后仅分配声明长度的 body；`io.ReadFull` 必须完整读取。截断或底层错误返回 `nil, error`，不把部分 body 交给消费者。
4. 错误分别说明 header/body 阶段，使用 `%w` 保留 `io.EOF`、`io.ErrUnexpectedEOF` 或底层错误以支持 `errors.Is`；错误不得包含 body 内容。
5. 成功只消费一帧，保留后续帧在 reader 中。遇到任何解码错误，调用方放弃该流，不使用自动同步/扫描恢复。

此处“分配前拒绝”由前缀检查先于 `make` 的代码顺序及只允许四字节读取的负例共同证明，不使用易波动的进程 RSS 断言。codec 没有连接所有权或超时；阻塞 reader 的时限由实际调用方设置，I2 不证明 slow-reader 防护。

### 写入

1. 在写出任何字节前检查限额与 body 长度；失败 writer 调用次数为零。
2. 保留先前缀、后 body 的顺序。每次 `Write` 检查 `(n, err)`：底层 error 非 nil 时保留其原因；error 为 nil 且 `n != len(input)` 时返回包裹的 `io.ErrShortWrite`。
3. 前缀失败不再写 body；body 失败不报告成功。不在 codec 内循环重试部分写入，不重发前缀，避免流状态不明时重复 frame。
4. 错误记录阶段与必要的长度，不记录 payload。调用方放弃失败的流；剩余消息重试机会仍由已提交的队列预算决定，codec 不补回额度、不生成 custody/delivery。

## 离线验收矩阵

| 测试组 | 输入 / 人工期望 |
| --- | --- |
| 旧入口兼容 | 1 B、32769 B、65536 B 完整 round trip；65537 B 与空 body 拒绝；手工前缀期望验证旧编码不变 |
| 新入口边界 | 限额使用 I1 的 `delivery.MaxFrameBodyBytes`：32768 B 成功，32769/65536 B 拒绝；prefix 声明 uint32 最大值也在 body 读取前拒绝 |
| 上限参数 | -1、0、65537、MaxInt64 → 零 I/O；1 和 65536 为有效上限，各验证刚好上限和超限 |
| 分配/读取次序 | Reader 只提供合法四字节前缀并记录任何后续 Read；空/超限声明返回 nil 与错误，body Read 次数为零；静态复核 `make` 在检查之后 |
| 截断与根因 | 前缀 0/1/2/3 字节，body 少 1 字节；Reader 分别返回 EOF、UnexpectedEOF 与独立 sentinel error；无部分返回，`errors.Is` 保留根因 |
| 流边界 | 两个合法帧连续放置：首次只取第一帧，第二次取第二帧；Reader 每次只返回 1 字节仍能按 `ReadFull` 完成 |
| 短写回归 | header 短写/零写且 nil error → ErrShortWrite、body 零调用；body 短写/零写且 nil error → ErrShortWrite；完整 n 但非 nil error 仍失败 |
| 错误与脱敏 | header/body 底层 sentinel error 可识别，阶段明确；合成 body 标记不出现在错误字符串中；失败没有内部自动重试 |

codec 测试的成功不代表队列提交、掉电恢复、节点隔离、真实网络成功或消息认证。测试不会使用 socket、sleep、子进程或新依赖。

## 已接受的实施与验证包

所有者在看到上述精确清单后于 2026-09-26 明确“接受，继续推进”，接受上文两个 Go 文件的实现、对应文档同步及以下离线验证；此包不含 Git push、正式实验、外部服务或依赖安装。命令已经执行，结果见下节。

仓库根：

```bash
gofmt -w tools/t0/internal/harness/proxy.go tools/t0/internal/harness/proxy_test.go
```

在 `tools/t0`：

```bash
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=60s ./internal/harness ./internal/delivery
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./...
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=60s ./...
```

仓库根：`./scripts/check-repo.sh`、`git diff --check`，复核 Go diff 与兼容入口、文档链接及工作区。

副作用仅 Go build cache 和 Go 测试临时文件，预计数分钟；没有后台服务，默认保留构建缓存，临时目录由测试清理。缓存权限如再阻断，保留首次失败并按同一命令申请环境复验，不能调整实现绕过失败。允许修复本包代码或测试缺陷后精准重验及最终回归，不重复正式 run，也不重判历史证据。

## 设计记录与后续门

2026-09-26 设计轮：所有者要求提交工作区并推进下一任务；已将 I1 和工程自审提交为 `0eb4885`，随后完成队列/事务接入设计及本 I2 清单。该轮只做源码与语义静态核对，I2 当时未实施、Go 命令未执行；短写缺口列入负例。文档检查 123 文件、118 个相对链接与差异检查通过。

接受 I2 不接受完整 schema 2、存储格式、安全路线或正式运行；队列容量计费、控制速率、动作引用限制、可恢复调度状态、时钟重建与安全状态联合提交仍须在后续纵向切片合同中明确。下一工作为收敛这份完整合同，I2 完成不等于消息闭环完成。

## 实施与验证记录（2026-09-26）

实际源码范围为 `proxy.go` 的 codec 与 `proxy_test.go`。新增显式上限入口，旧函数以 65536 B 委托同一实现；生产代码不依赖 delivery，测试使用 I1 的 32768 B 常量验证接入。限额校验在 I/O 前，声明长度校验在 body 分配前；写入检查 n/error，header 失败不写 body，短写返回可识别的 `io.ErrShortWrite`。错误保留阶段与原始原因，代码不添加 payload 到错误中。

测试以手工前缀、内存流和受控 Reader/Writer 覆盖旧入口成功/拒绝、新限额边界、零 I/O 参数拒绝、无 body 读取的超长拒绝、截断/底层错误、逐字节读取、连续两帧和短写。没有新增依赖、socket、后台进程或正式运行；没有改变网络入口的默认限额。

环境为 `go version go1.26.3 darwin/arm64`，所有 Go 验证使用 `GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off`。

| 命令 / 检查 | 实际结果 |
| --- | --- |
| 修复前 `go test -count=1 -timeout=60s ./internal/harness -run '^TestSyntheticFrameWriterRejectsShortWrites$'` | 退出码 1，预期回归复现：header/payload 短写均返回 nil；header 短写后 calls=2，期望 calls=1 |
| 两文件 `gofmt -w` | 退出码 0 |
| `go test -count=1 -timeout=60s ./internal/harness ./internal/delivery` | 退出码 0，修复后的短写及边界测试通过 |
| 首次 `go vet ./...` | 退出码 1，沙盒拒绝读取 Go build cache，静态检查未完成 |
| 首次 `go test -count=1 -timeout=60s ./...` | 退出码 1，`cmd/sw-v0-harness` setup failed；同一缓存权限错误，delivery/t0node 已通过但整体回归未完成 |
| 获准在沙盒外执行同一 `go vet ./...` | 退出码 0 |
| 获准在沙盒外执行同一全量 `go test -count=1 -timeout=60s ./...` | 退出码 0，harness/delivery/t0node 全部通过；两个 cmd package 为 `[no test files]` |

两次沙盒失败的关键错误均为 `open .../Library/Caches/go-build/6d/6d5319457acc88c4cf64c25d313c27ac1080dd5cda7b0ddcbd38f128af4e6f43-d: operation not permitted`。保留环境失败与修复前的真实缺陷复现，二者原因不同；复验没有改代码、测试或命令来规避缓存权限。没有重跑正式 harness/三节点实验。

仓库检查覆盖 123 个文件，`git diff --check`、6 份文档的 118 个相对链接检查均通过；源码范围复核确认 proxy 的 codec 以外区域保持原样。

结论仅为 I2 frame codec 离线验证通过。新的 32768 B 限额须由后续消息入口显式选择；内层解码、持久化、慢速流超时和 E2EE 均不在本次证据内。工作区保留本轮两个 Go 文件及此前六份设计文档的修改；未提交或推送本轮修改，没有后台进程，默认保留构建缓存。
