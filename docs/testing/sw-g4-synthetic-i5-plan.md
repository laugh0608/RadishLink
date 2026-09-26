# SW-G4 合成验证准备：三进程文字闭环单元 I5

- 状态：I5-I 有限实施已接受，实施与离线验收通过；I5-R 未执行
- 日期：2026-09-26
- 基线：`dc50626`，I1–I4 已提交
- 目标读者：消息实现、场景执行与证据复核者
- 用途：把现有持久消息 Node 接到三个独立进程和受控 TCP 传输，给出可整体评审的实施、验证与运行范围
- 非目标：生产网络协议、真实 E2EE、正式 SW-V1/V2 完整矩阵、节点掉电、实体台架、无线、媒体或性能承诺

## 范围与推荐决定

所有者在 I4 提交后同意继续形成下一工作包。设计轮核对本地源码，形成以下合同与文件清单；后续 I5-I 有限实施的接受与验证见文末。没有启动容器或网络服务。方案涉及测试控制协议和证据版本，按 L2 评审；容器运行及资源清理另按 L3 执行。

推荐先完成 `I5-I`：现有命令包中的消息进程、监督器、TCP 适配器、证据消费者和离线正负例，再执行 `I5-R`：三个隔离容器的有界网络矩阵。两者是同一纵向切片的实施与实测部分，不以 stub 或内存测试宣告三进程闭环完成。实施可先验收；网络运行只在产物、精确 revision/hash 和环境预检齐备且取得明确运行授权后开始。

运行标识固定为 `execution_mode=docker-tcp-i3`、`variant=i3-small4-tcp-v1`、`security_mode=synthetic`。只有 TCP 实际写入、接收及三个进程的文件提交相互匹配，才可得本 variant 的 PASS。I4 的 `offline-i3` 保持原合同。I5 仍使用固定公开 fixture、I3 四消息限额、envelope/store v1 和观测 v1，不推进 SW-G2、安全联合事务或 P0 验收。

## 已核对接口及实施约束

| 现有入口 | 实际约束 | I5 处理 |
| --- | --- | --- |
| `synthetic.InitNode/OpenNode` | 每个实例操作一个目录；没有跨进程写锁；Recovery 由存活监督端提供 | 每个节点独占一个 store；不把整批根目录挂给各节点；同一 store 不允许两个写进程 |
| `Submit` / `StepWithReport` | 只有提交后才返回已发布状态/报告；Step 时间严格递增，批次上限 128 输入/2 邻接事件 | 一个节点只有一个事务执行循环；网络读线程只能入有界待收队列，不能自行 Step |
| `Transmission.Write` | 发送额度已持久消费；机会只在当前 generation 有效且只能使用一次 | 完成本批全部写出或明确写失败前，不向该节点发下一个 Submit/Step；不重建 Transmission 或补回额度 |
| `ReadInput` | 使用 I2 有界 framing，随后解码 envelope；调用方负责超时/坏流关闭 | 在真实 socket 上调用；不把监督端提供的 frame 字节伪装成网络接收 |
| `Snapshot` | 只返回已发布、无正文的值副本；halted 返回错误 | 接入控制响应；不能让报告或监督器读取候选态来补齐证据 |
| `scenario.go` | 把时钟、oracle、记录与内存传输放在同一函数中 | 提取确有重复的 fixture/时序规则；分别保留 offline 与 TCP 执行器，消息状态机仍只在 synthetic |
| `evidence_v2.go` | 1333 行；严格绑定 offline profile、内存路由、零子进程、schema 2 | 先按观测 DTO、语义评估、bundle I/O 拆分再接 schema 3；不放宽 schema 2 以容纳网络字段 |
| `main.go` / `RunEndpoint` / `RunProxy` | 旧端点与代理处理 echo；错误和生命周期不满足 I5 证据要求 | 保留 V0 分支，新增明确的 synthetic 子命令；不复用 echo 作为 Node，不复制旧代理的静默错误路径 |
| `run-sw-v0-harness.sh` | 固定四 profile/hash 和 V0 生命周期；部分自检事实由 finalizer 生成 | 保留不改；新增 I5 薄入口，生命周期只有一个监督器负责，不从 canonicalEvidence 构造 I5 运行事实 |

## 进程、拓扑与数据归属

