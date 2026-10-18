# I5 准备执行合同与原生证据候选

更新日期：2026-10-18。

本文面向下一次准备包的实现者与复核者，规定执行源、输入、物理前置条件和原生证据之间的绑定关系，承接[环境可行性与内部接线](sw-g4-synthetic-i5-environment-feasibility.md)。它是离线设计与纯校验专题，不是可执行操作单、真实环境验收记录或启动授权。

## 范围与结论边界

所有者授权本包完成设计、纯校验、负例测试及文档同步，由 Astra 主持设计和独立验收，`gpt-6.1-sol high` 实施校验模块及测试。原离线实施授权不含 VM 启动、依赖安装、系统配置、提交或 push；验收后所有者另行明确要求将本包十个文件提交到 dev、不 push。全部真实入口继续 STOP。

本包使用独立的候选合同与证据 scope。既有 operation v1–v4、resource config v1、初始化/容量评审 schema 1、内部 attempt v2/receipt v3 和运行证据合同均不升级，也不自动接受新 scope。纯校验只判断调用方给出的有限 bytes、声明和显式时间是否一致，不访问路径、探测系统、执行源码、调用 UTM、运行密码工具或 APT。

候选执行合同即使完整，仍不能证明当前授权、真实介质、实际工具身份、物理额度或原生观测来源。结果明确保留执行、安装、物理验证和 I5-ready 为 false；原生证据模型的一致性通过也不能改写这些标志。当前已有内部接线能够处理合成进程和对象，但没有被本包接入真实公开入口。

## 执行源闭包

清单必须覆盖会参与该次准备链的仓库源码，不再沿用历史七、十、十二或十三文件合同推断新增初始化链已被绑定。文件以仓库相对规范路径、用途、原始字节长度与 SHA-256 标识，路径仅作为词法标识，不允许绝对路径、`..`、重复项、遗漏或未声明额外项。

| 角色 | 固定文件 |
| --- | --- |
| guest 入口与准备编排 | `scripts/inspect-sw-i5-guest.py`、`scripts/sw_i5_apt.py` |
| 通道、导出与证据 | `scripts/sw_i5_preparation_channels.py`、`scripts/sw_i5_preparation_evidence.py` |
| 初始化、隔离与生命周期 | `scripts/sw_i5_preparation_initialization.py`、`scripts/sw_i5_preparation_isolation.py`、`scripts/sw_i5_preparation_lifecycle.py` |
| 初始化/容量评审与 RPC | `scripts/sw_i5_preparation_plan.py`、`scripts/sw_i5_preparation_rpc.py` |
| 暂存、监督与传输 | `scripts/sw_i5_preparation_staging.py`、`scripts/sw_i5_preparation_supervisor.py`、`scripts/sw_i5_preparation_transport.py` |
| 资源与宿主控制 | `scripts/sw_i5_resources.py`、`scripts/sw_i5_utm_control.py` |
| 原生映射源资产 | `scripts/sw_i5_utm_result.js` |
| 本包评审校验器 | `scripts/sw_i5_preparation_execution.py` |
| 复核测试资产 | 文件名前缀 `scripts/test_sw_i5_` 加 `apt.py`、`channels.py`、`guest.py`、`initialization.py`、`lifecycle.py`、`preparation.py`、`preparation_plan.py`、`rpc_process.py`、`staging.py`、`transport.py`、`utm_control.py`、`utm_rpc.js`、`execution.py`，共十三份 |

这十四份既有 Python、一个 JXA 源资产与评审代码采用不同用途角色。测试属于复核证据绑定，不能被当成 runtime program 或被复制到 guest 后执行。未来新增真实初始化或宿主约束后端时必须扩展并重新审阅清单；不能为尚不存在的后端填写虚构 hash。

