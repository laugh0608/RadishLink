# Node 共享控制外发额度与责任轮转

- 日期：2026-10-28
- 范围：ADR 0007 D16 下的内部外发计费、责任轮转、数据 ACK 次数与显式迁移；L2 持久化/安全边界
- 授权：所有者要求提交上一批并继续下一步；业务政策批次已提交为 `62e0823`，本批完成离线实现、验证与文档，随后获所有者明确授权本地提交
- 面向：Node 状态拥有者、调度与恢复验证协作者；不替代真实签验、可信平台或传输验收

截至 2026-10-28 日终，当前实现已推进至 [schema v8 活动生命周期](node-activity-lifecycle.md)。本页版本、迁移与测试数字保留该批次时点；该批迁移须旧活动已停用，旧 session/动作隔离，不沿用本页早期版本可继续旧活动的行为。完整接续见[当天回顾](../status/2026-10-28-progress.md)。

## 交付与使用条件

在现有 Store/SQLite 原子事务内增加 `process_outbound_batch`，合并已有 queue/control 批处理与两类 ACK；旧批处理接口委托至该入口，没有新线程、服务、数据库、runner 或依赖。一次最多 128 个输入事件，同责任、同坐标的观察先合并；矛盾链路观察、错误坐标或业务权限拒绝使整笔失败，不返回部分发送结果。调用者只能提供已认证的内部事件，不能把该接口直接暴露给网络或手机。

| 边界 | 当前行为 |
| --- | --- |
| 共享总额度 | receipt、kind 2/3 对象、数据 ACK 和控制 ACK 共用既有 `control_output_rate`：4 frames/s、8192 bytes/s，各同值 burst；毫秒余额以整数计，第一次活动及同 boot 重开均空桶，不补停机额度 |
| 字节计费 | kind 2/3 按 522 bytes，ACK 按 127 bytes；既有内部 receipt 缓冲按 `max(522, body.len()+10)` 保守计完整 frame，最长现有 4096-byte buffer 收费 4106 bytes。内部 buffer 不是合法 COSE wire；未来严格编码仍须执行 512-byte COSE 上限 |
| 次数与失败 | 候选发送才检查/扣总额度，待机、重复、暂停及断链不扣；被限流的既有重试机会仍消费、不补发。额度、retry、ACK 次数及轮转位置在同一事务提交，失败/提交未知不返回发送许可 |
| 优先与轮转 | 有效已验证退出先于其他输出；退出责任内部轮转，receipt/报告/两类 ACK 在另一个共享序列中轮转。稳定责任键排序，从上次成功消费位置之后开始，末尾回绕；只在实际取得额度时移动游标，单次输入顺序不能抢占位置 |
| 数据路径 | 数据继续使用原 I1 RetryState 与调用方提供的 Admission，不扣控制桶；有界混合批次还处理数据事件。没有新加数据速率参数，也未证明物理链路公平或吞吐 |
| 数据 ACK | 仅已持久接收的消息可申请；中继已释放 payload、起点自己生成的消息及未知 key 均不建立 ACK 权限。仍检查活动、精确邻居凭据、政策和原消息 deadline；每消息最多四个 participant 槽，每槽最多十次，邻居换凭据不返还 |
| 去重与历史 | 同批重复 ACK 合并，跨批重复受共享桶及持久十次上限约束；ACK 不创建交付事实、不删除 payload、不返还业务重试。ACK marker 留在原消息记录中，不因证明清理或重开重置 |
| 有界维护 | 混合批次执行既有每类 256 条清理；原控制批处理/控制 ACK 包装入口因委托而同样推进清理，停止的 intent 可能已在随后显式 maintain 前清除；已交付历史不变 |

轮转只覆盖调用者在同一轮提供的责任集合，退出优先仍可能推迟普通控制；不保证有限重试内一定获得发送机会或送达。未来状态拥有者须公平枚举超过 128 个就绪责任，汇总同坐标的所有控制类型，并在进入本批次前处理已验证退出/本机封禁及剔除已失效输入。不得反复只提交一个偏爱的子集来声称实现全局公平。旧 `advance_queue` 单责任接口也执行 receipt 共享扣费及游标更新，不能绕过速率；它本身不能调度未提供的其他责任。

