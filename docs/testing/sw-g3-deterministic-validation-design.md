# SW-G3 确定性故障与证据设计

- 状态：Accepted（`SW-G3`，2026-08-28）
- 文档版本：1.0
- 日期：2026-08-28
- 适用范围：D0/P0 Docker/Ethernet 三节点软件验证设计

## 目的与授权边界

本文冻结候选 profile schema、固定 seed、单变量故障、测试数值、指标、观察窗、证据目录以及 `PASS/FAIL/INVALID` 口径，使后续 `SW-G4` 能提交精确实现与运行授权。

本文不修改 `tools/t0/`，不授权实现故障代理、构建代码、运行容器或安装依赖。所有数值是已接受的 D0 测试参数，不是产品默认值、外场指标、HaLow 性能或量产承诺。改变这些参数必须提升 profile/schema 版本，不能为让失败用例通过而原地放宽。

本设计继承：

- [`SW-G1` 覆盖层消息交付语义](../protocol/message-delivery-semantics.md)的 message key、lifetime、hop budget、custody、delivery/read、去重、配额与崩溃恢复不变量；
- [三节点软件探索与验证规范](t0-p0-software-validation.md)的 A—B—C 隔离拓扑与证据边界；
- [`SW-G2` 决策包](../security/e2ee-sw-g2-decision-package.md)的密码候选和身份/投递停止线。

## SW-G3 评审记录

- 结论：Accepted；
- 日期：2026-08-28；
- 接受范围：profile schema、固定 seed、单变量故障矩阵、D0 数值、观察窗、指标、证据目录、敏感数据边界和 `PASS/FAIL/INVALID` 判定；
- 直接结果：可以进入 `SW-G4` 精确实现/运行授权包设计，不能直接修改 `tools/t0/` 或运行三节点场景；
- 保留边界：`SW-G2` 未通过前，`SW-V1/V2` 只能使用合成不透明载荷，`SW-V3` 继续暂停；
- 授权边界：本 gate 不授权代码实现、依赖安装、容器、VM、硬件、射频或真实数据操作。

## 测试层级与结论边界

| 层级 | 内容 | 允许结论 |
| --- | --- | --- |
| `SW-V0` | 拓扑、代理和证据系统自检 | harness 在记录条件下有效 |
| `SW-V1` | 延迟、丢失、限速、乱序、重复、断链与 hop budget | Docker/Ethernet 单故障消息路径满足已覆盖不变量 |
| `SW-V2` | 配额、存储、重启、时钟、未知输入和资源负例 | Docker/Ethernet 恢复与拒绝路径满足已覆盖不变量 |
| `SW-V3` | 选定 E2EE 候选后的篡改、重放、状态回滚和 B 可见性 | 只覆盖固定候选/版本/平台的三节点 E2EE 集成 |

`SW-V1/V2` 在 `SW-G2` 通过前只能使用明确标记的合成不透明载荷和合成认证占位，不得宣称 E2EE。任何一层通过都不能外推射频、距离、媒体、功耗、硬件、法规或生产安全。

## 固定拓扑与前置条件

每个有效 run 必须建立：

```text
A ── ab ── B ── bc ── C
```

- A 只连接 `ab`，C 只连接 `bc`，B 是唯一公共下一跳；
- A→C 与 C→A 直连探针必须失败，B→A 与 B→C 必须成功；
- 三节点使用同一代码 revision、manifest schema 和协议测试版本；
- 每个节点使用独立、只属于本轮的状态目录；
- fault proxy 位于逻辑邻接入口，不使用 `NET_ADMIN`、host network、系统防火墙或宿主时钟修改；
- 所有输入均为合成 A/B/C 标识；payload 日志只记录长度与 SHA-256，不记录正文；
- 拓扑自检、时钟注入自检、fault hit count 和 evidence 写入自检任一失败时，本轮为 `INVALID`，不得判为产品 `FAIL`。

## Profile schema

每个 profile 是版本化 JSON，schema version 初始为 `1`，至少包含：