单样本由一个宿主监督器和 A/B/C 三个 Linux 容器组成。三容器各运行同一二进制的 `synthetic-node`，B 同时连 `ab`、`bc` 两张 internal bridge；A 只连 `ab`，C 只连 `bc`。不增加共享管理网络，不映射宿主端口，不使用 host network、privileged、NET_ADMIN 或 Docker socket 挂载。B 只做应用层转发；容器内 IP forwarding 设为 0 并核验，不改变宿主 sysctl。

控制面通过监督器拥有的 `docker start -ai` stdin/stdout 管道；先 `docker create -i`，给尚未启动的 B 接入第二张网络，再启动并保持管道。stderr 独立限额采集。Docker CLI 子进程退出、管道 EOF、写阻塞和消息乱序均可观察，不在失联后重发事务命令。Docker 已启动是运行前提，本包不启动桌面应用或 daemon。

数据面仅走节点间 TCP/IPv4，每条连接承载一个 I2 frame。接收邻接由本次 inspect 取得的源 IP、接收接口和预置邻接表共同绑定，不相信 payload 自报的 neighbor。禁止 A→C/C→A 地址进入数据发送表；B 的业务转发必须来自其本地提交后的 Transmission。控制面不允许提交任意原始 frame、历史内容或修改 store；初始化只传固定 profile/subcase，A 在本地构造公开合成载荷。

每个节点独占一个新建 named volume，仅挂 `/state`，容器根只读，另设 16 MiB `/tmp` tmpfs。volume 的名字、ID、标签、挂载和所有者在创建时登记；不挂工作区、用户目录或其他节点 volume。镜像内预建归固定测试 UID 所有的空 `/state`，新 volume 通过该目录初始化；固定 UID 及卷目录权限须由创建阶段核验，权限不满足即停止，不能改宿主目录权限凑通过。所有节点同一镜像，镜像仅含本批本地构建二进制与固定 profiles，基础为 scratch，不拉取镜像。

开始业务前，先在同一网络命名空间、同一监听器上做四个允许方向的探测及 A→C/C→A 两个拒绝探测。拒绝探测使用 inspect 得到的目标数字 IP，不能把 DNS 不解析当网络隔离；允许探测须有对端响应，探针独立标记并在 origin 前全部回收，不进入消息/fault 计数。同时保存裁剪后的网络成员、路由、IP forwarding 和挂载检查。允许方向失败、直达成功、存在额外网络/端口/共享 store 均 INVALID。

## 监督时钟与批次屏障

监督器是唯一逻辑时钟源，复用 TestClock；节点不使用 wall time 为消息续期或决定重试。逻辑观察窗仍为 0..30000 ms，固定每方向 50 ms 的**逻辑入批延迟**；socket 的实际耗时另行记录，不能把这 50 ms 写成测得的网络延迟。

控制协议 `control_version=1` 使用严格规范 NDJSON：固定结构、单 LF、未知/重复/缺失/null/别名字段拒绝；先限长再解码。公共请求字段为 version、session、node、request_sequence、clock_epoch、logical_ms、expected_generation、operation、typed detail。响应回显请求身份并包含连续 local_sequence、实际 generation、明确 error_code 和对应 typed result；无自由 map、默认成功或补值。session 为本批公开运行标识，epoch 为本次监督器的合成时钟域，不是身份凭据。

请求操作仅有 init、submit_fixture、step、arm_receive、send、drain、snapshot、probe、shutdown。init 绑定唯一 profile hash/subcase、节点、邻接表和空 store，重复 init 拒绝；submit_fixture 只允许 A 的固定动作；step 只携带待收条目 ID 与 link 事件，不携带消息正文。每次请求最多 64 KiB、响应最多 256 KiB；每节点同时最多一个控制请求。序号重放、跨 session/epoch、错误 generation、时钟倒退及未知 operation 立即拒绝并保留错误，不重试该事务。

固定执行次序：

