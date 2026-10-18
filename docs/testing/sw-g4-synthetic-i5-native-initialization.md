# I5 原生初始化与 bootstrap 离线实施

更新日期：2026-10-18。

本文面向准备链实现者与复核者，记录启动前物理承载候选、原生初始化职责、可重现源码组装与证据绑定，承接[第三包执行合同](sw-g4-synthetic-i5-execution-contract.md)。它不提供实际环境配置命令、启动操作单或真实环境通过结论。

## 范围与证据边界

所有者授权本包先确定物理承载与后端职责，再完成真实初始化后端、bootstrap 组装、原生证据绑定的离线实施及负例验收；由 Astra 主持设计和独立验收，委派 `gpt-6.1-sol high` 实施。原离线实施授权不含 VM 启动、依赖安装、系统配置、提交或 push；验收后所有者另行明确授权将本包十三个文件提交到 dev、不 push。真实 preparation-apt、UTM 和 I5-R 入口继续 STOP。

本包的“原生后端”指实现了 Linux 系统调用的代码，不代表已在 Linux/UTM 执行或核验。离线测试注入的 syscall 事实必须标记为 `injected-offline`；调用方提供的原生 JSON 与源码 hash 也不能认证来源。旧初始化、生命周期与第三包合同保持原版本及停止行为；新候选工件不能被当作旧操作单执行。

## 物理承载候选与启动前责任

选择启动前配置完整承载、启动后独立回读的候选。准备期 profile 与 I5 的 768 MiB 五域预算分别核算；每个完整设备 D 与额外硬预留 H 满足 D + H ≤ C。新增初始化目录不产生免费额度，也不把 tmpfs 内存、swap 和宿主 backing 合并成一次不完整计费。

| 写入面 | 启动前候选与职责 | 本包状态 |
| --- | --- | --- |
| guest root/var、EFI/固件 | 优先只读系统与输入；若启动必须写入，则使用独立、固定上限的写层并计入环境域。固件状态也需固定身份、路径和硬边界 | 未配置；现有可写 QCOW2 盘不能视为满足 |
| guest swap 与系统 tmpfs | 禁止准备载荷落入无额度 swap；系统自身所有可写 tmpfs、日志和启动写入也需逐项归属 | 未配置；历史 `/dev/vda4` swap 缺口保留 |
| 初始化 root 父目录 | `/run/radishlink-i5-preparation` 预置为独立 `noswap` tmpfs，固定 1 MiB、1024 inode 上限；从已有环境域切分，不额外扩张包络 | 后端只核验该挂载和身份，在其下创建本次 nonce 对象 |
| WORK / RESULT | 保留 128 MiB / 8 MiB 的独立 `noswap` tmpfs，创建挂载点后由既有 worker 私有 namespace 实施并回读 | 本包不在宿主执行 mount，不以空目录代替隔离通过 |
| 输入介质与副本 | 完整只读 ISO/squashfs 输入，256 MiB 上限；制作、宿主暂存及 guest 可见副本分别按并存峰值计费 | 树核验代码不证明实际介质制作或源副本额度 |
| 宿主 backing / 元数据 | 独立容量域需覆盖 backing、快照/稀疏文件增长及文件系统元数据；guest 分区大小不能单独保证宿主上限 | 未选择并实测可满足全部条件的宿主后端 |
| UTM/QEMU 状态与日志、宿主 swap/crash | 需要覆盖域外进程、系统和崩溃写入；只给 `.utm` 目录限额不足以证明 | 关键阻塞项；不自动关闭宿主 swap 或日志 |
| JXA / 证据 / 源码组装 | 归入受限宿主暂存与保留域，包含源 bytes、组装 ZIP、复制及报告并存峰值 | 内存组装上限不等于宿主实际物理额度 |

