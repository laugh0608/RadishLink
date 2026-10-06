# I5 整批资源隔离设计与运行停止检查

- 更新日期：2026-10-06
- 状态：保留整批 768 MiB；证据计费、容量探测及受限双构建 helper 离线通过，真实环境、运行接入与 daemon 隔离未完成，I5-R 禁止启动
- 目标读者：I5 实现、运行环境准备及证据复核者
- 用途：关闭构建及运行写入绕过批次计费的问题，给出下一实施包的可检验边界
- 非目标：创建环境、启动 daemon/VM、安装依赖、执行 I5-R、修改产品协议或扩大验证结论

## 本轮决定与交付

所有者在 2026-10-01 选择“保持整批 768 MiB：补充有容量硬上限的隔离构建环境设计，环境就绪前禁止 I5-R”。该次决定没有拆分构建与运行预算，也未授权实际创建或调整隔离环境；随后仅获准复制、移动专用 UTM 副本，范围见本页准备记录。

入口停止及本设计已提交为 `0f531d3`，证据输出计费、诊断限额与余量复查为 `287b264`，容量核验及受限双构建 helper 为 `538323f`，专用 UTM 副本准备记录为 `40a588c`。构建/daemon 隔离及环境验收仍未完成，不能将局部离线通过写成整批资源验收通过。

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

本轮 helper 收敛为 Linux 独立整块设备上的 ext4；真实目标和挂载命令尚未冻结。环境实施前必须核验下列条件；普通目录、稀疏文件的表观大小、单文件 ulimit 或定时 `du` 不足以证明总额受限：

1. 容量限制在第一个 bootstrap/daemon 写入前生效，覆盖并发写入、原子替换、被打开但已删除的文件、缓存和存储元数据；超额写入在底层失败。
2. 多个存储域和 tmpfs 的容量上限之和不超过 `768 * 1024 * 1024` 字节。诊断保留域也在总额内，不能另获不计费空间。
3. 工具链和源码只读；所有可写挂载、构建工作目录、日志和 daemon/builder 状态路径均可枚举且绑定本批。拒绝未知写入位置、外部 volume driver 或共享 builder。
4. 运行时重新核验实际挂载、文件系统/配额身份、容量、所有者与 daemon endpoint；一个自报 JSON 或环境变量不能证明容量机制生效。
5. 同时检查承载这些存储域的宿主文件系统余量与各域剩余额度，避免把 768 MiB 域内容量误当成“宿主至少 1 GiB 可用”的检查对象。

设计不保证冷 Go cache、Docker 元数据及 21 样本能放入该额度。若实际准备或构建在额度内不能完成，应保存明确失败并停止，不能自动增额、使用域外缓存或缩减矩阵。

### 本次细化：Linux 块设备容量域