1. 三节点 Init、初态快照与自检齐备后，A 在 0 ms Submit；首个 Step 为 1 ms，保留 I4 首槽迟到 1 ms 的条件。
2. 从已发布快照中的下一重试槽、已确认 ingress 的到期入批时刻、故障 up 和截止时刻取最小值。冻结时刻 `t` 的收件集合，按 A/B/C 顺序，每个到期节点最多一次 Step；同刻产生的 frame 只能在 `t+50` 入批。
3. 节点返回真实批次报告和快照，保留本批 Transmission 的临时句柄；报告不序列化可重放发送许可。监督器按报告中的稳定顺序安排发送，节点实际验证句柄仍属于当前 generation。
4. 每次发送先向目标 arm_receive，登记 `(sender, generation, transmission_index, direction_ordinal)` 及允许来源，再命令源节点 send。全局最多一个在途 socket，避免相同摘要的重传无法归因；关联号只走控制面，不修改 envelope v1。arm 的期望摘要不得决定接受 verdict，verdict 仍来自独立预登记 oracle。
5. 源节点以 Transmission.Write 直接写 socket，完整返回成功才记录 frame_written；计数/摘要 writer 不保存正文。写后关闭写半边，目标 ReadInput 成功且读到 EOF 后记录 transport_ingress，额外 frame/尾部字节、短读/短写与超时全部拒绝并关闭流。只有未被 drop 的 ingress 才进入目标待收队列。
6. 监督器收齐本次 write 与 ingress/drop 的回报，再 drain 对账；缺任一项不推进时钟、不生成接收事实。下一次 Step 引用具体待收条目，此时产生 frame_received，并与 verdict、batch_result、state_observed 关联。全部本批发送处理完成后才解除该节点提交屏障。
7. 30000 ms 仍执行截止结算和最终快照；不因 A 已 delivered 提前结束。停止接收并回收管道、listener、连接、节点、网络及 store 后生成真实 residuals。监督器中断或记录器溢出保留不完整证据，不伪造 observation_end。

一个 send 的 socket 写成功不保证接收或交付。写失败后额度仍已消费，不补发；故障定位证据不足时记 INVALID，确认是被测适配器/消息实现错误时记 FAIL，原始错误同时保留。宿主超时使用实际单调耗时，只负责终止挂起，不转成逻辑时钟推进或新一轮恢复机会。

### epoch、重启与不确定提交

I5 网络矩阵不注入重启，unexpected node exit 立即结束该样本，不自动换容器、重开 store 或续跑。仍须离线验证进程边界拒绝错误 epoch、倒退时间、低于监督器已确认 generation 的状态，以及断在“提交后、响应前”时不会重发命令或重放 Send。

既有 OpenNode 只能接收**仍存活监督器**给出的 Recovery；I5 不根据磁盘 Now 猜新的 monotonic 起点。监督器丢失、generation 确认不完整或提交结果未知时保留失败，新的监督器必须开始新的样本/epoch/目录。节点恢复入口和网络重启 profile 留给后续工作，不能以这条停止规则宣称重启恢复已通过。

## 五 profile、七子用例与故障定义

新目录 `tools/t0/profiles/i5/` 保存五份 JSON，文件名与 I4 同名，目录和版本明确区分。profile schema/evidence schema 均为 3；保留 I4 字段顺序和固定参数，替换上述 mode/variant，增加末尾 `control_version=1`、`transport=tcp-one-frame-v1`、`fault_layer=receiver-drop-or-sender-link-gate`。BASE、LOSS-EVIDENCE、DOWN-AB/BC 的 profile version 为 3；LOSS-EVIDENCE-BA 为 2。ID 与 seed 沿用 I4；新旧 schema 不相互接受，不改原 JSON。

| 顺序 | Profile / 子用例 | 唯一故障与验收重点 |
| --- | --- | --- |
| 1 | `SW-V1-BASE-001` / p1、p1024、p16384 | 无故障；实际网络 A origin → B custody → C history → A delivered；C 恰交付一次，B 清 body 后仍保留返回责任 |
| 2 | `SW-V1-LOSS-EVIDENCE-001` / p1024 | 目标 B 在 TCP ingress 后、入批前丢弃第一帧 C→B delivery；重传返回责任必须成立 |
| 3 | `SW-V1-LOSS-EVIDENCE-BA-001` / p1024 | 目标 A 同位置丢弃第一帧 B→A delivery；B 已清 body 后仍能返回 evidence |
| 4 | `SW-V1-DOWN-AB-001` / p1024 | A origin 后、Step(1) 前关闭 A→B 适配器发送 gate，向同批传 became_down；5000 ms 后同批恢复 gate 与 became_up |
| 5 | `SW-V1-DOWN-BC-001` / p1024 | B 首次收到 A data 的批次中传 B→C became_down，发送 gate 在该批前已关闭；检查该批确实提交 T-B，再登记屏障命中；5000 ms 后恢复 |

