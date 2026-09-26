# SW-G4 合成验证准备：场景与证据接入单元 I4

- 状态：有限范围 Accepted；实施与离线验证通过
- 日期：2026-09-26
- 基线：`112f1e8`，I3 合成持久文字路径已提交
- 目标读者：场景、消息实现与证据复核者
- 目标：用实际 I3 调用结果生成可独立核对的版本化离线证据，贯通 profile → 场景执行 → 事实 → 断言 → 三次比较
- 非目标：正式 Docker/网络运行、完整 SW-V1/V2 矩阵、真实安全、生产格式或实体台架

## 推荐范围与证据层级

承接 [I3](sw-g4-synthetic-i3-plan.md)和 [SW-G3 修订草案](sw-g3-revision-2-review.md)。2026-09-26 所有者以“接受，继续推进吧”接受下述有限 schema、观测接口、13 个 Go 文件、5 个 profile fixture、离线验收与修复后复验；实施结果见文末。I4 的接受不等于接受整体 SW-G3 修订或正式运行。

执行模式固定 `execution_mode=offline-i3`、`security_mode=synthetic`、`variant=i3-small4-offline-v1`；三个真实文件目录、一个存活的逻辑时钟监督端、内存字节流，无 socket。新 profile 属于该 variant 的测试输入，不能交给 V0 runner。未来正式运行须另选执行 variant、补齐环境与命令合同，不得删去 offline 标记后复用结果。

本包新增的是测试输入/证据接口及 I3 的只读观测接口，属于 L2。I3 envelope/store v1、I1 重试算法、I2 限额和 V0 历史合同不变；不安装依赖、不修改 CI，不修改或重判旧 evidence。

## 实施前消费者核对与接入选择

| 当前入口 | 已核对事实 | I4 接入方式 |
| --- | --- | --- |
| `internal/harness/profile.go` | `DecodeProfile` 仅接受四个 V0 ID、profile/schema 1 | 保留原函数合同；增加独立的版本 2 类型与严格 decoder，未知版本拒绝，不给旧 `Profile` 添一组可忽略字段 |
| `internal/synthetic/node.go` | Submit/Step 提交后才返回；内部队列、预算与 B 的 body 回收不可从公开 Query 全部观察 | 增加有界只读快照和批次报告；不开放原始 store、可写队列或任意文件操作注入 |
| `synthetic → harness` | envelope 已引用 harness 的 I2 codec | 场景编排放在现有 `cmd/sw-v0-harness` 包，同时调用两者；harness 不反向 import synthetic，避免循环依赖和第二份 codec |
| `cmd/sw-v0-harness/main.go` | `canonicalEvidence` 生成 V0 自检事实；网络 endpoint/proxy 仍是 frame echo | V0 分支不改；新增同包场景函数供离线集成测试调用，不把 echo 当消息 Node，不新增可执行 subcommand |
| `internal/harness/evidence.go` | 校验 schema 1、6 份必需 JSON/NDJSON；失败断言统一算 INVALID；比较目录为 1/2/3 | 公用文件/校验和工具继续复用；顶层 manifest 明确分派 schema，版本 2 独立校验结果、metrics 与事实引用 |
| `internal/harness/clock.go` / `proxy.go` | 有注入时钟、按方向计数的确定性代理 | 时钟单调推进；drop 先按 kind 筛选，再用既有代理计数，不能把 custody 算成首个 delivery；down/up 由确定屏障注入 |
| `scripts/run-sw-v0-harness.sh` | V0 Docker 生命周期、固定四 profile/hash、清理与汇总 | 本包不修改、不运行；正式网络控制面和资源治理另案 |

现有 `flow_test.go` 会在看到输出后登记 oracle。I4 必须先从固定输入独立构造允许的 key、核心、frame 摘要及用途集合；不能按运行时收到的任意 frame 动态授予接受，否则错误输出也可能被测试驱动器认可。独立固定向量与错误用途负例继续保留。

## 有限 profile schema 2

JSON 值使用显式 struct，固定字段顺序、紧凑编码，无尾部换行，所有字段必填且不允许 null。仓库与 bundle 中的 JSON 文件采用“规范值 + 单个 LF”的文件封装，满足 `.editorconfig`；loader 仅移除这个 LF 后调用值 decoder，重复 LF、额外空白仍拒绝，文件 hash 包含 LF。先以 64 KiB 上限读入，拒绝未知/重复/大小写别名字段、缺失、尾随值、整数非规范表示，再重编码逐字节核对。拒绝返回零对象；没有透传字段或默认补值。此规范编码仅用于合成测试。