纯校验对 Python AST 递归检查包括函数内部的导入，标准库根采用有限集合，其余必须解析到清单内的本地源码。不能仅以 `sw_i5_` 前缀判断是否属于本地依赖。现有两条动态 Python 依赖必须明确绑定：宿主控制的 `i5_inventory` 指向 `inspect-sw-i5-guest.py`，guest 入口的 `i5_apt` 指向 `sw_i5_apt.py`；配套的 `module_from_spec`、`exec_module` 不能用来接受任意加载器。guest 入口引用 `sw_i5_utm_result.js` 的路径也必须与资产条目绑定。未知动态导入、源码执行或未覆盖资产使闭包校验失败。

AST 与文件 hash 只能证明给定 bytes 对应已知依赖形态，不能证明任意 Python/JXA 的全部执行行为安全，也不是宿主软件供应链扫描。Python 解释器及标准库、macOS `osascript`/Foundation、UTM/utmctl/guest agent、guest 原生工具和系统库必须另有版本、二进制/包归属及来源绑定；这些外部组件不伪装为已被 Python AST 证明的源码闭包。原生映射的 JXA bytes 以摘要绑定并人工审阅，不宣称通用 JavaScript 依赖解析已经完成。

## 纯校验接口与版本

[纯校验模块](../../scripts/sw_i5_preparation_execution.py)提供 `validate_sources(manifest, sources)`、`validate_contract(raw, blobs, sources, *, now)` 和 `validate_evidence(raw, contract_raw, blobs, sources, *, now)`。`sources` 和 `blobs` 是调用方明确提供的不可变 bytes 映射；本模块没有 CLI 或默认 launcher。仓库已有纯评审函数通过普通静态导入复用，不导入、编译执行或运行映射中的待审源码。

| 对象 | scope / 主要内容 |
| --- | --- |
| 合同 schema 1 | `i5-preparation-execution-candidate`；UUID、nonce、revision、签发/失效时点、inputs、sources、external、preboot、bootstrap policy、native backend、authorization、budgets 与固定 false 标志 |
| 输入引用 | `plan/capacity/manifest/config/utmctl/media/program/bootstrap/jxa`；bytes 与 SHA-256，只有明确要求的载荷进入映射 |
| 源角色 | `execution/validator/review_tests/dynamic_edges`；执行与评审用途分开，精确集合不允许遗漏或隐式扩张 |
| 证据 envelope schema 1 | `i5-preparation-native-evidence-candidate`；合同、原始 report 和独立 receipt 的摘要/长度及固定 false 标志 |
| 原始 report schema 1 | `i5-preparation-native-report-candidate`；时间窗、事件链、基线摘要、原生工具声明、Release/Packages 链、工件、首因及清理错误 |
| 独立 receipt schema 1 | `i5-preparation-native-receipt-candidate`；绑定此前 report 与工件，不与 report 相互引用 |

JSON 限严格 UTF-8、256 KiB，拒绝重复键、未知字段、非有限数值、整数/布尔混淆和不支持的版本。两个映射内源码与输入/证据 bytes 总和限 32 MiB，单项按角色另限；该纯校验内存输入上限不增加准备期存储或 I5 资源预算。失效时点最长距签发 24 小时，调用方必须明确给定当前 UTC epoch；历史候选不能被当成永久有效授权。

## 输入与时间绑定

合同固定本次 UUID、nonce、执行 revision、失效时间、初始化计划、准备期容量声明、输入 manifest、配置、工具身份、介质以及 bootstrap/program/JXA 源。引用 bytes 时同时绑定 SHA-256 和长度；调用方提供的 blob 集合应恰好覆盖声明，不能以额外未审阅输入扩张执行面，也不能用仅有摘要的占位物替代必需 bytes。

原始 dpkg status、extended states 和密码策略保持在 guest 的受限区域；宿主合同只接收必要语义、长度及摘要，不要求把原始数据库或策略全文导出。APT 语义投影只包含已安装 `{name: version}` 集合、拟新增集合和固定隔离配置，绑定原始 status 摘要；纯校验不能证明这个投影确实从对应原库生成，真实后端必须独立验证该关系。源码、公开输入和合成 fixture 可以参与纯校验，真实输入中的凭据、私密通信和用户敏感内容仍不得进入报告或测试。