down 是**单向传输适配器不可用**，不执行 docker network disconnect、不关闭整张 bridge，也不代表双向物理断链。这样明确保留 I4 邻接事件语义，BC down 不额外阻断 B→A custody。gate 关闭期间误发属于实现 FAIL，不能由隐藏代理丢弃后掩盖；反方向仍可传输。若以后验证内核接口断开/真实双向断链，必须新增不同 fault_layer/variant。

BC 屏障须在 origin 后 1000 ms 内真实提交 custody；入批前关闭 gate 的准备动作不算命中。实现没有产生触发对象为 FAIL；触发存在而注入器未生效为 INVALID。drop 只计 delivery，不把 custody 当第一个对象；每个 profile 只命中一次。每子用例三次独立 store/容器/网络，共 21 样本；正常组全部通过才进入后续故障组，出现 FAIL/INVALID 即停止后续运行并保留尚未运行清单，不自动补跑。

## Evidence schema 3 与兼容

保留 I4 的事实与断言语义，新增执行事实，不能把网络 trace 删掉字段后伪装成 schema 2。公共观测 DTO 版本仍为 1；公共语义评估接收明确的内部合同参数，V2/V3 decoder 分别固定自己的合同，不提供任意 limits/expected override。V0 schema 1 与 I4 schema 2 的 decode、finalize、verify、compare 回归必须原样通过。

bundle 保留原八个文件及空 `logs/`，新增 `execution.ndjson`。各文件 schema 3 独立类型；规范 JSON + 单 LF、拒绝未知文件/symlink/字段及重算 checksum 后的语义篡改。原 events 保存确定性业务事实；execution 保存原始控制响应次序、进程生命周期、probe、socket/ingress/gate 与清理事实，以 source/local_sequence/request_sequence 关联 events，不能丢弃原始跨进程证据只保存监督器重写后的故事。

| 文件/字段族 | I5 增量 |
| --- | --- |
| `manifest.json` | 原业务绑定加 control_version、transport、fault_layer、host_binary_sha256、node_binary_sha256、image_id、Docker client/server 版本、daemon OS/arch、合同文档 hash、五 profile 的绑定；旧 binary_sha256 字段在 schema 3 不使用，避免双二进制含糊 |
| `topology.json` | 四方向真实 probe、两个数字 IP 拒绝 probe、网络成员与接口/forwarding 检查，均引用 execution 序号；同时保留允许图和禁止图 |
| `execution.ndjson` | schema、sequence、source、local_sequence、request_sequence、logical_ms、kind、typed detail；detail 按类型记录 session/epoch/generation、逻辑资源别名、实际耗时、退出码和有限错误；无正文、store dump 或任意环境变量 |
| `events.ndjson` | I4 业务事件类别升为 schema 3；每条加非空 execution_refs，frame_received 引用实际 ingress 与 step 消费，frame_written 引用真实 Write 成功，报告/快照/判定引用节点响应 |
| `metrics.json` | 逻辑 delivery_latency_ms 继续显式标作逻辑值；增加 socket 写/收/drop 数量与失败数，不对单消息输出 p95 或性能结论 |
| `assertions.json` | 原业务断言加三进程独立/唯一 store、实际拓扑、控制连续性、clock barrier、ingress 因果、gate/drop、运行资源和完整清理断言 |
| `residuals.json` | 逐项列出本批创建的容器/网络/volume/镜像/CLI 子进程数量、移除/退出事实、未完成项和残留连接；未知 inventory 或检查失败不能当 0 |

execution 每行最多 256 KiB，总计 16 MiB；events 继续每行 16 KiB、8192 事件/4 MiB；其余各文件最多 4 MiB，单 bundle 总计 32 MiB。控制回报在写入前限额；错误也不能绕过上限。stderr 仅限额诊断，不进入通过所依赖的证据；每节点最多 64 KiB，达到上限结束并记录 log_limit，禁止截断后 PASS。

validator 必须重算业务断言，同时从 execution 验证请求/响应连续、单 store 单进程、generation 不回退、每个实际 write 与唯一 ingress/drop 配对、无 control frame 注入、无跨节点读盘、故障与屏障命中、观察结束及清理。缺失来源、重复使用 ingress、伪造节点响应或逻辑事件与执行事实不符，重算 checksum 后仍拒绝。测试工具自报事实不是密码认证或独立审计证明。