| 字段 | 规则 |
| --- | --- |
| `profile_id` | 稳定 ID，例如 `SW-V1-LOSS-DATA-001` |
| `profile_version` | 从 `1` 开始；参数变化必须递增 |
| `seed_hex` | 固定 64-bit 十六进制字符串，不作为 JSON number |
| `topology` | 固定 `a-b-c-one-relay` |
| `payload_size_bytes` | 仅允许 `1`、`1024`、`16384`，资源批量 profile 另行明确 |
| `message_count` | 正整数且不超过本 profile 上限 |
| `lifetime_ms` | origin 首次创建起算，不因 retry/restart 重置 |
| `initial_hop_budget` | 默认 `2`；耗尽负例单独设置 |
| `fault` | 单一 fault kind、方向、触发事件和参数 |
| `retry` | 固定退避序列、最大尝试和停止 deadline |
| `observation_window_ms` | profile 允许的最长观察时间 |
| `expected_events` | 必须出现的状态与次数 |
| `forbidden_events` | 一旦出现立即 `FAIL` 的状态 |
| `evidence_schema_version` | 初始为 `1` |

未知 profile 主版本、未知 critical fault 字段、重复关键字段、负数、溢出或超上限参数在运行前拒绝，结果为 `INVALID`。已知主版本的未知 non-critical 字段只有在原样保存进 manifest 时才能忽略。

## 确定性与 seed 规则

- canonical base seed 固定为字符串 `0x524c535747330001`；
- 每个 profile 在下表固定自己的 seed，不从当前时间、PID、容器 ID、随机设备或宿主路径派生；
- 故障优先由“第 N 个语义事件”触发，只有延迟/观察窗使用单调时间；
- jitter 使用循环序列 `[0, 10, 30, 20, 40] ms`，不调用未记录 PRNG；
- reorder 固定把窗口内相邻第 1/2 个对象交换，窗口大小为 `2`；
- 每个 canonical profile 连续执行 `3` 个独立 run，保持相同 seed 和输入；归一化事件流移除 wall time、PID、容器 ID 和临时路径后，事件顺序与断言结果必须相同；
- 为诊断而使用不同 seed 必须创建新 profile ID 或 evidence variant，不能覆盖 canonical 结果。

## 通用测试参数

| 参数 | D0 接受值 | 说明 |
| --- | --- | --- |
| 普通 lifetime | `30000 ms` | 测试值，不是产品默认寿命 |
| 到期 profile lifetime | `2000 ms` | 由注入时钟推进，不等待宿主系统时间 |
| retry backoff | `250/500/1000/2000 ms` | 最多 4 次；deadline 更早时立即停止 |
| 单跳固定延迟 | `50 ms` | 每个方向分别施加，不与其他 fault 组合 |
| rate limit | `65536 B/s` | token bucket 初始 token 为 0，burst 上限 `16384 B` |
| test clock skew | `±300 s` | D0 接受窗口候选；`+301 s` 进入拒绝或 `TIME_UNCERTAIN` |
| tombstone replay margin | `10000 ms` | 使用注入时钟验证，不要求真实等待 |
| 正常队列上限 | `2048 messages / 32 MiB` | 仅供 1000-message profile，不能外推产品 |
| quota 负例上限 | `4 messages / 64 KiB` | 第 5 个 16 KiB message 必须显式拒绝 |
| 控制/receipt 上限 | `128 objects / 256 KiB` | 与 payload 队列分离且同样限速 |

### 观察窗

观察窗按单个子用例计算，三次 canonical run 各自独立计时。实现不得因为接近超时而自动延长；宿主明显过载、代理未命中或注入时钟失效时判为 `INVALID`，不能改判 `PASS`。

| 范围 | D0 接受观察窗 | 说明 |
| --- | --- | --- |
| `SW-V0-*` | `10000 ms` | harness 自检应快速闭合 |
| `SW-V1-*` | `30000 ms` | 包含 5 s 断链与固定 retry 序列 |
| `SW-V2-*`（除 flood） | `30000 ms` | 到期、clock fault 使用注入时钟，不等待真实时长 |
| `SW-V2-FLOOD-001` | `120000 ms` | 仅为 Docker/Ethernet 资源基线，不是性能承诺 |
| `SW-V3-*` | `60000 ms` | 候选接受后仍须在具体授权包中复核 |