过期检查由调用方传入显式 `now`，不读取系统时间。执行证据采用单一宿主监督 elapsed 时间域；guest 原始时间只能作为附属观测，不能直接与宿主单调时钟相减。每个阶段必须落入其既有父窗口，不因新增合同再增加一轮完整预算。

默认保守上界沿用生命周期 `CAPS` 与八个 `REAP_SLOTS`：init 6 秒、start 60 秒、readiness 60 秒、active 600 秒、watchdog cleanup 25 秒、watchdog report 2 秒、shutdown 120 秒、persist 6 秒、output 2 秒和八次各 2 秒 reap，合计 897 秒，绝对包上限 900 秒。guest 工作 540 秒、单 RPC 2 秒及 transport close 等限制仍嵌套于原窗口；不能把各自局部截止串接成额外预算。

## 物理边界与启动前置条件

准备期与 I5 运行期是不同 profile。I5 的五域合计 768 MiB 不变，准备期必须单独声明完整包络。每域完整 guest 设备 D 与额外宿主硬预留 H 必须满足 D + H ≤ C；独立副本在并存峰值分别收费，同一物理承载不能重复充当多个额度保证。已分配采样、剩余容量和 QCOW2 的当前大小都不能代替硬上限或证明未来拒绝写入。

| 时点 | 必须已满足的条件 | 不能留到该时点才做的动作 |
| --- | --- | --- |
| 启动前的独立环境准备 | guest root/var、EFI/固件状态、swap、系统 tmpfs；宿主 backing/元数据、UTM/QEMU 日志状态、swap/crash；介质创建与暂存副本、JXA 与证据写入全部有归属和硬边界 | 启动后再补系统盘、swap 或宿主日志额度 |
| 本次 init，至多 6 秒 | 对已配置后端和身份进行独立 readback，建立该次有界证据对象 | 创建 quota、制作介质、重配挂载/系统或隐式补齐缺失环境 |
| start 与 readiness | 精确目标身份和配置匹配；guest bootstrap 在其固定、独立且有界的操作内创建并回读固定对象 | 把尚未存在的 lease 当作 bootstrap 的启动前提，或由 transport 隐式创建对象 |
| transport 打开前 | 十三个初始化对象全部核对；两个 1024-byte 控制槽均为零且已固定身份、长度、权限 | 通过重新 open/execute 掩盖结果丢失，或动态换一套路径/句柄 |
| worker 放行前 | 原有双 admission、只读输入、cgroup/namespace/seccomp 与有界 RESULT 观测通过 | 用合同中的 true、工具退出 0 或旧盘点替代实际隔离读回 |

上述启动前外部配置必须先形成独立精确操作包，说明目标、命令、副作用、持续时间、清理/回滚和验证，再取得当次授权。本次候选合同只能描述、校验其声明；不能执行配置，也不能把“已声明”转成“已建立”。已有 10 月 9 日盘点确认的可写系统盘和 swap 缺口继续保留，旧单次启动授权已消费。

quota 应覆盖实际底层写入和元数据；guest 分区限额不能单独约束宿主 QCOW2 扩张。关闭 swap/日志或改变 crash 行为属于外部系统配置，必须评估影响并单独授权，不允许在失败处理里自动修改。无法为某个写入面提供完整硬边界时，选择调整设计或保持停止，不能依赖定时 `du`、运行后清理或静默忽略域外写入。

## 原生证据模型

候选证据按以下因果顺序绑定本次合同：preboot readback → 精确 start → bootstrap 与初始化 readback → 同一句柄上的单次 execute → guest 结果与有界导出 → transport/session reap → guest cleanup → 唯一 shutdown → host cleanup → 冻结报告 → receipt。这里 guest cleanup 是初始化对象收尾；worker 的回收必须已在 guest 结果及导出前完成。初始化对象的 guest cleanup、唯一 shutdown、host cleanup 共用现有 120 秒 shutdown 窗口，不能另向 watchdog cleanup 或 persist 借预算。失败可能提前终止业务阶段，但不能略去已发生动作的回收事实。