比较器先逐样本完整验证，再比较确定性业务事件、逻辑 metrics/断言及执行事实的稳定投影。投影仅替换预先列出的 session/clock_epoch 实例值、资源实例 ID/IP、宿主 wall 时间/实际耗时与 execution 原始交错序号为逻辑别名/因果关联；epoch 替换前须证明全样本唯一且所有节点与 store 使用同一绑定；不删除节点身份、epoch 绑定、request/local_sequence、generation、deadline、预算、拒绝原因、fault 或 ingress 关系。原始 execution 完整保留；跨进程异步到达可不同，因果必须相同。三次的 schema、profile/hash、subcase、mode/variant、两个 binary hash、镜像、工具链、源树和合同 hash 必须一致，repeat 恰为 1/2/3；不与 I4 比较为同一组。

PASS/FAIL/INVALID 继续遵循 I4：环境有效的实现违反合同为 FAIL，证据/监督设施失效为 INVALID；同时发生时保留两类原因。单样本 CLI 退出 0/1/2；批次部分完成不得 PASS。中断保留实际停止时刻、错误和清理结果，不伪造完整 bundle 或三次一致。

## 精确实施清单（I5-I 已接受，职责细化见实施记录）

以下文件均相对 `tools/t0/`，合计 24 个 Go 文件（11 个已有、13 个新增）、5 个新 JSON；另有一个新 shell 入口与一个新 Dockerfile。新文件按职责组织，避免继续堆叠超长 validator；不改 I1/I2、synthetic 状态机、envelope/store 格式、密码依赖或 go.mod。

| 文件 | 动作与职责 |
| --- | --- |
| `internal/harness/evidence_v2.go`、`evidence_v2_test.go` | 修改，保留 V2 DTO/事件编解码及拒绝回归 |
| `internal/harness/observation.go` | 新增，原样迁移共享观测 DTO，包名/导出签名不变 |
| `internal/harness/scenario_assessment.go`、`scenario_assessment_test.go` | 新增，提取语义评估并测试固定合同；V2/V3 不经改写 profile 来互相冒充 |
| `internal/harness/scenario_bundle_v2.go` | 新增，迁移 V2 文件消费者，保留历史语义 |
| `internal/harness/evidence.go`、`evidence_test.go` | 修改，只增加 schema 3 显式分派与混合版本负例 |
| `internal/harness/profile_v2.go`、`profile_v2_test.go` | 修改，提取固定 fixture 复用点；原 decoder 不放宽 |
| `internal/harness/profile_v3.go`、`profile_v3_test.go` | 新增，五 profile 严格 schema 3 合同 |
| `internal/harness/evidence_v3.go`、`evidence_v3_test.go` | 新增，执行事实、来源校验、V3 bundle 与三次比较；接近 1000 行时按现有职责重新评估 |
| `cmd/sw-v0-harness/main.go`、`main_test.go` | 修改/新增，分派 synthetic-node、synthetic-run；V0 命令/退出语义保持原样 |
| `cmd/sw-v0-harness/scenario.go`、`scenario_test.go` | 修改，复用真实重复的固定 fixture/时序；全部 I4 样本仍走原离线入口 |
| `cmd/sw-v0-harness/control.go`、`control_test.go` | 新增，严格控制 DTO、节点 actor、TCP 接收/发送与离线流测试 |
| `cmd/sw-v0-harness/process_scenario.go`、`process_scenario_test.go` | 新增，监督器、Docker 生命周期、屏障与执行记录；mock 仅验证编排失败，不记网络 PASS |
| `internal/synthetic/observe_test.go`、`recovery_test.go` | 修改，验证跨批句柄失效、只读快照、错误恢复上下文；不开放可变状态接口 |
| `profiles/i5/sw-v1-base-001.json`、`sw-v1-loss-evidence-001.json`、`sw-v1-loss-evidence-ba-001.json`、`sw-v1-down-ab-001.json`、`sw-v1-down-bc-001.json` | 新增，固定五 profile |

仓库根新增 `scripts/run-sw-i5-harness.sh`，只做参数校验、本地离线构建并 exec 同一个监督器，不另写第二套 Docker cleanup；新增 `tools/t0/Dockerfile.i5`，scratch + 本地 node binary/profiles，全部离线。现有 V0 shell、Dockerfile、四 profile、t0node 和历史 evidence 不变。文档同步本文、I4 后续链接、文字切片、SW-G3 修订、current、两份计划和索引。