| 顶层字段（依次） | 约束 |
| --- | --- |
| `schema_version` / `evidence_schema_version` | 均为 2；与 envelope/store v1 独立 |
| `profile_id` / `profile_version` / `seed_hex` | 仅下表五项；seed 固定小写 `0x` 加 16 位 hex |
| `variant` / `execution_mode` / `security_mode` | 上述三个固定值 |
| `topology` | `a-b-c-one-relay`，表示内存传输图，不证明主机网络隔离 |
| `envelope_version` / `store_version` / `limits_id` | 1 / 1 / `i3-small4-v1`；限额引用 I3 固定配置，不复制可覆盖参数 |
| `message_count` / `lifetime_ms` / `initial_hop_budget` | 1 / 30000 / 2 |
| `observation_window_ms` / `transport_delay_ms` | 30000 / 50；本 variant 每方向固定 50 ms，属于显式基线条件，不隐藏为第二个随机故障 |
| `retry` | 有序字段 `backoff_ms=[250,500,1000,2000]`、`timed_max_attempts=5`、`recovery_max_attempts=1`、`deadline_ms=30000` |
| `fault` | 有序字段 `kind`、`direction`、`trigger`、`index`、`duration_ms`，取值由下表固定，无自由 map |
| `subcases` | 有序数组，每项仅 `subcase_id`、`payload_size_bytes`；BASE 为 p1/p1024/p16384，其余仅 p1024，顺序固定 |

| Profile ID | Version / seed | fault 固定值（kind / direction / trigger / index / duration_ms） |
| --- | --- | --- |
| `SW-V1-BASE-001` | 2 / `0x524c535747330201` | none / none / none / 0 / 0 |
| `SW-V1-LOSS-EVIDENCE-001` | 2 / `0x524c535747330205` | drop / c-to-b / delivery-frame / 1 / 0 |
| `SW-V1-LOSS-EVIDENCE-BA-001` | 1 / `0x524c53574733020e` | drop / b-to-a / delivery-frame / 1 / 0 |
| `SW-V1-DOWN-BC-001` | 2 / `0x524c53574733020b` | down / b-to-c / custody-commit-before-forward / 1 / 5000 |
| `SW-V1-DOWN-AB-001` | 2 / `0x524c53574733020c` | down / a-to-b / origin-commit-before-send / 1 / 5000 |

旧 ID 的 version 2 明确采用修订重试、I3 小容量与更大 burst；seed 保持原值。新增 BA ID 使用修订包预留 seed。所有 profile 还须匹配 variant，不能与原 SW-G3 正常容量或其他运行模式比较。期望断言由版本化 validator 固定生成，不接受输入提供的成功布尔值或任意 expected 列表。

本包共 7 个子用例，每个 3 次独立目录执行，共 21 个离线样本。length 拒绝、quota 第五条、重启、满盘、损坏、重放、flood 等仍由 I1/I2/I3 的单元证据覆盖，**尚未接成这些正式 profile**。特别是 A 最多 4 个本地动作，不能直接用该入口发送第 5 条来声称测到 B quota；1000-message 更不能套入 I3。

## I3 观测合同与事实来源

不修改 envelope/store 格式，不把 observer 作为事务第二份持久日志。实施接口：

- `Snapshot()`：在 Node 锁内读取已发布状态，返回值副本；halted 时返回原有不确定结果错误，不输出候选态。包含 node、generation、now、每条消息的 key/核心摘要/deadline/状态、history/transport/body 字节计费标记、tombstone、合成收发计数，以及每队列 kind/neighbor/start/deadline/hops/status、已消费定时与恢复额度、bucket 余额/最后时刻及资源计费。数组有界，不返回 payload、原始动作内容或可修改引用。
- `StepWithReport(Batch)`：与现有 Step 共用唯一私有实现；Step 保持原签名及行为。返回原 transmissions、报告及 error。报告只在成功文件提交后标明 `committed=true`、前后 generation、实际队列决定及原因、尝试/Send、missed slots、预算前后值、quota cost 与事实变化。失败时不发布候选报告；已到期清理独立提交后拒绝输入时，报告明确只含 expiry 事务。
- Submit 不复制第二条实现路径：驱动器读取调用前后 Snapshot，并检查返回值与 generation、动作绑定及计数的变化。重复 Submit 不生成新的 origin commit。Snapshot 不消费额度，报告丢失不允许重新发送。