`send=true` 只是本次已持久消费的内部决定，既不是 socket 写结果，也不是一次性或可重放 token。真实交接仍须在同一串行拥有者内复查政策、时间、精确通道与当前责任；写失败/交接前撤销不能返还次数。批次中的任意错误不会放行其他项；未来输入层必须显式处理拒绝，不以吞错或重放成功决定恢复发送。

## schema v7 与兼容

`migration_v7.sql` 在已有 `messages` 中增加有界 `data_ack_budget`，在 `control_output_rate` 中增加两个有界轮转游标。ACK 状态最多四项、序列化上限 1024 bytes；游标各上限 512 bytes。它们分别属于原消息元数据与原固定辅助记录，不创建新可无限增长的表或提高配置额度。应用逻辑记录/预留不等于 SQLite 文件与索引页的硬空间上限。

新库初始化到 v7；普通 open 对 v1..v6 返回 `MigrationRequired`，由可信维护方按实际源版本调用 `migrate_v1/v2/v3/v4/v5/v6`。旧 SQL 未改，迁移在同一事务执行；错误源版本、重复迁移、损坏、时钟隔离及存储失败拒绝。v6 消息保留已有政策和业务/receipt 责任，数据 ACK 字段为 NULL，不凭空补建历史 ACK 预算，申请该类输出返回 `UnsupportedVersion`；新接纳消息从空 ACK 槽开始。更旧版本仍遵循 D15/政策迁移的输出隔离。

游标、ACK JSON 的结构/未知字段、四槽/十次、重复 participant 和绑定关联在重开/事务中检查。旧消息、已消费次数、原 retry 起点/时槽及活动截止均不重置。游标保留的历史责任键不要求责任仍存在，查找其后首个可用键并回绕；新活动生命周期仍未开放。

## 验证与限制