每项原生工具证据至少绑定工具身份、输入摘要、精确 argv、cwd、有限环境变量、退出状态、stdout/stderr 原始长度、保留长度及保留内容摘要、完整性和回收情况。argv 采用已有准备编排的固定只读查询、验签和 `apt-get -s --no-download` 请求，不能接受仅可执行文件名相同的任意命令。APT 子工作目录固定为已初始化 WORK 根下的新建 `apt` 目录；既有编排要求目录尚不存在，不能直接将已创建的 WORK 根传入。PATH、LANG、LC_ALL、HOME、TMPDIR、APT_CONFIG 对全部步骤一致，不能在 config dump 后更换配置或注入代理。验签必须将受信 key/预期指纹、InRelease 和解出的 Release 关联，再以认证后的 Release 摘要链核对 Packages；APT 求解必须绑定该次受限工作区、原生 status/extended states/策略摘要、架构、索引和固定请求。文件摘要相同、JSON 中的 `signature_verified=true` 或 `apt_resolved=true` 都不能替代这些阶段事实。

工具与输出的身份字段仍属于调用方声明。纯校验最多拒绝自相矛盾、缺失或未绑定的证据，不能凭 JSON 认证真实来源、密码学签名、Linux 内核拒绝行为或 UTM Apple event 的实际结果。report 中工件必须恰好由事件、工具流或认证 Release 声明引用，不通过任意额外工件导出数据库或策略。原生证据来源确认和物理边界验收始终是执行阻塞项；当前不存在可由此候选模型产生的真实 PASS。

取消、非零退出、超时、输出超限/截断、丢失结果、强制关机、未知残留与身份不符均保留首因及后续清理结果。成功清理不能抹掉失败；未知状态不能写成不存在。工具错误输出可以进入有效的失败记录，不能因其不满足成功语义而丢弃首因，也不能继续当成成功步骤。冻结后的 receipt 只绑定此前 report 的摘要与长度，并在原 persist 窗口记录后续持久化时间和结果，不把自身 hash 递归塞入自己。冻结报告不含发生在其冻结之后的持久化事实；失败时缺失 receipt 必须明确保留为未闭合。

## 离线验收记录（2026-10-18）

本包新增[纯校验模块](../../scripts/sw_i5_preparation_execution.py)和[负例测试](../../scripts/test_sw_i5_execution.py)，同步本专题及七份正式入口/专题文档，共十个文件。实施子任务只修改两份新脚本；Astra 主持设计、逐段审阅实现、独立运行测试及重算 hash 的变异检查，主持承担八份文档同步。这是工程离线验收，不是外部专业安全审计或原生执行验收。

| 实际执行的检查 | 结果与覆盖 |
| --- | --- |
| `python3 -B scripts/test_sw_i5_execution.py` | 主持最终运行 32 个方法通过（6.903 秒）；覆盖 JSON/类型/额度、源角色与导入闭包、声明绑定、旧消费者拒绝、纯函数无环境调用、物理前置缺项、工具参数/环境/语义、失败回收、冻结与 receipt、WORK/apt 鲜目录 |
| 主持独立八项变异 | 重新计算摘要后，局部 SCRIPT 覆盖、动态 builtin 别名、动态 loader 别名、额外未引用工件、错误 APT_CONFIG、bootstrap 布尔计数、早于冻结的 receipt、缺失关机均被拒绝 |
| `python3 -B scripts/test_sw_i5_preparation_plan.py` | 19 个方法通过 |
| `python3 -B scripts/test_sw_i5_utm_control.py` | 4 个方法通过；旧合同及入口停止检查保留 |
| `python3 -B scripts/test_sw_i5_apt.py` | 20 个方法通过 |
| `python3 -B scripts/test_sw_i5_guest.py` | 45 个方法通过 |
| `node scripts/test_sw_i5_utm_rpc.js` | 33 个纯用例通过，无 Application 调用 |
| 两份新增 Python 的 AST 语法检查 | 通过，无 bytecode 产物 |
| `./scripts/check-repo.sh`、`git diff --check` | 通过；仓库检查覆盖 218 个文件 |

