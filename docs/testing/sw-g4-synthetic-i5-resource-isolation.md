# I5 整批资源隔离设计与运行停止检查

- 日期：2026-10-01
- 状态：所有者已选择保留整批 768 MiB；证据写前计费已接入，隔离环境与构建接入未完成，I5-R 禁止启动
- 目标读者：I5 实现、运行环境准备及证据复核者
- 用途：关闭构建及运行写入绕过批次计费的问题，给出下一实施包的可检验边界
- 非目标：创建环境、启动 daemon/VM、安装依赖、执行 I5-R、修改产品协议或扩大验证结论

## 本轮决定与交付

所有者在 2026-10-01 选择“保持整批 768 MiB：补充有容量硬上限的隔离构建环境设计，环境就绪前禁止 I5-R”。没有选择拆分构建与运行预算，也没有授权实际创建或调整隔离环境。

第一轮交付是入口停止检查、离线拒绝回归和本设计，已提交为 `0f531d3`。所有者随后要求提交并继续推进；本次接入证据输出计费、诊断限额与余量复查，并细化后端方案。构建/daemon 隔离及环境验收仍未完成，不能将局部离线通过写成整批资源验收通过。

- shell 的 `preflight` 和 `run` 均以退出码 2、`I5_RESOURCE_ISOLATION_REQUIRED` 停止；停止发生在任何外部命令、目录创建和 bootstrap 构建之前。
- 直接调用 Go `synthetic-run` 的两种模式也在环境访问前停止；内部矩阵入口单独保留同一检查，避免跳过 shell 后运行。
- 现有只读预检函数和注入式场景测试保留，继续可离线验证；CLI 不能把这些结果报告为完整资源预检通过。
- 不提供环境变量、CLI 开关或“已准备”文件绕过停止检查；重新开放必须交付真实隔离实现及对应证据。

## 已确认的写入缺口

| 路径 | 当前事实 | 必须补齐的边界 |
| --- | --- | --- |
| shell bootstrap | 原入口先创建 `.tmp/i5-bootstrap.*`，再调用 Go 构建 | 第一笔写入前已处于隔离容量域；启动前失败不能留下未计费构建 |
| Go 构建 | bootstrap 和 Linux 节点构建使用工具链管理的缓存与临时文件 | 显式绑定本批 `GOCACHE`、`GOTMPDIR`、`TMPDIR` 等写目录，拒绝回退到用户缓存或系统临时目录 |
| Docker build | CLI 的 `--network=none --pull=false` 没有建立整批存储额度 | builder、镜像层、临时上下文和 daemon 新增状态均受硬上限约束；检查镜像大小不能替代此项 |
| 节点 store | `state.json` 与 `state.next` 各最多 1 MiB，写入前已有编码长度检查 | 三个独占卷预留保守 12 MiB；包括提交时旧/新文件共存及失败遗留，不以响应后的 StoreBytes 代替预留 |
| 节点 `/tmp` | 每节点 16 MiB tmpfs，最多三个活动节点 | 活动样本预留 48 MiB；即使它占内存，也不作为不计费临时空间 |
| bundle | 已在创建目录前预留全部文件、LF 和 checksum，文件写入前复查余量；原子写临时文件使用对应已预留字节 | 文件系统元数据仍需底层容量域覆盖；失败残留保留计费，不退款 |
| 错误与清理 | incomplete/rejected/batch-result 已接入独立诊断子额度，单文件限额含 LF | 独立诊断存储域和真实空间保留未创建；不能清理成功就删除失败证据 |
| 监控 | artifact/RSS 采样现在同时复查宿主余量，证据写入另行逐文件检查 | 构建和阻塞控制期间的独立定时检查仍待接入；不能代替硬容量约束 |

