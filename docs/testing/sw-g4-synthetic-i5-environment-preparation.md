# I5 专用环境准备评审包

- 更新日期：2026-10-09
- 状态：专属包表限额调整已获准应用，完整补充盘点及正常回收通过；依赖验签、安装差量和容量边界仍待关闭，I5-R 继续停止
- 目标读者：环境准备、I5 后端实现与证据复核者
- 范围：承接有效 guest 盘点，收敛工具输入、身份分工、写入归属和下一离线实施顺序
- 非目标：安装或更新依赖、改变身份/系统配置、创建磁盘、运行构建/daemon/I5-R；文内盘点操作只按各自明确授权的单次合同执行

当前接续：增强诊断、包表专属 512 KiB 限额与完整实测记录已提交为 `3aab466`。最新事实以[完整补充盘点](#完整补充盘点与正常回收通过2026-10-09)为准，次日工作见[2026-10-10 事项](../status/2026-10-09-progress.md#明日事项2026-10-10)。下文按执行阶段保留历史额度、失败、源摘要与当时提交状态，不代表旧操作包仍可执行。

## 初次准备结果（2026-10-06）

所有者要求“提交工作区更改，继续推进下一步”。四份实测结果文档已提交为 `c7b0aa1`，未 push；本轮随后只读核对源码、公开发布/安全资料及官方包索引，形成本文和[候选来源清单](../../tools/t0/i5-environment-candidates.json)。没有下载候选软件包或执行 guest 命令。

目标仍为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。已验证事实见[实测记录](sw-g4-synthetic-i5-resource-isolation.md#宿主回收与第二次盘点实测结果2026-10-06)，不在本文复制完整盘点。最近一次已验证状态为正常关机、无网卡及共享；本轮没有重新调用 UTM 状态接口，不能把历史状态称为本轮实时复核。

当前需要关闭三个具体问题：

1. 发行版包和官方包不是同一依赖图。Debian trixie 的 `docker.io` 不包含独立 `docker-cli`；仅安装原盘点清单中的名称不构成完整环境。
2. agent 为 root，而现有 Go 构建 helper 要求非 root、无 capabilities、单线程及域外只读挂载；安装工具不能自动满足这些前置。
3. 四域上限 720 MiB 加节点 tmpfs 48 MiB 已占满总额。四个满额 guest 盘加未计费的 backing/系统日志不能作为合格后端；完整物理占用边界仍未证明。

## 工具输入与容量复核（2026-10-09）

本次只读复核已保存的原始索引、guest 返回、宿主上的目标 VM 配置和官方说明；没有启动 UTM/VM、下载软件包、安装工具或运行 guest 命令。结论是：**当前配置不能进入 I5-R；768 MiB 方案尚未证明可行，也没有证据证明所有 Linux 后端均不可行。** 继续保留合同和公开入口 STOP，不先接入运行代码来代替环境证明。

### 输入闭包：发现前置依赖遗漏

四个固定 deb 的版本、架构、Size、SHA256、Depends 和 Recommends 与保存的 Packages 逐项一致；Packages/InRelease 的大小与摘要复算一致。候选 JSON 仍只是索引摘录，不是完整依赖锁：它没有记录以下全部关系字段，后续解析必须直接使用经验证的完整索引，不能只递归其 `depends` 字段。

| 固定包 | Installed-Size（KiB，索引声明） | 摘录之外必须处理的关系 |
| --- | ---: | --- |
| `containerd.io` | 80,956 | Conflicts/Replaces/Provides：`containerd, runc` |
| `docker-buildx-plugin` | 67,053 | Replaces：`docker-ce-cli` |
| `docker-ce` | 105,905 | **Pre-Depends：`init-system-helpers (>= 1.54~)`**；Conflicts：`docker.io`；Replaces：`docker-ce-cli (<< 5:28.0.0)` |
| `docker-ce-cli` | 43,965 | Conflicts：`docker-cli, docker.io`；Breaks/Replaces：`docker-ce (<< 5:0)` |

四包声明安装体积合计 297,879 KiB，约 290.90 MiB；它既不含 Go、Debian 传递依赖和维护脚本写入，也不是实际文件系统占用或构建峰值。预先安装且在批次内真正只读的工具输入与批次新增写入分开核算，不能把该数直接与 build 域 256 MiB 比较后判定可行或不可行。

依赖解析还必须固定 Recommends 的处理策略。Engine 推荐 rootless extras 等包，CLI 推荐 Compose；本批需求不自动包含它们，Git 等实际必需工具也不能因关闭推荐包而遗漏。应在离线解析中显式列出安装、保留、升级、删除及排除项，并拒绝未经评审的删除/升级；不能用包名的字符串集合自行替代 Debian 的版本、替代依赖、Provides 和安装顺序语义。[Debian 包关系规则](https://www.debian.org/doc/debian-policy/ch-relationships.html)。

旧 guest 盘点仅查询预设包名，不是完整 dpkg 数据库；成功返回中只有四个已安装包条目，无法据此判断所有依赖已满足。宿主本次仍未找到 `gpg/gpgv`，也没有 `apt-get/dpkg-query`；不安装替代工具或自行实现 OpenPGP。来源真实性应先闭合发布密钥信任与 InRelease 签名，再沿索引核验每个归档；现有摘要内部一致不等于这条信任链已通过。[apt-secure](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html)。

### 容量：发现 swap 与现有 backing 的未闭合写入

旧 guest 返回来自 2026-10-06 已通过的第二次盘点，原始 `guest.stdout` SHA-256 为 `b226c10590f90f5e31c954481f89ba30b72712024691490f22ac4c82e661f9b6`。本次重新读取其中 `SwapTotal=2709500 kB`，约 2.584 GiB；这只证明当时配置了 swap，不能声称发生了同等写入或已经超额。旧返回没有 `/proc/swaps` 和完整挂载拓扑，因此其承载路径和额度归属未知。

tmpfs 默认可以换出到 swap；三个 16 MiB 节点 tmpfs 不能仅凭“内存盘”排除磁盘写入。准备方案应明确禁用 guest swap，或证明所有换出写入在既有额度内；若考虑 `noswap`，必须核验目标内核/实际挂载支持，且它不能解决其他 guest 内存的换出。关闭 swap 是后续系统操作，不在本次执行。[Linux tmpfs 文档](https://docs.kernel.org/filesystems/tmpfs.html)。

本次只读检查宿主上的目标 `config.plist`：其 UUID 与本包一致，无网卡/目录共享/剪贴板共享，启用 UEFI、关闭 QEMU debug log；仅一个只读 CD 和一个可写 VirtIO QCOW2 系统盘，没有四个资源域盘。配置摘要为 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`。安装的 UTM 为 4.7.5（118）；这些是文件配置事实，不是运行状态、QEMU 实际参数或挂载只读性证明。

| 写入面 | 本次判断 | 继续条件 |
| --- | --- | --- |
| 四资源域 | 配置未创建；满额四盘之外没有余量 | 每域证明 `D + H <= C`，并验证容量拒绝路径 |
| 系统盘与 swap | 系统盘可写，旧 guest 配置约 2.584 GiB swap，完整归属未知 | 获得 swap/mount 事实；系统新增写入只读阻断或落入有硬上限的域 |
| 宿主 backing 与控制文件 | QCOW2 元数据另计；关闭 debug log 只覆盖一种日志 | 列清实际 QEMU 写入目标，包括是否有可写 UEFI 变量/状态、日志和临时文件，逐项绑定硬上限 |
| 构建和 daemon 峰值 | 未安装固定工具，未执行真实构建或 daemon | 在完整边界先成立后实测；不足即失败，不能依靠宿主空闲空间兜底 |

不采用 QEMU `-snapshot` 作为“系统盘不写”的证明：该选项仍将改动写入临时文件。宿主 ENOSPC 还可能使 QEMU 暂停，不能假定它等价于 guest 内可回收的拒绝；后续容量验收必须覆盖监督器失联/暂停及证据回收。[QEMU invocation](https://www.qemu.org/docs/master/system/invocation.html)。UEFI 与 debug log 的配置含义参考 [UTM QEMU 设置](https://docs.getutm.app/settings-qemu/qemu/)；本次没有推断或修改未经核对的变量文件路径。

### 取舍与下一交付

当前否决“按 256/160/240/64 MiB 直接创建四盘，然后装 Docker 并运行”的操作路线。建议保留目标 VM 作为准备候选，先补齐软件输入和承载证据；安装不解决系统盘、swap 或宿主 backing 的额度问题。若 UTM/APFS 始终不能给出硬限制证明，再单独评审具备直接有界块设备的 Linux 后端，不能静默更换平台、扩大 768 MiB 或放宽合同。

补充盘点应一次收齐下表，以免反复启动。本次核对后已按所有者“提交工作区更改，继续推进下一步”的要求完成既有入口的离线扩展和[单次操作包](#补充盘点实施与单次操作包2026-10-09)；随后明确获准执行，但在启动错误后停止，授权已消费，结果见本节之后的实测记录。旧 scope 不扩张，旧结果不补写成新证据。

| 必要事实 | 用途与边界 |
| --- | --- |
| 全部已安装包的名称、版本、架构、状态及关系字段；APT/dpkg 版本和 hold 状态 | 绑定 guest 基线并解析安装差量；不是运行 `apt update/install`，不读取凭据或输出任意源配置 |
| `gpgv`/`sqv` 等现有验签器的存在性、版本与所属包 | 选择成熟验证工具；缺失即记录，不在盘点过程中安装 |
| `/proc/swaps`、mountinfo、根/var/tmp/run 的挂载与块设备对应关系 | 确定 swap 和域外写入面；不执行 swapoff、mount、磁盘创建或格式化 |
| Docker/containerd 的现有 unit/socket 状态与服务启动策略存在性 | 为后续安装抑制与独占 daemon 设计提供输入；不启动、停止或改 unit |

上述缺口闭合前，可完成的仍是离线设计和精确操作包；运行接入、真实构建及 21 样本矩阵不具备放行条件。

## 补充盘点实施与单次操作包（2026-10-09）

上一轮复核的两份文档已提交为 `be7a874`，本单元实现随后提交为 `3331167`，均未 push。所有者已明确确认提交实现并执行包含正常关机及超时强制停止的一次 L3 操作，下述单次授权已经消费，不构成再次启动或续跑授权。没有修改 I5 运行配置、profile、evidence schema 或 STOP；补充盘点也不能证明签名可信、依赖闭包已解出或容量已满足。

### 独立范围与采集边界

沿用 [inspect-sw-i5-guest.py](../../scripts/inspect-sw-i5-guest.py)、[UTM 适配层](../../scripts/sw_i5_utm_result.js)及[回归入口](../../scripts/test_sw_i5_guest.py)，不另设运行后端。新增 guest `--details`、宿主 `--collect-utm details` 和离线 `--validate-details`；使用独立 `scope=guest-preparation-details`、`schema_version=1`，始终 `i5_ready=false`。旧 `guest-preparation-inventory` 和三个原 case 的输出格式/限额保持不变；旧验证器拒绝新 scope，新验证器拒绝旧 scope，不能交叉解释。

| 新字段 | 采集与解释 |
| --- | --- |
| `base_inventory` | 复用原采集，保留其 schema、nonce、网络、内核、块设备和身份存在性事实；补充采集结束再次检查仅 loopback |
| `packages` | `dpkg-query --no-pager -W` 不附包名过滤，返回完整字段表；包含名称/版本/架构、Status（含 hold）、Essential/Protected/Multi-Arch、Pre-Depends/Depends/Recommends/Suggests/Conflicts/Breaks/Replaces/Provides 和 Installed-Size；保留非 installed 行，不冒充全已安装 |
| `tools` / `tool_ownership` | 查询固定目录的 apt-get、dpkg、dpkg-query、gpgv、sqv 存在性及解析后的路径，用 `dpkg-query -S` 查询归属；结合包表确定所属包版本，不执行这些工具的版本探针。未找到是空路径列表；存在但归属查询失败则停止，不猜测版本 |
| `mounts` / `swaps` / `filesystems` | 读取 proc mountinfo/swaps 与 `/`、`/var`、`/tmp`、`/run` 的设备号和可用字节；保留挂载拓扑/传播关系/路径/文件系统、`/dev/` 来源，分别保存单个挂载和 superblock 的 ro/rw/noswap/size/nr_inodes，避免将只读 bind 与底层可写混为一项。剔除其他来源和任意 options，不留存原始 mountinfo。swap 保留承载路径/类型/大小/已用量/优先级，不读内容 |
| `services` | 仅对 docker.service、docker.socket、containerd.service、containerd.socket 执行 `systemctl show --all --no-pager`，限定 Id/LoadState/ActiveState/SubState/UnitFileState；另查 policy-rc.d 存在性，不读其正文或执行。exit 1 只有在全部四条记录完整且含明确 not-found、无 stderr 时接受；不从空返回推定服务不存在 |

dpkg 的字段语义来自 [Debian dpkg-query 手册](https://manpages.debian.org/trixie/dpkg/dpkg-query.1.en.html)，属性选择来自 [systemctl 手册](https://manpages.debian.org/trixie/systemd/systemctl.1.en.html)，挂载字段来自 [proc_pid_mountinfo](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)。这是独立实现，无复制第三方实现或新增依赖。不会读取 apt 凭据、任意源配置、私钥、machine-id 正文、进程参数、服务 Environment/ExecStart 或用户文件内容。

`3331167` 初版中，新 scope 的完整 stdout/stderr 每条最多 512 KiB，传输 stdout/stderr 每条最多留存 2 MiB；原 case 仍为 128 KiB/512 KiB。新增命令各限时 8 秒，当时 stdout 验收上限统一为 256 KiB、stderr 8 KiB；proc 单文件最多读取 256 KiB 加一个越界检测字节。后续 `3aab466` 仅将 package-table stdout 调整为 512 KiB，见[已应用提案](#调整提案及证据边界已获准应用)，其他限额不变。超限、重复包、缺列、部分服务记录、错类型、未知顶层字段、nonce/scope 混淆均失败，不截短为成功结果。JXA/Python 的 55/60 秒回收限时不变。子进程输出仍先 capture 再检查，这是返回与留存上限，不是内存/文件系统硬隔离或 768 MiB 验收。

### 已执行的单次操作合同

精确目标为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`；本次 nonce 为 `aaaf701e67ec731dafe6432503f34635`，已消费。操作包保留在本地忽略目录 `.tmp/i5-guest-return-aaaf701e67ec731dafe6432503f34635/`：`operation.json` 记录授权、基准/执行 revision 和执行源摘要；`run_inventory.py` 沿用先前一次性控制顺序并增加失败收尾保护，`test_control.py` 仅为合成生命周期验证。它们不是常驻服务或第二套 I5 运行入口。

执行前 `operation.json` 的 `authorized=false`，控制脚本会在任何应用调用前拒绝。得到当前任务的明确批准后，已先提交本单元并绑定执行 revision，复核所有源摘要，再将该次授权记录置 true。本次使用以下唯一入口；现有 `attempt.json` 会拒绝再次执行：

```text
python3 -B .tmp/i5-guest-return-aaaf701e67ec731dafe6432503f34635/run_inventory.py --authorized-once
```

入口按下列顺序执行；所有子命令的 stdout/stderr、退出/超时、配置摘要与结果留存于同一目录，不覆盖既有证据：

1. 校验源摘要、精确目录及新建 `attempt.json`，已有 attempt 即拒绝，不续跑。只读检查目标配置；必须无网卡、剪贴板关闭、目录共享 None。调用 `utmctl list` 和 `utmctl status <UUID>`，目标必须 stopped，保存全部 VM 状态。前置失败不启动、不停止用户已在运行的 VM。
2. 一次 `utmctl start <UUID> --hide`，最多 60 秒；启动后等待 30 秒。再复核配置，执行一次 `python3 -B scripts/inspect-sw-i5-guest.py --collect-utm details --nonce aaaf701e67ec731dafe6432503f34635`。控制层最多等待 65 秒供原 60 秒回收层保存失败；不重发 execute、不重跑旧 success/failure/inventory case。guest 命令为 `/usr/bin/python3 -I -B - --nonce <nonce> --details`，源码经 stdin 传入。
3. 仅在真实退出 0、无 signal/stderr、新 scope 验证及保存文件逐字匹配均通过时记录采集成功。缺工具、查询失败、权限提示、超限或超时均停止采集；不安装、不更换通道或自动授权系统权限。
4. 启动尝试后无论成功失败，通过 finally 对同一 UUID 执行 `utmctl stop <UUID> --request`。每次最多间隔 30 秒复查，等待最多 120 秒；仍未 stopped 时才执行一次 `utmctl stop <UUID> --force`，随后检查状态，不使用 kill。单个命令或日志写入失败会被记录，不跳过其余关机步骤。强制停止作为非正常结果保留，不能把该次报告为完整成功。
5. 最后比较全部 VM 状态及目标配置摘要；其他 VM 不修改。保存 `result.json`；目标未停、配置变化、其他 VM 状态变化、强制停止或任意错误均返回失败，交由人工处理，不自行修复或重试。

预计 5–10 分钟。主要副作用为 UTM/该 VM 的一次启动和关机、正常系统日志/虚拟磁盘写入及宿主准备证据；这些启动写入尚无 I5 容量证明，本包不是 I5 批次运行。控制层普通命令双流各留存最多 64 KiB，details CLI 双流各最多 2 MiB，超限仍为失败；不声称 UTM/QEMU 的内存或系统写入受这些输出限额约束。清理采用正常关机及上述超时强制停止，保留专用副本、隔离配置、源码包与全部失败证据，不删除磁盘或恢复共享。强制停止有未完成写回风险。

本次已确认范围同时包含启动、一次 details、正常关机及超时强制停止；不包含开网/共享、依赖安装更新、swapoff、挂载/格式化、身份修改、构建、daemon 启动、I5-R、源 VM/其他 VM 修改或远程写入。采集后在宿主离线复核新事实，再收敛依赖与容量设计，不能从采集成功直接放行安装。

### 本单元验证

- Python 回归 40 项通过，含原 27 项及完整包表、hold/Pre-Depends 保留、范围分离、512 KiB 新限额与旧限额保留、嵌套字段/部分输出拒绝、挂载敏感 options 过滤、网络前后检查、命令超时与证据回收。
- 适配层纯 JavaScript 自测 26 项通过；使用 Node 的独立 vm context 运行原 `--self-test`，无 Application/ObjC/UTM 调用。这不是本轮实际 JXA 或 guest 验证。
- 一次性控制脚本 7 项合成测试通过：正常完成、采集失败、采集超时、等待超时后的强制停止、关机日志写失败后继续收尾、已启动目标拒绝及未授权拒绝；同时覆盖已消费 attempt 不重跑。全部外部命令被 mock，未控制真实 VM。
- `--help` 退出 0；真实 Debian 字段返回、包表实际体积、UTM 新 case 传输及关机结果均待上述单次操作验证。
- 提交前 `./scripts/check-repo.sh` 通过（189 文件），`git diff --check` 通过。当时未启动应用/VM、安装依赖或改变远程状态；随后获准的一次真实操作单独记录如下。

## 补充盘点单次操作结果（2026-10-09）

**结果：启动阶段出现事件错误，未执行 guest details；正常关机等待超时后强制停止一次，目标最终 stopped。控制脚本退出 2，不能报告盘点通过。** 本次按已批准范围执行，没有重试启动、重新提交 guest 命令或更换通道。

| 步骤 | 实际返回与结论 |
| --- | --- |
| 输入绑定 | 执行 revision `3331167bb2762c9383ed22bda95e17d584b0a185`；复核源摘要一致，记录本次授权并新建 attempt |
| 启动前 | list/status 均退出 0，目标 stopped，配置隔离检查通过 |
| `utmctl start <UUID> --hide` | 退出 0，stdout 0 bytes，stderr 164 bytes，包含两条 `Error from event: The operation couldn’t be completed. (OSStatus error -10004.)`；按 stderr 非空规则失败，不用退出 0 覆盖错误 |
| guest 采集 | 未进入 details CLI，无 details 目录、guest 结果或新的包/swap/mount/service 事实 |
| 正常关机 | `stop --request` 退出 0、无 stderr；后续状态查询仍为 started，等待至 120 秒没有确认停止。实际 started 说明启动并非完全未生效，不能把报错描述为“VM 从未启动” |
| 超时回收 | 同一 UUID 的 `stop --force` 一次，退出 0、无 stderr；随后状态退出 0、stdout 为 stopped；未使用 kill |
| 收尾 | 前后全部 VM 状态清单逐字一致，目标配置摘要一致；没有变更其他 VM、安装依赖或执行构建/daemon/I5-R；本次控制进程已退出 |

本地证据根为上述 nonce 目录。`result.json` SHA-256 为 `56b962363cae4e184d45ce44d07c14bc6b7a43f5772308f452a289c438d9671c`，`start.stderr` 为 `4f4bedf1feb156b4ef0c65a1f55a72b85090c305df18065df7034075feb8de45`；前后 VM 状态清单摘要均为 `c6ae13589ae5b9473a3edd813ac7250bfe977b0a1ca2b8126620c6a58a4d952d`，目标配置摘要均为 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`。

本次只证明错误拒绝与超时回收分支实际执行，并确认最后停止；没有证明新采集字段、512 KiB 返回或真实依赖/容量条件通过。未完成启动事件错误根因诊断，也没有运行 guest 文件系统检查；强制停止可能留下未完成写回，不能由配置摘要相同推定系统盘完整性。

下一步先在宿主只读定位 `start --hide` 的事件错误及启动/关机行为，再按具体根因决定是否修改控制层和制定新单次操作包。不得把“VM 最后启动过”作为忽略 stderr 的理由，或将本次授权沿用为再次启动/盘点。原依赖、验签、swap 和容量缺口继续保留。

## 启动事件错误的只读诊断（2026-10-09）

上述失败记录已提交为 `71def9a`，未 push。本次仅核对已有两次原始证据、控制脚本、安装文件和上游固定版本源码；未调用 utmctl/应用脚本接口或重新查询、启动 VM，也未改系统权限、签名、安装文件或控制逻辑。

**诊断结论：高概率触发点是 `--hide` 附带的应用/窗口事件；本次提前收尾的直接原因，则已确定为新控制脚本拒绝非空 stderr。** 这两层要分开：尚无逐条 Apple event 的本机观测，不能声称已经证明具体哪条窗口调用被拒绝，也不能据错误码推定 VM 启动命令未生效。

| 核对对象 | 实际发现及含义 |
| --- | --- |
| 两次启动 stderr | 2026-10-06 成功盘点目录中的 `start.stderr` 也有相同两条 `-10004`，与 2026-10-09 失败目录逐字相同，均为 164 bytes、SHA-256 `4f4bedf1feb156b4ef0c65a1f55a72b85090c305df18065df7034075feb8de45`。这是原记录未明确披露的启动诊断，不是此次 guest details 新引入的错误 |
| 两版控制层 | 10-06 的 `command()` 保存 stderr，但启动分支只检查 exit code，随后等待 30 秒并执行三项 guest case；10-09 的 `command()` 同时拒绝 stderr，因而在执行等待和 details 之前进入 finally。保留严格拒绝是正确的，不能恢复旧脚本的漏检 |
| UTM v4.7.5 CLI | 通用入口在 `hide=true` 时先设置 auto terminate、枚举窗口并尝试关闭名为 UTM 的窗口，再执行子命令；真正 Start 子命令调用 VM 的 startSaving。事件失败 delegate 写 stderr 后返回 nil，没有在该处抛出错误；因此“打印事件错误但命令退出 0、VM 实际启动”与源码路径一致 |
| 本机权限和术语 | 实际 PATH 指向 `/Applications/UTM.app/Contents/MacOS/utmctl`，UTM 为 4.7.5（118）。现代方式读取的 entitlement 声明 app-sandbox 与 `com.utmapp.UTM.vm-access` scripting target；安装的 UTM.sdef 将 VM 接口放在此组，同时包含 CocoaStandard 的窗口接口。这支持可选窗口操作与 VM 操作权限范围不同的候选解释，但不等于本机拒绝事件已被逐项定位 |
| 错误码与关机语义 | 本机 SDK 的 MacErrors.h 将 `-10004` 定义为 `errAEPrivilegeError`。该名称只表达权限违例，不能据此要求重置 TCC 或扩大系统权限。UTM 的 request 定义明确允许 guest 忽略电源请求，返回 0 不代表已关机 |

源码与定义依据：[UTMCtl.swift v4.7.5](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/UTMCtl.swift#L49-L68)、[事件错误处理](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/UTMCtl.swift#L108-L126)、[上游 entitlement](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/utmctl.entitlements)、[Apple 错误定义](https://developer.apple.com/documentation/coreservices/erraeprivilegeerror)、[UTM stop method](https://docs.getutm.app/scripting/reference/#utm-suite)。上游用户的 [Issue #5509](https://github.com/utmapp/UTM/issues/5509)也报告过带 `--hide` 的 clone 返回该错误但实际完成操作；其版本与操作不同，只作旁证，不能替代本机验证。

本机只读签名核验需保留环境差异：首次使用旧 `codesign -d --entitlements :-` 得到 deprecated/invalid entitlements blob 警告；改用 `codesign -d --entitlements -` 能读取声明。随后 `codesign --verify --strict --verbose=2 /Applications/UTM.app/Contents/MacOS/utmctl` 在沙盒内退出 1，报 invalid signature；同一命令获准在沙盒外复核退出 0，报告 valid on disk 且满足 Designated Requirement。不能将沙盒内结果写成工具损坏或发生篡改，也不能把核验通过当作全部运行行为已证明。

本轮读取的 `utmctl` SHA-256 为 `288e61a73f0b70d9986687a8adc0f05bf2009e8f3843754288d2d174551c8ba5`，UTM.sdef 为 `b4fd52c64433658aeb3777774a06c2c1a77e2de611050928f5d55e9e626928b3`；这些绑定本次安装文件，不追溯证明过去所有运行的二进制相同。

关机超时的一个合理解释是：本次在启动返回错误后直接发送 request，跳过原定的 30 秒启动等待，guest 可能尚未准备好处理电源请求。旧次采集完成后再关机成功与此解释相容，但没有本次 guest 启动日志，不能排除其他 guest 原因，也不能说已证明 ACPI 故障或系统盘损坏。

### 最小修正方向与验证边界

下一实现建议只从新操作包的 `utmctl start <UUID> --hide` 去掉 `--hide`，保留同一 UUID、现有采集器、网络/共享隔离、stderr 非空即停止、单次执行和关机回收。该选项不是无网隔离或 VM 无显示后端的开关；去掉后不再执行 CLI 的 auto terminate/窗口关闭分支，允许 UTM 窗口保持可见。不通过忽略特定错误、改权限、重新签名、安装新版或换执行通道取得表面成功。

新包还应把启动尝试时刻与“VM started/guest 就绪”分开记录，并在失败收尾设计中明确启动尚未完成时的处理时序；不要把盲目增加 sleep 或仅延长关机超时当成已修复。首先覆盖无 `--hide` 的精确 argv、任意 stderr 仍拒绝、失败后不采集、单次启动及有界回收的离线回归，再提交新的精确操作包。现有 nonce/attempt 和源摘要均保留，不原地改写已消费操作包。

本次未修改执行代码，也未生成新的启动授权。是否能消除事件错误、完成 details 并正常关机仍需一次另行批准的真实操作；强制停止后的 guest 文件系统完整性也未验证。10-06 三项 guest 结果仍有有效原始证据，本次补记其启动 stderr 和旧控制层局限，不回写旧证据或把“guest 结果有效”扩展成“整个生命周期无错误”。

## 启动控制最小修正与单次包（2026-10-09）

在 `8652928` 诊断提交之后，已将旧单次目录中的控制逻辑收敛到 [sw_i5_utm_control.py](../../scripts/sw_i5_utm_control.py) 和[离线回归](../../scripts/test_sw_i5_utm_control.py)。旧操作目录及其中脚本保持原样；新入口只负责已授权补充盘点的启动/回收，不接入 I5 运行入口。采集器、JXA 适配层、guest scope/schema/限额、768 MiB 合同和全部 STOP 均未改动。

### 实施结果与时序含义

- 启动 argv 固定为 `/Applications/UTM.app/Contents/MacOS/utmctl start B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`，移除 `--hide`；不执行窗口关闭或 auto terminate 设置，允许 UTM 窗口显示。绝对工具路径及摘要绑定避免 PATH 换用其他副本。
- 任意 stderr、非零退出、超时、超限或证据写入错误仍失败。启动失败后不进入 details，即使 VM 实际已启动也不忽略错误；始终转入回收。
- 单调时钟事件分别记录 start-attempt、start-returned、vm-started-observed、boot-grace-complete、details-attempt、guest-details-verified 和关机阶段。`started` 只说明 VM 状态；保留启动调用返回后的 30 秒缓冲期，不是 guest 就绪探针。只有一次 details 的真实返回、scope 校验及落盘证据逐字匹配全部通过，才设置 `guest_details_verified=true`。
- 被拒绝的启动也可能已生效，因此失败后正常关机请求同样不早于启动调用返回后的 30 秒；没有增加缓冲长度或关机超时，也不把这一时序安排声称为 ACPI/文件系统修复。超时启动可能已运行多久仍未知，不重试启动或追加 guest 探针。
- 完整结果的 `passed` 只有在采集验证、目标停止、全部 VM 状态和配置不变、无错误且无强制停止时才为 true；有效采集与成功回收分开记录。新本地操作/结果分别使用 `i5-preparation-lifecycle-operation` / `i5-preparation-lifecycle-result`、schema 1，不是公共协议或 I5 evidence schema 的扩展；旧操作包不被新入口接收。

### 新单次操作合同：已授权执行并消费

精确目标仍为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。新 nonce 为 `84eef7a6f33f18cb4aa86c385d6c71a7`；本地忽略目录 `.tmp/i5-guest-return-84eef7a6f33f18cb4aa86c385d6c71a7/operation.json` 已固定上述基准 revision、五份源码/测试摘要、安装工具摘要及目标配置摘要，准备时 `authorized=false` 且没有 attempt。源码摘要覆盖基准之后的未提交实现；随后所有者明确授权本包，复核摘要一致后置 true 并执行一次，现已消费，结果见下节。

本次唯一执行入口为：

```text
python3 -B scripts/sw_i5_utm_control.py --authorized-once --nonce 84eef7a6f33f18cb4aa86c385d6c71a7
```

1. 在任何应用调用前检查当前授权、schema/字段、nonce/UUID、全部源摘要、工具摘要、配置摘要与无网卡/无共享条件；拒绝重定向的操作路径、缺失摘要和已有证据。独占新建 attempt，失败也消费该次尝试。读取全部 VM 状态及目标 stopped 基线；前置失败不启动、不停止用户已运行的 VM。
2. 上述精确 start 一次，最多 60 秒；不带 `--hide`。成功后检查同一 UUID 的 started 状态，经过上述 30 秒缓冲后复核隔离配置，再执行一次 `python3 -B scripts/inspect-sw-i5-guest.py --collect-utm details --nonce 84eef7a6f33f18cb4aa86c385d6c71a7`，控制层最多 65 秒。guest 仍只执行 `/usr/bin/python3 -I -B - --nonce <nonce> --details`，不重发或重跑其他 case。
3. 启动尝试后，无论结果如何，按上述缓冲时序对同一 UUID 执行 `utmctl stop <UUID> --request`；查询最多等待 120 秒、间隔不超过 30 秒。仍未确认 stopped 才执行一次 `utmctl stop <UUID> --force`，随后复查。这里的 utmctl 均指上述固定绝对路径；普通单命令最多 15 秒，不使用 kill。
4. 复核全部 VM 状态和目标配置，保存各命令双流/退出信息、阶段时序及最终结果；超时、强制停止、状态变化、配置变化和证据错误均保留为失败，不自动修复或重跑。关机命令/日志写入失败不跳过后续收尾步骤。

预计 5–10 分钟。主要副作用为可能显示 UTM 窗口、目标 VM 一次启动和关机、系统盘及宿主日志写入、宿主证据文件；强制停止可能留下未完成写回。正常关机及超时一次强制停止是本包完整回收范围；保留专用 VM、隔离配置及全部证据，不删除磁盘或退出用户应用。源 VM 和其他 VM 不操作。普通命令双流各最多留存 64 KiB，details CLI 各 2 MiB，超限失败；这不是进程内存、宿主写入硬上限或 I5 容量证明。

本包不包含联网/共享、安装更新、权限或签名修改、swapoff、挂载/格式化、身份重建、文件系统修复、构建、daemon 或 I5-R。此前强制停止后的文件系统完整性尚未证明；若此次启动或盘点失败，保留证据后停止，不另跑 fsck 或改变 guest。完成采集后可在宿主离线分析依赖、验签工具与 swap/容量事实，不能从盘点成功直接放行安装。

### 本轮离线验证与限制

- 新控制回归 3 个测试方法通过，覆盖 25 个生命周期/前置场景及 4 个非法 nonce：精确无 `--hide` argv、退出 0 加 stderr 拒绝、启动超时/启动异常/日志失败后不采集、started 未确认、采集失败/超时/证据不符、正常与强制回收、强制停止失败、其他 VM/配置变化、未授权/源或工具漂移/旧证据拒绝、单次消费和阶段时序。全部外部调用与时钟被 mock。
- 原采集器 40 项回归通过；控制入口 `--help` 退出 0。适配层未改动，本轮未执行真实 JXA、应用或 VM 调用。
- `./scripts/check-repo.sh` 通过（191 文件），`git diff --check` 通过；本轮四个文件尚未提交，未 push，未启动后台进程。当时新操作清单保持未授权且无 attempt；后续实测独立记录如下。
- 上述离线工作只完成实现和新包准备；随后实测在启动前停止，仍未证明去掉 `--hide` 能消除事件错误，也未验证真实包表返回或正常关机。

## 无 hide 单次包的启动前拒绝结果（2026-10-09）

**结果：控制入口退出 1，停在启动前基线检查；目标状态为 stopped，没有执行 start、guest details 或关机命令。** 所有者已明确授权上节完整单次包；本次没有修改冻结源码或放宽 stderr 检查，也没有重试。新建 attempt 后失败同样消费 nonce，四个历史单次授权现均已消费。

| 步骤 | 实际结果与限制 |
| --- | --- |
| 授权与输入 | 五份源码/测试、utmctl 安装文件及目标配置摘要一致；记录本次授权并新建 attempt；源码尚未提交，按操作清单 SHA-256 绑定 |
| `utmctl list` | 退出 0，stdout 750 bytes、stderr 666 bytes。stdout 摘要与前次 VM 状态清单相同；stderr 包含 TISFileInterrogator 的输入源缓存无效诊断及三组 duplicate keyboard layout identifier/replaced 诊断，因此被严格拒绝 |
| 目标状态 | 随后的 `utmctl status <UUID>` 退出 0、无 stderr，stdout 为 stopped；控制层随后报告 pre-boot baseline failed 并退出 1 |
| 未进入的阶段 | 无 start 命令、无 details 目录、无 guest 新事实；没有因本次失败触发正常/强制关机，也不能说已经验证无 `--hide` 的真实启动效果 |
| 退出后只读核对 | 配置摘要仍为 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`；仅比较已有本地文件，没有再次调用应用接口或查询 VM |

证据保留于 `.tmp/i5-guest-return-84eef7a6f33f18cb4aa86c385d6c71a7/`。`list-before.stderr` SHA-256 为 `0dcf51a4e58c40822f26b9311c23a751b1eba9d72212058385cf0cc6c3177930`，stdout 为 `c6ae13589ae5b9473a3edd813ac7250bfe977b0a1ca2b8126620c6a58a4d952d`。启动前拒绝分支位于生命周期 try/finally 之前，因此没有生成控制器 `result.json`；原始命令双流、退出 JSON、attempt 和工具退出码仍在，另存 `review.json` 明确标为事后复核，不冒充控制器或 guest 结果。

对现存各单次目录的顶层 stderr 只读比对发现，本次输入源诊断与过去两次 start 的 `OSStatus -10004` 不同，所查历史文件中未见相同输入源诊断。这只是已保留证据范围内的事实，不能推定警告必然无害、每次会复现、源自某一输入法，或与 VM guest 有关。此次调用未请求修改系统输入源；诊断中的 replaced 字样也不能解释为本控制脚本修改了键盘配置。未调查或修改兄弟项目、输入法注册、TCC、应用签名或 UTM 安装。

下一步先只读定位宿主输入源诊断的来源及可重复条件，并补齐启动前拒绝的结构化结果与精准回归；若需真实复现、修改诊断接受策略或改变系统配置，应提出具体范围再确认。不得靠重复运行等候 stderr 消失、过滤字符串或忽略诊断放行。现有源码保持此次冻结版本；完整依赖、验签、swap/容量和 I5-R 缺口继续保留。本次控制进程已结束，目标在最后一次查询时 stopped；没有查询或关闭 UTM 应用本身，不推定整个应用已退出。

## 宿主输入源静态诊断与启动前报告修复（2026-10-09）

本轮根据所有者“继续推进”开展文件/源码只读诊断及离线修复；没有再次执行 utmctl、应用脚本或 VM 操作，四次既有单次授权仍已消费。没有将宿主诊断改成允许列表或忽略 stderr。

### 静态证据与尚未定位的部分

- `/Library/Keyboard Layouts/` 和用户级 `Library/Keyboard Layouts/` 本次枚举均为空；系统对应目录只有 `AppleKeyboardLayouts.bundle`，其 Info.plist 的标识为 `com.apple.keyboardlayout.all`、版本 226。这只能排除所查两个目录中当前存在的自定义布局文件，不能排除输入法内置隐藏布局、运行时注册或缓存问题。
- 只读检查 HIToolbox 偏好中的当前/启用/选择输入源字段，未见错误日志中的三个数字 ID；这些字段不等于所有运行时输入源或缓存的完整表。本轮没有收集输入内容、输入历史、任意环境变量或用户文件正文，也不将偏好中的个人配置复制到仓库。
- 本机 SDK `TextInputSources.h` 说明输入源包含布局、输入法及模式，也存在对系统 UI 不可见的输入法专用布局。因此不能从目录为空或可见偏好中没有该 ID 推定不存在重复，也不能从负数 ID 推定第三方输入法有错。
- [UTM v4.7.5 固定源码](https://github.com/utmapp/UTM/blob/v4.7.5/utmctl/UTMCtl.swift#L174-L192)中 List 只读取 VM 列表并打印 id/status/name；同文件导入 AppKit 和 ScriptingBridge，本机 `otool -L` 可见 Foundation/ScriptingBridge 依赖。这支持“宿主框架初始化路径出现诊断”的候选解释，不能确定是哪一次调用、哪个资源或缓存项触发。未读取到该私有诊断的 Apple 实现依据；网页文档读取失败或搜索无直接解释，不作为根因证据。

现有静态证据不足以确定缓存损坏、重复布局来源或可重复条件，也不足以证明警告无害。没有依据去删除输入源缓存、修改键盘布局、操作输入法注册、重置 TCC、重签名或重装 UTM。兄弟项目保持未修改。

### 已完成的报告修复

修改前将上次执行清单中的五份源码逐字保存到原证据目录的 `source-snapshot/scripts/`，全部与历史清单 SHA-256 一致。旧命令证据、操作清单、事后 review 和缺失的 result 均保持原状；不为旧失败补造新格式结果，也不更新旧源摘要来复用授权。

[控制入口](../../scripts/sw_i5_utm_control.py)现在将 list/status 基线检查纳入异常记录与最终结果保存。新执行若在这一阶段失败，会返回 2、记录 `failure_phase=pre-boot-baseline`、`start_attempted=false`，并保留命令诊断。仅在有干净且明确的状态返回时设置 `status_before` / `stopped`；无法确认时为 null，不能默认为 stopped。没有做前后 VM 比较时 `all_vm_states_unchanged=null`，不伪造未变化结论。启动前拒绝不发出 stop，也不追加应用查询；源码/授权/配置等尚未通过且未创建 attempt 的拒绝仍不写结果。

已进入启动阶段的正常关机、120 秒等待、一次强制停止及后置核对保持原合同。命令证据写入失败现在也直接返回拒绝；最终 result 文件写失败时，控制层在控制台输出带真实原因的失败报告并返回 2，不能先打印 passed 后才暴露落盘失败。结果 scope/schema 1 保留，新增可为空的观测与失败阶段字段；仓库搜索未发现回归测试以外的结果消费者，不修改 guest schema 或 I5 运行证据。

本轮新控制回归 4 个测试方法通过，覆盖 37 个操作场景和 4 个非法 nonce；新增 list/status 的诊断、非零退出、超时、超限、目标缺失、日志写失败、状态未知和结果落盘失败，明确验证不启动/不关机、不补查 VM、真实诊断留存及 attempt 不复用。全部进程与时钟为合成 mock；原采集器 40 项回归和控制入口 help 通过。真实宿主输入源问题与无 hide 的 VM 启动效果仍未实测通过。

`./scripts/check-repo.sh` 通过（191 文件），`git diff --check` 通过。本轮仍为四个未提交文件，未 push；未启动应用、VM 或后台进程，未改系统或远程状态。当时宿主取证包尚未执行；后续获准观察结果独立记录如下。

### 有界取证包：仅宿主观察，已授权执行并消费

为区分现有静态推断与新的宿主观测，已准备 `.tmp/i5-host-input-diagnostic-4d34a7df66809deff3bfdae901ee59a7/`，含 `probe.py`、源码/工具摘要及 `plan.json`；准备时为 `authorized=false` 且无 attempt，随后所有者明确确认执行，复核摘要后置 true，结果见下节。独占 attempt 限制一次执行，现已消费。此包不使用生命周期入口，也不会在诊断干净后继续启动 VM。

本次唯一执行入口：

```text
python3 -B .tmp/i5-host-input-diagnostic-4d34a7df66809deff3bfdae901ee59a7/probe.py --authorized-once
```

精确顺序是 `/Applications/UTM.app/Contents/MacOS/utmctl list` 一次，再对 UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726` 执行同一路径的 `status` 一次，各限时 15 秒，双流各最多留存 64 KiB，保留真实退出/超时/诊断/截断标识。即使首条出现诊断也只按计划完成第二条观察，不重试任何命令；有诊断仍返回 2，结果固定 `i5_ready=false`，无 VM 启动/关机，不运行 guest。无诊断只表示本次未复现，不能追认旧失败、证明根因解决或放行 I5。

预计 1–2 分钟，命令自身累计限时 30 秒；可能激活或显示 UTM，产生宿主框架/应用日志与本地诊断文件，不请求更改系统输入源或 VM 配置。控制进程结束后保留证据，不删除缓存，不退出用户 UTM 应用，不停止任何 VM。此包不包含安装、修复、模拟按键、输入源切换、启动 VM、联网或改变 stderr 接受策略。未经本次明确授权不执行；独立合成检查的未授权、正常、诊断和超时四种场景已通过，所有外部进程均被 mock。

## 宿主单次观察结果与下一盘点包（2026-10-09）

所有者明确确认后，按上述宿主取证包只执行 list 和目标 status 各一次；控制进程退出 0。两条命令均退出 0、无 stderr、无超时或超限。list stdout 为 750 bytes、SHA-256 `c6ae13589ae5b9473a3edd813ac7250bfe977b0a1ca2b8126620c6a58a4d952d`，与前次已保存清单相同；status stdout 为 `stopped` 加换行、8 bytes，SHA-256 `f247a76b2893208aae7751dbf51f4c495efacfb6d9e743802870300f31ac45c8`。没有发出 start、stop 或 guest 命令。

原始证据保留于 `.tmp/i5-host-input-diagnostic-4d34a7df66809deff3bfdae901ee59a7/`；`observation.json` SHA-256 为 `6f2039ec408998cc0b376e4ce10f20ec6a6cbc336ee03aaf5f0eee7f70505df0`，固定 `i5_ready=false`。随后仅通过文件读取核对目标配置，摘要仍为 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`。未进一步查询应用/VM 状态或退出 UTM 应用。

**本次输入源诊断未复现，不能证明根因已修复，也不改判此前的失败。** 没有发现本次查询阻断，后续无需仅为等候空 stderr 而反复诊断；若另获准的一次盘点再遇到任何 stderr，仍按原规则停止。宿主观察授权已消费，不能转用为 VM 启动授权。

### 修复后控制层的单次盘点包：已授权执行并消费

已准备新 nonce `d2296e284bb28efceea73d121e1e08f9`，位于 `.tmp/i5-guest-return-d2296e284bb28efceea73d121e1e08f9/operation.json`，准备时 `authorized=false`、无 attempt，随后所有者明确授权并执行一次，现已消费。清单绑定基准 `8652928f1685d73ccb2c8adc6f9c2c67600b699c` 和其后的五份源码/测试摘要，包括已修复的启动前结构化报告；控制脚本 SHA-256 为 `03db020f3fead3b1dbd01b8f08db84e5b6dd446c385e4a0aab23f76d15d9aae9`，测试为 `e596bd6223fbf81c480de9aea4651f53fd6a38a04c48cecc8c5d943b45dcff26`。源码仍未提交；安装工具和隔离配置摘要继续精确绑定。

本次唯一执行入口为：

```text
python3 -B scripts/sw_i5_utm_control.py --authorized-once --nonce d2296e284bb28efceea73d121e1e08f9
```

精确目标为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。通过全源/工具/配置校验、无网卡/共享检查及 list/status stopped 基线后，执行一次固定绝对路径 `/Applications/UTM.app/Contents/MacOS/utmctl start <UUID>`，不带 `--hide`，最多 60 秒；检查 started，保留 30 秒启动缓冲，复核配置后调用一次既有 `--collect-utm details --nonce d2296e284bb28efceea73d121e1e08f9`，外层最多 65 秒，guest 内容及限额不变。不重复执行，也不改用其他通道。

启动尝试后不论结果都按同一时序执行 `stop <UUID> --request`，最多等待 120 秒、状态间隔不超过 30 秒；仍未 stopped 才强制停止一次并复查。所有 utmctl 均为上述固定绝对路径，普通命令最多 15 秒；最后比较全部 VM 状态和目标配置。未进入 start 的基线失败只保存失败结果，不关机、不追加应用查询。任意 stderr/超时/超限/日志错误仍失败，强制停止也不能报告完整成功。

预计 5–10 分钟。副作用为可能显示 UTM 窗口、目标 VM 启动/关机、系统盘和宿主日志写入及本地证据；强制停止可能留下未完成写回。正常关机和超时一次强制停止构成整个回收范围，保留专用 VM 与证据，不退出用户应用、不删除磁盘或缓存。采集仅查询现有包/工具归属、swap、挂载和选定 unit；不安装、联网、开共享、改输入源/TCC/签名、swapoff、挂载/格式化、修复文件系统、改身份、构建、启动 daemon 或运行 I5-R。成功采集后只做宿主离线复核，不自动安装或放行运行。

本轮未修改执行代码，沿用上节通过的离线回归；文档更新后仓库检查（191 文件）与 `git diff --check` 通过。工作区四个文件仍未提交，未 push；本次宿主取证控制进程已结束，最后目标查询为 stopped，UTM 应用本身未被查询或关闭。

## 无 hide 启动及正常回收通过、details 超限失败（2026-10-09）

所有者明确授权后，复核新单次包 `d2296e284bb28efceea73d121e1e08f9` 的全部源码/工具/配置摘要，执行一次。**控制入口最终退出 2，失败阶段为 details；无 hide 启动和正常关机在本次条件下通过，没有使用强制停止，但完整补充盘点仍失败。** 本次没有重复启动、重发采集或扩大限额。

| 阶段 | 本次真实返回 |
| --- | --- |
| 启动前 | list/status 均退出 0、stderr 为空，目标 stopped；约 0.474 秒完成基线 |
| 启动 | `start <UUID>` 无 `--hide`，退出 0、stdout/stderr 均为空；约 2.789 秒返回，3.411 秒观察到 started。此前两类宿主诊断本次均未出现，不代表已逐项证明其历史根因 |
| guest 采集 | 32.797 秒发出一次 details；JXA 传输退出 0、无 stderr/超时，正确返回 guest exited=true、exit_code=2、signal_code=0；guest stdout 为空，stderr 67 bytes，内容为 `I5_GUEST_INVENTORY_FAILED: dpkg-query output exceeds details limit` 加换行 |
| 失败传播 | 宿主 details CLI 退出 2，控制器记录 `failure_phase=details`、`guest_details_verified=false`、`passed=false`；没有把传输成功写成盘点成功 |
| 回收 | 33.344 秒请求正常关机；63.718 秒确认 stopped，`forced_stop=false`。前后全部 VM 状态逐字一致，配置 SHA-256 一致；控制进程已结束 |

本地证据根为 `.tmp/i5-guest-return-d2296e284bb28efceea73d121e1e08f9/`。`result.json` SHA-256 为 `678f2b4c927400dbe9a1c1b3b89d48dc90b58aec7be4eb9b1d98b9fdeda0781f`；`details/guest.stderr` 为 `d99cf7e8afc5a7bf05e98c30738ccdcad1844561b00dd154290a22d4228fde2b`；前后 list 摘要均为 `c6ae13589ae5b9473a3edd813ac7250bfe977b0a1ca2b8126620c6a58a4d952d`，配置摘要均为 `6c70116bf220ec2b5fbaa13fdcf2806c06c85f82939335b3bd16e8565d9132dc`。五份已执行源码逐字归档到 `source-snapshot/scripts/`，与授权清单摘要一致；review 仅记录授权已消费及真实 result 摘要，不更改原始结果。

### 已定位的边界与剩余诊断缺口

`details_command()` 在子进程 stdout 大于 256 KiB **或** stderr 大于 8 KiB 时返回同一错误；包表 `dpkg-query -W` 与路径归属 `dpkg-query -S` 都经过这个 helper。因此现有失败文本只能证明其中一次 dpkg-query 触发流限额，不能确定是哪条子命令、哪个流、实际字节数或包数量，也不能推定 512 KiB guest 结果上限被触发。guest 结果未序列化输出，不能把之前内部执行的检查当作已取得的新盘点事实。

下一步先在离线实现中补齐超限错误的操作阶段、stdout/stderr 实际字节数及各自限额，覆盖两种 dpkg 查询和两个流的拒绝回归；再依据可核对的体积证据设计完整且有界的采集方式。不得把错误猜成“包太多”后直接扩大预算、删掉依赖字段、截断为成功或再用同一授权尝试。当前没有修改采集器限额或 scope，没有依赖安装、swap/挂载变更、身份处理、构建或 daemon/I5-R 运行。

本次只证明上述一次启动、失败结果传输和正常回收，不证明 guest 文件系统完整性、完整包表、依赖闭包、验签或 768 MiB 容量条件满足。五个 VM 相关单次操作包和一次宿主观察均已消费；后续真实操作仍需新的精确范围。UTM 应用本身未查询或关闭，目标以本次最后状态确认 stopped 为准。

文档更新后 `./scripts/check-repo.sh` 通过（191 文件），`git diff --check` 通过；执行代码本轮未改动，四个文件仍未提交，未 push。

## dpkg 超限诊断细化与下一取证包（2026-10-09）

上述启动控制、回归及实际结果已按所有者要求提交为 `a0b77b0`（`fix(i5): 完善盘点启动回收与失败证据`），未 push。本轮随后仅修改采集器的超限诊断及离线测试，不启动 VM，不改变既有额度、完整字段、scope/schema、采集顺序或失败拒绝。

`details_command()` 的调用者现在显式指定固定操作标签：包表为 `package-table`、工具路径归属为 `tool-ownership`、服务为 `service-state`。超限错误保留原前缀，追加 `operation`、`exceeded`（stdout、stderr 或两者）、两条流的实际字节数及各自限额、子进程退出码。计数在解码前完成，不回显超限内容或动态参数；未知操作标签在执行命令前拒绝。stdout 仍为 262144 bytes，stderr 仍为 8192 bytes，8 秒超时、512 KiB guest 结果及 2 MiB 传输限额均未变。正常查询失败、非空 stderr 和超时继续按原规则拒绝，不用字节诊断替代错误。

历史失败仍不能反推具体查询或真实大小；没有重写 `d2296e...` 的错误文本或执行清单。新诊断只影响下一次按新源码执行时的错误信息，不能证明当前限额足够，也不是对子进程内存的硬限制。

离线验证：

- `python3 -B scripts/test_sw_i5_guest.py`：44 项通过。新增四项测试覆盖两个 dpkg 操作 × 单/双流超限 × 成功/失败退出码，UTF-8 字节边界、恰好等于限额、非空 stderr 继续拒绝、未知标签执行前拒绝，以及两个真实调用点的标签传递；合成 CLI 到宿主保存链确认新诊断完整保留且仍以 exit 2 失败，超限内容/动态参数不进入消息。
- `python3 -B scripts/test_sw_i5_utm_control.py`：4 个测试方法通过，原 37 场景及 4 个非法 nonce 不变；本轮控制层未修改。
- `./scripts/check-repo.sh` 通过（191 文件），`git diff --check` 通过。上述均为宿主离线验证，不涉及实际 UTM/JXA/guest 调用；新四文件改动尚未提交，未 push，无新增后台进程。

### 一次真实限额取证：已授权执行并消费

新清单 `.tmp/i5-guest-return-e13f44e7384cb91280f193aff569ec15/operation.json` 绑定基准 `a0b77b02b00e46b9306f8d84d3e4666b5a6cbce4`、其后的五份源码/测试、固定 utmctl 和隔离配置摘要；准备时 `authorized=false`、无 attempt，随后所有者明确确认并执行一次，现已消费。采集器摘要为 `53f8e0258ab728d6d32c46e0f08be7bd5c89eba1634ad988f1a1f2ed4388eb43`。本次目的为取得可区分的真实超限证据；如果仍超限，完整盘点仍必须失败，不能为了获得成功扩大额度。

本次唯一执行入口：

```text
python3 -B scripts/sw_i5_utm_control.py --authorized-once --nonce e13f44e7384cb91280f193aff569ec15
```

精确目标仍为 `RadishLink-I5-Debian13-ARM64` / `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。严格校验源码/工具/配置、无网卡/共享、list/status stopped 后，仅一次固定绝对路径 `/Applications/UTM.app/Contents/MacOS/utmctl start <UUID>`（无 hide，60 秒）；确认 started，保留 30 秒缓冲并复核配置后，只运行一次 `--collect-utm details --nonce e13f44e7384cb91280f193aff569ec15`（外层 65 秒）。任意诊断仍停止，不重试或追加命令。

启动尝试后成功或失败均正常关机，等待至多 120 秒，仍未停止则强制停止一次并复查；回收使用同一路径的 `stop <UUID> --request` / 必要时 `stop <UUID> --force`，普通命令限时 15 秒。未进入 start 的失败不关机。最后保存真实结果并比较全部 VM 状态和配置，强制停止、错误或不一致均失败。预计 5–10 分钟；可能显示 UTM 窗口并产生系统盘/宿主日志和本地证据写入，强制停止有未完成写回风险；结束后保留专用 VM 与全部证据，不退出用户应用、不删除磁盘或缓存。除增强错误信息外，范围与上次完全一致，不安装、联网、开共享、改身份/输入源、swapoff、挂载/格式化、修复文件系统、构建或执行 daemon/I5-R。

## 包表 stdout 真实超限结果与有界调整提案（2026-10-09）

所有者确认后执行 `e13f44e7384cb91280f193aff569ec15` 单次取证包。无 hide 启动正常，guest details 仍以 exit 2 失败；正常关机于约 62.658 秒确认 stopped，未强制停止，前后全部 VM 状态及目标配置一致。增强诊断给出的本次事实为：

| 字段 | 真实返回 |
| --- | --- |
| `operation` | `package-table`，对应完整包表 `dpkg-query -W` |
| `exceeded` | `stdout` |
| `stdout_bytes` / `stdout_limit` | 385968 / 262144 bytes，约 377 KiB 超过 256 KiB |
| `stderr_bytes` / `stderr_limit` | 0 / 8192 bytes |
| 子查询 `exit_code` | 0；查询执行成功，返回体积被当前采集策略拒绝 |

宿主传输退出 0、无诊断/超时，guest stdout 为空、stderr 199 bytes，保留完整数值；没有取得完整包表 JSON，也未进入后续工具归属/挂载/swap/service 补充采集。旧次没有细节的失败不能据此改写，本次新证据单独成立。

本地根目录为 `.tmp/i5-guest-return-e13f44e7384cb91280f193aff569ec15/`。`result.json` SHA-256 为 `4183c74957f69563eabf0c95c16c52d4e9375e58bc0c7b04e8f493c0fab56543`，guest stderr 为 `98a470075546f4e997e127f481b94b5bf0939d6e62bf6f07478d6264e02c7a57`。五份执行源码已按原清单摘要归档到 `source-snapshot/scripts/`，授权消费另记 review；原始证据未重写。控制进程已结束，未追加 UTM 查询或关闭用户应用；六个 VM 相关单次包和一次宿主观察均已消费。

### 调整提案及证据边界：已获准应用

真实字节数表明当前完整包表无法通过 256 KiB 门。建议仅把 `package-table` 这一个查询的 stdout 验收上限改为 **512 KiB（524288 bytes）**；本次观察值低于提案上限 138320 bytes。此余量不是未来包表大小保证，也不能由原始表长度推定完整 JSON 一定低于最终限额。

工具归属和服务 stdout 继续为 256 KiB，所有查询 stderr 继续为 8 KiB；8 秒查询超时、最终 details 512 KiB、宿主传输 2 MiB、旧 inventory 限额及 I5 整批 768 MiB 均保持不变。保留所有包、关系字段和严格 schema 校验；不截断、删字段或压掉错误。若后续完整 JSON 或其他阶段仍超限，继续失败并保留证据，不自动扩容。这个提案调整的是环境准备子查询的返回验收上限，不提供对子进程内存或宿主磁盘的硬限制证明。

可审阅候选保留在 `.tmp/i5-package-table-limit-review-20261009/`：`proposal.diff` 为两文件补丁，另有拟应用源码/测试及前后摘要，准备时 `review.json` 的 `applied=false`；随后所有者明确确认，按前后摘要复核后已应用。候选及应用后的 45 项离线回归均通过，覆盖观察体积 385968、提案边界 524288 接受和 524289 拒绝，并明确验证归属/服务仍在 262145 拒绝、最终结果与传输限额不变。所有子进程为 mock，测试不代表真实完整盘点会通过。

### 实施与实测包：已授权执行并消费

可批准的完整范围为：复核上述候选和当前源码摘要，应用这两个文件的精确补丁，运行 45 项采集回归、控制回归及仓库检查，然后仅执行以下新单次包。该范围不包含 Git 提交或 push。新目录 `.tmp/i5-guest-return-bc35d1722b5534637cf3e5fc06adae40/` 准备时只有未授权的 operation.json、无 attempt；清单绑定拟应用源码摘要，获准应用并通过检查后才执行，现已消费，旧授权不能复用。

```text
python3 -B scripts/sw_i5_utm_control.py --authorized-once --nonce bc35d1722b5534637cf3e5fc06adae40
```

目标仍为 `RadishLink-I5-Debian13-ARM64` / `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。校验固定源码/工具/配置、无网卡/共享及 stopped 基线后，按同一控制层执行一次绝对路径 `/Applications/UTM.app/Contents/MacOS/utmctl start <UUID>`（无 hide，60 秒），确认 started、保留 30 秒缓冲、复核配置，再采集一次 `details`（该 nonce，外层 65 秒）。启动尝试后正常关机，等待至多 120 秒，仍未停止才强制停止一次并复查；普通控制命令 15 秒，前置失败不关机，任意 stderr/错误仍拒绝。

预计 5–10 分钟，包含可能显示 UTM、启动/关机产生的系统盘/宿主日志和本地证据写入；强制停止有未完成写回风险。保留 VM 和全部证据，不删除磁盘/缓存或退出用户应用；不联网、开共享、安装更新、改身份/输入源、swapoff、挂载/格式化、修复文件系统、构建、启动 daemon 或运行 I5-R。实测完成后仅在宿主离线复核数据；失败不追加运行或调整其他限额。

当时只执行已获准的增强诊断包并离线准备提案；后续获准应用和实际结果单独记录如下。文档更新后仓库检查（191 文件）及 `git diff --check` 通过。当前四文件改动仍未提交、未 push。

## 完整补充盘点与正常回收通过（2026-10-09）

所有者明确确认后，按候选前后 SHA-256 应用包表专属 512 KiB 上限；45 项采集测试、控制回归和仓库检查通过，再执行 `bc35d1722b5534637cf3e5fc06adae40` 一次。**本次控制入口退出 0，guest details 完整通过，VM 正常关机，无强制停止；前后全部 VM 状态和目标配置一致。** 约 33.046 秒完成采集，63.414 秒确认 stopped。该授权已消费，没有追加运行、安装或改变其他限额。

- guest stdout 为 474110 bytes，小于最终 524288 bytes 上限，余量 50178 bytes；stderr 为空。该余量只是本次结果，不保证未来包表增长后仍满足。
- 宿主传输 stdout 为 632402 bytes，stderr 为空；独立离线 `--validate-details` 再次通过，结果始终 `i5_ready=false`。
- 本地证据根为 `.tmp/i5-guest-return-bc35d1722b5534637cf3e5fc06adae40/`；result SHA-256 为 `f3905f10eb65d36ff14c90240bf75efaa41935ffe4ab3351f9931825e492efa4`，guest stdout 为 `0eea97df8ad7c11b61e7cf5da3b4774d32e3fcb2b7d90c23066f35f66a92c300`，传输 stdout 为 `339d94f52c879ba21c0a2b5703a20695bf8f6ab8998448ead6bdbb2de348ed15`。五份执行源码按清单摘要保存在 `source-snapshot/scripts/`，review 记录授权消费与实际成功结果。

### 新事实及其工程含义

| 范围 | 本次 guest 事实 | 后续含义 |
| --- | --- | --- |
| 完整包表 | 1565 行，1282 个 arm64、283 个 all；状态均为 `install ok installed`，未见 hold。按表字段回算原始 TSV 为 385968 bytes | 补齐已安装包基线；不是完整安装差量解析或包数据库健康审计 |
| 验签/包工具 | 路径归属确认 `/usr/bin/apt-get` 属 apt 3.0.3，dpkg/dpkg-query 属 dpkg 1.22.22，gpgv 属 2.4.7-21+deb13u1+b4，sqv 属 1.3.0-3+b2 | guest 已有成熟验签器，不需要为了后续验签先安装工具；本次未执行验签、导入 key 或读取 apt 源/凭据 |
| 已有候选基础依赖 | libc6 2.41-12+deb13u3、libseccomp2 2.6.0-2、libsystemd0 257.13-1~deb13u1、init-system-helpers 1.69~deb13u1、nftables 1.1.3-1；apparmor、ca-certificates、procps、xz-utils 也已安装 | 可用于固定版本依赖解析，不能代替 Debian 版本/替代依赖/冲突和安装顺序求解 |
| 明确未安装的包 | 包表未见 docker-ce/CLI/Buildx、containerd.io、docker.io/containerd/runc、golang-go、iptables、git、git-man、pigz；原工具路径检查也未见 Go/Docker/containerd/runc | 安装差量至少还要处理固定工具候选、iptables 和项目实际所需 Git；pigz/其他推荐包需显式取舍，不据此自动安装 |
| swap | `/dev/vda4` 分区，2709500 KiB，优先级 -2，采样 used=0 | 明确落在系统盘；used=0 不能证明整个运行期间没有换出，也不能作为 I5 额度归属证明 |
| 根与 EFI | `/` 与 `/var` 同为设备 254:3，对应 `/dev/vda3` ext4，可写且根传播为 shared；`/boot/efi` 为 `/dev/vda2` 可写 vfat，efivarfs 也可写 | 系统盘及固件变量写入面仍需明确归属和硬限制；构建私有 namespace 尚未建立 |
| 临时挂载 | `/tmp`、`/run`、`/dev/shm` 为可写 tmpfs，所采 flags 未见 noswap；特定 systemd credentials tmpfs 则明确带 noswap | 不能把普通 tmpfs 推定为不换出；没有创建 I5 三个 16 MiB 节点 tmpfs 或四个容量域 |
| 服务与安装抑制 | 四个 Docker/containerd service/socket 均 not-found、inactive/dead；选定属性查询 exit 0；policy-rc.d 不存在 | 没有现有 daemon 服务可复用；后续安装必须先设计显式启动抑制，不能让维护脚本先启动服务 |

本次仍为 Debian 13 ARM64、内核 6.12.101+deb13-arm64、Landlock ABI 6；这些事实不改变“当前 UTM 后端不能进入 I5-R”的结论。来源签名、归档、包内维护脚本/许可材料、完整依赖闭包、build 身份交接、系统盘/swap/宿主 backing 的硬上限均未验证或实施。

### 下一步收敛顺序

1. 用本次完整包表作为精确基线，固定 Recommends 策略及必需 Git/iptables 的安装差量；复核 Pre-Depends、替代依赖、Provides、Conflicts/Breaks/Replaces，不自行写简化解析器冒充 APT 求解。
2. 将发布密钥独立可信依据、现有 Packages/InRelease 和 guest 现有验签器收敛成有界验签/离线解析操作包；本次只确认工具存在和归属，尚无签名验证结果。候选来源 JSON 的 `signature_verified=false`、`install_authorized=false` 继续保留。
3. 基于已确认的 `/dev/vda4` swap、可写根/EFI 和共享传播挂载，明确系统新增写入与宿主 backing 的额度归属；不先创建满额四盘或安装 Docker，再尝试补计费。768 MiB、公开运行 STOP 与 I5-R 条件不变。

当前没有下一份已授权 VM 操作包；七个 VM 相关单次包和一次宿主观察均已消费。本次控制进程已结束、目标最后为 stopped，UTM 应用本身未查询或关闭。实测记录更新后仓库检查（191 文件）和 `git diff --check` 通过；当时四文件尚未提交，随后按所有者收尾要求提交为 `3aab466`，未 push。

## 工具来源与固定输入

以下保留 2026-10-06 的固定候选与准备设计；2026-10-09 的复核没有更新版本、来源候选 JSON、运行配置或 evidence schema。候选缺失的关系字段及新增容量证据以上节为准。

以下是本轮选定的**评审候选**，不是已验证安装锁。清单使用独立 `scope=i5-environment-source-candidates`，固定 `install_authorized=false`、`i5_ready=false`，没有运行入口读取它。后续正式安装锁必须来自通过真实性校验的索引、完整依赖解析和实际文件校验，不能简单把两个布尔值改成 true。

| 输入 | 固定候选 | 当前证据及缺口 |
| --- | --- | --- |
| Go | `go1.26.8.linux-arm64.tar.gz`，63,811,405 bytes，SHA-256 `211ffced9dcb9633a55eac6364816ec0ddd951389a740e88fa8b3337971bdda0` | [Go 官方 JSON](https://go.dev/dl/?mode=json&include=all)和[发布记录](https://go.dev/doc/devel/release#go1.26.8)；未下载/解包；不改变 `go.mod` 的 1.26 |
| Docker Engine / CLI | Docker 官方 Debian trixie arm64 的 `docker-ce` / `docker-ce-cli`，均 `5:29.8.2-1~debian.13~trixie` | 版本、Filename、Size、SHA256、Depends 已从官方 Packages 提取；签名链和包内文件未验证 |
| containerd/runc | 官方 `containerd.io=2.3.6-1~debian.13~trixie` | 不混装 Debian `containerd`/`runc`；包内 runc 的版本、路径和许可须解包后核对，不能把静态 tar 的发布说明直接当成 deb 内部证据 |
| 构建器客户端 | 官方 `docker-buildx-plugin=0.37.1-1~debian.13~trixie` | 当前抓取索引可见此版本；[上游已有 0.37.2](https://github.com/docker/buildx/releases/tag/v0.37.2)，正式锁定前须处置差异，不能用 latest 静默替换候选 |
| 基础依赖 | 来自 Debian trixie 的固定依赖闭包 | 仍需按 guest 已安装版本解析 libc6、libseccomp2、libsystemd0、iptables/nftables 等；Git、procps、xz-utils 也是待核验输入，不能由“Debian 已安装”推定齐备 |

Docker 官方的[Debian 安装说明](https://docs.docker.com/engine/install/debian/)区分 `docker-ce`、CLI、`containerd.io` 和 Buildx 等包；本方案不使用联网便利安装脚本，也不执行 `apt upgrade`。顶层五个候选归档合计 134,863,381 bytes，只是传输文件大小，不包含 Debian 闭包、解包体积、只读介质、安装日志或批次构建缓存。环境准备自身的磁盘上限、预计时间和精确回滚仍须在闭包固定后计算。

2026-10-06 查询的 [Debian runc 安全跟踪](https://security-tracker.debian.org/tracker/source-package/runc)将 trixie 的四项问题列为 vulnerable，包括 CVE-2025-52881、CVE-2025-52565、CVE-2025-31133 和 CVE-2026-41579；[containerd 跟踪](https://security-tracker.debian.org/tracker/source-package/containerd)也有未修复项。因此本轮不选“直接安装发行版 Docker 全套”作为默认方案。这不是对合成矩阵可利用性的定论，也不表示官方候选已完成安全验收。官方 [29.8.2 发布记录](https://docs.docker.com/engine/release-notes/29/#2982)列出安全修复和组件更新；正式安装前仍应按固定构件复核 advisory 及功能兼容性。

### 元数据真实性与许可

- 已取得 Docker 官方 `Packages.gz`（56,440 bytes）及 `InRelease`；后者 Date 为 `2026-10-02T16:24:32Z`。Packages 的大小和 SHA-256 与 InRelease 中 `stable/binary-arm64/Packages.gz` 项一致。
- `Packages.gz` SHA-256 为 `3271cf684b10183a5f930877b67efe0294f92ded4718caec59a0fd9a586d7146`；InRelease 为 `247d0572861a9deb52b8e6c1ba065685253af3c5c2fe433ae77f89d15e681ba6`。原文保留在本地忽略目录 `.tmp/i5-environment-plan-20261006/`。
- 当前 PATH 未找到 `gpg` 或 `gpgv`，**未验证 InRelease 的 OpenPGP 签名**。摘要匹配只证明两份材料内部一致；不能证明发布者身份，也不能当作安装通过条件。本轮未安装验签工具、导入 keyring 或自写密码验证算法。
- 正式准备包应绑定经独立核对的发布密钥、签名验证结果、完整索引 hash、每个依赖的 filename/version/architecture/size/hash 及解析后的闭包；索引更新须重新评审，不能自动选新版。
- 安装前取得并保留 Go 归档的 LICENSE/PATENTS、各 deb 的 copyright/NOTICE 及包内第三方清单；记录来源、版本、归属和更新路径。顶层项目的许可证名称不代替闭包审查，也不构成产品分发许可结论。本轮只引用公开元数据，没有复制第三方实现代码。

## 导入与准备阶段

继续保持 VM 无网卡、无剪贴板/目录共享。候选导入方式为宿主验证完整离线包后制成只读介质，经目标专用 VM 的只读光驱接入；不把 guest agent stdin 协议扩展为任意大文件传输，不临时启用共享。当前 `sr0` 已有介质，后续操作包必须先核验并记录原介质引用、替换和恢复动作；本轮不修改它。

候选只读输入根为 `/opt/radishlink/i5/inputs/<bundle-sha256>/`，包括固定工具链、源码和安装清单。源码输入需保留可验证的 Git revision/clean-tree 证据；现有预检会调用 Git，仅复制 `git archive` 后伪造 revision 文件不能替代它。禁止导入宿主 Go cache、预编译本批 bootstrap/node 或既有 Docker 镜像来规避批次计费。

安装阶段只修改目标副本：固定版本依赖、专用账号、只读输入和服务启动抑制。正式命令必须显式阻止 Docker/containerd 安装后自动启动及 socket activation，先检查既有 policy-rc.d/unit 状态；不能覆盖已有控制文件、以 `|| true` 忽略失败或让服务先启动后再关闭。维护脚本写入、源介质卸载、服务状态核验和失败保留都属于该次 L3 包，未获准前不运行。

已存在 machine-id 和三份 SSH 公钥只说明存在性。身份处置限定在专用克隆，方案需说明是否保留或重建、会改变哪些文件及失败恢复；不得读取/记录私钥或把源身份内容复制进 evidence。当前无网络的盘点不要求为继续设计而立即重建身份。

## 无特权构建与权限交接

| 角色 | 可以访问 | 必须拒绝或隔离 |
| --- | --- | --- |
| root 准备者 | 当次批准的磁盘、挂载、namespace、账号和精确权限交接 | 不执行 Go 构建；不把 root agent 直接交给 `build_pair` |
| 专用 build 身份 | 只读工具链/源码、唯一可写 build 域；HOME/cache/temp 全在该域 | root UID、额外组、继承/许可/有效/ambient capabilities、可写域外挂载、Docker/containerd/DBus/guest-agent 控制入口 |
| 监督器身份 | 完成交接后的二进制、证据域和本批独占 Unix Docker endpoint | 其他 VM/项目、共享 Docker context、TCP/SSH endpoint；不将此身份误称为无 Docker 特权身份 |
| 独占 daemon | 明确批准的本批 daemon 目录与容器生命周期能力 | 默认 `/var/lib/docker`、共享 containerd、外部 builder、自动拉取与额外日志目录 |

账号名候选为 `radishlink-i5-build` 与 `radishlink-i5-run`；实际 UID/GID 必须查询并绑定，冲突拒绝，不能直接占用猜测的数字。build 不加入 Docker 组；能连接 Docker socket 的监督器仍具高权限，不能由“非 root UID”推定安全隔离。[Docker daemon 攻击面](https://docs.docker.com/engine/security/#docker-daemon-attack-surface)说明了 socket 权限的意义。

沿用 `sw_i5_build.py` 的单线程、no_new_privs、Landlock ABI ≥ 5、close_fds 和空环境映射。root 在独立 mount namespace 内先设私有传播、建立只读输入/域外挂载，再清空 supplementary groups 与 capabilities 并降权；`mount --bind` 不会自动使所有子挂载只读，必须复核整个 mountinfo。[mount 手册](https://man7.org/linux/man-pages/man8/mount.8.html)、[setpriv 手册](https://man7.org/linux/man-pages/man1/setpriv.1.html)。

只读挂载不能阻止连接其中的 Unix socket，Landlock 文件写规则也不能代替这项控制。构建 namespace 必须遮蔽管理 socket/agent 通道，拒绝继承的连接 FD；不以“全挂载 ro”证明 build 没有 daemon 权限。降权或隔离失败直接停止。

现有容量探测要求四域根目录 owner 等于调用者，不能在不同身份间原样复用同一假设。下一实现需明确两阶段 owner/权限核验及移交：构建进程和后代已回收后，才由准备者对已绑定的确切挂载根及产物路径执行移交，记录前后身份；不递归 chown 未解析目录，不把改变 owner 当成刷新容量额度。此处只细化设计，未修改配置 schema 或现有检查。

## 写入路径与完整容量

各域仍沿用 [768 MiB 分配](sw-g4-synthetic-i5-resource-isolation.md#本次细化linux-块设备容量域)；以下路径是相对实际批次根的候选职责，完整绝对路径须在运行前绑定：

| 域 | 应包含的写入 |
| --- | --- |
| build（256 MiB） | 现有 `go-stage/` 的 HOME/cache/modules/temp、bootstrap/node、构建日志和 Docker build context；Buildx 客户端状态也须显式归属 |
| daemon（160 MiB） | Docker data-root/exec-root、containerd root/state/socket、PID、daemon tmp、builder 元数据、镜像、volumes、daemon stdout/stderr；12 MiB store 保守预留包含在本域内 |
| evidence（240 MiB） | 正常 bundle、checksum、临时替换文件及文件系统元数据 |
| diagnostic（64 MiB） | incomplete/rejected/batch-result 及明确归属的环境诊断；不能靠外部默认日志补救域内耗尽 |
| 节点 tmpfs（48 MiB） | 三节点各 16 MiB；保留 `--ipc none` 和额外挂载拒绝 |

Docker 的 data-root 不覆盖所有外部 containerd 写入；`DOCKER_TMPDIR`、exec-root、containerd 的 root/state 和两边日志都要单独绑定。[dockerd 参考](https://docs.docker.com/reference/cli/dockerd/)、[containerd image store](https://docs.docker.com/engine/storage/containerd/)。Docker 29 新安装默认的 image store 与原文 VFS 候选不能混用；后端类型必须固定并实查，不能未知时自动回退。

候选采用固定 Buildx 客户端和本 daemon 内的 builder，显式开启 BuildKit；不依赖缺插件后的 legacy fallback，也不采用会另起容器或连接远程的 builder。[Docker 弃用说明](https://docs.docker.com/engine/deprecated/#legacy-builder-fallback)。这要求把客户端配置/HOME、插件路径及 builder endpoint 纳入检查；原 `docker build --network=none --pull=false` 两项参数本身不足以证明全部写入受限。保留 scratch + 本地输入，不另换镜像构建协议来跳过合同。

### 不把 guest 容量误作宿主容量

对每个域记 `C` 为既定完整上限、`D` 为 guest 块设备上限、`H` 为该域对应宿主格式/分配元数据及域外控制记录的可证明硬上限，必须满足 `D + H <= C`。环境日志和系统盘新增写入要分配到明确域内；没有硬上限或归属的项不能取零。不同层中同一批数据不重复相加，但 backing 额外元数据、独立复制品和日志要另计。

现有 helper 接受 `0 < D <= C`，因此保留每域上限时可以选择小于上限的实际设备，为已证明的 H 留空间；不能先把四盘做满再补计费。所有域的 C 加 48 MiB tmpfs 仍为 768 MiB。本轮没有擅自调整五个上限，也没有假定 H 的数值。

UTM 文档说明 raw 镜像在 APFS 上可能为稀疏文件，QCOW2 会随写入增长；[QEMU 格式规范](https://www.qemu.org/docs/master/interop/qcow2.html)另含映射表/refcount 等元数据。因此 logical size、`du` 快照或“raw 无 QCOW2 头”均不足以证明宿主完整上限。[UTM Drive](https://docs.getutm.app/settings-qemu/drive/drive/)。

专用 VM 系统盘在 build 的私有 namespace 之外仍可能写入，启动/运行日志也可能落在宿主 bundle；给 build 设 Landlock 不能控制这些进程。真实后端需证明系统/工具输入只读，或把相应增量写入放进有硬上限的承载域。仅在批次开始/结束比较系统盘大小不能覆盖运行期间峰值。本轮尚无这样的 UTM/APFS 后端，不提供看似可运行的四盘格式化命令。

guest 根文件系统的 ≥ 1 GiB 可用与 macOS 上承载 VM 的物理文件系统余量分别检查；前者不能替代后者。余量采样用于检测外部压力，不是 768 MiB 硬限制。无法证明宿主容量或该额度不足时，保存失败并停止，不扩大总额或把系统开销重新命名为免费空间。

## 下一实施顺序与完成条件

| 顺序 | 在现有结构中交付 | 完成条件 |
| --- | --- | --- |
| 1 | 把本候选清单收敛为可信、完整的安装输入 | 发布密钥/签名、归档实际 hash、Debian 闭包、包内服务/许可清单及 Buildx 版本差异全部关闭；才形成精确安装命令和回滚 |
| 2 | 在 `sw_i5_resources.py` 细化每域设备与完整承载上限的关系 | 实际 H 有硬限制证据；拒绝未知 backing、双份复制遗漏、满额 D 外加 H；不把自报 JSON 当内核/宿主证明 |
| 3 | 在 `sw_i5_build.py` 及已有测试入口落实身份/权限交接 | root/capabilities/额外组/socket 可达/域外子挂载可写均拒绝；后代未回收不得移交；保持单一构建入口 |
| 4 | 在既有 `process_runtime.go` / `process_scenario.go` 接入固定 daemon、builder 及全部写目录 | endpoint、owner、版本、后端、日志/tmp、store 预留和阻塞期间检查一致；失败保留证据，不切换共享 daemon |
| 5 | 汇总一次有界环境操作包并取得当次批准 | 精确路径/设备、安装和配置命令、时间、额度、清理/回滚都可审阅；容量拒绝、真实构建及 daemon 行为另行实测 |

若第 2/3 项需要新增配置版本或改变安全边界，先列出字段、旧版本行为及证据消费者影响并确认范围，再实施；本轮未将这些候选接口写入运行代码。公开 I5 shell/Go 入口继续硬停止，原 I5 合同、profile 和 evidence schema 1/2/3 不变。

当前可推进的是来源真实性/闭包和承载机制设计；不能把尚未闭合的安装清单包装成可批准执行的命令。无需为了这些宿主离线工作再次启动 VM。后续完整操作包准备好后按仓库 L3 规则一次说明副作用与回收，不重复索要已经授权的包内步骤。

## 初次准备验证与限制（2026-10-06）

- `c7b0aa1` 提交前，仓库检查（186 文件）和 `git diff --check` 通过，提交后工作树干净；随后才产生本包文件。
- 机器可读候选清单与抓取的 Packages 精确版本/架构/大小/SHA-256 对照；共四个 deb 候选及一个 Go 归档。清单不被运行入口消费，不等于依赖安装或锁定通过。
- 本包完成后，`./scripts/check-repo.sh` 通过（188 文件），`git diff --check` 通过；新增 JSON 解析及其四个包条目与原始索引的独立逐项对照通过。
- 首次沙盒内 curl 退出 7，原因是无法连接本机代理 `127.0.0.1:10808`；获准后同 URL/目标在沙盒外读取成功。InRelease 随后只读取得；网页工具的 containerd 下载页及原始 Packages 页面曾报 Internal Error，不将网页读取失败当成软件包不存在。
- 验签工具查找未找到，未执行密码学验证；这是尚未关闭的证据缺口，不用摘要匹配替代。
- 未运行 Go/Python 实现测试、构建或 VM：本轮没有改实现、依赖、系统或设备。本文只完成设计/来源细化，不代表新的环境验收。

## 本次复核验证与限制（2026-10-09）

- 四个 deb 的固定版本/架构/大小/hash/Depends/Recommends 与本地原始索引逐项对照通过，补查 Pre-Depends、Conflicts、Breaks、Replaces、Provides 和 Installed-Size；没有更新索引或下载归档。
- 重新计算 Packages、InRelease 和旧 guest 返回摘要，并只读检查目标 VM 配置；旧盘点不代表当前 guest 状态，配置文件不代表实际 QEMU 运行参数。验签、完整依赖解析及容量实测仍未完成。
- `./scripts/check-repo.sh` 通过（189 文件），`git diff --check` 通过；仅更新本准备包与当前状态，没有运行实现测试、构建、VM 或新增后台进程，没有修改系统、设备或远程状态。