I5-I 不调用 Docker、不启动 socket listener；codec/actor/编排负例用有界 reader/writer 与注入的进程接口验证，并通过结构化命令构建测试检查生命周期参数。既有 I3 测试的短命 helper 按原合同执行并 Wait。真实 TCP 与三容器验收只能来自 I5-R，不能用 net.Pipe 或 mock 填补。实现如果确需增加字段、文件职责或改公共观测语义，先在本包明示差异，不静默扩大有限合同。

## 验收顺序与运行合同（候选 I5-R）

### 实施验收

1. 先完成 V2 拆分，检查原 schema 1/2 拒绝、I4 21 样本与三次比较不变，再接 V3。
2. 控制/传输负例覆盖：超长/缺字段/重复序号、错 epoch/generation、同刻第二次 Step、额外 frame、短读/短写、错误邻接、未知句柄、已消费句柄重复使用、超时/EOF、在完成 sends 前提交、队列超限、孤立 ingress、report 丢失、失败清理与 partial inventory。
3. bundle 负例覆盖：把 echo 当 Node、伪造独立 store、数字 IP probe 缺失、日志/文件超限、无来源状态、篡改 fault/gate/epoch/预算、事件与 execution 不符、混合双二进制或镜像、第四样本。重算 hashes 后仍须拒绝。完整实现错误 trace 必须可保存为 FAIL。
4. 只格式化范围内 Go 文件；module 内离线执行下列命令，仓库根另跑 repo/diff 检查及新 shell 的 `bash -n`。不新增依赖、自动下载工具链或更新 CI。

```bash
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./...
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./...
```

### 有界运行与停止/清理

已实现的根目录入口如下，**本轮未执行这两个入口**；它们供后续 I5-R 使用：

```bash
./scripts/run-sw-i5-harness.sh preflight
./scripts/run-sw-i5-harness.sh run --matrix i5-seven-v1 --repeats 3
```

preflight 与 run 都先在 `.tmp/i5-bootstrap.*` 有界离线构建宿主检查器，再使用同一个 Go 预检函数读取 git、Go、Docker client/server、profile/hash 与环境；preflight 不创建 Docker 资源、不启动 daemon。它会留下本地 bootstrap 二进制和 Go cache，不是零文件写入。只接受本地 Unix Docker endpoint，拒绝远程 TCP/SSH context。执行前要求源树干净且记录完整 revision、合同/profile hash、实际 Docker/Go 版本及架构；构建后记录宿主监督器和 Linux 节点二进制 hash。缺失/不支持架构、Docker 不可用、固定 profile 不符、既有同名资源、可用磁盘不足 1 GiB 均停止；不回退到内存模式、下载依赖或替换工具链。

run 内部用本地 Go 工具链离线构建宿主和 `CGO_ENABLED=0 GOOS=linux` 节点二进制，显式匹配 daemon arch；镜像构建采用 `--network=none --pull=false`。单次批次只构建一次镜像，每个样本新建三容器、两网络、三 volume，串行执行 21 样本，完成一个子用例三次后立即 compare。prepare/start/probe/stop 等临时 CLI 也由监督器创建、限时和 Wait；不使用无人管理的 shell background。

| 资源或时间 | 固定上限 / 预期 |
| --- | --- |
| 活动消息节点 | 3；每容器 0.5 CPU、256 MiB memory、64 pids，cap-drop ALL、no-new-privileges、无 restart policy |
| 宿主监督器 | 1；有界队列与字节计费，RSS 256 MiB 阈值；超过终止并保存证据，不声称操作系统已为普通进程施加硬 memory limit |
| 活动 socket / 待收 | 全局 1 个业务连接；每节点至多 128 个待收 frame、合计 body 上限 4 MiB；超过即拒绝并停止 |
| 控制/收发等待 | 单操作 5 s 实际单调时限；listener accept 只在 arm/probe 期间开放处理机会，超时关闭 |
| 单样本 | 30 s 逻辑观察窗、512 调度时刻；包含建立/探测/业务在内最多 120 s 实际耗时 |
| 批次 | 含离线构建最多 45 min 实际耗时，预期数分钟至数十分钟；清理另外最多 60 s；不保证机器性能 |
| 产物与诊断 | 每 bundle 32 MiB；整个批次含构建/临时/store/诊断最多 768 MiB，写前计费并检查宿主余量；named volume 纳入计费，超限停止 |

主要副作用仅为本批 Docker image/container/internal network/named volume、`.tmp/i5-bootstrap.*` 二进制、本地构建缓存和 `artifacts/sw-v/i5-<batch-id>/` 证据；不接触无线、外部服务、账号、其他项目或用户数据。所有 Docker 对象记录返回 ID，并带 `org.radishlink.sw-i5.batch` 与 sample/node 标签；名字只作显示，清理前重新按 ID 复核标签与挂载。