调度报告的 `Send` 只表示已持久消费的发送决定。`frame_written` 必须来自 `Transmission.Write` 完整成功；`frame_received` 必须来自 `ReadInput` 成功且确实进入目标 Step。目的 history、A delivered 和 B body 清理必须分别由相应已提交快照变化证明；不得从预期场景、单个返回码或代理转发推断。

观测版本记 `observation_version=1`，仅为 I4 接口/证据合同。变更其字段语义须提升版本或证据版本；不序列化 I1 私有字段，不提供修改队列、补发、清空预算或跨 scope 的接口。

## 确定性场景驱动

1. 每个子用例独立 Init A/B/C 三目录，固定合成 run、epoch、scope、message ID 和 payload 向量；监督端保存每节点确认 generation 下限。一个三次比较批次共用这些 fixture 值，目录和 Node 对象独立；跨比较批次不得导入旧状态。固定 seed 是输入标识，本包不使用 PRNG。
2. 复用 TestClock，只跳到下一次实际输入、计划槽、down/up 或 deadline。同一时刻先收齐各节点输入，按 A/B/C 固定顺序各调用一次；队列排序沿用 I3。新建队列在当前 Step 中结算，不能同刻补调第二次 Step；A 在 now=0 Submit 后首次 Step 为 1 ms，明确记录为首次槽迟到 1 ms。
3. 每次 Step 后立即在相同时刻调用返回的 Write；通过 I2 字节流后进入传输图。故障 drop 在完整写出、进入接收前发生，命中点记录 direction/kind/key/序号/摘要；没有命中的对象不算故障成功。所有接收统一在 now+50 ms 排入目标批次，不使用宿主 sleep。
4. AB down 屏障在 A Submit 成功后、首次 Step(1) 之前；BC down 在首次接收 A 数据的 B 批次中一并传入对应 link-down，使 T-B 与首次转发决定按已接受 I3 次序处理。down 起点为实际屏障时刻，up 固定为起点+5000；只注入一次，无重启、随机丢包或反复抖动。T-B 屏障须在 origin 后 1000 ms 内出现。
5. 观察至 30000 ms，最后只做合法到期结算与快照。报告需保留到期前的返回责任事实：不能因为终点队列已 expired 而遗漏 B 清理 body 后曾保留 delivery 责任。不能看到 A delivered 就提前结束并漏检后续重复交付。
6. 每队列仍受 I3 的 64 批次上限；不按每毫秒轮询来触发该上限。单子用例最多 512 个调度时刻、8192 个事件、128 个待接收 frame，超过即停止并保存原因，不能截断后 PASS。

固定输入为 run_id=32 个 `1`、clock_epoch=32 个 `2`、message_id=32 个 `3`、scope=`i4-small4`、action_ref=`one`，payload 为所选长度个 ASCII `x`，originated=0。oracle 预登记仅允许该核心对应的 AB/BC data 和固定 custody/delivery 路径及用途，完整 frame 摘要按 I3 v1 字段合同独立编码计算；其他输入默认拒绝。fixture 是公开合成标识，不是凭据。不同目录隔离三次样本，不能把同一 Node 复用三次当成重复实验。

驱动器只负责时钟、输入与记录，不实现另一份消息转发、重试或持久化状态机。现有 `flow_test.go` 可保留为 I3 回归；I4 的重复比较必须调用新增的同一场景函数，不能复制测试里的 world 后再用编造事件交给 finalizer。

## Evidence schema 2

沿用现有 bundle 文件结构及安全路径/校验和工具，增加 `metrics.json`。精确清单为 `profile.json`、`manifest.json`、`topology.json`、`events.ndjson`、`metrics.json`、`assertions.json`、`residuals.json`、`checksums.sha256` 和空 `logs/`。I4 不收集日志正文，不导出 payload/store 文件，不写容器占位值。未知文件、symlink、缺失字段/文件和跨版本混合拒绝。

