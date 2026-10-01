# SW-G4 合成验证准备：离线实施单元 I1

- 状态：Accepted（2026-09-26 所有者授权）；I1 已实施，离线验证通过
- 日期：2026-09-26
- 设计基线：`fd49809` 的文字闭环/SW-G3 草案及本轮工程自审修订
- 目标读者：消息实现与验证评审者
- 产物：可供后续消息状态机调用的有界重试算法和长度检查
- 非目标：正式 SW-V1/V2、E2EE、持久化、网络或产品用户入口

## 本次评审与范围

前一轮根据用户“提交工作区更改，继续推进下一步”完成工作区提交、技术自审和本清单；当时没有把推进评审解释为已经接受全部新语义。2026-09-26 所有者随后明确“接受，开始实施”，接受本包有限算法、四个源码文件和列出的离线验证范围；整体 SW-G3/schema 2、事务和安全路线仍待评审。

选择 I1 的原因：现有 `internal/harness` 提供代理、时钟和证据，`internal/t0node` 仍使用探索性 ACK 和周期重传；二者都不是正式消息调度职责的合适归属。在同一个 Go module 内建立 `internal/delivery`，只放实际待消费的算法；不新增 module、runner、命令入口、网络服务、通用框架或密码占位实现。

## 精确文件清单

| 动作 / 文件 | 职责 |
| --- | --- |
| 新增 `tools/t0/internal/delivery/retry.go` | 队列级纯状态转换、定时槽/恢复额度、同刻事件与停止原因 |
| 新增 `tools/t0/internal/delivery/retry_test.go` | 手工推导的事件表、边界与错误不变性；不以实现本身生成期望值 |
| 新增 `tools/t0/internal/delivery/limits.go` | 各层长度、相加溢出及声明/实长一致性检查；不读取/分配 payload |
| 新增 `tools/t0/internal/delivery/limits_test.go` | 上限、上限加一、溢出、截断/不一致的数值负例 |
| 更新本文件与 `docs/status/current.md`、`docs/status/d0-t0-p0-plan.md`、`docs/status/project-execution-plan.md` | 只记录实际实施、验证、剩余门；失败保留原因，不升级为场景通过 |

其他代码、`go.mod`、lockfile、V0 profiles、旧 runner/decoder/proxy、Dockerfile、CI 和历史 evidence 保持原样。I1 不引入 profile/evidence/state JSON schema，也不在测试中创建一套假持久化数据库。若四个源码文件不足以清楚承载本单元，先说明实际职责差异再修订范围。

## 重试算法合同

推荐使用显式值对象和纯转换函数；下表为语义合同，局部 Go 标识可按仓库命名习惯确定，不能改变含义。字段私有或构造时完整校验，错误返回原状态和无发送决定；返回值不执行 I/O。

| 对象 | 必需数据 / 校验 |
| --- | --- |
| Policy | 固定 backoff `[250,500,1000,2000] ms`，5 个定时槽含初次、1 个恢复额度；不接受任意扩展次数 |
| QueueState | 首个计划时刻、已结算槽索引、恢复额度是否已用、最近已处理批次及时间、当前 up/down、暂停/终止事实；不得存放 payload/密钥 |
| Deadline | 调用方提供已证明的本地保守 deadline；非负 `int64` 毫秒，与本轮逻辑时间同一坐标；不从 now 或 link-up 重建 lifetime |
| EventBatch | 一个 now、至多一个 link 变化、已验证的 stop/pause 事实、准入结果；缺省/未知枚举和同刻 up/down 矛盾拒绝 |
| Decision | 是否尝试、是否允许发送、已消费定时槽数、恢复额度变化、原因；从未代表 custody/delivery 或准许删除 |

状态属于一条队列；message key/邻接/receipt 类型的索引和队列配额由后续调用方管理，I1 不建立无界队列 map。数据队列与证据队列调用同一个算法但各有状态：A 数据队列可在验证 custody 后暂停，证据队列不能因为自己刚发送成功就传入终止事实。

具体顺序：