正常结束或异常均先停止节点、关闭并 Wait 控制进程，再移除本样本容器、网络、volume；整个批次结束才移除本批镜像。只移除本次 inventory 精确拥有的对象，不用 prune、宽泛 label 批量删除或目录递归清理。inspect 权限/连接错误不能当“不存在”；清理失败保留具体 ID 和诊断，结果 INVALID 并停止下一样本。失败证据保留，不自动重跑；产物目录和 Go cache 默认保留。若需继续，先根据失败重新明确修复与剩余运行范围。

本包把命令、次数、主要副作用、上限和回收边界放在同一处，后续可一次确认 I5-I 及满足前置后的 I5-R，不必逐样本重复询问。I5-I 的接受不启动 L3 操作；实施后如命令/对象/上限与本文不同，须先交付实际差异及精确产物再执行。

## 设计复核与当前交付

编写 Agent 静态核对了 I3 Node/store/observations、I4 scenario/profile/evidence、现有 clock/proxy、V0 main/shell/Dockerfile 及当前计划。主要关闭的设计缺口是：三进程/store 所有权、控制面不转发正文、Write 前后的 generation 屏障、重复 frame 的发送归因、逻辑与实际时间分离、单向 down 层级、跨进程事实链和双二进制绑定。不是独立复核或运行结果。

设计轮仅新增本方案并同步文档入口；当时没有创建上述源码、profiles、shell、镜像或测试 evidence。设计检查只证明文档和引用一致，不能证明拟定控制协议、资源预算、网络隔离或三次比较实际成立。当时下一项交付为 I5-I 实现及离线验收；现已完成，后续为满足前置并获运行授权的 I5-R。许可证、安全适配、上海法规与复用设备输入仍按[当前状态](../status/current.md)单独关闭。

设计轮验证：`./scripts/check-repo.sh` 通过（149 文件），`git diff --check` 通过；逐项核对实施清单的 11 个已有 Go 路径存在、13 个新增路径尚未占用，共 24 个且无重复。未运行 Go 测试、构建、Docker 或网络实验；本轮没有后台进程或测试产物，未提交、未推送。

## I5-I 实施范围记录（2026-09-26）

所有者在方案交付后要求“提交更改，继续推进下一步”；方案已提交为 `0065f03`，本轮开始 I5-I 代码与离线验收，不启动 I5-R、Docker、socket listener、设备或远程操作。

实施中的职责细化：新增 `internal/harness/network_bundle.go` 承载 schema 3 文件读写与比较，新增 `cmd/sw-v0-harness/process_runtime.go` 承载宿主准备、构建与批次资源管理；其余场景/控制职责保持原清单。候选范围由 24 个 Go 文件扩大为 26 个（11 个已有、15 个新增），仅按已有职责拆分，不扩大场景或接口。已有文件无必要时不制造形式性改动。

共享镜像归批次所有：样本 residuals 只清点其独占的三个容器、两网络和三个 volume；镜像 ID 仍绑定每份 manifest。批次结束后精确删除镜像，并写 `batch-result.json`；样本通过而镜像清理失败时批次必须 INVALID，不把仍被后续样本使用的镜像当样本残留。路由表摘要是保留的环境诊断，比较时仅对该随运行 IP 变化的摘要使用显式诊断别名；隔离断言依赖网络成员、接口和数字 IP probe，不能用摘要证明路由正确。

离线控制集成测试可以用真实 Node、三个独立临时 store 和受控字节流构造 schema 3 **校验器 fixture**，验证事实消费者与负例；fixture 的合同判定不是 Docker/TCP 运行结果，不发布为 I5-R evidence。真实 socket、容器挂载/权限和 daemon 行为继续等待 I5-R。

## I5-I 实施与离线验证结果（2026-09-26）

实际修改 4 个已有 Go 文件、新增 15 个 Go 文件、5 个 profile JSON、shell 入口及 Dockerfile；计划范围内其余已有文件无需改动，没有为凑清单制造差异。V2 观测/语义/文件职责分离，共享内部语义合同由各版本严格 decoder 构造；V0/schema 1 与 I4/schema 2 不接受 schema 3 作为旧数据。