每份 JSON 使用明确的版本 2 类型；所有整数字段使用有界 int64，序号从 1 连续递增，时间范围 0..30000。JSON/事件行也采用严格规范编码；NDJSON 每行单对象加 LF，无空行，每行最多 16 KiB。单文件最多 4 MiB，单 bundle 共最多 8 MiB，写入前计数，不能等写满后才判断。

| 文件 | 完整内容类别与固定约束 |
| --- | --- |
| `profile.json` | 上述完整原始规范 profile，hash 纳入 manifest；subcase 参数必须来自该 profile |
| `manifest.json` | schema_version=2、observation_version=1；batch_id/run_id/evidence_id、repeat=1..3；profile_id/version/sha256、seed_hex、variant、subcase_id、execution_mode、security_mode；git_revision（40/64 hex）、git_dirty、binary_sha256、go_version、host_os/architecture；started_at/ended_at（UTC）；topology、payload_size_bytes、message_count、observation_window_ms；exit_code、result、normalized_events_sha256。run_id 为单样本 ID，batch_id 绑定三次比较，不进入 envelope；无 daemon/container/image 字段 |
| `topology.json` | schema_version、execution_mode、topology；固定 edges=[A→B,B→A,B→C,C→B]，denied_edges=[A→C,C→A]；check 记录为传输图路由拒绝事实，明确不是网络 probe；引用自检事件 sequence |
| `events.ndjson` | 每行 schema_version、sequence、monotonic_ms、node、kind、message_key（无消息则 null）、generation_before/after、cause_sequence（无因则 0）、detail；detail 为按 kind 区分的显式结构，禁止自由 attributes map、成功占位或真实内容 |
| `metrics.json` | schema_version；source_event_count；origin_commits、custody_commits、destination_commits、delivery_accepts_a/b、body_releases_b、data/control_attempts、data/control_frames、duplicate_receives、rejects、expiries、fault_hits；各 Node 的 payload/history/control 对象和字节峰值；delivery_latency_ms 数组及 sample_count。单消息不输出伪精确 p50/p95/p99，不把逻辑延迟描述为宿主性能 |
| `assertions.json` | schema_version；固定断言列表，每项 id、category（environment/implementation）、passed、source_sequences、reason_code；来源序号不得为空或指向其他子用例，期望缺失时引用观察窗结束记录；禁止随意省略失败断言 |
| `residuals.json` | schema_version；inventory_complete；owned_store_count=3、removed_store_count、pending_frame_count、active_child_count=0、cleanup_complete；临时目录只用逻辑编号，不记录宿主绝对路径。I3 没有常驻文件句柄，完成观察后释放 Node 引用、精确清理三个 store 并核实不存在，才递增 removed_store_count。证据目录为有意保留的产物，不计成未清理 store |

事件种类及 detail 合同：

| kind | detail 内容 / 真实产生位置 |
| --- | --- |
| `environment_check` | check_id、passed、reason_code；驱动器路由/clock/记录器自检结果 |
| `submit_result` / `batch_result` | operation、error_code、committed、transaction_kinds、input_count；实际调用完成后记录，提交区间须与快照一致 |
| `verdict_decision` | receiver、neighbor、frame_sha256、purpose、verdict；来自预登记 oracle 的实际调用，message_key 在公共字段中。接受判定本身不代表事务提交，须关联后续 batch_result 与快照 |
| `state_observed` | 完整上述有界 Snapshot，不含正文；初态、每次提交后和观察结束各记录 |
| `retry_decision` | queue_kind、neighbor、start/deadline、reason、attempt、send、missed_slots、timed_before/after、recovery_before/after、wire_cost、global/neighbor_credit_before/after；仅来自已提交批次报告 |
| `frame_written` / `frame_received` | direction、kind、core_sha256、frame_sha256、wire_bytes、send_sequence；分别来自 Write/ReadInput，接收关联真实写出序号 |
| `fault_transition` | direction、trigger、action=drop/down/up、matched_sequence、hit_index；down/up 共一个故障周期，命中计数只增一次 |
| `observation_end` | now=30000、remaining_messages、pending_frames、reason_code；不足观察窗则不可报告正常结束 |

非预期错误导致提前停止时使用 `execution_aborted`，detail 为实际 now、stage、error_code、reason_code；保留已有事实与清理结果，不伪造 now=30000。validator 将证据结构/关联错误与被测实现不变量分开：自洽地记录了重复交付等实现错误的完整 trace 应得 FAIL，而不是因不满足产品断言直接当成无法解析；伪造/缺失来源或与事件不符的指标才拒绝证据。