首跑与审查问题保留如下：

1. 子任务首次 `python3 -B -m unittest discover -s scripts -p test_sw_i5_execution.py` 为 exit 1：21 个方法中 6 errors、1 failure，被 `changed JXA asset AST edge` 抢先阻断；全文件查找误将不同函数的局部 `source` 当成重复赋值。主持独立源码闭包检查也复现 exit 1。改为只检查 `collect_utm` 的词法范围后通过，没有放宽固定 JXA 依赖目标。
2. 主持重算摘要的变异曾接受三种动态源码绕过和未引用工件；修复固定锚点遮蔽、动态加载器别名和工件精确引用集合，并加入持久回归。不存在“只有摘要匹配就足够”的结论。
3. 审查收紧精确工具 argv/cwd/env、原始事件事实绑定、独立对象身份、失败后的清理序列及时间归属。冻结报告止于 freeze，后续持久化由 receipt 记录；工具语义失败另保留有界 `tool_diagnostics`，不吞掉检查原因或覆盖原始首因。
4. 对照既有编排发现已初始化 WORK 根不满足新建工作目录要求，改为固定 WORK/apt。新增 32 方法的首次运行 exit 1：合成测试误将 manifest 字符串传入要求 bytes 的旧编排，产生 `TypeError`；修正测试传参后通过，没有修改旧运行代码。兼容测试在合成临时目录中验证鲜目录约束，并在缺失输入处停止，未调用任何原生工具。

所有候选样例、工具输出和环境观察均为合成数据。AST 检查只覆盖固定已审阅源码形态，JXA 与复核测试按 bytes 绑定；没有通用反射安全分析、外部二进制来源/版本核验或对 supplied program/bootstrap 与固定源码实际组合关系的证明。原始 status 到语义投影的关系、密码学验签、原生 APT、真实物理额度、Linux/UTM 拒绝与回收以及当前任务执行授权，仍全部是独立阻塞项。

离线验收结束时，`dev` 为 `4281fb0`，相对本地 `origin/dev` ahead 3，本包十个文件未暂存、未提交。随后所有者明确授权将这十个文件提交到 `dev`、不 push，本包实现与记录随本次提交保存；提交前仅同步文档中的提交状态，未改变已验收代码。后续缺口与顺序梳理不包含下一包实现或外部操作授权。没有启动 VM、安装依赖、调用真实 UTM/原生工具、修改系统配置或远程状态；离线测试子进程已结束，无本轮后台进程。临时目录由测试清理，旧 evidence/cache 未清理。最后一次真实 VM 状态仍只能引用历史实测，本轮未查询 VM 状态。

后续第四包的物理承载候选、原生初始化、源码组装与独立 binding 实施另见[原生初始化与 bootstrap 离线实施](sw-g4-synthetic-i5-native-initialization.md)。本页 schema 1 及其历史验收结果不随新增后端自动升级；本页的“后端缺失”是第三包时点及其旧合同的明确边界。

## 后续关闭顺序

1. 将本候选设计落实为真实初始化及物理约束后端，补齐未知写入面与完整外部组件身份；在离线故障注入中验收，更新源闭包。
2. 固定真实基线、输入介质、工具与执行 bytes，生成无占位值的操作单；重新验证执行 revision、全部源码/资产/输入摘要、容量与时间账本。
3. 为启动前配置和单次准备验证分别明确外部动作及当次授权。Linux/UTM 验收须覆盖硬拒绝、取消、停摆、输出丢失、监督器强杀、正常/强制收尾与未知残留，不能由本包替代。
4. 验签与原生 APT 差量通过后，再评审安装/克隆身份与实际容量方案；准备验证不包含安装。完成完整 I5 资源/daemon 边界及环境验收后，才有资格另行评审入口重开和 I5-R 的 21 样本授权。

本包不减少上述任何停止条件，也不改变 E2EE、法规、许可证或正式场景的证据状态。