候选后端为专用 Linux 环境中的固定容量块设备及 ext4 文件系统。原设计允许评估受限 loop；本轮首版 helper 明确拒绝 loop、device mapper、md 和分区，仅接受独立整盘，避免遗漏 backing 层分配及别名。以后纳入 loop 必须另补实际 backing 计费，不能只看表观长度。`losetup --sizelimit` 能限制设备寻址范围，但不是整个宿主占用的证明。[losetup 手册](https://man7.org/linux/man-pages/man8/losetup.8.html)、[ext4 磁盘结构](https://docs.kernel.org/filesystems/ext4/super.html)。

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

### 容量探测与受限双构建 helper（2026-10-01 后续实施）

[只读入口](../../scripts/check-sw-i5-resources.py)只提供 `inspect` 和 `self-test`；[容量核验](../../scripts/sw_i5_resources.py)与[构建阶段](../../scripts/sw_i5_build.py)使用 Python 标准库，不需先编译 Go。没有新增依赖、安装工具、执行 mount 或调用真实构建。Python 入口在导入本地模块前禁用 bytecode 写入。

`inspect` 接受独立的配置版本 1：仅有 `schema_version`、`root`、`host_path` 和四域的预期 `major:minor`。未知字段、重复键、缺域、设备复用、非规范绝对路径及超大配置均拒绝。它不是 I5 证据 schema；输出始终含 `scope=local-block-domains-only` 和 `i5_ready=false`，退出 0 只表示本次本地探测通过，不能作为运行许可。

核验直接读取当前 `/proc/self/mountinfo`、块设备节点、`/sys/dev/block` 和 `statvfs`：

- 四个精确挂载点必须是完整 ext4 根、互不复用设备、无嵌套挂载/别名，域目录属于调用者且 mode 为 0700，挂载带 `nosuid,nodev`。拒绝 symlink 路径及 mountinfo/路径设备号不一致。
- 按 sysfs 的 512-byte sector 计算设备容量，分别不得超过既定 256/160/240/64 MiB；文件系统块总量不得大于设备容量，每域还要有可用字节和 inode。文件系统有效数据容量可以更小。
- `host_path` 必须位于域外，且与承载 batch 根目录的 ext4 文件系统一致；单独检查至少 1 GiB 可用。它只核验 Linux 本地承载层，**不能证明虚拟磁盘所在物理宿主及 hypervisor 日志的余量/计费**。
- 检查前后重新读取挂载表；阶段内绑定 mount ID、major:minor、sysfs 身份、fsid、根 inode 和容量。身份改变、探测出错或余量不足即永久停止本阶段，后续读数恢复也不续跑。

构建 helper 要求预先准备好的专用 mount namespace：除 build 外的所有挂载均只读，源码及 Go 可执行文件是域外只读输入；调用者非 root、无继承/许可/有效/ambient capabilities，启动器单线程。helper 自身不创建 namespace，也不声称已经准备好运行环境。

子进程在执行 Go 前设置 `no_new_privs` 和 Landlock，要求 ABI 至少 5、架构 x86_64/aarch64，失败无降级；只允许 build 域内的文件写入、截断、目录/普通文件/FIFO/symlink 创建与 rename，禁止新建 socket、设备节点及受管 device ioctl。Landlock 对 chmod、chown、xattr、utime 等存在限制，因此还必须验证其余挂载只读；并关闭继承的非标准 FD，将输出重定向到 build 域。该组合尚无本项目 Linux 实测，不作为任意恶意程序、网络或 IPC 的完整沙箱。[Linux Landlock 文档](https://docs.kernel.org/userspace-api/landlock.html)、[Linux syscall UAPI](https://github.com/torvalds/linux/blob/master/include/uapi/asm-generic/unistd.h)。

两个构建共用独占 `build/go-stage/`、缓存及临时路径；目录已存在即拒绝，不自动删除或续跑。bootstrap 和 node 均使用 `-mod=readonly -buildvcs=false -trimpath`，显式关闭工具链下载、module proxy、sumdb、GOENV、GOWORK、telemetry 和 CGO；环境从空映射建立，不继承 GOFLAGS 或用户缓存。build 整个 256 MiB 保留到批次结束，不在两个构建之间重发额度。单文件额外限制为 32 MiB，core dump 为 0；这些是更紧的拒绝条件，不能代替块设备上限。

每个构建最长 300 s，每 250 ms 重新核验容量域；阻塞在编译器等待期间也检查。失败或结束后向本次创建的进程组发送 SIGKILL、等待 Go 主进程，再有界核验进程组消失；有残留或清理错误则失败，保留原错误与清理错误。失败日志和部分输出保留在 build 域，不退款、不递归删除。进程组机制尚未以真实 Go 编译器验证，不宣称能回收主动脱离进程组的程序。

**接入边界**：`build_pair` 已有双构建流程和失败处理，但未接入 shell 或 Go 运行入口；只读 `inspect` 也不会修改停止策略。既有 Go 运行路径、Docker 构建/daemon 存储、store 阶段账本、阻塞控制请求监控及证据版本绑定仍需完成。不得手动调用 helper 代替尚未获得的环境实测授权。

### 环境操作包草案（盘点已通过，安装与容量准备未执行）

2026-10-06 有效盘点后的来源候选、身份交接、builder 写入及宿主容量缺口统一收敛到[专用环境准备评审包](sw-g4-synthetic-i5-environment-preparation.md)；下表保留本设计的约束与路由，具体候选清单不在两处维护。

所有者随后提供 UTM 资产位置，允许从干净基线复制专用 VM 或复用通用 Debian。已选择前者，并在精确复制/原生移动授权后建立 `RadishLink-I5-Debian13-ARM64`，UUID 为 `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`；2026-10-06 完成隔离与有效盘点后已正常关机，事实见本页实测结果。下表仍是工具安装、身份和容量验收的待审内容，不继承已消费的启动授权，也不提供猜测设备号的格式化/挂载命令。

| 操作 | 已收敛的参数与检查 | 仍缺的执行输入 |
| --- | --- | --- |
| 准备 Linux | 已实测 Debian 13 ARM64、内核 6.12.101、Landlock ABI 6、Python 3.13.5；无网卡/共享；当前 guest agent 为 root | 固定 Go 1.26 与 Docker/containerd/runc 来源、版本、校验及离线导入方式；克隆身份处置和无 capabilities 构建身份；不得复用 root agent 作为构建身份 |
| 建立四域 | 四块独占整盘，容量最多 256/160/240/64 MiB，ext4；独立 0700 挂载点 | 实际设备 ID、绝对路径、宿主 backing 及环境日志的计费方式；不得格式化既有共享盘 |
| 准备构建 namespace | 所有域外挂载只读，build 是唯一可写挂载；源码、Go 与配置路径固定 | 实际 namespace 命令及其精确回收对象；特权准备者退出/移交方式 |
| 只读探测 | `python3 -B scripts/check-sw-i5-resources.py inspect --config <已复核配置的绝对路径>` | 配置中的真实 root、host_path 与四个 major:minor；探测 stdout 的域内留存路径 |
| 受限构建验收 | 两个构建各最多 300 s，清理最多约 5 s；验证域外写入/截断/rename 拒绝及日志留存 | 当次运行授权、宿主层 ≥ 1 GiB 复查、真实 ENOSPC/开放删除文件/并发写入与后代回收用例 |
| daemon/builder 接入 | 独占 Unix endpoint、全部存储和日志位于 daemon 域，保持 160 MiB | 固定 Docker/containerd 版本、实际路径、driver 与启动/清理命令；此项未实现 |

后续主副作用是创建独占磁盘与文件系统、挂载/namespace、构建产物和日志；环境准备时长需在 guest 盘点后估算，构建时间上限如表所示。失败先停止本批进程并保留域内证据，只有核对所有者、批次与精确设备/挂载身份后，才按获准方案卸载和释放本批对象。不清理现有共享 daemon、其他 VM 或用户数据。guest 准备的完整命令未补齐前，不申请笼统环境授权。

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

第一轮完成入口停止检查，第二轮完成第 2/3 项中的证据/诊断输出子项，第三轮完成容量核验与受限双构建 helper 的离线实施。随后已复制专用 UTM 目标，并于 2026-10-06 完成隔离、宿主结果回收和有效 guest 盘点；未完成真实容量环境、运行入口接入、daemon 隔离与第 4 项安装/容量精确操作包。下一步针对盘点缺口固定工具来源、无特权执行、环境命令和宿主 backing/日志计费，并完成 daemon/store 与证据绑定。环境测试属于单独外部操作，不是离线回归的一部分。

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

2026-10-01 容量探测与双构建 helper 的实际验证：

| 验证 | 结果与边界 |
| --- | --- |
| `python3 -B scripts/check-sw-i5-resources.py self-test` | 20 项通过；kernel 数据、Landlock syscall、进程启动/等待/信号均注入。覆盖配置拒绝、设备号及 sector 读取、容量/余量/inode、挂载别名与变化、symlink、只读环境、缓存归属、双构建共用额度、超时/低空间取消、进程组残留、原错误与清理错误、失败日志和半成品保留 |
| 原入口停止回归 | `env GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 -timeout=30s ./cmd/sw-v0-harness -run 'TestNetworkEntrypointsStopBeforeEnvironmentAccess\|TestI5ShellStopsBeforeBootstrap'` 在 `tools/t0` 执行通过；真实 shell 只运行 builtins，无 bootstrap、Docker 或 TCP |
| 仓库检查 | `./scripts/check-repo.sh` 通过（182 文件）；`git diff --check` 通过 |

失败保留：首次 self-test 退出 1，失败夹具沿用了 macOS 的 `arm64`，没有注入 Linux 架构；修正后下一次 self-test 因 macOS 不提供 `os.O_PATH` 报 ERROR。该次合并检查命令被后续仓库检查的退出 0 覆盖，但测试结果未计为通过。补齐 Linux 常量夹具后改为独立调用 self-test，最终 20 项均通过；没有放宽生产平台/ABI 条件或执行实际 Landlock。新增测试只创建自动回收的合成临时文件，没有启动子进程。

本轮未重跑未修改的 Go 全量套件；未执行真实 Linux `inspect`、受限 Go 双构建、块设备写满、namespace、mount、Docker、VM、daemon 或 I5-R。没有安装依赖及后台服务；环境操作包仍缺真实目标和精确命令。更改尚未提交，`dev` 领先本地记录的 `origin/dev` 2 个既有提交，远程状态未改变。原 I5 合同、profile、schema 1/2/3 与依赖保持不变。

## UTM 副本准备记录（2026-10-01）

容量探测与双构建 helper 随后提交为 `538323f`。所有者提供 UTM 列表及 VM 存放目录，允许从干净基线复制或复用通用 Debian；只读盘点后，选用独立副本以保留通用 builder 和其他项目现场。实际复制及原生 Move 在说明目标、预计 1–5 分钟、副作用和失败保留方式后取得当次授权；没有启动、安装、格式化、挂载或执行实验。

| 项目 | 实际结果 |
| --- | --- |
| 源 VM | `Debian13-ARM64-CleanBase`，UUID `21197987-AEBB-46E6-ABDC-B9762F5C0CE4`，复制前后均 stopped |
| 新 VM | `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`，ARM64、4 GiB RAM，保持 stopped |
| 最终位置 | 操作员 `~/VirtualMachines/RadishLink-I5-Debian13-ARM64.utm`；UTM 以该外部 bundle 的快捷方式注册 |
| 操作 | 一次 `utmctl clone 21197987-AEBB-46E6-ABDC-B9762F5C0CE4 --name RadishLink-I5-Debian13-ARM64`，退出 0；随后通过 UTM 原生 Move 移到指定目录，默认 Documents 中该目标已不存在 |
| 注册清单 | 8 → 9；只新增上述 UUID，原 8 项 UUID/name/status 不变，终态全部 stopped |
| 源保护 | config、EFI、qcow2 的前后完整 SHA-256 一致；hash 读取结束后精确 `lsof` 无句柄输出 |
| 副本核验 | EFI 与 qcow2 完整 hash 等于源；配置差异仅 `Information.Name` 和 `Information.UUID` |
| 存储口径 | 源 qcow2 文件长度为 7,589,986,304 bytes（约 7.07 GiB）；不以 APFS clone 的逻辑长度推算实际新增物理占用，也不把系统盘快照当作 768 MiB 批次容量域 |

源 config SHA-256 为 `44fba0b4f260cce3b464f65a389d8bf8fcee14d1646770b6541740b123744fc9`；EFI 为 `855c86a4b77feb693c78af3d8e7101c17279c19c691163dae3306fd3c302d162`；`Data/FFF05A20-E829-493C-8F40-B40884425A3F.qcow2` 为 `3ea30804109fab315cda997f83052d0f7a2df95ea79e7ff6da643d0dbb5f248b`。记录不收录配置备注中的登录信息。

保留的异常与处理：沙盒内帮助命令曾退出 134；获准沙盒外读取 `utmctl clone --help` 后正常。副本初始位于 UTM 默认 Documents；配置直接读取在沙盒内外均被 macOS 以 `Operation not permitted` 拒绝，没有通过更改隐私权限或手工搬移绕过。按已说明的原生 Move 操作完成后，在目标目录正常读取并完成验证。第一次文件夹导航未完成移动，核对目标 absent 后重新打开 Move 对话框并完成；没有重跑 clone。首次并行 hash 与句柄检查观察到读取进程，待 hash 完成后串行复查才确认零句柄。

**剩余边界**：副本继承 Shared 网络和原 MAC；guest 内的 machine-id、SSH host key、实际 Debian/内核、Landlock ABI、Go/Python/Docker 与 guest agent 状态均未检查。首次启动前应明确网络隔离和克隆身份处理。四个容量域尚未创建，批次资源硬限额、宿主 backing/环境日志归属及 I5-R 验收均未通过。下一步仅为该副本的 guest 盘点与精确准备包；本次授权不包含启动或安装。

## 首次 guest 盘点操作包（2026-10-06，一次授权已执行）

副本准备记录已提交为 `40a588c`。2026-10-01 晚所有者要求停止推进，当时仅准备本地未跟踪草稿并完成语法、帮助及 macOS 拒绝检查。2026-10-06 所有者要求接续开发，本轮复核并修正[盘点脚本](../../scripts/inspect-sw-i5-guest.py)，增加[离线回归](../../scripts/test_sw_i5_guest.py)。该实施包随后提交为 `3a346af`。所有者审阅精确目标、副作用、时间和关机/强制停止范围后确认执行；一次授权已使用，以下为当次操作合同，结果见本页末，不再作为待执行或可重复授权。

本包只针对 UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`、`~/VirtualMachines/RadishLink-I5-Debian13-ARM64.utm`，预计 5–10 分钟。先复核 UUID、路径及 stopped 状态，通过 UTM 原生设置移除全部网卡、关闭剪贴板和目录共享，保存后读取配置核验，再启动一次。保留源 VM 及其他 VM 状态。此变更将持久修改该副本配置；启动和关机会写系统盘日志，不属于 768 MiB 批次实测。配置失败则不启动；本包结束保留隔离设置，不自动恢复 Shared 网络。

启动与只读检查的命令形态如下，`<nonce>` 须替换为本次新生成的 32 位小写十六进制值；不能把占位文本原样执行：

```text
utmctl start B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --hide
utmctl exec B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --input --cmd /usr/bin/python3 -I -B - --nonce <nonce> < scripts/inspect-sw-i5-guest.py
utmctl stop B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --request
```

盘点脚本通过 guest agent 的 stdin 执行，只把 JSON 写到 stdout。读取内核、架构、内存、块设备容量、根盘余量、网卡/路由、指定包版本与工具位置，并只查询 Landlock ABI；不执行 Go/Docker、不建立隔离规则、不安装软件、不复制源码或创建 guest 文件。仅记录 machine-id 是否非空及 SSH 公钥文件数量，不收集其内容、不重新生成身份；`identity_regeneration_verified` 和 `i5_ready` 始终为 false。返回必须包含匹配 nonce 的可解析 JSON；空输出或仅退出 0 不算完成。脚本在其他信息读取及包查询前要求网卡只有 `lo`，盘点结束时再次检查；任一次不满足即退出 2，不输出成功 JSON，由操作员进入关机收尾。前后快照不能代替启动前移除 VM 网卡。

guest agent 或 Python 不可用时保留具体错误并关机，不临时安装；正常关机请求后最多等待 120 秒，若本包获准的超时处置也被授权，才对同一 UUID 使用 `utmctl stop ... --force`，记录为非正常关机，随后复核全部 VM 状态。即使盘点失败也进入关机收尾；没有单独授权时不使用 `--kill`、不删除副本或系统盘。安装依赖、修改 machine-id/SSH key、创建四个容量域、构建、启动 daemon 和 I5-R 均不在本包范围内。

本地验证：脚本语法解析通过；`--help` 退出 0；macOS 上传入合法 nonce 时按预期退出 2，报告 `Linux guest required`。这不证明 guest agent、Linux 内核或实际工具可用；实际执行结果待授权后补充。

### 2026-10-06 操作与返回校验补充（当次合同）

1. 执行前用 `utmctl list`、`utmctl status B86E1A47-9A67-4ECF-A51F-2B2F29CDB726` 核对目标及全部 VM 状态；目标必须 stopped。只读解析目标 `config.plist`，仅输出 Name、UUID、网络模式与共享开关白名单，不输出 Notes、MAC、登录信息或完整配置。2026-10-06 本轮已核对 Name/UUID 与目标相符、网络为 Shared、剪贴板为 true、目录共享为 VirtFS；未核验实时运行状态。
2. 本包获准后，打开 UTM，使用该副本的原生设置移除全部网卡、关闭剪贴板及目录共享。保存后重新解析配置，要求 Network 为空、ClipboardSharing 为 false、DirectoryShareMode 为 None；不满足则不启动，不猜测其他配置值可等价放行。不改源 VM、其他副本、身份文件或系统权限。
3. 生成本次 32 位小写十六进制 nonce，固定脚本 SHA-256。只在仓库忽略目录 `.tmp/i5-guest-inventory-<nonce>/` 保存该次 stdout、stderr、退出码、校验结果及操作摘要；不复制完整 VM 配置。本次准备证据与系统启动日志不是 768 MiB 批次实验，不能写成批次验收证据。
4. 按上文命令启动一次，通过 guest agent 的 stdin 执行一次脚本。宿主为 start/exec/stop 单次控制命令设置最多 60 秒等待；guest 内唯一包查询最多 15 秒。超时、guest agent 不可用、Python 不可用、非零退出或返回校验失败，保留真实错误并进入关机收尾，不自动重跑盘点或安装依赖。
5. 只有 guest 命令退出 0，才用下述宿主命令校验完整 stdout；不以管道最后一项退出码覆盖 guest 失败。校验器不探测宿主，限读 128 KiB，拒绝空/截断 JSON、重复键、非有限数字、过深嵌套、错误 nonce/版本/范围、缺失或类型错误字段、非 loopback 返回以及伪称环境就绪/身份已重建。通过仅表示返回封装和字段完整，内部事实仍需人工核对；nonce 不证明 VM 身份或结果真实性。

```text
python3 -B scripts/inspect-sw-i5-guest.py --validate-result --nonce <nonce> < .tmp/i5-guest-inventory-<nonce>/stdout.json
```

6. 不论盘点成功或失败，均对同一 UUID 请求正常关机，每次最多间隔 30 秒复查，共等至 120 秒；本包单独包含获准后的超时 `utmctl stop B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --force` 一次，记录非正常关机风险（系统盘可能未完成写回），不用 `--kill`。最后复核目标 stopped 与其他 VM 状态；失败则明确报告，不删除副本。保持新隔离设置，恢复原 Shared 网络/共享须另行授权。

本包原预计 5–10 分钟，副作用为持久修改目标配置及启动/关机日志写入；不安装工具、不修改 machine-id/SSH key、不创建容量域、不启动构建/daemon/I5-R。当次获准先提交脚本、回归和相应文档，再执行上述范围；commit 不包含 push。后续结果记录不扩大这次单次运行授权。

### 2026-10-06 离线复核记录

- 原草稿发现额外网卡后仍继续采集并退出 0，仅返回 `loopback_only=false`，与操作包的立即停止要求不符；现已改为前置拒绝及结束复查。
- 增加同一脚本的 `--validate-result` 宿主模式，不新建另一套运行入口；不修改 I5 合同、profile、schema 1/2/3 或资源额度。
- `python3 -B scripts/test_sw_i5_guest.py`：12 项合成回归通过，覆盖完整采集与身份内容保护、网卡前置/结束拒绝、读取异常、非 Linux 拒绝、包缺失/失败/超时、返回封装负例、CLI 非零退出和宿主校验不调用探测。测试注入平台/文件系统/包查询，不执行 VM、真实 dpkg、Go/Docker 或 Landlock。
- `--help` 退出 0；本机 macOS 直接盘点按预期退出 2（`Linux guest required`）。`./scripts/check-repo.sh` 通过（185 文件），`git diff --check` 通过。未改 Go 代码，未重跑 Go 套件或历史正式实验。
- 上述离线复核完成时，VM 启停等外部操作尚未执行；随后单次获准操作见下节，离线通过不替代其失败结果。

## 首次 guest 盘点执行结果（2026-10-06）

**结论：盘点失败，结果回收未通过；VM 已正常关机，I5-R 仍停止。** 所有者确认后先提交 5 个文件为 `3a346af`，再按当次合同启动一次、发起一次盘点。没有自动重跑，不能以 CLI 的退出 0 推断 guest 完成或环境就绪。

| 项目 | 实际证据与结论 |
| --- | --- |
| 目标与基线 | UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`，名称/路径与合同一致；初始共 9 台 VM，全部 stopped |
| 隔离配置 | UTM 原生设置移除唯一网卡；最终 `Network=[]`、`ClipboardSharing=false`、`DirectoryShareMode=None`。配置保存后、启动前及关机后均复查；不从 UI 选中状态直接推导落盘成功 |
| 工具 | 本机 UTM `4.7.5 (118)`，`utmctl` 指向应用自带二进制；未更新或安装 |
| 启动 | `utmctl start ... --hide` 退出 0，等待 30 秒后发起一次盘点 |
| 盘点 | `utmctl exec ... --input --cmd /usr/bin/python3 -I -B - --nonce ...` 退出 0，stdout 和 stderr 均为 0 bytes；无法确认 guest 脚本完成或其真实退出码 |
| 返回校验 | 宿主 `--validate-result` 退出 2，`I5_GUEST_INVENTORY_FAILED: Expecting value: line 1 column 1 (char 0)`；没有取得可接受 JSON、nonce 或任何内核/工具/容量事实 |
| 关机 | 无论失败均执行 `utmctl stop ... --request`，退出 0；首次状态为 started，约 30 秒后的下一次为 stopped；未调用 force/kill |
| 最终状态 | 全部 9 台 VM 的 UUID/name/status 清单与基线逐字一致；目标保留隔离配置，其他 VM 未操作。宿主控制脚本退出 2，无遗留批次进程；UTM 桌面应用保留打开 |
| 未执行 | 依赖安装、身份重建、容量域创建、构建、daemon、I5-R、远程写入均未发生；环境精确准备包仍缺有效 guest 盘点 |

本地忽略证据目录为 `.tmp/i5-guest-inventory-f4ff9922a903d2b5d2b59c59a2ba8713/`，保留控制脚本、命令/退出码、stdout/stderr、配置白名单、运行前后清单及 `result.json`；不将完整 VM 配置或登录信息复制进证据文件。盘点脚本 SHA-256 为 `0517094f18759c930548655a54980622fd082b254a01d93b0286ce5eab6b36f9`，宿主单次控制脚本为 `5b8d505b81fd0bee11b8dea30516ec25e6551fa1d0302f3a0fe2ee95cc20575e`；隔离完成至关机后的配置 SHA-256 保持 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`。这些是准备操作证据，不计作 I5 批次验收。

保留的失败与中间状态：沙盒内 Python 包装的首次 `utmctl list` 未返回输出，包装因断言退出 1，当时未保存子进程退出码；沙盒外同目的只读复验退出 0。`utmctl start/stop --help` 在沙盒内均退出 134、无输出，沙盒外同命令复验退出 0。UI 首轮未保存修改、后续一次保存仍读到 VirtFS，均未启动；重新打开确认并保存后才满足三项配置条件。最后的盘点空返回是独立失败，不能被此前成功复验覆盖。

### 结果回收诊断与下一步

以下保留首次失败后的判断与计划；后续已完成适配层及第二次盘点，见[实测结果](#宿主回收与第二次盘点实测结果2026-10-06)。

只读核对本机 `UTM.sdef` 可见结果属性名为 `exited`，其 Cocoa key 为 `hasExited`。上游 [v4.7.5 的 Exec 实现](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/UTMCtl.swift#L437-L485) 使用 `result["hasExited"]` 轮询，并把缺失的退出码默认为 0；[官方脚本接口](https://docs.getutm.app/scripting/reference/#execute-result)提供进程对象及结果读取。[上游问题 #7932](https://github.com/utmapp/UTM/issues/7932)报告这一字段差异导致提前返回空输出。安装版本、静态代码与本次现象吻合，因此**宿主过早回收结果是有依据的候选根因**；本轮未通过另一执行通道取得真实 guest 结果，不能写成已在本机证明根因或 guest 无故障。

下一工作包先收敛宿主结果回收方式：保留同一个 guest 进程句柄，显式等待 `exited=true`，要求真实退出码及完整 stdout/stderr，保留 60 秒上限和现有 JSON/nonce 校验；先用离线用例覆盖尚未退出、缺失字段、超时、非零退出和空返回。具体通道及精确命令另行审阅，不修改系统安装的 UTM、不把延长启动等待当作修复、不自动退回网络/共享或 guest 落盘方案。再次启动/执行需要新的明确范围；现有授权已消费。有效盘点之前，不猜测工具缺失、设备号、Landlock ABI 或四个容量域的可行性。


## 宿主结果回收适配层与受限实测包（2026-10-06）

状态：宿主适配及离线验证随后提交为 `4ce4a25`。所有者明确要求“提交工作区更改，然后确认，继续推进”，确认下述一次受限操作包；真实执行已完成，结果见下一节。首次盘点失败记录保留，本节操作合同的单次授权已经消费，不开放 I5-R。

### 实现与证据边界

- 沿用 [inspect-sw-i5-guest.py](../../scripts/inspect-sw-i5-guest.py)，增加 macOS `--collect-utm success|failure|inventory` 模式；原 guest 采集与 `--validate-result` 语义不变，新增参数互斥。宿主执行前后只读核对精确 VM 名称/UUID、无网卡、剪贴板关闭和目录共享 None；配置不符即拒绝。
- [sw_i5_utm_result.js](../../scripts/sw_i5_utm_result.js) 是该入口的单一 UTM 适配层。使用系统 `/usr/bin/osascript -l JavaScript`（JXA）调用 UTM 官方进程接口，不替换 UTM 二进制、不新增第三方依赖，也不通过 UI 输入命令。源码按本机 `UTM.sdef`、[UTM 脚本接口](https://docs.getutm.app/scripting/reference/)与 [Apple JXA 文档](https://developer.apple.com/library/archive/releasenotes/InterapplicationCommunication/RN-JavaScriptForAutomation/Articles/OSX10-10.html)独立编写；无复制上游实现。
- 仅选择 UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`，要求其已经 started；一次 `execute` 返回的进程句柄供后续全部 `getResult` 使用，每 250 ms 查询，明确等待布尔 `exited=true`。缺失字段、错类型及事件错误直接失败，不改读 `hasExited`、不重发 execute、不默认退出码 0。
- JXA 内部使用单调时钟，总限时 55 秒，结果查询事件单次最多 5 秒；Python 外层 `subprocess.run` 用 60 秒上限覆盖 JXA 启动及阻塞事件，并负责终止/等待宿主子进程。终止宿主适配器**不证明 guest 进程结束**；外层当次操作必须进入 VM 关机收尾，不能继续下一命令。
- 结果包含真实 exit/signal、同次 nonce/case/UUID、轮询次数和 base64 双输出。每条 guest 输出的验收上限为 128 KiB，缺失流、错误 base64、错误绑定或未确认退出均拒绝；对传输 stdout/stderr 各保留最多 512 KiB，超过上限保留原长度并失败。`capture_output=True` 仍会先在宿主内存中接收输出，再校验/截断留存；这些是返回验收与证据留存上限，不是 Python/JXA/UTM 的采集内存硬隔离，也不属于 I5 的 768 MiB 批次环境验收。
- 正常回收后保留 exit 17 等非零结果；成功/失败合成探针分别要求 stdout/stderr 中的精确 nonce 标记和退出 0/17。`failure` 用例确认通过时，宿主入口仍退出 17，不能通过默认 0 掩盖。inventory 仅在 guest exit 0、无异常 stderr 且既有 JSON 校验通过后接受。
- 自动保存到仓库忽略目录 `.tmp/i5-guest-return-<nonce>/<case>/`：输入源/适配层 SHA-256、传输退出码/超时、原始双输出、解析后的执行记录、guest 双输出和失败原因。拒绝同 nonce/case 重复目录及路径重定向，不覆盖旧证据；诊断写入失败同时保留原始原因。此目录只供准备证据，不代表正式实验产物。

### 离线验证

```bash
python3 -B scripts/test_sw_i5_guest.py
osascript -l JavaScript scripts/sw_i5_utm_result.js --self-test
python3 -B scripts/inspect-sw-i5-guest.py --help
```

- Python 27 项回归通过：包含原 12 项，以及真实非零退出保留、双流与 nonce 校验、空/部分/超限返回、signal、配置隔离、证据保留/不覆盖、超时不重发、诊断写失败和 CLI exit 17。
- JXA 24 项合成用例通过：同一进程句柄等待、执行一次、缺字段/错类型、退出码/signal、超时、迟到结果、事件错误、停止 VM 拒绝，以及原生适配方法的对象/参数绑定。
- `--help` 退出 0；`./scripts/check-repo.sh` 通过（186 文件），`git diff --check` 通过。没有修改 Go 代码、原 I5 profile 或实验合同，未重跑无关 Go 套件。
- `--self-test` 分支只运行纯 JavaScript 与假应用对象，不调用 `Application`、`ObjC` 或 UTM。Python 测试只使用合成临时目录及注入子进程结果，不执行真实 `osascript --collect`、guest 命令或 VM 操作。
- 以上离线结果本身不证明 macOS 自动化权限、JXA 与实际 UTM 记录的映射或 guest 可用；当时真实探针尚未运行。后续实测结果单独记在下一节，不用成功实测覆盖第一次失败。

### 已执行的一次受限实测合同

目标仍为同一专用 VM，保持现有网络/共享隔离；当次预计 5–10 分钟。合同要求先本地提交本工作包（代码及接续结果文档，不 push），再固定新 revision、guest/适配层/控制脚本 hash 和本次新 nonce。启动前核验 UUID、配置及 stopped，并保存全部 VM 的状态清单。若配置不符，不修改或启动。

```text
utmctl list
utmctl status B86E1A47-9A67-4ECF-A51F-2B2F29CDB726
utmctl start B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --hide
python3 -B scripts/inspect-sw-i5-guest.py --collect-utm success --nonce <nonce>
python3 -B scripts/inspect-sw-i5-guest.py --collect-utm failure --nonce <nonce>
python3 -B scripts/inspect-sw-i5-guest.py --collect-utm inventory --nonce <nonce>
utmctl stop B86E1A47-9A67-4ECF-A51F-2B2F29CDB726 --request
```

精确执行条件：

1. 启动一次后等待 30 秒，再调用 success；该合成程序只等待 1 秒、向 stdout/stderr 打印绑定 nonce 的标记并退出 0，不访问文件、身份或网络。宿主执行退出 0 且记录满足约定才继续。
2. failure 同样只等待 1 秒、输出两条合成标记，随后退出 17；**宿主退出 17 且 `execution.json` 的 exited/exit/signal/nonce/双流均正确**才算该负例通过。其他退出或缺证据均停止，不把任何非零退出笼统当作预期失败。
3. 前两项通过后，才执行一次现有 guest inventory（`/usr/bin/python3 -I -B - --nonce <nonce>`，源码经 stdin 传入）；保留原只读范围和全部校验。不继续使用本次已知可能提前返回的 `utmctl exec`，不用延长 sleep 代替可靠结果回收。每项最多一次，最多共三次 guest execute，不自动重试、不加额外探针。
4. 宿主控制必须使用 finally 收尾：成功、失败、权限拒绝或超时均请求同一 VM 正常关机；每次最多间隔 30 秒复查，等至 120 秒仍未 stopped 时才使用本包已批准的同一 UUID `utmctl stop ... --force` 一次；最后核对 stopped 和其他 VM 状态，不使用 kill。强制停止存在未完成写回风险。
5. 失败保留证据，停止后续 case。若系统提示新的自动化权限，停在提示处由用户确认，不自动授予权限或换通道。JXA 不负责关闭 VM，也不假装超时已取消 guest 工作。

该次副作用仅为启动/关机系统日志及宿主准备证据；不改 VM 配置、不开放网络/共享、不安装/更新工具、不改身份、不写 guest 脚本文件、不建容量域、不构建、不启动 daemon/I5-R、不修改源 VM 或其他 VM。收尾保留隔离配置和失败证据。取得有效盘点后，再据实际内核、工具和设备资料准备四个容量域与 daemon 接入的下一操作包，不从本次结果直接授权那些操作。

## 宿主回收与第二次盘点实测结果（2026-10-06）

**结论：成功/失败双流探针及有效盘点通过，目标正常关机；I5 容量环境未准备，I5-R 继续停止。** 本次先提交 7 个文件为 `4ce4a2564e927047c33f55cd3b38a689c0322ebf`，再启动同一专用 VM 一次。没有重新调用已知空返回的 `utmctl exec`，没有重试任何 case。控制脚本最终退出 0。

| 步骤 | 实测结果 |
| --- | --- |
| 启动前 | 精确 UUID/name 及隔离配置通过；目标及全部 9 台 VM 均 stopped；list/status/start 退出 0 |
| success | CLI 退出 0；同一进程句柄查询 5 次后确认 exited=true；guest exit 0 / signal 0；stdout/stderr 精确匹配本次 nonce 标记 |
| failure | CLI **退出 17**；查询 5 次后确认 exited=true；guest exit 17 / signal 0；双流标记精确匹配，因此负例通过 |
| inventory | CLI 退出 0；查询 2 次确认 exited=true、exit 0 / signal 0；stderr 为空；完整 JSON、nonce、隔离与非就绪声明校验通过 |
| 关机 | 正常关机请求退出 0；首次状态为 started，30 秒后复查 stopped；未使用 force/kill |
| 最终复核 | 全部 VM 清单逐字等于启动前，目标及其他 8 台均 stopped；配置白名单与完整配置 hash 不变 |

宿主适配器均退出 0、无 stderr、未超时；失败探针的 17 是 guest 真实退出经宿主入口保留后的结果。该次实际证明 JXA/UTM 进程接口可以等待并回收双流及非零退出，盘点成功；没有对系统安装的 `utmctl` 修补或对照重测，因此不把第一次失败的候选代码根因写成已独立实证。

### 实际 guest 事实及含义

| 盘点项 | 事实 | 证据边界 |
| --- | --- | --- |
| 系统与 ABI | Debian GNU/Linux 13 (trixie)，aarch64，内核 `6.12.101+deb13-arm64`；Landlock ABI 6 | 满足 helper 的 ABI ≥ 5 前置；未建立规则或验证真实写入拒绝 |
| Python/agent | Python `3.13.5`；python3 包 `3.13.5-1`；qemu-guest-agent `1:10.0.11+ds-0+deb13u1` | 本次 stdin 程序及结果回收可用 |
| 已有基础工具 | util-linux `2.41-5`、e2fsprogs `1.47.2-3+b11`；找到 mount/unshare/mke2fs | 只查包及可执行文件存在性，未执行格式化、挂载或 namespace |
| 待准备工具 | 指定包清单无 Go/Docker/containerd/runc；已查固定目录中的对应可执行文件列表为空 | 不能排除未搜索目录或其他包名；足以说明既定入口所需工具尚未证明可用，不能宣称全盘无任何副本 |
| 包查询状态 | `dpkg-query` 退出 1，返回已安装包及八条包缺失诊断 | 缺包属于盘点事实，诊断保留在 JSON 中；不等于 inventory 失败，也不静默抹去该退出 |
| 身份与权限 | uid/euid 0；CapEff/CapPrm 均 `000001ffffffffff`；NoNewPrivs=0、Seccomp=0 | 当前 agent 进程不满足无特权构建条件，不能直接作为 build helper 调用者 |
| 克隆身份 | machine-id 非空，SSH 公钥文件计数 3；identity_regeneration_verified=false | 未读取任何身份/密钥内容，未验证与源的差异，也未重建身份 |
| 网络 | 只有 lo，IPv4 路由仅表头、IPv6 路由均 lo；启动前后 VM 配置无网卡/共享 | 只覆盖本次隔离状态，不授权开放联网安装 |
| 存储 | `vda` 53,687,091,200 bytes（可写），`sr0` 1,073,741,312 bytes（只读）；根文件系统可用 40,936,665,088 bytes | 四个独占容量盘未创建；未取得新盘设备号或证明虚拟磁盘 backing/宿主物理余量，不把根盘当批次域 |
| 内存 | MemTotal=4,007,504 kB，MemAvailable=3,355,660 kB，SwapTotal=2,709,500 kB | 单次快照，不能替代批次资源限制、RSS 或容量验收 |

### 证据与后续工作包

本次 nonce 为 `376bad7d1e03645dac69df2f7067c86a`；本地忽略目录 `.tmp/i5-guest-return-376bad7d1e03645dac69df2f7067c86a/` 保留三项完整执行记录、传输/guest 双流、输入 hash、命令退出码、控制脚本、配置白名单、前后 VM 清单及 `result.json`。没有保存完整配置或登录信息。

| 固定输入 | SHA-256 |
| --- | --- |
| `scripts/inspect-sw-i5-guest.py` | `bee566862fe37f340ca48f735a81c00a89b3e3469014ad7f6905dbc0b8ae1afb` |
| `scripts/sw_i5_utm_result.js` | `247549218c87dc2624afe08d543366a40eb18dc870d118dec7bceeccdf0e6391` |
| 本次 `run_inventory.py` | `b622f871cfd4e56887e2fb90135ea69cc2e2b1cfaa841e5bb3ef45a83cde2674` |
| 隔离配置（前后相同） | `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc` |

每个 JXA 调用仍由 Python 限时等待 60 秒；单次控制脚本对 CLI 外层多留 5 秒，仅用于宿主回收及记录超时，不重发 execute。这些是宿主等待上限，不构成 guest 执行的硬超时或取消保证；超时后 guest 完成状态仍未知，必须进入 VM 关机收尾。该次未触发超时。沙盒外调用只执行已确认的精确 VM 操作；未因自动化权限受阻。控制脚本和宿主适配器均已退出，无本轮遗留测试进程。

下一包先完成可审阅设计与离线实现，再申请具体外部操作：

1. 固定 Go 1.26 的具体补丁版本，以及 Docker/containerd/runc 的来源、版本、许可证、校验和依赖闭包；设计保持现有隔离的导入路径、安装清单、磁盘增量及回滚方式。本次不推断可联网安装或复用其他项目工具。
2. 给出克隆身份处置及独立无特权构建身份的精确操作；将 root 准备阶段与构建进程区分，列出只读源码/工具链、namespace、capabilities 清空与特权移交的可验证条件。身份重建尚未获执行授权。
3. 固定四个独占磁盘的宿主格式、完整容量上限、目标路径和创建后设备绑定办法，先解决 backing 元数据、UTM/guest 日志及诊断的额度归属，再形成创建/格式化/挂载命令；不得假设新盘必为 vdb–vde。完整物理开销不能被证明纳入 768 MiB 时保持 STOP。
4. 在现有 helper 上完成 daemon/store 及构建运行接入、证据版本绑定和负例，再给出容量超限、域外写入、进程回收与真实构建的有界环境验收包。不开旁路入口，不用本次盘点通过解除运行停止。

本次单次授权已消费；没有安装工具、改身份、创建磁盘、构建、启动 daemon、运行 I5-R 或远程写入。本次结果记录随后更新于既有四份文档；`./scripts/check-repo.sh` 通过（186 文件），`git diff --check` 通过。实测后没有改代码，不重复已通过的离线套件。当次交接时这四份文档尚未提交；所有者随后要求提交，记录为 `c7b0aa1`，未 push。后续环境设计见[准备评审包](sw-g4-synthetic-i5-environment-preparation.md)。