message_key 使用 I3 Key 的四字段；frame 摘要仅用于合成一致性检查。原始 run/epoch、message ID 使用固定 fixture，因此三次事件可直接比较；批次/样本运行标识和宿主元数据只在 manifest，不需要通过删除业务字段来凑一致。事件不写 wall time、PID、容器 ID 或临时路径，因此版本 2 归一化仅做严格解码/规范编码，不删除消息身份、generation、deadline、预算、拒绝原因或 fault。

## 独立核对、失败与重复比较

validator 先检查格式、版本、文件清单与 checksum，再按 profile/subcase 对事件做关联核对并重算 metrics/assertions/result。校验和只发现文件不一致，不是证明真实执行的签名；人工/测试伪造完全自洽数据仍非可信硬件证据。至少核对：

- 每节点 generation 从 Init 的 0 连续推进；无提交时不得出现新增消息/终态/额度；报告与对应前后快照相符，state_observed 不可自行宣告送达。
- A origin 唯一、B custody 唯一、C history/receive counter 恰为 1；A delivered 必须能追溯经 B 返回的 delivery 接收及实际合成判定；B body 清理必须与其接收 C delivery、终态和返回责任在同次提交。
- 每次发送关联已提交 Send 决定和完整 Write；每次接收关联同 key/摘要的允许方向写出，命中 drop 的帧不得再接收；未知邻接或没有发送来源的接收拒绝。
- 定时至多 5、恢复至多 1；控制/数据分别核对，missed/blocked 也消费预算；wire cost=body+4，不超 token/资源配置。未到期字段不得变宽，deadline 后不产生新的写出/用户交付。
- 独立返回责任在 data 清理后仍保留，所有重复不增加 history、action 或重置起点。观察结束、资源清理事实与 manifest 时间/退出码一致。

| 结果 | 定义 |
| --- | --- |
| PASS | 环境有效、指定故障精确命中、实现断言全部满足、证据完整且清理完成；只记 offline-i3 PASS |
| FAIL | 环境有效且有足够证据时，实际实现违反断言、合法输入报错或未在观察窗完成。驱动器有效但实现根本未产生应有触发对象时，同样是实现 FAIL，不能借“fault 未命中”掩盖 |
| INVALID | 路由/clock/记录器自检、注入设施或证据完整性失败；若有效触发帧已出现但代理没有按计划命中，是 injector INVALID。同时观察到的实现失败仍须保留，不能覆盖为成功 |

编码/版本或文件结构被破坏时，校验器直接拒绝 bundle；不生成补齐后的 PASS 证据。可解析但断言失败的完整 bundle 保留 FAIL/INVALID 原因。命令层预留退出码 0=PASS、1=FAIL、2=INVALID；I4 暂无运行 CLI，不改变旧 V0 的退出码合同。

三次比较按 `(profile schema, evidence schema, observation version, profile ID/version, seed, variant, subcase, mode, limits, git revision, binary hash)` 分组；同 batch、repeat 恰为 1/2/3、独立 run_id。先逐个验证，再比较完整规范事件、重算 metrics 与断言。混入 V0、换 payload、不同源版本/二进制或少一次均拒绝；三份相同的失败不能算 PASS。不删错因、不调换事件顺序，不覆盖失败目录或自动进行第四次运行。

## 已接受的精确实施与验证包

| 文件 | 改动 |
| --- | --- |
| `tools/t0/internal/harness/profile_v2.go`、`profile_v2_test.go`（新增） | 有限 schema 2 类型、五 profile 七子用例校验、独立固定向量及拒绝 |
| `tools/t0/internal/harness/evidence_v2.go`、`evidence_v2_test.go`（新增） | 版本 2 写入、事实核对、指标/断言重算及比较，复用现有文件安全工具 |
| `tools/t0/internal/harness/evidence.go`、`evidence_test.go`（修改） | Verify/Finalize/Compare 按 manifest schema 严格分派；V0 路径与旧 NormalizeEvents 不变，覆盖跨版本拒绝 |
| `tools/t0/internal/synthetic/observe.go`、`observe_test.go`（新增） | 只读快照/报告类型，资源与预算事实，不引入持久 observer |
| `tools/t0/internal/synthetic/node.go`、`node_test.go`、`state.go`（修改） | Step 单实现与报告收集，失败/expiry/句柄行为兼容；预算观测复用现有 replay |
| `tools/t0/cmd/sw-v0-harness/scenario.go`、`scenario_test.go`（新增） | 同包编排与离线集成验收，调用实际 I3、clock/proxy/evidence；不改 main.go 命令分支 |
| `tools/t0/profiles/i4/` 下五文件（新增） | `sw-v1-base-001.json`、`sw-v1-loss-evidence-001.json`、`sw-v1-loss-evidence-ba-001.json`、`sw-v1-down-bc-001.json`、`sw-v1-down-ab-001.json`，仅供该离线 variant |