使用既有 macOS ARM64、Rust 1.97.1、本地缓存及合成临时库，无依赖下载或 manifest/lock 变化。新增 14 项调度测试（含子进程入口），覆盖四类混合控制的 4-frame 竞争、数据独立处理、8192-byte 拒绝、毫秒 refill、被限流 receipt 的 retry 消费、重复与非发送不计费、轮转顺序/跨重开延续、空桶、四 ACK 槽/十次及邻居换代不返还、未知/起点/失去 payload/撤销/到期拒绝、错误批次原子拒绝、v6 显式迁移/故障、损坏状态拒绝。受控进程在 COMMIT 前后退出，核对混合 receipt/控制/两类 ACK 计费、游标、retry 与 schema 同时提交或均不提交。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::outbound_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::data_tests::reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision -- --exact
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml -- --test-threads=1
./scripts/check-repo.sh
git diff --check
```

开发失败均保留：

| 阶段 / 退出码 | 结果与处置 |
| --- | --- |
| 最初全量，101 | 121/126 库测试通过；两项旧 schema 断言、两项旧 receipt 空桶假设及一项控制路径清理时点断言不匹配，按新版本/计费/委托行为修正 |
| 新定向首轮，101 | fixture 调错既有 submit/send 参数，编译失败；修正调用与逐笔安全状态修订，不修改产品入口 |
| 随后定向，101 | 5/7 通过；两项未建立既有 action scope，补齐正常准备流程 |
| 增强定向，0 | 当时 13 项通过；邻居换代不返还用例随后加入全量 |
| 首次 Clippy，101 | 一个 collapsible-if，按建议合并条件，未关闭 lint；复验退出 0 |
| 增强全量并行，101 | 138/140 通过；一处无关清理断言被批量替换误改，恢复为 1；D15 `reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision` 重开出现 `Busy: store owner lock`，根因未确认，精确单测复验退出 0 |

并行 Busy 是既有未定位锁风险的再次出现；串行通过不能证明该风险修复。没有添加锁重试、延时、吞错或关闭测试。最终串行全量退出 0：**140 项库测试 + 2 项 CLI 测试通过**；fmt、Clippy、仓库卫生与 diff 检查通过。这些条件不覆盖 Linux、物理掉电、真实密码/通道、跨进程公平或网络表现。

## 接续与停止线

本批随后提交为 `0a77399`；同日接续完成[入站限速与 16 对象验签等待](node-control-ingress.md)的自有有界准入。跨 boot 新活动、超 128 责任的真实枚举、签验结果与政策/通道绑定、实际发送交接仍分别待接入。许可证/R2/Phase B、G1/G2、可信平台、I5 与硬件/射频停止线保持。

本批未启动服务、网络、VM、设备或正式实验，没有依赖安装、系统配置、采购、push 或远程修改。受控测试进程正常退出或按故障测试结束；临时库由测试清理，忽略目录保留本批构建缓存和测试日志。

## 候选遍历接续（2026-11-02）

- 基线：D18 已按所有者要求提交为 `8573e88`，提交后工作区干净，dev 相对本地 origin/dev ahead 3，未 push。
- 范围：所有者要求继续下一步，完成[外发拥有者接线工作包](../architecture/node-outbound-owner.md)及首批只读候选遍历；沿用已有工具链、依赖和 schema v9，不改权限、wire、预算或历史迁移。
- 结论：可以从当前域/活动发现保留的 queue / kind 2/3 邻居责任；不是全局就绪调度、跨重启访问公平、真实工作池或传输验收。

`start_outbound_scan` 创建绑定运行者/域/活动的不可序列化位置；`scan_outbound_page` 通过稳定 keyset 与 LIMIT 返回至多 128 个引用，最多 1 个额外键判断尾页，不读出正文，不消费重试、令牌、修订或原成功消费游标。Exit、OrdinaryControl（receipt 后 report）和 Data 分开遍历；ACK 不从数据库补造。中途读取失败不推进位置，尾页 complete 后显式拒绝旧位置；新一轮重新开始，旧拥有者、旧活动与旧域位置拒绝。

所有查询仍受当前活动和时间停止线约束。业务只选择 policy_stopped=0 的当前域/活动责任，控制只选择当前活动非 terminal 的原始责任；具体就绪、权限和期限由原事务算法判断。页后发生政策变化时，原批处理继续拒绝旧准备，不把发现时 revision 当作授权。只读候选保留合法提交之间的遍历位置，插入在位置之前的键等待下一轮；这是实时集合遍历，不是冻结快照。

新增 8 项合成测试：130 条真实接纳并建立转发责任的多页遍历，分页之间仍用原事务调度到尾项；遍历位置前插入的新责任在下一轮可见；128 个 receipt 跨到零 ID 报告；退出/receipt/report/data 分组及不造 ACK；空集合和 terminal；其他 Store、同 boot 重开及同 boot 活动切换；D18 新域隔离/旧责任保留；发现后停止导致原事务整笔拒绝；receipt 已读而 control 查询失败时位置不前移。测试复用原合成准备 helper，不增加产品测试替身或旁路准入。

| 验证 / 退出码 | 实际结果 |
| --- | --- |
| 首轮定向 / 101 | 4/6；两项测试仅 receive 中继消息却未 schedule_forward，实际没有数据队列，返回空页符合合同。补齐原入口准备步骤，不放宽扫描或调度逻辑 |
| 扩展定向 / 0 | 8/8，通过完整分界与部分读失败矩阵 |
| 默认并行全量 / 0 | 207 项库测试 + 2 项 CLI 测试通过（库测试 145.29 秒）；包含新增同 boot 切换用例，未出现 owner lock Busy |
| 收尾定向 / 0 | 增强页间插入测试，并核对政策拒绝为 Conflict、读取故障为 StoreUnavailable；产品实现未再改变。8/8 通过（9.59 秒，outbound-scan-handoff.log），fmt 与 all-targets Clippy `-D warnings` 通过 |

日志保留在忽略目录 `.cache/node/2026-11-02/outbound-scan-*.log`，不删除首次失败。执行命令：

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::outbound_scan_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
./scripts/check-repo.sh
git diff --check
```