## SW-V0：harness 自检

| Profile | Seed | 输入 | 通过条件 |
| --- | --- | --- | --- |
| `SW-V0-TOPOLOGY-001` | `0x524c535747330101` | 四个正/负连接探针 | A/C 直连双向失败，B 到两端成功 |
| `SW-V0-FAULT-HIT-001` | `0x524c535747330102` | 不进入产品状态机的 synthetic frame | 指定第 2 个对象只命中一次，未指定方向零命中 |
| `SW-V0-EVIDENCE-001` | `0x524c535747330103` | 一条 synthetic event | manifest、events、assertions、checksums 均可解析并互相引用 |
| `SW-V0-CLOCK-001` | `0x524c535747330104` | 注入时钟前进/回拨 | 单调测试时钟不回拨，wall clock 异常可观测且不修改宿主时间 |

`SW-V0` 未通过时，后续 run 一律 `INVALID`。

## SW-V1：单变量网络故障矩阵

除特别说明外，每项使用 1 KiB payload、1 条 message、30 s lifetime、hop budget 2；无终止性断链时必须在 30 s 观察窗内完成 destination delivery。

| Profile | Seed | 唯一 fault | 必须断言 |
| --- | --- | --- | --- |
| `SW-V1-BASE-001` | `0x524c535747330201` | 无 | A 入队、B custody、C 交付一次、A/B 验证 delivery 后释放 payload |
| `SW-V1-DELAY-001` | `0x524c535747330202` | 每跳/方向固定 50 ms | 状态顺序不变，时间线反映注入延迟 |
| `SW-V1-JITTER-001` | `0x524c535747330203` | 固定 jitter 序列 | 不提前确认、不重复交付 |
| `SW-V1-LOSS-DATA-001` | `0x524c535747330204` | 丢弃 B→C 第 1 次发送 | retry 复用 message key 与 lifetime，C 交付一次 |
| `SW-V1-LOSS-EVIDENCE-001` | `0x524c535747330205` | 丢弃 C→B 第 1 个 delivery evidence | duplicate 触发 C 幂等重发，用户交付仍为 1 |
| `SW-V1-DUP-AB-001` | `0x524c535747330206` | A→B 第 1 个对象复制 2 份 | B 只保存一个 payload，不延长 lifetime |
| `SW-V1-DUP-BC-001` | `0x524c535747330207` | B→C 第 1 个对象复制 2 份 | C 用户交付计数为 1 |
| `SW-V1-DUP-EVIDENCE-001` | `0x524c535747330208` | delivery evidence 复制 2 份 | A/B 终态幂等，不复活 payload |
| `SW-V1-REORDER-001` | `0x524c535747330209` | B→C 相邻对象窗口 2 交换 | 允许窗口内处理；窗口外显式拒绝，不静默扩大 |
| `SW-V1-RATE-001` | `0x524c53574733020a` | B→C 65536 B/s | 1 B、1 KiB、16 KiB 子用例均不绕过预算且最终交付一次 |
| `SW-V1-DOWN-BC-001` | `0x524c53574733020b` | B custody 后 `bc` 断开 5 s | B 重启前后保留责任，恢复后交付一次 |
| `SW-V1-DOWN-AB-001` | `0x524c53574733020c` | A 入队后 `ab` 断开 5 s | A 不误报 custody/delivery，恢复后同 key retry |
| `SW-V1-HOP-001` | `0x524c53574733020d` | initial hop budget 1 | B 不转发，C 零交付，到期后无 delivery evidence |

每种网络 fault 单独运行；组合断链、丢包加乱序或限速加重试不属于首轮 `SW-G3` 接受矩阵。

## SW-V2：资源、持久化与恢复矩阵