合计 13 个 Go 文件、5 个 JSON；文档同步本文、SW-G3 修订草案、文字切片、current、两份计划及索引。禁止修改 I1/I2、store.go、旧四 profile、SW-G3 1.0、V0 shell、go.mod/lockfile、密码依赖或历史 evidence。职责确需超出该清单时先报告，不能用 schema 2 名义顺带改完整矩阵。

必需验收包括：上述 21 个实际离线路径样本的三次比较；只读快照不共享内存、不改变 generation；报告不暴露失败候选或重放 Send；原有 I3/旧 V0 回归；未知/混合版本、profile/subcase/seed/limits 错配；删除提交/发送事件、篡改计数/额度/释放正文时刻、伪造接收来源、重复/跳跃 generation；这些篡改即使重算 checksums 仍必须拒绝。另用完整失败 trace 验证实现 FAIL 与设施 INVALID，不能只测试 success bundle 的 hash。

已接受并执行：13 个范围内 Go 文件 `gofmt -w`；module 内下列离线命令，以及失败修复后的同范围复验：

```bash
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./internal/synthetic ./internal/harness ./cmd/sw-v0-harness
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go vet ./...
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./...
```

21 样本在单元测试临时目录串行生成，同一子用例三份 bundle 比较后清理；单时刻活动临时数据上限 128 MiB。禁止 t.Parallel 扩大文件测试并发；新场景无子进程，既有 I3 回归仍仅执行其 48 个受控短命 helper 并 Wait。不得构建或启动 Docker、socket、长期服务、GUI、密码依赖或访问真实设备。保留 Go cache；沙盒缓存拒绝保留失败并申请同命令复验，不借提权安装依赖。

正式运行包仍缺：消息 Node 的进程/传输入口、网络 topology 和屏障协议、节点间逻辑时钟/故障收集、精确镜像/命令/次数/资源清理与授权。I4 不把内存路由图自检替代网络隔离，不把三次离线比较登记为 SW-V1/V2 正式结果。完成 I4 后才能据其实际接口编制该包。

## 设计轮记录

I3 已提交为 `112f1e8`，设计轮只静态读取既有实现与合同，形成上述消费者、版本、事实来源、判定和离线实施范围；未创建新源码、JSON 或 evidence，未运行 Go、Docker、网络场景。设计自审由编写 Agent 完成，不是独立评审。

设计轮待确认、现已获所有者接受的实质选择：先落地 offline-i3 variant；只接五 profile 七子用例；有限 schema 2 与观测 v1；以真实事务/发送事实驱动证据及三次比较。接受不改变安全、许可证、RF、硬件和正式运行停止线。

设计轮验证：`./scripts/check-repo.sh` 通过（135 文件），`git diff --check` 通过，七份变更文档的 130 个相对链接目标存在。静态复核明确了 import 方向、V0 分派兼容、四动作容量限制、事务事实与发送事实的区别、oracle 预登记及 FAIL/INVALID 分类。检查只证明文档和仓库约束，不证明尚未实施的 schema/validator/场景成立。


## 2026-09-26 实施与验证记录

范围内 13 个 Go 文件与 5 个 profile JSON 已完成。保留 `DecodeProfile` 和 V0 命令分支原合同，Verify/Finalize/Compare 在严格读取 manifest 主版本后分派；I4 没有新 CLI、socket、Docker 或外部依赖。

观测 DTO 由 harness 的版本 2 证据合同持有，synthetic 在既有单向依赖上返回该类型；`observe.go` 负责从已发布状态生成副本及 BatchReport。这样证据校验不依赖 synthetic，不复制消息状态机，也不制造循环 import。StepWithReport 和旧 Step 共用同一执行实现；文件失败不发布候选报告，独立 expiry 提交与调度上限错误有各自准确的事务标记。