没有真实 worker、严格 CBOR/MLS、密码签验、socket 或输出许可接线。工作包已列明后续批次截点、工作量配额、ACK 来源、页间退出优先、交接复核和停止/Join；这些仍须各自实施与验证，不以 8 项内部测试声明全局公平成立。许可证/R2/Phase B、新图 G1/G2、可信平台与真实运行前置保持。本批更改留在工作区未提交，未 push，测试结束后无本任务后台进程；临时库由测试清理，原日志与构建缓存保留。

收尾仓库检查通过（319 文件），51 个本地 Markdown 锚点及 `git diff --check` 通过。manifest/lock、全部 SQL、根入口与原调度算法未变；Cargo.lock SHA-256 仍为 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24`。D18 的本地提交没有改写历史，也没有 fetch/push；dev 仍相对本地 origin/dev ahead 3。

上述交接后，所有者明确要求“提交新的工作区更改，然后继续推进下一步”，候选遍历批次据此本地提交；不包含 push。后续开发与验证单独记录，不用提交授权扩大真实运行范围。

## 同步拥有者周期接续（2026-11-02）

- 基线：候选遍历已提交为 `7ee3120`，提交后工作区干净，dev 相对本地 origin/dev ahead 4，未 push。所有者要求继续下一步，本批实施[工作包第二批](../architecture/node-outbound-owner.md#第二批已实施同步离线拥有者周期)的 Node 自有同步周期与合成验证。
- 结论：候选遍历、调用者已捕获的同坐标观察、显式 ACK 输入与原批处理共同构成一个有界同步步；没有真实输入队列、签验、工作池、网络或输出交接。
- 兼容：schema v9、manifest/lock、原 SQL、权限/限速/尝试次数、原 RetryState 与 Service/CLI 不变；不新增持久行、游标、配置或发送许可。

### 实际接线与失败语义

`start_outbound_cycle` 为当前拥有者建立两个不透明运行期位置。`process_outbound_cycle` 先检查当前 scope、expected_revision、可信 Clock、活动期限与 ACK 输入数，再重新读取完整退出集合、各取一份 Data / OrdinaryControl 工作页。每步最多 80 个退出责任、16 个数据候选、16 个普通控制候选和 16 个 ACK 输入，合计不超过原 128 个输入事件；80 来自原 D16 的 20×4 上界，其余只是内部工作量分配，不提高额度或宣称这些极限组合均已实测可达。退出源超过上界整步 StoreCorrupt，不先截断再发送普通工作。

调用者先处理本机控制和完整已验证结果，再提供已捕获、认证、合并的观察；回调必须有界、非阻塞且无外部效果，不能在其中等待签验或 I/O。所有候选必须显式给出同坐标 Batch，没有默认观察。ACK 由调用者显式供应，至多 16 个；超限拒绝，重复由原批处理合并，候选扫描不自动创建 ACK。准备完成后委托原 `process_outbound_batch` 的一次事务；空步委托 maintain。

内部暂存扫描位置，成功 COMMIT 后才发布进度和关闭本步时刻；任何 Err 不返回部分决定、不跳过候选，原错误/source 继续保留。提交结果未知沿原 Store 隔离，不自动重放。成功步之后，同一句柄不能用同一单调毫秒补交晚到输入；须等待更大的真实可信采样，不能伪造 +1。本机停止/封禁仍立即通过原事务执行，不受调度步关闭坐标限制。

周期之间重新读取完整退出集合并检查当前政策；旧 owner、同 boot 活动切换、冻结域及新域均拒绝旧周期。重开不恢复运行期输入或决定，持久 retry、ACK 次数和成功消费位置仍由原数据校验；空桶不补停机额度。该结果证明稳定集合的有界访问与内部优先关系，不证明全局发送公平、物理耗时、真实通道或有限尝试内送达。

### 实际验证

新增 13 项测试（含受控子进程入口）：130 条数据责任与 33 条 receipt 在每组 16 条工作片内到达尾项；退出、receipt、报告、数据、两类 ACK 混合竞争原控制桶而数据独立；17 个 ACK 整步拒绝、16 个重复只消费一次；旧 revision、错误观察坐标、关闭坐标、读失败/观察 Busy/事务写失败均不前移位置；通过原 16 槽任务完成路径提交合成已验证退出后下一步优先；到期清理、本机停止、空步维护和合并 Stop 优先；旧 Store/活动/域拒绝；损坏查询源伪造 81 个退出责任时拒绝而不截断；BeforeCommit / AfterCommit 未知；两次实际子进程分别在 COMMIT 两侧退出，重开核对原 retry、ACK、时钟一并生效或全部未生效，不恢复 ACK 输入。

只使用既有 macOS ARM64、Rust 1.97.1、本地缓存及合成临时数据库。故障进程由测试等待退出，不代表物理掉电或 Linux 测试。

| 验证 / 退出码 | 实际结果与处置 |
| --- | --- |
| 首轮编译 / 101 | 两项测试误把数组重复表达式写入模式，Rust 拒绝；改用字段绑定与等值 guard，未改产品逻辑 |
| 第二轮编译 / 101 | guard 从 Vec 索引移动非 Copy 决定，改为借用匹配；不为测试给产品决定增加 Copy/Clone |
| 扩展定向 / 0 | 13/13，12.74 秒，包含受控子进程及事务失败矩阵 |
| all-targets Clippy / 0 | `-D warnings` 通过，未抑制 lint |
| 默认并行全量 / 0 | **220 项库测试 + 2 项 CLI 测试通过**，库测试 152.64 秒，未出现 owner lock Busy；日志 outbound-cycle-full.log |

命令沿用本页入口，定向过滤为 `store::outbound_cycle`，最终全量不增加串行参数。开发失败日志与成功日志均保留在 `.cache/node/2026-11-02/outbound-cycle-*.log`，没有清理既有 evidence/cache。

收尾 fmt、仓库检查（322 文件）、55 个本地 Markdown 锚点及 `git diff --check` 通过。manifest/lock、全部 SQL、根入口、原 retry/外发算法及 Service/CLI 未变；Cargo.lock SHA-256 仍为 `b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24`。测试及故障子进程均已退出，临时库由测试清理，无本任务后台进程；日志与缓存保留。dev 相对本地 origin/dev ahead 4，本批未暂存/提交，未 fetch/push 或改变远程状态。生产 run 仍拒绝；许可证/R2/Phase B、新图 G1/G2、可信 boot/UTC、真实密码/设备/VM/网络及数据迁移停止线保持。

上述交接后，所有者明确要求提交工作区，再回顾当天提交、核对文档并单独作日终文档提交；同步周期本地提交据此授权，不包含 push 或继续新的实现工作。

同步周期随后已提交为 `c4ffb5b`。当天提交、代码与文档核对、最新接续及最终工作区状态统一见[11 月 2 日回顾](../status/2026-11-02-progress.md)，前述“未提交”保留各批交接时点，不表示当前仍未提交。

## 单次交接离线接续（2026-11-08）

按[单次交接设计](../architecture/node-outbound-owner.md#单次交接与撤销设计2026-11-08)复核了单批滞留、末次尝试与后到终结的区分、复核与合成写入的顺序。首批使用队首串行推进，以合成回调报告写入结果和关闭要求。没有新的持久行、配置、依赖或 Service/CLI 入口。

14 项定向用例覆盖五类提交后交接、无关 Store 提交、无绑定/否决/重复、原计费不变、提交前失败与提交未知、短写续写偏移、撤销后原通道关闭、同凭据重连、有效 custody 暂停、单调与 UTC 期限、最后一次控制机会、原始自身退出例外、写入失败和旧拥有者拒绝。下一批及旧队列调度入口在当前批未清空时返回 `Busy`。

仍需真实输入路由提供认证后的通道实例与终结事件。用例里的关闭是需关闭哪个实例的结果，完整写入是回调报告；实际通道关闭、字节所有权、可信时钟、端到端安全和 worker Join 未验证。

使用既有 Rust 1.97.1 工具链、离线锁定依赖和合成临时数据库。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::outbound_handoff_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml --quiet
```

