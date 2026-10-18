# I5 宿主写入边界与原生生命周期离线接入

更新日期：2026-10-18。

本文供准备链实现者与复核者使用，承接[原生初始化与 bootstrap](sw-g4-synthetic-i5-native-initialization.md)，冻结完整写入账本、库包交付和父监督职责，并记录本包的离线实现与故障验收。它不是宿主配置操作单，也不是 Linux/UTM 实测报告。

## 授权与当前裁决

所有者明确授权先收敛宿主完整写入硬边界、冻结父监督和库包交付，再实施原生后端生命周期的离线接入；Astra 主持设计与独立验收，委派 `gpt-6.1-sol high` 实施。离线实施时没有 VM 启动、依赖安装、系统配置、提交或 push 授权；验收后所有者另行明确授权将本包 28 个文件提交到 dev，不 push。preparation-apt、UTM 与 I5-R 的真实入口保持 STOP。

当前 Mac/UTM 候选裁决为 **`blocked-host-system-writes`**。已有证据没有覆盖 macOS swap、崩溃报告、系统日志和 UTM/QEMU 域外状态的整批硬上限；这些面必须保留 unknown，不能通过补一个目录 quota、填写零、采样未增长或自报 verified 变成 bounded。本包关闭的是“不知道哪些责任尚缺”的设计问题，没有关闭真实物理门。

