# I5 环境可行性收敛与下一次操作包

- 日期：2026-10-13，Asia/Shanghai
- 状态：Draft，可审阅；安装差量为基线草案，完整依赖闭包及 768 MiB 后端可行性未通过，下一次操作尚不可执行
- 用途与读者：供所有者、环境实施者及复核者决定验签/解析范围、完整容量边界及后续实施前置
- 本轮授权：读取已保存证据、核算、形成文档并执行仓库检查；不启动 VM、不安装依赖、不运行 I5-R
- 非目标：新增解析器或运行入口、调整五域额度、接受安装锁、安全/许可证结论、修改旧 evidence 或授权记录

## 结论与证据基线

本轮已将安装需求归类，并把全部已知写入面逐项对应到原 768 MiB 合同。**当前 UTM 配置不具备 I5-R 条件；现有证据不能证明 768 MiB 对所有后端都不可行。** 下一次环境操作建议只做来源验签和原生 APT 离线模拟，结果回收后停止；安装、隔离配置、真实容量拒绝及冷构建仍是后续独立范围。

本轮是文档设计与证据核对；涉及的未来系统/依赖操作按 L3 评审，本轮不执行。未改变 [I5 资源合同](sw-g4-synthetic-i5-resource-isolation.md)、候选 JSON、入口 STOP、profile 或 evidence schema。