| Profile | Seed | 唯一 fault/输入 | 必须断言 |
| --- | --- | --- | --- |
| `SW-V2-QUOTA-001` | `0x524c535747330301` | B 上限 4×16 KiB，第 5 条进入 | 第 5 条 `REJECTED_QUOTA`，不返回 custody 成功 |
| `SW-V2-READONLY-001` | `0x524c535747330302` | B payload commit 前注入只读错误 | fail closed；A 保留责任；B 无 custody evidence |
| `SW-V2-FULL-001` | `0x524c535747330303` | C 安全/消息提交前注入 ENOSPC 等价错误 | 无 delivery evidence、无用户交付、状态不部分推进 |
| `SW-V2-CORRUPT-001` | `0x524c535747330304` | B 启动时状态 checksum 错误 | `QUARANTINED`，不转发、不确认 |
| `SW-V2-RESTART-A-001` | `0x524c535747330305` | A `QUEUED` 提交后重启 | 同 key/lifetime 恢复，不创建新用户消息 |
| `SW-V2-RESTART-B-001` | `0x524c535747330306` | B custody 提交后重启 | payload、deadline、去重和责任同时恢复 |
| `SW-V2-RESTART-C-001` | `0x524c535747330307` | C `COMMITTED` 后、evidence 发送前重启 | evidence 可幂等重建，用户交付不重复 |
| `SW-V2-CLOCK-FUTURE-001` | `0x524c535747330308` | originated-at 比接收端快 301 s | 拒绝新 custody 或 `TIME_UNCERTAIN`，deadline 不变晚 |
| `SW-V2-CLOCK-ROLLBACK-001` | `0x524c535747330309` | 接受后 wall clock 回拨 1 h | 使用保守 deadline，不恢复完整 lifetime |
| `SW-V2-EXPIRE-001` | `0x524c53574733030a` | 2 s lifetime 后注入时钟越过 deadline | 不再转发/交付，payload 清理且 tombstone 保留 10 s margin |
| `SW-V2-VERSION-001` | `0x524c53574733030b` | 未知主版本 | 高成本处理前 `REJECTED_UNSUPPORTED` |
| `SW-V2-LENGTH-001` | `0x524c53574733030c` | 密文长度 16385 B | 分配/落盘前有界拒绝 |
| `SW-V2-CONFLICT-001` | `0x524c53574733030d` | 同 key、不同 authenticator | 保留先到记录，后到 `REJECTED_CONFLICT` |
| `SW-V2-FLOOD-001` | `0x524c53574733030e` | 1000 个 1 KiB 唯一 ID | 队列/来源配额不超限，控制与 receipt 不饥饿，记录 p50/p95/p99 |

持久化 fault 还必须参数化遍历 `SW-G1` 的提交边界：origin 安全状态/消息入队、relay payload/deadline/去重、destination 接收安全状态/消息记录/去重 marker/evidence 状态。每个注入点是独立子用例；实现不得只选择“容易恢复”的一个点。

## SW-V3：E2EE 候选共用负例

`SW-G2` 接受候选及其 crash-safe 协调方式后，`SW-V3` 必须复用 `SW-V1/V2` 的相关 profile，并增加：

- 密文、不可变核心、credential、`KeyPackage`、`Welcome`、`Commit` 和 delivery evidence 的单字段篡改；
- 旧 epoch、已交付 message key、过期 key package 和撤销身份的重放；
- 安全状态写入前后崩溃及旧数据库回滚；
- A/C 同时建组、并发 commit、分区 fork 与恢复；
- B 可见字段、文件、日志和内存导出清单。

每个候选使用相同抽象 profile 和期望不变量，但保留库特定故障点；不得为某个库降低公共判定条件。精确 suite、credential、epoch 窗口与库故障点由 `SW-G2` 候选授权包补充，不在本文猜测。

## 指标与断言

所有有效 run 至少输出：