源码入口为 [shell](../../scripts/run-sw-i5-harness.sh)、[监督器](../../tools/t0/cmd/sw-v0-harness/process_runtime.go)、[进程场景](../../tools/t0/cmd/sw-v0-harness/process_scenario.go)、[bundle writer](../../tools/t0/internal/harness/network_bundle.go) 和 [store](../../tools/t0/internal/synthetic/store.go)。不改变 synthetic 状态机或 envelope/store v1 来绕过资源问题。

## 推荐的隔离方案（待实现及环境评审）

采用专用于本批的 Linux 执行环境，在同一环境内构建宿主监督器、Linux 节点和镜像，并通过本地 Unix endpoint 使用独占 Docker daemon。现有共享 Docker/OrbStack daemon 不能仅凭 endpoint 为 Unix 就被视为符合隔离条件。

宿主系统、已安装工具链与只读源码是预先存在的输入；本批新增的 bootstrap、Go cache/temp、daemon/builder 存储、镜像、卷、证据与诊断全部进入有容量硬上限的存储域。不得通过先在域外构建、复制产物入域，或把 daemon 写入声明为环境开销绕过总额。环境准备与安装本身另有精确授权，不借准备过程提前执行本批构建。

环境后端的选择及具体挂载/配额命令尚未冻结。实施前必须提供能核验下列条件的后端方案；普通目录、稀疏文件的表观大小、单文件 ulimit 或定时 `du` 不足以证明总额受限：

1. 容量限制在第一个 bootstrap/daemon 写入前生效，覆盖并发写入、原子替换、被打开但已删除的文件、缓存和存储元数据；超额写入在底层失败。
2. 多个存储域和 tmpfs 的容量上限之和不超过 `768 * 1024 * 1024` 字节。诊断保留域也在总额内，不能另获不计费空间。
3. 工具链和源码只读；所有可写挂载、构建工作目录、日志和 daemon/builder 状态路径均可枚举且绑定本批。拒绝未知写入位置、外部 volume driver 或共享 builder。
4. 运行时重新核验实际挂载、文件系统/配额身份、容量、所有者与 daemon endpoint；一个自报 JSON 或环境变量不能证明容量机制生效。
5. 同时检查承载这些存储域的宿主文件系统余量与各域剩余额度，避免把 768 MiB 域内容量误当成“宿主至少 1 GiB 可用”的检查对象。

设计不保证冷 Go cache、Docker 元数据及 21 样本能放入该额度。若实际准备或构建在额度内不能完成，应保存明确失败并停止，不能自动增额、使用域外缓存或缩减矩阵。

### 本次细化：Linux 块设备容量域