1. 校验参数、状态计数和时间坐标，拒绝负数、回拨、加法溢出、未知/矛盾事件；已暂停/终止状态不能被 up 事件复活。
2. 批次中的 stop/pause 优先于发送；`now >= deadline` 时停止发送。I1 不决定迟到 evidence 是否改变用户历史，只返回禁止发送。
3. 对仍活动的队列更新 link 状态。初始状态明确为 up 或 down；初始 down 是已观察断链，首次 up 可使用恢复额度；初始 up 及重复 up 不触发。
4. 初次槽在 start，随后为 start 加 `250/750/1750/3750 ms`。一次调用结算所有已到期槽，较早槽记 missed；只为最新槽产生最多一次尝试，down 或准入拒绝也消费该槽。
5. down→up 可额外使用一次恢复额度；start 前只更新可达性，不消费额度或发送。恢复与定时到期同批次合并一次尝试；配额/hop 拒绝也消费恢复机会。
6. 返回新状态和原因；无到期槽/恢复事件时不发送。同刻同内容批次重放为无发送的幂等观察；同刻新内容拒绝，防止调用方先发包后补终态事件绕过优先级。算法不产生 goroutine、timer、sleep 或自动重跑。

调用方负责把状态消费提交成功后才真正发包；若提交后、发包前崩溃，允许消耗一次机会而没有发包，不允许从旧预算重新获得额外机会。该 I/O 顺序和跨进程时钟恢复留待持久化单元证明，I1 的值拷贝测试不称为 crash-safe 实测。

## 长度算法合同

只处理数值元数据，区分正文、不透明合成 payload、编码后 envelope body 与 header；不提供“认证成功”结果。

- 正文与合成 payload 分别要求 `1..16384 B`；空正文或空 payload 在本单元显式拒绝，后续控制消息不能借用文字类型通过。
- frame 最大 `32768 B` 定义为传给现有 length-prefixed transport 的 body（包含应用测试信封及 payload），不包含该 transport 的 4-byte 长度前缀；这不是生产密文上限。
- header 与编码后 payload 的相加必须先做溢出检查，再比较 frame 上限；编码后大小由编码器提供，不能把原始 payload 大小当成 JSON/base64 后大小。
- 对外声明的 payload/frame 长度必须与已提供的实际长度一致；未知类别、负数、零、不一致或超限返回包含类别与界限的错误；不输出实际正文。
- 测试覆盖 `0/1/16384/16385`、`32768/32769`、负数、`MaxInt64` 加法溢出和长度不一致。I1 只能验证元数据规则，无法证明网络 reader 已在分配前拒绝。

后续 transport 集成必须复用并参数化现有 `ReadSyntheticFrame` 的入口限额，保留 V0 的 65536 B 默认合同；不能先按旧上限分配再调用 I1 然后声称新上限已实现。该集成不在 I1 文件范围。

## 精准测试与验收

| 测试组 | 手工期望 |
| --- | --- |
| 定时基础 | up 时在 0/250/750/1750/3750 各一次；下一槽前 1 ms 不发；全部消耗后不再自动发送 |
| 5 秒断链 | down 时 5 槽已消费且零外发；5000 ms up 恰好一次；重复 up 不再发 |
| 调度迟到 | 先处理 0，再跳到 5000；其余 4 槽结算但最多一次尝试；同时 up 仍最多一次 |
| deadline | deadline 前 1 ms 可按其他条件尝试；相等及后 1 ms 均禁止；stop 与定时同刻零发送 |
| 碰撞/资源 | 250 ms up 与定时合并；配额拒绝仍消耗机会；计数、时钟非法时错误且输入状态未变化 |
| 暂停/重复 | custody 对应 pause 后保留状态且不发；重复同刻调用不重复消耗；stop 后不复活 |
| 身份隔离 | 两份独立队列状态无共享计数；算法不接收凭据或声称验证身份 |
| 长度 | 逐项检查各层独立上限、编码长度差异、溢出及不一致；错误路径不分配 payload |

通过仅表述为“I1 离线算法及边界单元测试通过”。不得写 `SW-V1 PASS`、`SW-V2 PASS`、三节点闭环或持久恢复通过。新测试不得使用 socket；已读取的现有 harness/t0node 测试只用内存流、直接方法调用和测试临时目录，不调用网络运行入口。

## 实施验证命令与副作用

下列命令已在 I1 接受并授权后执行，结果见下节。复用已安装 Go 1.26.3 与标准库，没有安装依赖、下载工具链或改变 go.mod。

仓库根执行格式化：

```bash
gofmt -w tools/t0/internal/delivery/retry.go tools/t0/internal/delivery/retry_test.go tools/t0/internal/delivery/limits.go tools/t0/internal/delivery/limits_test.go
```

在 `tools/t0` 执行：