场景驱动用 profile 固定向量预登记 oracle，调用真实 I3、I2、TestClock 与 drop proxy，分别记录判定、提交、发送、接收、故障和结束事实。校验器独立计算定时槽、恢复次数、整数 token 变化和资源账本，核对 generation、输入/判定/发送因果和释放责任；不把一致性摘要当认证。snapshot 不输出正文。三次比较同时绑定源码 revision、测试二进制 hash、profile/subcase 与 variant，并拒绝第四个目录、缺失或重复样本。

| 已执行验证 | 实际结果 |
| --- | --- |
| 五 profile / 七子用例 | 每个在三个独立临时 store/bundle 目录执行，21 个样本均为 offline-i3 PASS，七组三次比较一致；每次完整集成测试遍历均执行这一矩阵 |
| 观测兼容与失败 | Snapshot 副本修改不影响 Node 或 generation；重开保留已消费预算、不重放 Send；提交前/后错误不发布候选报告；坏输入伴随 expiry 与 65 批次 schedule_limit 报告正确 |
| profile/事件/manifest 拒绝 | 未知/混合版本、重复/缺失/null/别名字段、非规范表示、超限/超深输入、错 seed/variant/limits/subcase、时间/序号/因果边界均覆盖 |
| 事实及派生文件负例 | 删除提交/发送、伪造发送来源/判定用途、修改 generation/额度/正文回收/接收计数、事务类型、队列状态或 hop 不能获得 PASS；事件、metrics、assertions 被改写并重算 hashes 后仍被校验器拒绝 |
| 结果分类与比较 | 完整实现错误 trace 产生 FAIL；环境自检失败产生 INVALID；两种 bundle 均可完整保存和验证，不改写为 PASS。二进制不一致、部分结果、第四份结果、symlink/额外文件及缺 checksum 均拒绝 |
| 格式化与精准验证 | 范围内 13 文件 gofmt；包级 `go test -count=1 -timeout=120s ./internal/synthetic ./internal/harness ./cmd/sw-v0-harness` 通过，最终场景测试约 14 s |
| 全量验证 | `go vet ./...` 与 `go test -count=1 -timeout=120s ./...` 在设置 GOTOOLCHAIN=local、GOPROXY=off、GOSUMDB=off 后通过；最终复验场景包约 14.2 s，既有 synthetic 恢复测试亦通过 |

开发失败保留：一次从 module 目录执行带 `tools/t0/` 前缀的追加/编辑命令，报 `no such file or directory` / `FileNotFoundError`，没有写入目标；已改为仓库根目录执行。首次精准测试退出 1，因 `Library/Caches/go-build/...: operation not permitted` 被沙盒阻断；获准同离线命令复验后暴露 `state.go:133:33: not enough return values`（退出 1），系扩展重放计数返回值时遗漏拒绝分支，修复后精准测试及追加负例回归通过。没有改缓存路径、下载工具链、放宽测试或删除失败记录。最后全量 vet/test 在沙盒内通过，不将早期缓存失败抹去。

仓库检查通过（148 文件）、`git diff --check` 通过；七份文档的 130 个相对链接目标存在，5 个 JSON 文件语法与单 LF 封装检查通过。证据文件上限、空日志目录、精确清理和记录器拒绝截断均有验证；本轮临时 store/bundle 已按测试生命周期清理，I3 短命子进程回收，Go cache 保留。测试 evidence 使用实际当前 revision/测试二进制 hash，并保守标记 dirty；没有将临时样本发布为正式 evidence。

`evidence_v2.go` 已超过 1000 行，静态复核其固定 DTO、事实校验与文件消费者职责后，本轮保留在已接受文件范围内且低于 1500 行；扩展矩阵前应按这些职责拆分，避免继续堆叠场景特例。当前结论只覆盖七个有限离线子用例及所列拒绝路径，不是独立审计或完整 SW-G3 矩阵。

下一工作包应基于实际 I4 接口设计消息进程/传输入口、监督时钟与事件屏障、三节点网络拓扑和证据收集，再形成精确实现与运行范围。该包尚未形成；本轮不启动正式 V1/V2 网络运行，不扩大现有 E2EE、许可证、HW/RF 授权。