依据 Linux 官方 [tmpfs 文档](https://docs.kernel.org/filesystems/tmpfs.html)，`size` 与 `nr_inodes` 是独立限制，普通 tmpfs 可以进入 swap，`noswap` 才明确禁止；`size=0` / `nr_inodes=0` 不能用作有界方案。官方 [cgroup v2 文档](https://docs.kernel.org/admin-guide/cgroup-v2.html)要求按父级可用 controller 逐层启用，分配 domain controller 的非根父组不可容纳进程。这里引用当前文档说明机制，目标 guest 的内核版本、挂载选项和拒绝行为仍须原生实测。

因此本包可以冻结 guest 侧的候选结构和明确的前置检查，不能宣称完整物理方案已可执行。宿主全域写入没有可证明的硬边界时继续停止；不能以采样、定时清理、声明 `verified=true` 或目录限额代替未知面。后续环境配置须提供精确目标、操作、副作用、持续时间和回滚方案并取得当次授权。

## 后端职责

原生后端只负责九个新建 guest 对象及一个既有只读输入：nonce root、WORK/RESULT 挂载点、control、两个 1024-byte 零槽、parent/supervisor/worker 三个 cgroup，以及输入树的身份与内容核验。宿主 JXA root、证据 parent、attempt 三个对象由宿主 owner 另行产生事实，不能从 guest 十对象推导十三对象齐备。

预置 cgroup 根只核验，不自动改变系统或上级委派；本次 nonce 父组启用 `cpu memory pids` 后才创建两个叶子组，并核对既有硬限制与空进程状态。内核伪文件只能打开已有文件，不能用 `O_CREAT` 造出同名普通文件。创建、写入、独立回读及删除都固定目录 FD 与 inode；只读输入绝不纳入清理。

完整输入树包括 manifest 声明的文件及 by-hash 副本。新 scope 的输入摘要表示 manifest 与树内容关系，不能冒充旧计划的介质 image 摘要。原始 dpkg status 仍留在 guest；由提供的 bytes 生成必要包表投影只能证明字节和语义关系，不能证明这些 bytes 来自当前系统数据库。

bootstrap 与后续显式调用在同一进程内持有 backend 和 FD，收尾使用同一对象。不得通过 JSON 序列化 FD 或只凭路径重认领对象；callback 失败后仍须进入独立清理预算，首因与清理失败分别保留。创建后无法固定身份的对象标为未闭合，不盲删。任何删除之前先核验所有已创建 cgroup 均为空；未知条目、身份替换、非空 cgroup 或未回收子进程均不能写作清理成功。

逐步 deadline 检查不能抢占阻塞中的单次系统调用。外层父监督器的绝对截止、kill/reap、报告持久化及现有生命周期接入仍有独立责任；本包同进程 owner 不宣称已实现全部真实监督路径。init 6 秒、readiness 60 秒和既有总计 897 秒 / 绝对 900 秒预算不扩张。

## 源码组装与证据绑定

组装只处理调用方给出的明确源码 bytes，执行 AST、hash 和内存 ZIP 操作；不导入、编译执行待审源码，不自动运行 bootstrap。产物是没有 `__main__` 的库 ZIP，bootstrap 是包内固定 `bootstrap_owner` 函数；调用方必须显式使用。旧 transport 不消费该库包，本包也不添加另一套进程启动器。固定成员、元数据与入口 bytes 使同一输入可生成相同产物；成员缺失、额外项、重复、路径穿越、链接或未审阅动态加载必须拒绝。AST 检查只覆盖已审阅依赖形态，不是任意 Python 的安全证明。

新增独立候选 binding scope，绑定旧合同原始 bytes、组装产物和原生初始化/独立回读/收尾事实。声明核心中的 program/bootstrap 引用必须与实际新组装产物相同，不能保留占位 bytes 后另挂一份不相关产物。旧合同仍是第三包的历史声明核心，其中 `native_backend=absent` 不可被改写为自动执行授权；真实运行合同的未来版本须单独评审。host 三对象缺失或身份不符不能默认补齐；所有结果保留真实性、执行、安装、物理验证与 I5-ready 为 false。

## 实施接口与兼容边界

| 文件 / 接口 | 实际职责 |
| --- | --- |
| [原生后端](../../scripts/sw_i5_preparation_native.py) `NativeGuestInitialization(contract_raw, manifest_raw, *, expected, syscalls=None)` | 接收既有 isolation schema 1 与输入 manifest；`expected` 精确绑定 root parent、cgroup root、readonly input 的 dev/ino/mount ID。默认后端只允许 Linux root；任何显式注入都固定标记 `injected-offline` |
| `initialize` / `readback` / `cleanup` / `close` | 初始化单次使用；独立读回包含实际 cgroup 快照和三个前置对象的挂载/容量事实；清理独立 deadline、逆序、身份绑定。close 只关闭 FD，不冒充对象清理 |
| [组装与绑定模块](../../scripts/sw_i5_preparation_bundle.py) `assemble` / `validate_artifact` | 精确四份 runtime 源：apt、isolation、resources、native；输出 manifest/program/bootstrap bytes。单 runtime 源至多 2 MiB，库 ZIP 至多 8 MiB；校验重新组装并比较精确 bytes |
| 固定 `bootstrap_owner` | 同一实例初始化、二次回读、一次显式 callback、finally 清理和关闭；callback 返回值不进入报告，保留首因与清理错误。固定入口可测试，调用方映射中的待审源码不被执行 |
| `project_status` | 校验提供的 status bytes 与 baseline 摘要相符，再生成包表语义；输出不包含原始 status，仍不认证当前系统来源 |
| `validate_binding` | 独立 `i5-preparation-native-binding-candidate` schema 1；校验旧声明核心、实际组装产物、原生构造参数、十个 guest / 三个 host 对象、实际快照、收尾与 status 投影的关系 |

binding 的原始引用精确为 `native_contract/bundle_manifest/program/bootstrap/native_initialization/native_readback/native_cleanup/host_initialization/status_projection`，另有内嵌 `native_expected` 三身份映射和四个新实现/测试源摘要；旧核心的原始输入、源清单及 preboot 声明仍按原校验器完整检查。JSON 限 256 KiB，全部映射总额沿用 32 MiB；这些是纯校验输入上限，不新增物理额度。

原生对象必须位于对应承载的 device，三个前置承载的 device 和 mount ID 各不相同；root 观察容量不能超过声明中的系统 tmpfs 预留，输入 FS 不能超过声明的完整 input 设备和域额度，完整树不能超过观察容量。以上只拒绝具体矛盾，不证明整台宿主、实际介质 image 或所有系统 tmpfs 已受限。

此 binding 要求完整初始化和独立回读；部分初始化失败保留在原始 owner 失败记录，不补造十三对象。完整初始化后的清理失败可以形成一致的失败事实，但保留 pending/errors 和 `cleanup_complete=false`。旧 operation、执行候选 scope、合成生命周期 exact-type gate 和真实入口均未修改；新库包不能交给旧 transport 执行。

## 离线验收记录（2026-10-18）

本包新增两份实现、两份测试和本专题，同步八份文档，共十三个文件。两个 `gpt-6.1-sol high` 子任务分别实施后端和组装/绑定；Astra 主持设计、逐段审查、独立运行测试、重算摘要变异检查及全部文档同步。属于工程离线验收，不是专业安全审计或真实环境验收。

| 实际执行的检查 | 主持结果与覆盖 |
| --- | --- |
| `python3 -B scripts/test_sw_i5_native.py` | 26 个方法通过（最终冻结后独立复验 0.817 秒）；平台/身份/挂载拒绝、完整输入树、内核伪文件、槽内容、单次生命周期、deadline、部分创建、取消、逆序清理与旧合成入口拒绝 |
| `python3 -B scripts/test_sw_i5_bundle.py` | 最终 33 个方法通过（冻结后独立复验 7.245 秒）；确定性 ZIP/完整源闭包、待审源码不执行、重算 hash 后拒绝、原生构造/挂载/cgroup/对象绑定、额度矛盾、旧消费者拒绝、固定 owner 的 finally 与首因保存 |
| 生产者到消费者的完整离线验收 | 实际 `NativeGuestInitialization` 使用 `MemorySyscalls` 产生 init/readback/cleanup 原始结果，再进入完整 `validate_binding`；另验证固定 bootstrap 使用同一实际 backend 和注入 syscall。host 三对象仍明确是独立提供的合成事实 |
| 主持独立四项后端变异 | 叠加 root mount、worker 伪文件 inode 替换、parent 出现活进程、输入硬链接均拒绝；前三项所有对象保留且无 unlink/rmdir，输入硬链接在任何 mkdir 前拒绝，关闭后 FD 清空 |
| 主持独立七项绑定变异 | 重新计算摘要后，布尔 counter、三个 device 混用、输入观察容量不足、构造 UID 不符、pending 身份布尔值、root 超声明预留、input FS 超完整设备额度均拒绝 |
| `python3 -B scripts/test_sw_i5_execution.py` | 32 个方法通过（7.040 秒），旧合同与 STOP 保留 |
| `python3 -B scripts/test_sw_i5_preparation_plan.py` | 19 个方法通过（0.395 秒） |
| `python3 -B scripts/test_sw_i5_initialization.py` | 16 个方法通过（29.045 秒） |
| `python3 -B scripts/test_sw_i5_preparation.py` | 20 个方法通过（3.100 秒） |
| `python3 -B scripts/test_sw_i5_utm_control.py` | 4 个方法通过（0.137 秒） |
| `node scripts/test_sw_i5_utm_rpc.js` | 33 个纯用例通过，无 Application 调用 |
| 四份新增 Python 的 AST 语法检查 | 通过，无 bytecode 产物 |
| `./scripts/check-repo.sh`、`git diff --check` | 通过；仓库检查覆盖 223 个文件 |

首跑及审查发现保留如下：

1. 主持审阅发现先删除控制槽再检查 cgroup 的顺序可能破坏仍在使用的控制对象；改为任何删除之前验证全部已创建组已回收，失败保留所有对象。
2. 子任务首次 native 18 方法运行 exit 1，发现固定上层目录被替换后仍可能清理部分子对象；补每次重开固定父目录、mount 身份和全局清理前置。第二次 18 方法运行 exit 1 是测试仍预期九项错误，而新前置返回一个首因；修正测试预期，没有放宽拒绝。
3. 主持独立 probe 曾确认旧合成 binding 样例把三个不同 filesystem 放在同一个 device 上仍返回一致；补精确设备/mount 分离、对象承载关系、原始 cgroup 严格计数和输入/root 与容量声明的对应检查。随后新增实际 producer 到完整 binding 的离线测试，避免只用手写观察样例证明接口兼容。
4. 补齐真实快照及构造入参绑定，注入器不能以自报 `kernel` 伪装原生；源码 fingerprint、pending identity 拒绝 bool/int 混淆，清理顺序与完整角色集合固定。core 的 program/bootstrap 必须绑定本次确定性组装 bytes。
5. 组装子任务首跑 25 方法 exit 1，13 errors 来自测试 fixture 的 `dict.update` 重复传入 `manifest` 关键字，产生 `TypeError`；改为先写组装工件、再明确覆盖 APT manifest 后通过，没有放宽实现校验。中途导入测试类曾导致 unittest 连带发现 26 个 native 方法，全部通过；改为模块导入后，最终组装测试计数为 33。

尚未执行任何原生 Linux、UTM、密码学验签或 APT 求解，没有真实物理配置或来源认证；没有把注入结果写成原生 PASS。离线实施期间未启动 VM、安装依赖、改变系统配置、提交或 push；旧 evidence/cache 未清理。离线验收结束时 `dev` 为 `c232d9e`，相对本地 `origin/dev` ahead 4，十三个文件未暂存、未提交。随后所有者明确授权将这十三个文件提交到 dev、不 push；本包实现和记录随本次提交保存，提交前只同步文档中的提交状态，已验收代码未改动。远程状态未改变，后续缺口梳理不包含下一包实施授权。测试子进程均已结束，没有本轮后台进程；固定入口测试使用的临时目录已由测试清理。

## 后续关闭顺序

第五包承接本节的宿主裁决、交付及监督接线，见[宿主写入边界与原生生命周期](sw-g4-synthetic-i5-host-delivery.md)。本页同进程 bootstrap 与四模块库包仍保留其历史范围；新增路径不把本页未覆盖的真实环境条件改写为通过。

1. 先解决宿主全域写入硬边界与 guest 启动写入，形成可审核的物理配置操作包；不能先启动再补额度。
2. 接入真实父监督与生命周期，固定工具/解释器/内核来源、介质 image 与完整输入树、status 基线、源码组装产物和新版执行合同，生成无占位操作单。
3. 另行授权启动前配置及单次 Linux/UTM 验收，覆盖真实拒绝、取消、部分创建、身份替换、强杀、回收和未知残留；离线结果不替代该步骤。
4. 验签与原生 APT 差量通过后再评审安装与克隆；完整 I5 资源/daemon 边界通过后，才另行评审 I5-R 入口与 21 样本授权。