Apple 的 [APFS 卷说明](https://support.apple.com/en-asia/guide/disk-utility/dskua9e6a110/mac)区分保证可用空间的 Reserve Size 和限制单卷分配量的 Quota Size；[安全虚拟内存说明](https://support.apple.com/en-ie/guide/mac-help/mh11852/27/mac/27)说明虚拟内存会使用磁盘。由单卷限制不能推导其他卷或系统写入也受该限制。因此 APFS quota 只保留为部分宿主存储面的候选机制，不能作为整台宿主写入已受控的结论。这里是机制资料和工程推论，没有执行当前宿主探测或更改配置。

若后续仍选择此 Mac/UTM 路径，必须先提供全部域外写入的可核验硬边界；若做不到，应由所有者重新选择承载环境或明确修改预算合同。不能在本包中自动关闭宿主 swap/日志、改系统卷或迁移实验宿主。

## 完整写入账本

继续使用现有 preparation capacity 的域与 `PREP_SURFACES`，不新增第二套 cap。准备期完整包络和正式 I5 的 768 MiB 仍是两个不同 profile；每域完整 guest 设备 D 加额外硬预留 H 不得超过 C。

| 既有写入面 | 必须覆盖的组件与责任 | 物理关闭条件 |
| --- | --- | --- |
| `guest_root_var` | guest 系统根、`/var`、启动服务和系统日志 | 完整只读或有固定上限的全部写层；原可写 QCOW2 不自动满足 |
| `efi_firmware` | guest EFI/固件持久状态；宿主固件状态另归 `utm_qemu_logs_state` | 精确文件、设备、身份和硬边界；独立宿主写入不得藏入 guest D |
| `guest_swap` | 所有 guest swap，包括历史 `/dev/vda4` | 启动前处理并独立回读；used=0 不能证明禁用 |
| `guest_system_tmpfs` | 系统所有可写 tmpfs、初始化根的 1 MiB/1024 inode | 每个挂载的 size/inode/noswap 与总预留，不能只核验载荷 WORK/RESULT |
| `preparation_work` / `preparation_result` | 原 128 MiB / 8 MiB 任务域 | 继续按完整 noswap tmpfs 硬上限预留 H |
| `readonly_input` | APT 输入介质和独立 library 介质的完整设备 | 二者 D 求和纳入同一既有 input 域，树 bytes 不代替介质 bytes |
| `input_media_creation` | 输入和库介质制作时的完整产物与临时副本 | 所有并存副本和制作开销计入 H，不因未来删除免计费 |
| `input_media_staging_copy` | 宿主暂存和交付副本 | 与制作源分开计费，身份与峰值完整绑定 |
| `host_backing_metadata` | 宿主 backing 增长、快照、文件系统元数据 | guest 分区或稀疏文件逻辑大小不能单独证明上限 |
| `utm_qemu_logs_state` | UTM/QEMU 日志、保存状态、配置和域外状态 | 当前候选 unknown；重定向单个日志文件不足以关闭 |
| `host_swap_crash` | macOS swap、崩溃报告和相关系统写入 | 当前候选 unknown；不能填零或推断禁用 |
| `host_jxa_source` | JXA、源码、ZIP、manifest、描述符与组装 buffer | 按并存峰值汇入已有 environment/H，不另加免费源码域 |
| `host_evidence_export_source` / `host_evidence_retained` | 回收源与持久化证据 | 两份独立 H，沿用已有 host-retention 上限 |

每个 bounded 面的组件只能分解已有 logical/copies/peak/hard-limit 声明。没有已证明的互斥生命周期时按并存求和，不能把若干复制步骤取 max。一个面可以包含多个明确物理域，组件逐项引用；每域的 hard reserve 是已有面额度的切分，域内组件峰值不得超过它，各域预留之和不得超过原面上限。D 还须累计每个完整设备大小，不能只加 payload。APT 与 library 必须分别绑定不同设备与挂载，不能用一个虚构文件系统代表两者。

不同名称或目录不能重复认领同一物理额度；同一 realm 的相同/嵌套承载必须聚合或者保留阻塞。组件的 host/guest realm 固定，配置与观察 bytes 应绑定同一容量声明、面、身份和限制，hash 只证明字节关系，不认证来源。

## 交付方式

冻结为启动前独立的只读 library 介质，固定成员与入口；不把库 ZIP 塞入 APT 输入树，也不扩大旧 48 KiB program/RPC 限制。APT 树摘要、APT 介质 image 摘要、库 ZIP 摘要和 library 介质 image 摘要保持不同语义。库介质、APT 介质、初始化根与 cgroup 承载的身份不得混用。

控制面只携带六字段描述符：`schema_version/scope/uuid/nonce/manifest_sha256/delivery_sha256`。独立 library 树固定六个文件：`library.zip`、`library-manifest.json`、`isolation.json`、`apt-manifest.json`、`expected.json`、`delivery.json`。delivery 绑定前五份 bytes，最后一份就是 delivery 自身，不把自身摘要递归写入；描述符再绑定 delivery 的摘要。完整六文件和介质大小都纳入容量账本。

禁止任意 Python 字符串、路径、argv 或 callback 成为描述符的一部分。待审源码的纯校验不执行它；没有默认 launcher，也不能把旧四模块 bootstrap 的同进程 callback 当作新的隔离任务入口。新七模块生命周期库使用独立 scope，旧四模块组装入口保持原含义。

真实库加载还须保证只读挂载、固定祖先/文件身份、无链接、完整成员、消费前后摘要一致和 FD 生命周期。按路径校验后再由普通 `sys.path` 重开同一路径，不足以证明消费的是同一对象。本包的离线适配不能冒充该真实加载路径已验收。

## 父监督与 FD 所有权

| 进程职责 | 持有与执行 | 失败后的责任 |
| --- | --- | --- |
| 宿主生命周期 owner | 本次 start/readiness/shutdown 票据、宿主证据和现有总预算；经注入 RPC 发起一次 guest 执行 | 调用受限恢复与关机、回收本地会话并冻结结果；本地 transport 已回收不能证明 guest 已回收 |
| guest 协调父进程 | 独立 guest 时钟、取消通道、已登记 PID 与受限 IPC | 在原预算内 kill/reap；不持有可用于重新认领 native 对象的路径清理能力 |
| 持久 native FD owner | 唯一 `NativeGuestInitialization` 实例；init、readback、cleanup、close 跨阶段持有相同 FD | 部分创建保留真实登记；cleanup 只处理身份仍相符的对象；阻塞可由父进程终止 |
| 既有任务 supervisor / worker | 复用现有进程准入、cgroup/lease 与任务隔离；仅保留明确授予的能力 FD | 任务代码不在 native owner 中运行，不继承 owner 的所有目录 FD 或续租写端 |

所有登记必须在对应子进程获得继续执行的许可前完成。owner 被 SIGKILL、回报丢失或身份无法确认时，父进程保留 pending/unknown；不得构造新 owner 按路径 cleanup，也不能把 close FD 写成清理成功。退出、kill 请求成功、wait/reap 和 cgroup 空状态是不同事实，不能互相替代。

宿主绝对单调时间值不跨 guest 时钟域直接解释；guest 从明确的有界时长建立自己的截止。现有默认保守时间账本 897 秒、绝对至多 900 秒不扩大，init/readiness/active/cleanup/reap/persist 等开销均须在已有阶段内切分。阻塞 syscall 不能只靠同进程 deadline 检查约束。

新 transport 分支必须打破“先打开尚未创建的槽”的循环：单次固定执行先创建 native 对象，然后确认槽与初始化事实，再授予初始租约和任务准入。execute 响应丢失不能重试；停止和恢复继续走原生命周期责任。

## 证据与兼容

新原生生命周期事实使用独立 scope；旧 task export 保留原格式并嵌入新 export。宿主沿用已有 watchdog、host report 和 EvidenceStore，不为本包创建另一套证据存储。旧 scope 仍严格校验原字段；新 scope 明确分派，不能宽松接受未知字段或任意对象。

完整原生初始化可以另交既有 binding 校验；部分失败只保留实际观察和登记，不补造齐备的十个 guest / 十三个总对象。所有注入 syscall 结果标记 `injected-offline`，执行、安装、物理通过与 I5-ready 标志保持 false。纯候选一致、离线任务通过和真实环境可执行分别表述。

## 实施与验收记录

### 实施接口

| 接口 | 本包职责与边界 |
| --- | --- |
| `plan.review_host_coverage` | 精确引用已有 capacity；固定组件、责任人、realm、多物理域及配置/观察 bytes；macOS 全域写入保持阻塞 |
| `bundle.assemble_lifecycle` / `validate_lifecycle_artifact` | 确定性七模块库：apt、isolation、resources、native、supervisor、channels、native_lifecycle；完整扫描局部导入，不扩展旧四模块 artifact 的含义 |
| `bundle.validate_delivery` | 校验六文件、三份实际 config bytes、双介质、copy/assembly 峰值及小描述符；不加载或运行提供的源码 |
| `rpc.validate_invocation_descriptor` | 唯一六字段纯校验；transport 和 bundle 复用，旧 48 KiB 限制不变 |
| `native_lifecycle.NativeGuestConfig` / `NativeTaskAdapters` | 显式 bytes 快照与注入适配器；配置构造不触发真实 native 初始化 |
| `native_lifecycle.run_native_guest` | guest 协调父进程、持久 FD owner 与现有 supervisor/worker 的离线进程接线；没有默认 syscall 或任务 launcher |
| `channels.validate_native_export` | 原生事实和旧 task export 的严格联合校验；沿用已有 export 总上限，新增 facts 至多 128 KiB |
| `transport.run_transport` / `lifecycle.fork_lifecycle` | 明确新 request scope；guest 初始化事实从 transport 回收，宿主不调用 Linux backend；新 scope 不接受旧 SyntheticInitialization 参数 |

新 RPC action 为 `execute-native` 和 `native-ready`，只在注入适配器中可用。真实 `JXAProcessRPC` 与 JXA native API 明确拒绝它们。ready 使用内部有界 pipe，不增加 guest 文件对象；等待 ready 期间保留原时钟并响应控制 EOF/取消。旧请求不能消费新 export，新请求也不能消费旧 export 或其他 delivery 摘要的结果。

为保持旧执行合同的精确源码闭包，共用 IPC 函数归入既有 channels，staging 保留原导入 API；原生常量归入既有 isolation，native 保留别名；新 export 校验也由 channels 持有。旧模块不反向导入新 runtime，未放宽 nested import 的 AST 检查。宿主继续使用原 EvidenceStore/receipt，无新的持久化协议。

### 实际验证

主持 Agent 对冻结代码完成独立复跑，全部为本机合成数据与显式注入；未调用真实 Linux 初始化、UTM 或 APT：

| 验证 | 结果与覆盖 |
| --- | --- |
| `test_sw_i5_preparation_plan.py` | 28 方法通过；完整组件、物理域分离与已有容量绑定 |
| `test_sw_i5_bundle.py` | 41 方法通过；旧四模块兼容、新七模块源码闭包、六文件交付及完整副本计费 |
| `test_sw_i5_native_lifecycle.py` | 15 方法通过；真实 fork/pipe 的正常链、取消、初始化/清理阻塞、强杀 owner、部分创建、登记失败/挂起、报告丢失和输出阻塞；强杀后额外精确观察 S/W PID 消失，报告仍保留 reap 未确认 |
| `test_sw_i5_native_host.py` | 3 方法通过；六文件实际配置经原生 P/N/S/W、注入 RPC 与既有 host lifecycle 到持久 receipt，覆盖正常、显式取消和 execute 响应丢失不重试 |
| `test_sw_i5_transport.py` / `test_sw_i5_rpc_process.py` / `test_sw_i5_lifecycle.py` | 分别 20 / 13 / 18 方法通过；新 scope、单次 execute、ready 前取消/EOF、delivery 绑定及既有生命周期 |
| `test_sw_i5_utm_rpc.js` | 43 项纯 JavaScript 用例通过；真实 native action 保持 STOP，没有调用 Application/ObjC |
| 受影响回归 | execution 32、native 26、initialization 16、channels 14、staging 4、guest 45、preparation 20、APT 20、UTM control 4 方法通过 |

主持独立变异验收共 15 项拒绝：覆盖跨 realm/设备别名、嵌套物理根、硬预留不足、完整设备超额与 bool mount 身份；漏计 APT by-hash 副本、旧库冒充新交付与隐藏初始化根；进程 PID 别名、reaped/exit 矛盾、task 未知字段、清理角色缺失、对象 inode 别名与初始化根容量越限。相关声明重新编码或重新绑定摘要后仍拒绝。它们证明消费者约束，不认证物理观察来源。

完整链用例先校验实际 delivery/config bytes，再执行仓库中的 native producer；RPC 的固定槽由测试服务映射为真实 control/ACK/ready pipe，ZIP 只校验、不加载。正常用例核对实际 export 等于落盘 host-report 中的 export，并重开 receipt；取消和丢响应用例核对整包失败与仅一次 execute。它不证明 UTM 文件槽或真实 FD loader。

实施中发现并修正的失败保留如下：

1. transport/RPC 初次测试因交付校验 API 尚未落地出现 ImportError（transport 9 errors、RPC 1 error）；改为 rpc 持有唯一描述符校验，bundle/transport 复用，修复后各自完整测试通过。
2. native 最初六方法验收暴露 fixture 未等 ACK 即续租及任务完成时续租转发的 EPIPE 竞态；fixture 改为等确认，转发失败不伪造 ACK，只有完整有效终态报告可被接受。
3. 审阅发现 guest 原默认子预算合计 542 秒、初始化后重新计时、owner 退出早于 pipe EOF、ready 登记超出旧小消息上限等问题；已把初始化至输出共同限制在 540 秒、等待完整 EOF，并为事实使用 128 KiB 上限。
4. 登记失败后的 SIGKILL 原先没有预留确认 reap 的时间；已切分同一截止。任务报告或 owner 丢失时可能跳过停止、或在 N reap 后继续按旧 PID 发信号；已让 P 完成停止并确认撤销信号票据后，N 才能 waitpid，未知对象保留 pending。
5. 完整链 fixture 最初把 MemorySyscalls 的设备/mount 身份与其他合成域撞号，触发拒绝；修正 fixture 的独立域并重新绑定，未放宽消费者。主持首次三方法运行因临时 Unix socket `bind` 被沙盒拒绝而 exit 1（3 errors）；获准在沙盒外按同一精确命令复验，3 方法通过，没有连接外部服务。
6. 完整观察中的 bool/int 混淆、创建/清理顺序、遗漏 cleanup 错误及 S/W 未确认时仍尝试清理等边界已收紧，负例通过。owner 被强杀后不创建替代 owner，也不通过路径重新认领对象。

真实 FD loader 和库源码消费仍未实施；Mac/UTM 全域硬边界及 Linux/UTM 物理故障验收仍未通过。注入 `MemorySyscalls`、合成 cgroup/guard 和结果文件不能证明实际 mount、cgroup、namespace、不可杀任务或 session 外后代的行为。

收尾：`./scripts/check-repo.sh` 通过（227 文件）、`git diff --check` 通过，18 个新增/修改 Python 文件 AST 检查通过。`dev` 保持 `b8fb2d5`，相对本地 `origin/dev` ahead 5；本包 28 个文件（8 份文档、20 个脚本/测试）未暂存、未提交。没有启动 VM、安装依赖、改变系统配置、提交或 push，远程状态未改变。测试自身持有的父进程均确认退出/reap；故障样本的已知 S/W PID 另行观察不再存在，不能据此改写报告中的未确认 reap。所有本轮执行会话均结束，无本轮后台任务，合成临时目录由测试清理。

随后所有者明确要求将上述 28 个已验收文件提交到 `dev`、不 push；本包实现和记录随本次提交保存。提交前只同步三处文档的提交状态，已验收代码未改动；随后仅梳理剩余缺口和下一包顺序，不继续实现、启动 VM 或安装依赖。

## 后续关闭条件

第六包的设计裁决见[宿主可行性与真实 FD loader 合同草案](sw-g4-synthetic-i5-host-loader-decision.md)。其稳定预期/本次观察和可信加载职责是待接受的新设计，不改写本页六文件候选及离线验收结果。所有者后续已选 A、暂不采购，并确认仅有 Mac/UTM；[已有资源与预算评估](sw-g4-synthetic-i5-linux-host-assessment.md)判定暂无合格宿主，准备包络仅为有前提的候选，尚不进入实施。

1. 为当前被阻塞的宿主系统写入提出可证明方案，或由所有者决定承载/合同变更；补齐真实配置、观察和全部副本的完整计费。
2. 固定真实库加载、guest 工具/解释器/内核、介质 image、APT 树和 status 基线，生成无占位符的操作清单。
3. 另行明确授权启动前配置与单次 Linux/UTM 验收，覆盖真实额度拒绝、阻塞、取消、owner 强杀、未知残留、关机与回收；不得直接沿用离线授权。
4. 只有这些门实际关闭后才评审验签/APT 差量、安装/克隆以及完整 I5 资源/daemon 边界和 I5-R 授权。