增补重开负例时，定向测试退出 101。测试在重开后仅推进 1 ms，空桶无法发出新 ACK，测试对空项解包。改用原 4 frames/s 允许新 ACK 的最早 250 ms 补充间隔，保留生产限速。补充采集前引用长度检查时，同一命令首次退出 101，`E0599` 指出持久轮转位置仍需原责任校验入口。保留该入口，并让它与采集入口复用同一引用校验。

最终定向 14/14、默认并行全量 234 项库测试与 2 项 CLI 测试通过，库测试耗时 128.66 秒。fmt、Clippy、仓库检查和 `git diff --check` 通过。测试子进程均已退出，改动留在工作区，未暂存、提交或推送。

上述代码、用例和文档随后按所有者要求本地提交为 `494c671`。输入来源、实例及停止的接续设计见[拥有者输入与关闭评审](../architecture/node-outbound-owner.md#拥有者输入与关闭评审2026-11-08)。

## 晚到逐跳 ACK 终结离线接续（2026-11-08）

使用合成的已核验入站逐跳 ACK、可信采样和已登记通道，验证数据暂停与控制终结的原事务。首片只保留一条待提交终结，接纳时取消整批交接，有短写则指示关闭原实例。提交前或明确回滚后都阻止新调度，提交未知交由 Store 隔离。整个路径不返回待发 ACK，不退还已扣次数，数据 custody 仍保留唯一载荷及原交付状态。

五项定向用例覆盖同毫秒数据暂停冲突、短写旧实例撤回与重连、旧批 `Busy` 与控制末次机会、错误绑定/未知对象/旧实例拒绝、当前凭据变更、提交前失败和提交未知。已确认合成关闭结果及原终结的持久状态。实际通道关闭、可信采样来源、ACK 严格解码及认证仍待接线。

首次 `cargo fmt` 退出 1，新增测试模块文件当时尚未建立，补齐文件后重新格式化。首次 `cargo test --offline --locked --manifest-path node/Cargo.toml store::outbound_terminal_tests` 退出 101。未知提交用例的输入助手先读取已隔离 Store 的修订，导致辅助断言 panic。改为在注入故障前捕获调度输入，复验实际调度入口的拒绝。

最终用既有 Rust 1.97.1 工具链和锁定依赖离线验证，定向 5/5、默认并行全量 244 项库测试与 2 项 CLI 测试通过，库测试耗时 149.12 秒。fmt、Clippy `--all-targets -- -D warnings`、仓库检查和 `git diff --check` 均通过。测试进程已退出。接续代码和文档留在工作区，未暂存、提交或推送。

上述晚到终结代码、用例和文档随后按所有者要求本地提交为 `89815e5`。

## 待发 ACK 描述符离线接续（2026-11-08）

首片覆盖明确提交的 T-C 新接纳和具备原入站邻居责任的控制新接纳。两路共用 16 个运行期描述符及既有外发周期和计费，描述符绑定原入站实例。没有改变 schema、wire、持久额度、依赖或 Service/CLI。中继 T-B、可回 ACK 的合法重复和真正的入站解码/验权仍待各自评审。

七项新增用例覆盖错误实例或 relay 拒绝、旧视图/Known/Merged 拒绝造 ACK、控制原责任缺失、满 16 槽时第 17 条持久接纳保留、原共享速率和单次机会、截点前关闭/到期/issuer 撤销、交接后同凭据重连、明确回滚和提交未知。关闭与写入均使用离线结果，未实测传输。

既有 Rust 1.97.1 和锁定依赖下，离线定向 `store::outbound_ack_tests` 7/7 通过。默认并行全量 251 项库测试和 2 项 CLI 测试通过，库测试耗时 152.46 秒。fmt、Clippy `--all-targets -- -D warnings`、仓库检查和 `git diff --check` 均通过。测试进程已退出，新改动留在工作区，未暂存、提交或推送。

上述 ACK 描述符代码、用例和文档随后按所有者要求本地提交为 `ed0c8e2`。