实现包括：严格控制请求/响应和独立节点 actor；当前 generation 的单次发送机会；真实 TCP 接口的有界读写、半关闭/EOF 与邻接绑定；监督器逻辑时钟、入批/发送屏障、单向 gate 和 delivery 丢弃；schema 3 原始执行事实、来源核对、结果重算、文件校验及重复比较；独立 store/container/network 所有权、精确标签核对和残留查询。七个场景通过字节流驱动实际 Node 构造校验器 fixture，不是三个真实 OS 进程或 TCP 实验。

容器创建前先登记本批精确名称，命令返回不确定时保留未解析 inventory；清理只在重新核对名称、batch/sample/node 标签并取得实际 ID 后执行。外来标签拒绝删除，inspect 失败不当不存在。共享镜像由批次记录负责，样本资源与共享资源结果分别保存。预检检查本地 Docker endpoint、干净源树、五 profile 绑定、架构和磁盘；构建后复核源码 revision/dirty 状态。预检分支与 run 共用检查函数，不由 shell 维护第二套 profile 合同。

| 验证 | 实际结果与边界 |
| --- | --- |
| 拆分后的 V0/I4 回归 | harness 与命令包通过；I4 原有五 profile/七子用例共 21 个离线样本及三次比较仍通过 |
| 七个 I5 字节流场景 | 真实 Node、独立临时 store 与注入网络/进程接口通过；BASE 的三份独立 fixture 通过 V3 write/verify/compare；不登记为 I5-R PASS |
| 控制与发送拒绝 | 非规范/超长请求、未知操作、重复序号、错 session/epoch/generation、同刻批次、未消费发送前提交、响应短写、额外 frame/短帧/错误邻接均拒绝；提交后响应丢失不重放，拨号失败不退还机会 |
| 证据与分类 | 缺 ingress 来源、缺写出、改 generation、共享 store、非数字目标 probe、错 epoch/序号/摘要、伪造清理拒绝；重算 checksum 后的指标篡改仍拒绝；完整实现错误 fixture 为 FAIL，完整环境失败 fixture 为 INVALID，均可保存和验证 |
| 生命周期与预检 | 注入创建完成后超时，仍能凭精确名称和标签解析 ID 清理；拒绝外来标签删除；清理失败保留对象与错误。预检拒绝 dirty tree 和远程 Docker，测试未执行外部命令 |
| 格式与静态检查 | 范围内 Go 文件 gofmt；`bash -n scripts/run-sw-i5-harness.sh`、全量 `go vet ./...` 通过 |
| 全量离线回归 | 设置 GOTOOLCHAIN=local、GOPROXY=off、GOSUMDB=off 后，`go test -count=1 -timeout=120s ./...` 通过；最后一次完整回归命令包约 18.7 s，synthetic 包约 10.1 s；之后预检入口收敛的精准测试与全量 vet 再次通过 |

开发失败保留：多次 Go 编译/精准或全量测试因 `Library/Caches/go-build/...: operation not permitted` 退出 1，均保留失败并获准同命令离线复验；未换缓存目录、下载依赖或放宽测试。编译曾因错误调用 `CompareEvidenceRepeats`（实际为 CompareEvidenceRuns）与拆分后 unused strings import 退出 1，修复后通过。早期控制测试使用 TempDir 默认权限而未建立 0700 独占 store，I3 正确拒绝；测试已改为专属 0700 子目录。另一个测试错误地期待 1 ms 首槽立即发包，实际上初始 token 不足会消费该槽；已改为在 250 ms 的真实可发送槽验证发送屏障，I1/I3 行为未改。

本轮未执行 shell preflight/run、Docker build/create/start、socket listener、网络 probe 或 I5-R 矩阵；容器实际挂载、目录权限、daemon 启动时序、真实 TCP 与网络隔离仍需 I5-R 验收。自审及字节流 fixture 不替代这些入口。没有新依赖、CI、E2EE、射频、设备或远程变更；测试临时 store/bundle 按生命周期回收，既有 I3 短命 helper 已 Wait，Go cache 保留。方案提交为 `0065f03`，本轮新实现尚未提交。

最终仓库检查：`./scripts/check-repo.sh` 通过（171 文件）、`git diff --check` 通过；实际 19 个 Go 文件格式检查为空，五份 I5 JSON 保留单 LF 封装。所有新增/修改源码文件均低于 1000 行。工作区保留本轮实现和文档更改，`dev` 领先已知 `origin/dev` 6 个提交，未推送；没有本轮遗留后台进程。