本地 `dev` 基线为 `763d7ac`，核对前工作区干净。原始输入沿用[完整补充盘点](sw-g4-synthetic-i5-environment-preparation.md#完整补充盘点与正常回收通过2026-10-09)及[候选清单](../../tools/t0/i5-environment-candidates.json)：

| 输入 | 原始位置（仓库相对路径） | 本轮复算 SHA-256 |
| --- | --- | --- |
| 完整 guest 返回，474110 bytes | `.tmp/i5-guest-return-bc35d1722b5534637cf3e5fc06adae40/details/guest.stdout` | `0eea97df8ad7c11b61e7cf5da3b4774d32e3fcb2b7d90c23066f35f66a92c300` |
| Docker Packages.gz，56440 bytes | `.tmp/i5-environment-plan-20261006/docker-Packages.gz` | `3271cf684b10183a5f930877b67efe0294f92ded4718caec59a0fd9a586d7146` |
| Docker InRelease，32480 bytes | `.tmp/i5-environment-plan-20261006/docker-InRelease` | `247d0572861a9deb52b8e6c1ba065685253af3c5c2fe433ae77f89d15e681ba6` |

这些忽略目录证据只读取、不修改或提交。包表为 1565 条、16 个字段，全部 `install ok installed`，该快照未见 hold；它是选定字段的盘点，**不是原始 dpkg status、APT extended_states 或完整 APT 配置副本**。没有据此伪造可用于正式求解的包数据库。VM 配置和 stopped 均引用 10 月 9 日历史事实，本轮没有查询实时状态。

## 安装差量草案

### 解析策略与明确需求

建议解析策略为：关闭自动 Recommends/Suggests，显式请求项目必需包；现有 1565 包默认保留原版本，不允许自动升级、降级、删除、重新安装或修复系统。若原生求解只能通过这些动作完成，输出冲突并停止，重新评审差量。策略是本操作包候选，尚未应用于 guest。

[现有预检](../../tools/t0/cmd/sw-v0-harness/process_runtime.go)调用 Git 核对 clean tree 和 revision，并执行 `docker build`；[构建 helper](../../scripts/sw_i5_build.py)关闭工具链自动下载。因此 Git、固定 Go 和固定 Buildx 均须显式列入，不能因它们不是 Engine 的强依赖而省略。Debian 的 Recommends 开关不会证明被省略包对项目无用，见 [apt-get](https://manpages.debian.org/trixie/apt/apt-get.8.en.html)。

| 分类 | 对象与固定候选 | 基线及处理 |
| --- | --- | --- |
| 明确新增，归档输入 | `go1.26.8.linux-arm64.tar.gz` | 路径盘点未见 Go；保留既有候选，不另外安装 `golang-go`；归档尚未下载/核验 |
| 明确新增，deb | `docker-ce:arm64=5:29.8.2-1~debian.13~trixie` | 未安装；含 `iptables` 强依赖、`init-system-helpers` Pre-Depends |
| 明确新增，deb | `docker-ce-cli:arm64=5:29.8.2-1~debian.13~trixie` | 未安装；不连带安装 Compose |
| 明确新增，deb | `containerd.io:arm64=2.3.6-1~debian.13~trixie` | 未安装；包内 runc 不再另配发行版 runc |
| 明确新增，deb | `docker-buildx-plugin:arm64=0.37.1-1~debian.13~trixie` | 未安装；已有 0.37.2 差异评审项保留，不能静默换版本 |
| 明确新增，版本待解析 | `iptables:arm64`、`git:arm64` | 均未安装；必须取自完整且通过验签的 Debian 索引，不能猜版本 |
| 候选传递依赖，待原生求解 | `libip4tc2`、`libip6tc2`、`git-man`、`liberror-perl` | 基线均未见；只是针对 iptables/Git 的待核对项，不声称已形成闭包，也不把这四项当成新增全集 |
| 排除自动引入 | `docker-ce-rootless-extras`、`docker-compose-plugin`、`docker-model-plugin`、`pigz` | 当前选定的独占 daemon/scratch 构建方案未提出需求；如实际硬依赖要求它们，停止评审，不强行排除以求成功 |
| 不选择的平行工具栈 | Debian `docker.io`、`docker-cli`、`containerd`、`runc`、`golang-go` | 包表均未见；不运行卸载命令，不复制官方文档中的批量 remove 示例 |
| 升级/降级/删除/重装 | 候选允许集合均为空 | 最终以固定输入上的 APT 结果复核；`--no-remove` 仅拒绝删除，不足以保证零升级 |

顶层是 **1 个 Go 归档 + 6 个明确 deb 需求**，其中四个 deb 已有固定候选、两个待定版本；不把它写成最终安装包数。

### 原版本保留基线

| 包 | 10 月 9 日版本 | 作用/限制 |
| --- | --- | --- |
| `libc6` | `2.41-12+deb13u3` | 候选依赖输入，仍由原生工具比较 Debian 版本 |
| `libseccomp2` | `2.6.0-2` | containerd 候选依赖输入 |
| `libsystemd0` | `257.13-1~deb13u1` | Engine 候选依赖输入 |
| `init-system-helpers` | `1.69~deb13u1` | 必须纳入 Pre-Depends/安装顺序求解 |
| `nftables` | `1.1.3-1` | 不代替尚缺的 iptables |
| `apparmor`、`ca-certificates` | `4.1.0-1`、`20250419` | 关闭推荐安装不意味着删除已有包 |
| `procps`、`xz-utils` | `2:4.0.4-9`、`5.8.1-1+deb13u1` | 保留现有诊断/解包工具 |
| `apt`、`dpkg` | `3.0.3`、`1.22.22` | 已有原生求解与包工具，不先安装替代解析器 |
| `gpgv`、`sqv` | `2.4.7-21+deb13u1+b4`、`1.3.0-3+b2` | 工具存在不等于签名通过；本包优先评审 gpgv 单一路径 |
| `debian-archive-keyring` | `2025.1` | 包存在不等于其中密钥已独立核对 |

另已查见 `libxtables12=1.8.11-2`、`libnftnl11=1.2.9-1`、`libmnl0=1.0.5-3`、`libcurl3t64-gnutls=8.14.1-2+deb13u4`、`perl=5.40.1-6`；这有助于后续差量核对，但不证明 Git/iptables 的全部版本关系成立。

完整 Docker stanza 另含 `containerd.io` 对 `containerd/runc` 的 Conflicts/Replaces/Provides，Buildx 对 CLI 的 Replaces，Engine/CLI 的版本化 Breaks/Replaces。正式解析必须使用完整 stanza 和 Debian 索引，不能递归候选 JSON 的 `depends` 字符串替代原生 APT。[Debian 包关系规范](https://www.debian.org/doc/debian-policy/ch-relationships.html)是语义依据，本轮只做字段对照。

### 安装体积与缺失输入

四个固定 deb 的归档合计 **71,051,976 bytes**，加 Go 为 **134,863,381 bytes（约 128.616 MiB）**；四 deb 的 Installed-Size 合计 **297,879 KiB（约 290.897 MiB）**。这些分别是传输字节和索引声明安装体积，不能相互替代。

准备阶段峰值还包含 Debian 新增闭包、Go 解包、索引/介质副本、APT/dpkg 状态、维护脚本/日志、回滚副本和文件系统开销，当前不能给出可信的总数。安装前必须同时列明归档留存与解包共存峰值、输入介质复制峰值；不只相加 Installed-Size。已准备且批次内真正只读的工具输入不占本批新增构建额度；准备阶段也不得提前生成 bootstrap/node/image 来转移批次成本。

仍缺：Debian trixie 对应来源的完整 Release/InRelease/Packages 与索引范围、可信密钥材料及完整 fingerprint、原生求解输入/结果、各新增包的精确版本/大小/hash、包内维护脚本/许可和 Go 实际归档。旧 Docker 索引只内部摘要一致，`signature_verified=false`、`install_authorized=false`、`i5_ready=false` 均保持。

## 768 MiB 完整写入核算

### 固定额度与判定式

| 域 | MiB | bytes | 域内已有预留/必须覆盖 |
| --- | ---: | ---: | --- |
| build | 256 | 268435456 | 两次 Go 构建、cache/temp/HOME、二进制、上下文、Buildx 客户端状态/日志及元数据 |
| daemon | 160 | 167772160 | data-root/exec-root、containerd root/state、builder、镜像、PID/socket/tmp/日志；含 12 MiB store 预留 |
| evidence | 240 | 251658240 | 正常 bundle、checksum、原子替换峰值及元数据 |
| diagnostic | 64 | 67108864 | 最多 32 MiB incomplete/rejected、最多 4 MiB batch-result；其余 28 MiB 仍要覆盖诊断/元数据 |
| node tmpfs | 48 | 50331648 | 三个 16 MiB，不重复发放，不额外开放 `/dev/shm` |
| 合计 | **768** | **805306368** | 四个磁盘域合计 720 MiB，无第六个免费域 |

对四个磁盘域，沿用 `D_i + H_i <= C_i`：D 是实际 guest 整块设备上限（已包含 ext4 元数据），H 是该域对应、未包含在 D 中的宿主 backing/控制记录等额外开销硬上限。系统新增写入、独立导出副本等也必须分配到某个 C 内，不能遗漏或重复归属。同一逻辑数据在 guest 与 backing 的表示不再算两遍，但独立副本需要计峰值。节点 tmpfs 的 48 MiB 继续计入总额。

**若 D 分别取 256/160/240/64 MiB，四域可容纳的 H 合计就是 0。** 当前已知的域外写入不能取零，所以“满额四盘后安装”路线不成立。可考虑在原 C 内减小实际 D，为有证据的 H 留空间；本轮不猜 H、不调整子额度、不创建盘。每个域内峰值能否容纳真实冷构建和 21 样本，仍需在硬边界建立后验收。

### 完整归属及关闭方法

| 写入面 | 归属/拟处理 | 当前缺口与拒绝条件 |
| --- | --- | --- |
| Go/bootstrap/node/Buildx 客户端 | build；空缓存起步、保留现有受限构建 helper | 运行接入及身份移交未完成；用户缓存、域外 temp 或预构建输入均拒绝 |
| daemon/containerd/builder/镜像/store | daemon；所有 root/state/tmp/log 显式绑定 | 单设 data-root 不足；版本、image store、builder、socket 和控制阻塞期间检查未实证 |
| bundle 与原子写 | evidence | 文件字节账本已有，块级硬边界未建；导出时原件与副本并存须预留 |
| 失败/回收记录 | diagnostic | 32 + 4 MiB 后的 28 MiB 不是可直接给宿主使用的净余量，还含文件系统与其他诊断 |
| 节点 tmpfs | 48 MiB；三个 size=16 MiB，IPC none | 实际 noswap/挂载及拒绝路径待验；不能把宿主或 guest 其他 tmpfs 算进这三个额度 |
| guest `/dev/vda4` swap | 候选在专用环境内禁用并验证全程无其他 swap；否则全部换出需有界归属 | 历史容量 2,774,528,000 bytes，约为总额 3.445 倍，used=0 仅为采样；不能保留这条未计费写入通道 |
| guest 根/var、EFI、efivarfs | 批次输入只读；必要新增状态须重定向到既定域 | 目前可写，启动日志、journal、随机种子、包状态等不受 build namespace 约束；EFI 分区只读也不证明固件变量不写 |
| guest `/tmp`、`/run`、`/dev/shm` | 列出系统与 daemon 所需状态，限制在既定域或拒绝额外写入口 | 现有普通 tmpfs flags 未见 noswap；换出与额外挂载尚未关闭，不能默认免费 |
| 四盘 backing 格式/宿主分配 | 各自 H；保留可证明的硬上限 | QCOW2/raw 的表观长度及 du 样本不能替代物理上限；四盘尚不存在 |
| UTM/QEMU 日志、UEFI 变量、状态/临时文件 | 精确清单后纳入域内硬上限，或证明不写 | 关闭 debug log 不覆盖所有写入；实际路径与上限未绑定 |
| 宿主换出/崩溃转储等系统写入 | 必须识别是否因本批新增、是否纳入现行完整写入合同；无法隔离时提交边界评审 | guest swapoff 不控制 macOS；本轮未调查、未修改宿主系统，不默认为零或自行豁免 |
| 宿主证据回收副本 | evidence/diagnostic 的完整额度内保留复制峰值 | 不以删除源后最终小于额度证明复制过程达标；旧准备采集器不是 I5 硬隔离回收器 |

tmpfs 的换出语义以 [Linux 文档](https://docs.kernel.org/filesystems/tmpfs.html)为依据，目标内核支持和实际挂载仍需实查。[UTM 磁盘说明](https://docs.getutm.app/settings-qemu/drive/drive/)不能证明本项目完整宿主硬上限；[QEMU snapshot](https://www.qemu.org/docs/master/system/invocation.html)仍写临时文件，不能用它宣称系统零新增写入。

宿主/guest 的 ≥ 1 GiB 余量检查只是外部压力保护，不增加 768 MiB；缓存清理和分阶段删除不重新发放账本额度。准备期安装空间与运行期新增写入分别记录，不能把本批产生的后台写入改名为“预装环境”排除。

### 可行性决定

1. **当前 UTM 配置：拒绝进入 I5-R。** 原因是存在未受限写入通道与未知 H，且四域/隔离尚未创建；不是已经观察到一次运行超过 768 MiB。
2. **UTM 有界改造：保留为待证明候选。** 必须先拿出宿主承载、系统/固件/日志和交换的完整硬限制机制，再定实际 D、身份交接及真实拒绝实验。只读静态资料不足时保持 STOP，不先安装尝试。
3. **其他 Linux 后端：只保留比较方向。** 若 UTM 无法关闭上述边界，再评审其他后端的成本和约束；不自动换平台、采购、提高额度或豁免写入。

当前无法给出可批准的四盘尺寸/格式化命令或安装总空间。未知值明确阻止执行，这就是本轮容量收敛结论。

## 下一次环境操作包：验签与原生离线解析候选

### 目标、范围和执行前缺件

精确目标仍为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`；只允许该专用副本，保持无网卡、无剪贴板/目录共享。目标是取得可复核的来源验签与安装差量；**不是安装包、I5 环境验收包或 I5-R 授权包**。

| 执行前交付物 | 必须绑定的内容 | 当前状态 |
| --- | --- | --- |
| 离线来源集合 | 原 Docker 索引，所选 Debian 来源/suite/component/architecture 的完整签名和索引；逐文件 size/hash，拒绝无关源 | Docker 原件可用，Debian 集合未固定 |
| 信任集合 | Docker 完整 fingerprint 与独立可信依据、Debian 官方归档 key 对照、专属只读 keyring 格式/hash | 未完成；不从待验证 InRelease 自己接受签名者 |
| 解析输入 | 原始 dpkg status/extended_states、native/foreign architectures、包 selections 与基线差异；禁止使用重建 TSV 冒充原库 | 下一次从目标只读取得，输出本地 hash/必要语义字段，不采源凭据 |
| 专用 APT 配置 | 固定索引、隔离 lists/cache/log/status/preferences，关闭系统片段和 hooks，冻结全部已有包版本 | 未实现/验证；不得只加 `-s` 后继承系统配置 |
| 只读介质 | 完整镜像文件及 hash、精确挂载点、原 `sr0` 介质引用与恢复值 | 未创建；不替换已挂介质或使用共享目录 |
| 容量与回收实施 | 元数据准备自身的输入/暂存/双份输出峰值、超限拒绝、子进程取消及正常关机 | 待离线实施与复核，不复用旧采集器的留存限额声称硬限制 |
| 单次绑定 | 新 revision/源码摘要、VM/utmctl/config 摘要、新 nonce、全部 VM 前后状态、当前任务明确批准 | 未形成，不填写 `authorized=true`，历史七包不可复用 |

Docker 密钥获取位置以[官方 Debian 安装说明](https://docs.docker.com/engine/install/debian/)中的 `https://download.docker.com/linux/debian/gpg` 为候选；同源下载地址本身不满足独立信任核对。[Debian 归档签名页](https://ftp-master.debian.org/keys.html)提供官方 fingerprint/轮换信息。实际 key 内容、fingerprint、有效性/撤销处理须另行固定，本轮没有下载或导入密钥。

### 顺序、命令形状与验收

以下为供评审的 argv/配置要求，带 `<...>` 的参数尚未绑定，**不是当前可执行指令**。先补输入和适配层，再生成逐字、无占位符的单次清单；本轮不新增一个能绕过现有停止线的 runner。

| 步骤 | 拟执行操作/命令形状 | 通过条件与失败处理 |
| --- | --- | --- |
| 宿主前置 | 离线核验 manifest、只读介质和源码；核验目标 UUID/config/stopped、全部 VM 状态 | 未绑定项、状态差异、旧 attempt 或已消费 nonce 均在启动前拒绝 |
| 介质与启动 | 保存原介质，按精确配置装入只读输入；沿用无 hide 启动/严格 stderr 检查的生命周期原则 | 仅目标启动一次；不改网络/共享/磁盘容量，启动错误进入回收 |
| guest 基线 | `/usr/bin/dpkg --print-architecture`、`--print-foreign-architectures`；只读校验 status/extended_states 与 selections | 无安装中状态；与 1565 包基线的任何差异停止重评；不自动适配新基线 |
| 来源验签 | `/usr/bin/gpgv --homedir <空的专属目录> --keyring <已核对只读keyring> --status-fd 1 <InRelease>` | 保存真实退出码及状态，匹配完整 signer/primary fingerprint；正常诊断 stderr 可保留，不按是否为空替代签名判断；任一失败不继续 |
| 索引链 | 从已验签 Release 数据核对路径、size、SHA-256；受限解压固定 Packages，校验 suite/component/architecture/日期 | 不用同一个未验证索引证明自己可信；过期/时间异常停止，不关闭日期/真实性检查 |
| APT 隔离核对 | 用 `APT_CONFIG=<专属配置>` 调用 `/usr/bin/apt-config dump`；只处理批准的本地 `file:` 索引输入 | 无系统配置片段、网络源、未批准 hooks 或默认 cache/log；缺任一索引不联网补齐 |
| APT 模拟 | `/usr/bin/apt-get -s --no-download --no-install-recommends --no-remove -o APT::Install-Suggests=false install <六个精确name:arch=version>` | 完整记录 Inst/Conf/Remv 与新增闭包；无升级/降级/删除/重装/原库变化，包数及关系可解释；不执行真实 dpkg 安装 |
| 回收 | 保存索引/配置/status 摘要、逐包差量及 stdout/stderr/退出码；核对原始包数据库未变，正常关机并恢复原介质 | 后代已退出、目标 stopped、其他 VM 状态及非批准配置未变；失败残留保留，输出只称准备证据 |

gpgv 验证成功需要与预审 keyring 和指纹共同解释，不能把任意 key 导入后返回 0 当成可信来源，见 [gpgv 手册](https://manpages.debian.org/trixie/gpgv/gpgv.1.en.html)。APT 原生模拟保留安装关系语义，单凭 `-s` 不证明配置、缓存或外部包装器无副作用。[apt.conf](https://manpages.debian.org/trixie/apt/apt.conf.5.en.html)说明 `APT_CONFIG`/配置片段读取顺序与各状态目录，因此必须先验证专属配置不读系统片段；不采用仅追加 `-c` 的伪隔离。APT 输出非零或缺输入不追加 `--fix-broken`、`--ignore-missing`、`--allow-unauthenticated`。

索引准备可以在专属 APT 状态目录内使用固定本地介质生成 lists；必须将准确 argv、`file:` 源、索引文件名映射和写目录一并列入后续实施清单。它不更新系统 `/var/lib/apt/lists`，不接触系统 `/etc/apt`，不把网络 `apt update` 隐藏在“解析”中。原始 status 只在 guest 内复制到受限暂存区并冻结，不导出可能含非必要文件路径的完整库；外带结果为 hash、版本/关系和差量。

### 时间、空间、副作用与回滚候选

- 计划一次运行预计 10–15 分钟；建议控制上限为启动 60 秒、就绪检查 60 秒、验签每份 30 秒、索引准备与解析合计 300 秒、结果回收 60 秒、正常关机 120 秒，包级最多 15 分钟。不是实测保证；超时停止，不自动重试或续跑。
- 准备操作空间建议先以只读元数据介质不超过 256 MiB、guest 专属暂存不超过 128 MiB、guest 结果不超过 8 MiB、宿主传输/解码/诊断合计留存不超过 32 MiB 作为待评审限额；stdout/stderr 每步分别不超过 2 MiB/64 KiB。完整索引尚未收齐，不能保证这些数足够；不足时调整草案并重新评审，不截断为成功。
- 上述是**准备操作候选限额，不是新增的 I5 运行额度**。宿主镜像制作双份占用、系统启动/暂存/swap/日志额外写入仍须在该次准备合同中绑定和说明；尚无完整准备期硬限制证据，所以这些数字目前不能用作执行许可或实际峰值结论。
- 实际副作用包括目标开关机、原 CD 引用临时替换、guest 受限暂存与启动日志、宿主证据落盘；即使只模拟 APT 也不能称“完全无写入”。只读介质与受限暂存所需挂载必须精确列入最终合同；不改 swap、其他挂载、账号、服务、系统密钥库或系统包状态，相关操作留给后续安装/隔离合同。
- `finally` 必须先取消并确认该次 guest 进程/后代退出，再正常关机、确认 stopped 后恢复原介质；外层超时不能证明 guest 已停止。若要沿用一次强制停止作为最后回收，必须在最终合同中明确列出 UUID、等待时间与数据完整性风险，当前无此授权；强制停止结果不能 PASS。
- 旧强制停止后的系统盘完整性缺口保留。验签/解析结果即使成功也不能关闭它；正式安装前另行制定不对已挂载可写根做修复的检查方案。本包不执行 fsck、自动修复或把“能启动”写成完整性通过。
- 回滚只恢复本包明确改变的 CD/临时设置，不宣称回滚启动日志或文件系统所有写入。暂存/失败证据按精确 manifest 保留，不递归清理 VM 或仓库；清理命令须在最终合同中绑定具体目标。

现有 [UTM 生命周期控制器](../../scripts/sw_i5_utm_control.py)只接受 preparation-details，现有采集输出上限属于返回/留存检查，且超时不保证 guest 取消。**它目前不能直接执行本包。** 后续实施应复用既有传输和生命周期职责，增加严格隔离的验签/解析范围、逐步退出码/限额/后代回收测试；旧 details scope 及历史合同不扩张。该实现不在本轮文档任务内。

## 决策顺序与完成条件

| 下一动作 | 产物/关闭标准 | 当前结论 |
| --- | --- | --- |
| 宿主离线输入准备 | 完整索引、信任依据、精确 keyring/介质清单；所有版本/hash/大小可审阅 | 可继续只读资料核对；不安装工具、不生成授权记录 |
| 验签/解析包离线实施 | 固定配置、受限输出、取消/回收、拒绝测试，准确 argv 和零占位符 manifest | 待单独实施；准备完整后再申请一次 L3 执行 |
| UTM 完整承载方案 | 每域实际 D/H、系统/固件/交换/宿主写入全部有机制和硬上限；容量不足时如何拒绝及回收 | 未通过；不能用验签包通过替代 |
| 安装与隔离准备 | 已验证归档/许可/维护脚本，安装总峰值、服务自动启动抑制、身份与恢复清单 | 本包不包含；依赖差量成功也不自动安装 |
| 真实环境验收与 I5-R | 独立硬边界、冷构建、daemon/store、域外拒绝、后代回收通过后，再评审入口重开与 21 样本 | 继续 STOP；不改 768 MiB 或原矩阵 |

本轮文档由同一编写者核对，不构成独立安全/法律审查。安装差量草案、容量归属和下一包范围已形成；验签、APT 闭包、来源归档及容量实测均未执行。不以准备文档完成宣称环境就绪。

## 本轮验证与交接

- 用 Python 标准库只读复算上述三个原始文件的摘要，核对 1565 条包记录、所列表内版本/缺包事实、四个固定 deb 的唯一索引记录及 size/hash/Depends/Recommends；归档、Installed-Size、swap 和五域字节算术全部通过。这不是 Debian 版本求解或密码学验签。
- `./scripts/check-repo.sh` 通过（193 文件，包括新文档）；`git diff --check` 通过。复核新增文档与六处状态/索引更新，未修改受运行合同绑定的源码、候选 JSON、预算配置或旧原始证据。
- 本轮只改文档，没有运行 Go/Docker/guest 测试、构建、VM、安装或 I5-R；未新增后台进程、未提交/push、未改变远程状态。改动保留在本地 `dev` 工作区供审阅。