候选后端收敛为专用 Linux 环境中的固定容量块设备及 ext4 文件系统；可用受限 loop 设备承载，但不得只检查 backing file 的表观长度。`losetup --sizelimit` 能限制设备寻址范围，ext4 的总块数和块大小可用于交叉核对；是否覆盖全部实际写入还须靠挂载、路径和真实拒绝测试验证。[losetup 手册](https://man7.org/linux/man-pages/man8/losetup.8.html)、[ext4 磁盘结构](https://docs.kernel.org/filesystems/ext4/super.html)。

本次固定用于有限实现的子额度如下；它们共同分割原 768 MiB，不是各阶段重新发放预算，也不承诺每个额度足够运行：

| 容量域 | 上限 | 覆盖对象 |
| --- | --- | --- |
| build | 256 MiB | bootstrap、Go cache/temp、节点二进制、Docker 构建上下文和构建侧诊断 |
| daemon | 160 MiB | Docker/containerd/builder 数据、镜像层、named volumes、运行状态及其日志 |
| evidence | 240 MiB | 21 样本的正常 bundle、checksum、写入临时文件与该域元数据 |
| diagnostic | 64 MiB | 一次最多 32 MiB 的 incomplete/rejected、最多 4 MiB 的批次结果，以及剩余诊断/元数据余量 |
| node tmpfs | 48 MiB | 三节点各 16 MiB，样本清理核验前不重新发放 |

四个磁盘域共 720 MiB，节点 tmpfs 共 48 MiB。表中为每域完整容量包络，包含该域文件系统元数据；真实有效载荷容量会更小。loop backing 文件的宿主分配开销、环境日志、额外挂载和构建插件写入也必须能归属到这些额度；不能证明归属时保持 STOP。不得把四个满额镜像再加域外诊断/日志视作达标。具体设备、文件系统参数、工具版本和宿主额外开销的处理仍须环境实施包评审，当前没有已验证的 Linux 后端。

推荐目录职责以本批根下的 `build/`、`daemon/`、`evidence/`、`diagnostic/` 四个挂载点区分；bootstrap 与两个 Go 构建必须显式绑定 build 域，`GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off` 不变。源码与工具链只读；不在宿主用户缓存、默认临时目录或工作区留下额外构建副本。证据默认保留在所属容量域内；导出副本另计费，不把“复制后删原件”当成没有峰值双份占用。

Docker 侧保留独占 daemon 与本地 Unix endpoint。不能仅设置 `data-root`：Docker 文档说明 containerd image store 可以使用独立路径；因此 data-root、exec-root、containerd root/state、builder 与日志都须纳入 daemon 域并按实际版本核验。可评估独占经典 VFS driver 以减少 overlay 挂载依赖，但其深复制会增加磁盘消耗，不能以“简单”推定 160 MiB 足够；未知版本/后端不自动回退。[Docker 存储配置](https://docs.docker.com/engine/daemon/)、[containerd 存储](https://docs.docker.com/engine/storage/containerd/)、[VFS 行为](https://docs.docker.com/engine/storage/drivers/vfs-driver/)。

另一个需显式关闭的默认写入口是容器 `/dev/shm`。本次创建参数加入 `--ipc none`，inspect 必须确认 `IpcMode=none`，同时严格检查只有约定的 16 MiB `/tmp` tmpfs；不按空目录大小假定 tmpfs 没有容量。Docker 将 IPC none 定义为不挂载 `/dev/shm`；真实挂载结果仍待环境验收。[Docker IPC 选项](https://docs.docker.com/reference/cli/docker/container/run/)。

### 本次有限实施边界

- `internal/harness/network_write_budget.go` 实现带锁预留与失败停止，累计额度跨 bundle 共用，溢出检查避免整数回绕；空间探测失败保留原因，不因下一次探测恢复而自动继续。
- `WriteNetworkBundleBudgeted` 在创建目录前预留整份 bundle，逐文件和 checksum 写前复查；既有离线 fixture writer 保留，监督器使用带预算入口。正常编码与 schema 3 文件逐字保持一致；单 bundle 32 MiB 的检查补齐 checksum 大小，读写双方一致。
- `process_artifact.go` 为 incomplete/rejected/batch-result 共用诊断预算，包含 LF，拒绝短写，保留 Write/Sync/Close 错误链；创建或写入失败不退款、不自动删除已有证据。
- `checkHostDisk` 被预检、原监控采样和输出检查共用，拒绝缺失/多文件系统、非法数字、整数溢出及少于 1 GiB 的余量。当前仍使用原宿主路径；将它绑定到真实存储域和承载文件系统的双重检查属于后端接入，不能以这个 helper 宣称已经实现。
- 运行入口仍硬停止。本次没有把 bootstrap、构建、daemon 或 store 的写入接入共享阶段账本，也没有建立上述容量域；文件字节账本不替代块级容量边界。

## 写前账本与余量检查

硬容量域是工具链、builder 和并发写入的最后边界；应用可控写入仍必须写前计费，两者都需要实现。

- 整批只有一个预算所有者，贯穿 bootstrap、构建、样本、清理和最终结果。阶段交接绑定同一批次及存储域，不重新发放 768 MiB。
- 对无法逐次拦截的构建写入，先预留其完整硬限额分区，启动后只能在该分区写入。阶段完成后实查占用与残留，确认容量回收才调整预留；失败或占用未知时不退款。
- store 与 tmpfs 在样本创建前预留，清理并核验真实移除后才释放；清理失败停止下一样本并保留预留。
- bundle 与 JSON 输出编码后，按确切字节数预留，再创建文件。失败时保守保留计费；不得因短写、Sync/Close/Rename 失败而假定磁盘为空。checksum 与诊断使用同一规则。
- 普通写入不能消费预留的失败证据额度；该额度至少覆盖一次完整 incomplete/rejected 输出及最终批次诊断，精确大小由编码上限与失败路径测试确定，不再沿用当前“32 MiB 加 LF”的含糊单文件上限。
- 每次预留、启动构建/样本、发送可能提交 store 的控制请求及写出证据前复查宿主余量；构建和等待控制响应期间另有可取消的定时检查。检查失败、低于合同宿主余量或容量域改变，终止当前阶段并回收本批进程。
- 余量采样仍有竞态，不能宣称在与其他宿主进程并发时实时保证 1 GiB 不被消耗；硬容量域约束本批最大占用，余量检查负责检测外部压力并停止。

失败停止、进程 Wait、精确资源回收与证据输出的先后必须覆盖：普通额度用尽、域内 ENOSPC、宿主余量下降、检查器失败、构建失败和 daemon 失联。诊断写入也失败时保留原错误与诊断错误，结果为 INVALID，不伪造 batch-result 已保存。

## 下一实施包与放行条件

| 顺序 | 交付 | 验收条件 |
| --- | --- | --- |
| 1 | 冻结具体后端与所有写目录/挂载清单 | 给出容量机制、并发与元数据处理、诊断预留和合计；不改变 768 MiB，不默认使用现有共享 daemon |
| 2 | 实现阶段预算、受限 bootstrap、构建与持久化写入接入 | 所有旧入口使用同一实际资源验证；没有绕过 flag；构建前拒绝不能先写缓存 |
| 3 | 完成离线注入验收 | 到界/超界、并发预留、短写/Sync/Rename 失败、构建错误、域身份改变、余量探测错误、清理残留与诊断保留均有拒绝证据 |
| 4 | 准备环境操作包并取得当次授权 | 精确环境/路径、容量、daemon 命令、时长、全部副作用、停止和回收方案可审阅；未获授权不实际创建 |
| 5 | 环境实测与干净 revision 预检 | 实测证明底层容量机制拒绝超限；检查并发、开放删除文件、实际 Go/builder 路径；停止检查不能只靠 mock 放行 |
| 6 | 固定产物并取得 I5-R 运行授权 | 完整 revision、合同/附录/profile hash、两个 binary hash、镜像和后端证据绑定，再执行原 21 样本矩阵 |

第一轮完成入口停止检查；本次完成第 2/3 项中的证据/诊断输出子项，未完成整项。下一步为具体后端的设备/挂载验证、受限 bootstrap 和构建接入，再准备精确环境操作包。环境测试属于单独外部操作，不是离线回归的一部分。

## 合同、版本与历史兼容

原 [I5 合同](sw-g4-synthetic-i5-plan.md)本轮保持逐字不变，原文 hash 不受普通文档整理影响。schema 1/2/3、五份 I5 profile、control v1、envelope/store v1 和 I4 fixture 均不修改。

本设计是原合同的资源实施补充及当前停止依据，不是已执行的实验合同。以后开放运行时，现有 manifest 仅绑定原合同 hash，不能冒称同时绑定了本附录。必须先评审资源后端配置与本附录的 hash 绑定方式及证据消费者的版本/兼容方案；保留历史解码，新增负例拒绝遗漏或混用绑定，不静默复用旧 schema 3 来承载新字段。

## 本轮验证记录

2026-10-01 第一轮实际执行（`0f531d3`）：

| 验证 | 结果与覆盖边界 |
| --- | --- |
| 新增 Go 入口测试 | shell、直接 Go preflight/run、内部矩阵入口均返回资源停止；内部矩阵没有调用注入的进程 runner |
| 新增 shell 测试 | 在测试临时目录复制真实入口，用空 PATH 执行两个模式，均退出 2 且诊断精确一致；没有 bootstrap、缓存或产物写入；短命 bash 进程由测试等待退出 |
| 全量 Go 离线回归 | `GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./...` 通过，覆盖既有 I1–I5 fixture 和新增拒绝路径 |
| 静态检查 | 同样离线环境下 `go vet ./...` 通过；范围内 gofmt、`bash -n scripts/run-sw-i5-harness.sh` 通过 |
| 仓库检查 | `./scripts/check-repo.sh` 通过（175 文件），`git diff --check` 通过 |

失败记录保留：首次精准测试因 Go cache 的 `operation not permitted` 退出 1，获准同命令沙盒外复验后发现 `networkExit` 没有 `Unwrap`，`errors.Is` 不能取得底层停止原因，测试退出 1；补齐错误链后全量测试通过。首次全量 vet 也因 Go cache 权限退出 1，获准同命令沙盒外复验通过。未换缓存目录、安装或下载依赖、放宽断言。

以上只验证入口停止与既有离线兼容。没有执行真实 shell preflight/run、Docker、socket listener、VM、隔离环境或容量超限实测；构建/写入预算修复及环境验收仍未完成。既有 I3 短命 helper 随全量测试执行并由测试管理；没有该轮遗留后台服务。该轮更改随后提交为 `0f531d3`，未推送。

2026-10-01 证据计费实施的实际验证：

| 验证 | 结果与边界 |
| --- | --- |
| 预算及并发 | 恰到界、超界、非法/溢出长度、缺失/未初始化预算、空间检查错误保留、并发预留均通过；共享账本的定向 `go test -race` 通过 |
| 真实临时文件输出 | 两份 bundle 共用精确总额通过，第三份或差 1 byte 均在创建目录前拒绝；LF/checksum 纳入计费；新旧 writer 的各文件逐字一致并通过既有 verifier；32 MiB 的文件清单在 finalization 前也必须留出 checksum，恰到含 checksum 总额的边界通过 |
| 失败与诊断 | 写中余量检查失败保留已写文件及整份预留；Create/短写/Write/Sync/Close 注入失败保留原因和计费；原证据额度耗尽及注入清理失败后仍能保存独立诊断 |
| 资源读数与容器参数 | 缺失/多行/非法/溢出/低余量的 df fixture 均拒绝；IPC 默认共享内存、缺失/过大/额外 tmpfs 均在 prepare 阶段拒绝并执行原精确清理 |
| 全量离线回归 | `GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=120s ./...` 通过；命令包约 17.3 s、synthetic 约 8.8 s；之后补充的清理失败诊断、checksum 清单边界及 bundle 精准回归通过 |
| 静态与仓库检查 | 全量 `go vet ./...` 通过，范围内 gofmt；`./scripts/check-repo.sh` 通过（179 文件），`git diff --check` 通过 |

本次失败记录：精准测试、全量 vet 和定向 race 首次均因 Go cache 权限退出 1，获准同命令沙盒外复验；精准测试中预算总额断言使用两个等价常量组成 OR，被 vet 的 `suspect or` 拒绝，已拆为独立合同值和分项合计断言。修正后全量测试、vet 和定向 race 通过。收尾 checksum 精准回归中 harness 包通过、命令包缓存权限失败，命令退出 1，同命令沙盒外复验两包通过；没有更换缓存、下载依赖或删除失败记录。

实施验收交接时，本次更改尚未提交；当时只有入口停止检查的 `0f531d3` 已提交，`dev` 领先本地记录的 `origin/dev` 1 个提交，未推送。所有者随后要求提交本批更改，提交号以 Git 记录为准。没有 Docker/VM/挂载/配额环境操作，没有后台服务；这些测试不验证冷构建能容纳于 256 MiB、daemon 能容纳于 160 MiB 或环境容量机制实际生效。原 I5 合同、五 profile、依赖及证据 schema 未改，I5-R 仍禁止启动。