```bash
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=60s ./internal/delivery
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./internal/delivery
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=60s ./...
```

全量单元回归只消费现有离线测试，不运行正式 harness 命令、listener 或 Docker；不接触真实用户数据。仅写本机 Go build cache 与测试临时目录，预计数分钟，无长期进程。若工具链或缓存权限不足，记录原失败并按同一验证范围处理，不改测试逃避失败。相关代码修改后可以精准重跑失败用例，但不重跑历史正式实验。

仓库根执行 `./scripts/check-repo.sh` 和 `git diff --check`，复核 diff 与残留。默认保留构建缓存；测试临时目录由 Go 测试清理，不删除历史 artifacts。提交/推送依用户当次指令，不由本包产生远程授权。

## 实施与验证记录（2026-09-26）

- 实施范围：清单中的四个 Go 文件，位于同一 module 的 `internal/delivery`；未改 V0、harness、t0node、依赖、CI 或历史 evidence。
- `NewRetryState` / `RetryState.Advance` 使用私有值状态、显式枚举与同刻批次，固定五个定时槽和一次恢复额度；错误返回原状态和空决定，迟到调度最多产生一次尝试，同刻重复不会发包。
- `CheckLength` / `CheckFrameBodyLength` 区分正文、合成载荷与编码后 frame body，在相加前检查溢出，未知类别、空值、超限和声明不一致均显式拒绝；只检查数值，不证明 reader 已在分配前拒绝。
- 测试采用手工期望事件表；覆盖固定时序、5 秒断链、单次恢复、调度迟到、同刻冲突、deadline、资源拒绝、暂停/终态、不合法输入的状态不变性、独立队列与反复链路抖动预算。长度测试覆盖编码前后区别、边界、溢出及截断/不一致元数据。
- 环境：macOS ARM64，`go version go1.26.3 darwin/arm64`；测试显式禁用 module proxy、checksum 服务及工具链下载。

| 实际命令 / 检查 | 结果与限制 |
| --- | --- |
| 上述四文件 `gofmt -w` | 退出码 0 |
| `GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=60s ./internal/delivery` | 退出码 0；随后增加链路抖动预算断言，由全量回归覆盖最终文件 |
| `GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./internal/delivery` | 最终源码检查退出码 0 |
| 同环境变量的 `go test -count=1 -timeout=60s ./...`，首次沙盒运行 | 退出码 1；`pattern ./...: open .../Library/Caches/go-build/2e/2e1109c2543dd4b7a6ab01f001070793b488ff7f31d2d856035cfd28be3a4788-d: operation not permitted`；delivery 已通过，但整体回归未完成 |
| 相同全量命令获准在沙盒外复验 | 退出码 0；delivery、harness、t0node 全部通过；两个 cmd package 为 `[no test files]`，不代表 CLI 全流程验证 |

首次失败属于构建缓存访问权限，保留该失败而不计为产品测试失败或隐去；复验没有变更代码、测试、工具链或命令参数。结论仅为 I1 离线算法及边界单元测试通过；没有正式 profile/run、三节点、持久化或 E2EE 证据。仓库/文档检查结果在本轮交接中记录，不由单元测试结果推定。

最终代码复核将定时槽耗尽原因明确命名为 `timed_slots_exhausted`，避免被调用方误读为消息终态或恢复额度也已耗尽；该修改后 `go vet` 与获准的相同全量离线命令再次退出 0。仓库检查覆盖 122 个文件、`git diff --check` 与 12 处修改文档的本地标题链接检查均通过。没有提交或推送本轮更改，没有启动长期进程或清理旧 evidence/cache。

## 后续阻塞与批准记录

- I1：上述有限范围已接受、实施并完成离线验证；该结果不授权扩展下一单元或正式运行。
- 后续消息合成闭环：完整 schema 2、队列/控制资源预算、T-A/T-B/T-C/T-D、时钟恢复、编码与 reader 集成、证据字段和精确运行包仍需完成；I1 通过不自动开放。
- 真实安全：身份架构、库 API、原子协调、relay-clear proof、许可证/R2/Phase B 条件保留。
- 实体/无线：三节点复用设备、2000 元预算可行性与上海法规路径仍待关闭。

本次接受仅覆盖 I1，不接受真实 E2EE、整个 schema 2 或任何容器/硬件操作；下一步先完成消息队列与 schema/事务/reader 集成的精确设计及范围，再进入后续实施。