- 提交到 destination delivery evidence 的单调时延及 p50/p95/p99；
- custody、delivery、read、retry、duplicate、conflict、reject、expire、evict 次数；
- 用户交付次数、重复交付率和虚假 delivery 次数；
- 各节点 payload/tombstone/control 对象数与字节峰值；
- fault 计划次数、实际命中次数与首个命中事件；
- 重启前后状态 hash、deadline、remaining hop budget 与安全 epoch 的单向性；
- 退出码、观察窗、未完成对象和残留容器/网络/目录盘点。

首轮 correctness 硬门为：重复用户交付 `0`、虚假 delivery `0`、未验证 evidence 导致的 payload 释放 `0`、配额越界 `0`、deadline/hop/security state 变宽 `0`。时延分位数只作为 Docker/Ethernet 基线记录；除观察窗外不设产品性能 PASS 线。

## Evidence manifest 与目录

```text
artifacts/sw-v/<run-id>/
├── manifest.json
├── topology.json
├── profile.json
├── events.ndjson
├── metrics.json
├── assertions.json
├── residuals.json
├── checksums.sha256
└── logs/
    ├── a.log
    ├── b.log
    ├── c.log
    └── proxy.log
```

manifest schema 1 至少记录：evidence ID、run ID、Git revision/dirty、profile ID/version/hash、seed、开始/结束时间、host/daemon/container architecture、工具链、节点镜像 digest、测试二进制 hash、拓扑、输入规模、观察窗、退出码和结果。`checksums.sha256` 必须在其他证据写完后生成；缺少必需文件、checksum 不符或 manifest 与 profile 不一致时为 `INVALID`。

`events.ndjson` 使用节点单调时间与 run-relative sequence，不把 wall clock 当全局事件顺序。日志不得包含 plaintext、密钥、完整 credential、完整稳定身份、真实联系人、宿主绝对路径或精确位置。

## PASS / FAIL / INVALID

- **PASS**：前置自检有效，fault 按计划精确命中，所有 expected/forbidden assertion 满足，证据和 checksum 完整，残留复核完成；profile 的 3 个 canonical run 都必须 PASS。
- **FAIL**：环境与 fault 有效、证据完整，但实现违反任一不变量、超出观察窗或返回错误结果。任一有效 run FAIL，则该 profile FAIL；后续重跑成功不能抹去失败。
- **INVALID**：拓扑、fault injector、时钟、工具链、资源前提或证据链无效，不能判断产品实现。修复 harness 后可以新 run 重试，但必须保留原 INVALID 证据。

命令退出 0 只是必要条件。脚本打印 `PASS`、单元 mock、两节点结果或缺少负例均不能替代上述判定。

## 执行顺序与停止线

1. `SW-G3` 已接受；下一步由 `SW-G4` 提交精确实现文件、依赖、命令、Docker 外部状态、时长和清理授权；
2. `SW-G4` 获得明确授权后，先实现/验证 `SW-V0`，再逐项 `SW-V1`，然后 `SW-V2`；
3. 单故障 profile 全部稳定后，才能另行设计组合故障；
4. `SW-G2` 和候选运行授权通过后，才能执行 `SW-V3`；
5. 任一 FAIL 返回实现或设计根因，不增加 fallback、不延长窗口、不删除失败记录；
6. 任一 INVALID 先修 harness/环境，不能计入通过率。

## SW-G3 已接受检查项

2026-08-28 评审确认：

1. profile schema、固定 seed 与三次 canonical 重复足以复现；
2. 所有首轮 fault 都是单变量且能证明已命中；
3. 数值是 D0 测试参数，不冒充产品或无线指标；
4. `SW-G1` 的 lifetime、hop、custody、delivery、去重、配额和崩溃边界均有正负场景；
5. manifest、事件、指标、checksum、残留和敏感数据边界闭合；
6. `PASS/FAIL/INVALID` 不依赖重跑挑选结果；
7. `SW-G2` 未完成时不会误称 E2EE；
8. 本文不授权实现、容器运行、依赖安装、硬件或射频操作。

`SW-G3` 已接受，但不构成实现或运行授权。未经 `SW-G4` 明确授权，不得据此扩展 `tools/t0/` 或重跑三节点场景。
