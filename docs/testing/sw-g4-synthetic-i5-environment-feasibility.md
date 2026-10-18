# I5 环境可行性收敛与下一次操作包

- 日期：2026-10-18，Asia/Shanghai
- 状态：最新离线实现 `fa48743`，宿主/loader/路线 A 预算设计 `40520ae`，均未 push；所有者确认仅有 Mac/UTM、暂不采购，暂无满足完整写入合同的 Linux 宿主。真实验签/原生闭包、FD loader、物理环境验收及 I5-R 均未通过，下一次操作尚不可执行
- 用途与读者：供所有者、环境实施者及复核者决定验签/解析范围、完整容量边界及后续实施前置
- 授权沿革：初稿为证据核对与文档设计，随后逐轮明确授权离线实现、测试与提交，各节保留当时范围；始终不启动 VM、不安装依赖、不运行 I5-R
- 非目标：自写 OpenPGP/依赖求解器、开启真实运行入口、调整五域额度、接受安装锁、安全/许可证结论、修改旧 evidence 或授权记录

## 结论与证据基线

初稿已将安装需求归类，并把全部已知写入面逐项对应到原 768 MiB 合同。**当前 UTM 配置不具备 I5-R 条件；现有证据不能证明 768 MiB 对所有后端都不可行。** 10 月 18 日收尾已选 A，当前先受[已有宿主资源门](sw-g4-synthetic-i5-linux-host-assessment.md)阻塞；不能直接执行初稿的验签/APT 建议。资源、真实加载链与完整物理边界关闭并另获授权后，才评审来源验签和原生 APT 离线模拟；安装及正式 I5 仍是独立范围。最新顺序见[日终接续事项](../status/2026-10-18-progress.md#接下来的事项)。

初稿阶段仅做文档设计与证据核对；后续离线实现另按各节记录。涉及的未来系统/依赖操作按 L3 评审，本日未执行。未改变 [I5 资源合同](sw-g4-synthetic-i5-resource-isolation.md)、候选 JSON、入口 STOP、profile 或 I5 运行 evidence schema；新增准备合同独立版本化。

本页初稿及六处入口同步已按所有者要求提交为 `e16ee48`，未 push。随后获准继续补齐信任输入与离线实施方案；信任输入见[续接输入与实施方案](#续接可信输入与离线实施方案2026-10-13)，已提交实现见[UTM 传输与证据持久化](#utm-传输与证据持久化离线续接2026-10-13)，RPC/生命周期见[内部接线验收](#受监督-rpc-与单次生命周期离线接线2026-10-18)，最新实现与缺口见[初始化合同与容量账本离线评审](#初始化合同与容量账本离线评审2026-10-18)；[10 月 13 日回顾](../status/2026-10-13-progress.md#接下来的事项)保留当时接续顺序。前面的静态包表不视为原生求解结果。

初稿开始时本地 `dev` 基线为 `763d7ac`，核对前工作区干净。原始输入沿用[完整补充盘点](sw-g4-synthetic-i5-environment-preparation.md#完整补充盘点与正常回收通过2026-10-09)及[候选清单](../../tools/t0/i5-environment-candidates.json)：

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
| 明确新增，版本候选已取证 | `iptables:arm64=1.8.11-2`、`git:arm64=1:2.47.3-0+deb13u1` | 均未安装；续接已取得完整索引中的精确条目，仍待验签及原生求解，不是安装锁 |
| 候选传递依赖，待原生求解 | `libip4tc2`、`libip6tc2`、`git-man`、`liberror-perl` | 基线均未见；只是针对 iptables/Git 的待核对项，不声称已形成闭包，也不把这四项当成新增全集 |
| 排除自动引入 | `docker-ce-rootless-extras`、`docker-compose-plugin`、`docker-model-plugin`、`pigz` | 当前选定的独占 daemon/scratch 构建方案未提出需求；如实际硬依赖要求它们，停止评审，不强行排除以求成功 |
| 不选择的平行工具栈 | Debian `docker.io`、`docker-cli`、`containerd`、`runc`、`golang-go` | 包表均未见；不运行卸载命令，不复制官方文档中的批量 remove 示例 |
| 升级/降级/删除/重装 | 候选允许集合均为空 | 最终以固定输入上的 APT 结果复核；`--no-remove` 仅拒绝删除，不足以保证零升级 |

顶层是 **1 个 Go 归档 + 6 个明确 deb 需求**。初稿时两个 Debian 版本待定，续接已补齐候选；不把直接需求数写成最终安装包数。

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
| `gpgv`、`sqv` | `2.4.7-21+deb13u1+b4`、`1.3.0-3+b2` | 工具存在不等于签名通过；初稿优先评审 gpgv，续接改为下文固定 sqv 验签候选，不作为运行时 fallback |
| `debian-archive-keyring` | `2025.1` | 包存在不等于其中密钥已独立核对 |

另已查见 `libxtables12=1.8.11-2`、`libnftnl11=1.2.9-1`、`libmnl0=1.0.5-3`、`libcurl3t64-gnutls=8.14.1-2+deb13u4`、`perl=5.40.1-6`；这有助于后续差量核对，但不证明 Git/iptables 的全部版本关系成立。

完整 Docker stanza 另含 `containerd.io` 对 `containerd/runc` 的 Conflicts/Replaces/Provides，Buildx 对 CLI 的 Replaces，Engine/CLI 的版本化 Breaks/Replaces。正式解析必须使用完整 stanza 和 Debian 索引，不能递归候选 JSON 的 `depends` 字符串替代原生 APT。[Debian 包关系规范](https://www.debian.org/doc/debian-policy/ch-relationships.html)是语义依据，本轮只做字段对照。

### 安装体积与缺失输入

四个固定 deb 的归档合计 **71,051,976 bytes**，加 Go 为 **134,863,381 bytes（约 128.616 MiB）**；四 deb 的 Installed-Size 合计 **297,879 KiB（约 290.897 MiB）**。这些分别是传输字节和索引声明安装体积，不能相互替代。

准备阶段峰值还包含 Debian 新增闭包、Go 解包、索引/介质副本、APT/dpkg 状态、维护脚本/日志、回滚副本和文件系统开销，当前不能给出可信的总数。安装前必须同时列明归档留存与解包共存峰值、输入介质复制峰值；不只相加 Installed-Size。已准备且批次内真正只读的工具输入不占本批新增构建额度；准备阶段也不得提前生成 bootstrap/node/image 来转移批次成本。

续接已补齐候选 Debian 来源范围、完整 InRelease/Packages、公钥文件及官方预期 fingerprint，并取得六个 Debian 静态新增候选的版本/大小/hash。仍缺公钥实际指纹核验、来源验签、原生求解输入/结果、最终新增闭包、包内维护脚本/许可和 Go 实际归档。旧 Docker 索引只内部摘要一致，`signature_verified=false`、`install_authorized=false`、`i5_ready=false` 均保持。

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
| 离线来源集合 | 原 Docker 索引，所选 Debian 来源/suite/component/architecture 的完整签名和索引；逐文件 size/hash，拒绝无关源 | 三组 Debian main/arm64 候选已固定，压缩/解压摘要一致；四份 InRelease 均未验签 |
| 信任集合 | Docker 完整 fingerprint 与独立可信依据、Debian 官方归档 key 对照、专属只读 keyring 格式/hash | 三份公钥及官方预期主指纹已固定；实际 key 指纹/有效性未由成熟工具验证 |
| 解析输入 | 原始 dpkg status/extended_states、native/foreign architectures、包 selections 与基线差异；禁止使用重建 TSV 冒充原库 | 下一次从目标只读取得，输出本地 hash/必要语义字段，不采源凭据 |
| 专用 APT 配置 | 固定索引、隔离 lists/cache/log/status/preferences，关闭系统片段和 hooks，冻结全部已有包版本 | 未实现/验证；不得只加 `-s` 后继承系统配置 |
| 只读介质 | 完整镜像文件及 hash、精确挂载点、原 `sr0` 介质引用与恢复值 | 未创建；不替换已挂介质或使用共享目录 |
| 容量与回收实施 | 元数据准备自身的输入/暂存/双份输出峰值、超限拒绝、子进程取消及正常关机 | 待离线实施与复核，不复用旧采集器的留存限额声称硬限制 |
| 单次绑定 | 新 revision/源码摘要、VM/utmctl/config 摘要、新 nonce、全部 VM 前后状态、当前任务明确批准 | 未形成，不填写 `authorized=true`，历史七包不可复用 |

Docker 密钥获取位置以[官方 Debian 安装说明](https://docs.docker.com/engine/install/debian/)中的 `https://download.docker.com/linux/debian/gpg` 为依据；同源下载地址本身不满足独立信任核对。续接已保存公钥、Docker 官方文档固定提交和[Debian 归档签名页](https://ftp-master.debian.org/keys.html)，详见下文。没有导入系统密钥，公钥实际指纹、有效性/撤销及来源签名仍待核验。

### 顺序、命令形状与验收

以下为供评审的 argv/配置要求，带 `<...>` 的参数尚未绑定，**不是当前可执行指令**。先补输入和适配层，再生成逐字、无占位符的单次清单；本轮不新增一个能绕过现有停止线的 runner。

| 步骤 | 拟执行操作/命令形状 | 通过条件与失败处理 |
| --- | --- | --- |
| 宿主前置 | 离线核验 manifest、只读介质和源码；核验目标 UUID/config/stopped、全部 VM 状态 | 未绑定项、状态差异、旧 attempt 或已消费 nonce 均在启动前拒绝 |
| 介质与启动 | 保存原介质，按精确配置装入只读输入；沿用无 hide 启动/严格 stderr 检查的生命周期原则 | 仅目标启动一次；不改网络/共享/磁盘容量，启动错误进入回收 |
| guest 基线 | `/usr/bin/dpkg --print-architecture`、`--print-foreign-architectures`；只读校验 status/extended_states 与 selections | 无安装中状态；与 1565 包基线的任何差异停止重评；不自动适配新基线 |
| 公钥/来源验签 | 先由 GPG `--show-keys` 核对完整主/子指纹，再由固定 sqv `--cleartext --keyring ... --output ...` 验签；准确参数见续接方案 | 保存真实退出码、认证输出及签名者，限定预审主证书及有效绑定子钥；正常诊断 stderr 可保留；任一失败不继续 |
| 索引链 | 从已验签 Release 数据核对路径、size、SHA-256；受限解压固定 Packages，校验 suite/component/architecture/日期 | 不用同一个未验证索引证明自己可信；过期/时间异常停止，不关闭日期/真实性检查 |
| APT 隔离核对 | 用 `APT_CONFIG=<专属配置>` 调用 `/usr/bin/apt-config dump`；只处理批准的本地 `file:` 索引输入 | 无系统配置片段、网络源、未批准 hooks 或默认 cache/log；缺任一索引不联网补齐 |
| APT 模拟 | `/usr/bin/apt-get -s --no-download --no-install-recommends --no-remove -o APT::Install-Suggests=false install <六个精确name:arch=version>` | 完整记录 Inst/Conf/Remv 与新增闭包；无升级/降级/删除/重装/原库变化，包数及关系可解释；不执行真实 dpkg 安装 |
| 回收 | 保存索引/配置/status 摘要、逐包差量及 stdout/stderr/退出码；核对原始包数据库未变，正常关机并恢复原介质 | 后代已退出、目标 stopped、其他 VM 状态及非批准配置未变；失败残留保留，输出只称准备证据 |

验签必须与预审 keyring 和指纹共同解释，不能把任意 key 导入后返回 0 当成可信来源。APT 原生模拟保留安装关系语义，单凭 `-s` 不证明配置、缓存或外部包装器无副作用。[apt.conf](https://manpages.debian.org/trixie/apt/apt.conf.5.en.html)说明 `APT_CONFIG`/配置片段读取顺序与各状态目录，因此必须先验证专属配置不读系统片段；不采用仅追加 `-c` 的伪隔离。APT 输出非零或缺输入不追加 `--fix-broken`、`--ignore-missing`、`--allow-unauthenticated`。

索引准备可以在专属 APT 状态目录内使用固定本地介质生成 lists；必须将准确 argv、`file:` 源、索引文件名映射和写目录一并列入后续实施清单。它不更新系统 `/var/lib/apt/lists`，不接触系统 `/etc/apt`，不把网络 `apt update` 隐藏在“解析”中。原始 status 只在 guest 内复制到受限暂存区并冻结，不导出可能含非必要文件路径的完整库；外带结果为 hash、版本/关系和差量。

### 时间、空间、副作用与回滚候选

- 计划一次运行预计 10–15 分钟；建议控制上限为启动 60 秒、就绪检查 60 秒、验签每份 30 秒、索引准备与解析合计 300 秒、结果回收 60 秒、正常关机 120 秒，包级最多 15 分钟。不是实测保证；超时停止，不自动重试或续跑。
- 准备操作空间建议先以只读元数据介质不超过 256 MiB、guest 专属暂存不超过 128 MiB、guest 结果不超过 8 MiB、宿主传输/解码/诊断合计留存不超过 32 MiB 作为待评审限额；stdout/stderr 每步分别不超过 2 MiB/64 KiB。完整索引尚未收齐，不能保证这些数足够；不足时调整草案并重新评审，不截断为成功。
- 上述是**准备操作候选限额，不是新增的 I5 运行额度**。宿主镜像制作双份占用、系统启动/暂存/swap/日志额外写入仍须在该次准备合同中绑定和说明；尚无完整准备期硬限制证据，所以这些数字目前不能用作执行许可或实际峰值结论。
- 实际副作用包括目标开关机、原 CD 引用临时替换、guest 受限暂存与启动日志、宿主证据落盘；即使只模拟 APT 也不能称“完全无写入”。只读介质与受限暂存所需挂载必须精确列入最终合同；不改 swap、其他挂载、账号、服务、系统密钥库或系统包状态，相关操作留给后续安装/隔离合同。
- `finally` 必须先取消并确认该次 guest 进程/后代退出，再正常关机、确认 stopped 后恢复原介质；外层超时不能证明 guest 已停止。若要沿用一次强制停止作为最后回收，必须在最终合同中明确列出 UUID、等待时间与数据完整性风险，当前无此授权；强制停止结果不能 PASS。
- 旧强制停止后的系统盘完整性缺口保留。验签/解析结果即使成功也不能关闭它；正式安装前另行制定不对已挂载可写根做修复的检查方案。本包不执行 fsck、自动修复或把“能启动”写成完整性通过。
- 回滚只恢复本包明确改变的 CD/临时设置，不宣称回滚启动日志或文件系统所有写入。暂存/失败证据按精确 manifest 保留，不递归清理 VM 或仓库；清理命令须在最终合同中绑定具体目标。

初稿时 [UTM 生命周期控制器](../../scripts/sw_i5_utm_control.py)仅有 details 生命周期，采集超时不保证 guest 取消。随后已新增准备范围的内部编排、独立监督、双向租约及传输/持久化模块，见后续实施节；公开 preparation-apt scope 仍在外部调用前 STOP，**当前不能直接执行本包**。旧 details scope 及历史合同不扩张，内部函数和合成测试不构成真实生命周期已接通的证据。

## 决策顺序与完成条件

| 下一动作 | 产物/关闭标准 | 当前结论 |
| --- | --- | --- |
| 宿主离线输入准备 | 完整索引、信任依据、精确 keyring/介质清单；所有版本/hash/大小可审阅 | 固定索引/公钥字节及依据已取得；仍缺实际指纹/签名、原生基线、介质与源程序交付绑定，不把 review manifest 当执行授权 |
| 验签/解析包离线实施 | 固定配置、受限输出、取消/回收、拒绝测试，准确 argv 和零占位符 manifest | 内部编排至传输/持久化已提交；10 月 18 日 RPC/生命周期内部接线及 897/900 秒核算通过离线验收，已提交为 `17a142e`，未 push；随后初始化/容量校验已提交为 `e6d50ff`，合成初始化/暂存接线随本次提交保存，未 push；仍缺真实输入/初始化后端、完整硬额度及包含新增源文件的执行合同，完整后再申请 L3 执行 |
| UTM 完整承载方案 | 每域实际 D/H、系统/固件/交换/宿主写入全部有机制和硬上限；容量不足时如何拒绝及回收 | 未通过；不能用验签包通过替代 |
| 安装与隔离准备 | 已验证归档/许可/维护脚本，安装总峰值、服务自动启动抑制、身份与恢复清单 | 本包不包含；依赖差量成功也不自动安装 |
| 真实环境验收与 I5-R | 独立硬边界、冷构建、daemon/store、域外拒绝、后代回收通过后，再评审入口重开与 21 样本 | 继续 STOP；不改 768 MiB 或原矩阵 |

本轮文档由同一编写者核对，不构成独立安全/法律审查。安装差量草案、容量归属和下一包范围已形成；验签、APT 闭包、来源归档及容量实测均未执行。不以准备文档完成宣称环境就绪。

## 初稿验证与交接

- 用 Python 标准库只读复算上述三个原始文件的摘要，核对 1565 条包记录、所列表内版本/缺包事实、四个固定 deb 的唯一索引记录及 size/hash/Depends/Recommends；归档、Installed-Size、swap 和五域字节算术全部通过。这不是 Debian 版本求解或密码学验签。
- `./scripts/check-repo.sh` 通过（193 文件，包括新文档）；`git diff --check` 通过。复核新增文档与六处状态/索引更新，未修改受运行合同绑定的源码、候选 JSON、预算配置或旧原始证据。
- 本轮只改文档，没有运行 Go/Docker/guest 测试、构建、VM、安装或 I5-R；未新增后台进程、未提交/push、未改变远程状态。改动保留在本地 `dev` 工作区供审阅。

## 续接：可信输入与离线实施方案（2026-10-13）

本节在 `e16ee48` 之后形成。**已固定输入字节及其信任依据，尚未将索引判为可信。** 宿主 PATH 未找到 gpg/gpgv/sq/sqv/apt-get；没有安装替代工具、自写 OpenPGP 验证器或启动 guest。后续验签失败仍必须停止，不把下列摘要一致当作真实性通过。

### 完整索引、来源范围与有效期

新证据保存在 `.tmp/i5-source-inputs-20261013/`。`input-manifest.json` 为只供评审的本地清单，SHA-256 `aba40b4e108d3a3e87f846d59875956198b02c6545675debc429ecc5438f858e`，记录 13 个完整输入的 URL/相对路径/bytes/hash、静态包条目和失败；不被运行入口消费，四个就绪/授权字段均为 false。没有改写 `tools/t0/i5-environment-candidates.json` 或旧 Docker 原件。

候选范围为 Debian `trixie`、`trixie-updates`、`trixie-security` 的 **main/binary-arm64**，以及原 Docker `trixie/stable/binary-arm64`。不包含 backports、其他架构、contrib/non-free 或第三方镜像；原生求解若需要范围外输入，报告缺口，不自动扩源。三份 arm64 Packages 分别含 33690、5、918 个 `Architecture: all` 条目，不需要为此重复导入 binary-all；这是本次实际索引事实，不是对所有仓库布局的假设。

| 本地文件 | bytes | SHA-256 |
| --- | ---: | --- |
| `debian-trixie.InRelease` | 140421 | `0584fba32e13e0ab8285fb16c27adea1ec03a73669c18702821094fd6ca86675` |
| `debian-trixie.Packages.xz` | 9614192 | `be16b37b2f740f066ea93d35d56f04f94d63693e5a3eb421b052bf86fae75bcd` |
| `debian-trixie-updates.InRelease` | 47340 | `7348aa608c589b8d6421e8311f69deba685235a87681abe1879981f846f9122d` |
| `debian-trixie-updates.Packages.xz` | 4424 | `fe771d58d4af39dbb94142d6f3ce578d340c6b1364c172d9e87f2287bdc4994b` |
| `debian-trixie-security.InRelease` | 43405 | `bb902750387fe79f2b00ddac62b8b704b44ffa898c46bbc5d8cc37e9318af850` |
| `debian-trixie-security.Packages.xz` | 267436 | `cc3408b5c79a4a53c6af798750ba0e1d12525846f2914f3c0817cbeb251d2da5` |

主/updates 的来源根分别为 `https://deb.debian.org/debian/dists/trixie/`、`https://deb.debian.org/debian/dists/trixie-updates/`，security 为 `https://security.debian.org/debian-security/dists/trixie-security/`。InRelease 按根路径取得；Packages.xz 使用根下 `main/binary-arm64/by-hash/SHA256/<表中摘要>`，避免取索引期间发布更新造成混配。本轮按完整字节校验压缩和解压内容，均与各自 InRelease 的 SHA256/Size 一致；解压时每份只读取最多 64 MiB + 1 byte，超过即拒绝，未写出额外 Packages 副本。

三份解压 Packages 分别为 56162922、15274、1855167 bytes，共 **58033363 bytes（约 55.345 MiB）**；压缩合计 **9886052 bytes**。它们是各选定组件/架构的完整索引，不是手摘的依赖子集。新/旧签名元数据、公钥和两个依据原文共 **10254588 bytes**，不含 manifest、API 查询记录和失败残片；这不是介质构建或准备期总峰值。

| 来源 | 索引声明的 Date（UTC） | 索引声明的 Valid-Until（UTC）及处理 |
| --- | --- | --- |
| trixie | 2026-09-12 07:55:41 | 未提供；记录缺失，不伪造为永久有效 |
| trixie-updates | 2026-10-13 08:11:41 | 2026-10-20 08:11:41 |
| trixie-security | 2026-10-13 07:32:57 | 2026-10-20 07:32:57 |
| 原 Docker | 2026-10-02 16:24:32 | 未提供；不自动刷新原固定候选 |

日期字段本身也要等签名通过才可采信。本集合最早的声明失效时刻为 **2026-10-20 15:32:57（Asia/Shanghai）**；执行时间达到或超过此时即拒绝使用该集合，重新收集并评审，不能关闭 Valid-Until、修改时钟或回填过往验签时间。实际可用期还可能被密钥有效期、撤销或时间异常进一步缩短；没有自动定时任务。

### 公钥材料与独立依据

| 公钥文件 / 来源 | bytes / SHA-256 | 官方预期主指纹（尚未从文件实测） |
| --- | --- | --- |
| `docker.asc`；[Docker key](https://download.docker.com/linux/debian/gpg) | 3817 / `1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570` | `9DC858229FC7DD38854AE2D88D81803C0EBFCD88` |
| `debian-archive-13.asc`；[trixie archive key](https://ftp-master.debian.org/keys/archive-key-13.asc) | 11861 / `6f1d277429dd7ffedcc6f8688a7ad9a458859b1139ffa026d1eeaadcbffb0da7` | `04B54C3CDCA79751B16BC6B5225629DF75B188BD` |
| `debian-security-13.asc`；[trixie security key](https://ftp-master.debian.org/keys/archive-key-13-security.asc) | 11873 / `844c07d242db37f283afab9d5531270a0550841e90f9f1a9c3bd599722b808b7` | `5E04A1E3223A19A20706E20F9904613D4CCE68C6` |

Docker 的预期指纹取自 Docker 官方文档仓库[固定提交原文](https://github.com/docker/docs/blob/393d3f6566e20b416ec642c95e1d13a61a46b29e/engine/install/debian.md)，与 download.docker.com 的 key 文件分开取得。原文保存为 `docker-debian-doc-393d3f6.md`，SHA-256 `90749a2ce9f6409ddff7678d00830d68bce9581e710a87ad70553fbe1915f60a`。这是历史官方身份依据，不证明 2026 年密钥未撤销；不执行其 apt-key/install 指令，不接受其中“只看末 8 位”的核对方式。

Debian 指纹取自[官方归档签名说明](https://ftp-master.debian.org/keys.html)，与待验 deb.debian.org/security.debian.org 索引分别取得；依据页保存为 `debian-keys.html`，SHA-256 `b271f4c351a3b54f6a6be9667bb834809d12ee514055b903ccb06839d274e3e0`。这是官方 HTTPS 信任依据，不声称线下交叉签署或不同管理方独立证明。三份 key 未导入系统 keyring，也未提交进仓库。

本轮复查旧包表另确认 `gpg=2.4.7-21+deb13u1+b4`、`gnupg=2.4.7-21+deb13u1`、`python3-apt=3.0.0` 已安装；这是包记录，不是 `/usr/bin/gpg` 路径及运行行为的实测。下一包须先核对 gpg/sqv/apt-get/apt-config 的路径归属、版本和实际能力，失败不安装。

验签方案在初稿 Draft 上收敛为：**GPG 仅检查 key 文件元数据，sqv 1.3.0 负责验证 cleartext InRelease，APT 再沿同一签名和索引链生成本地列表**。选择 sqv 是为了明确使用其证书/子钥绑定、撤销/过期与密码策略检查；不把 gpgv 失败后的切换当作容错，也不自动放宽策略。[sqv 手册](https://manpages.debian.org/trixie/sqv/sqv.1.en.html)说明相应验证语义；原有运行 gate 与密码候选库均不改。

拟绑定的参数形状如下，仍不是可执行合同；`IN` 为待固定的只读介质根，`WORK` 为待证明硬限额的暂存根：

```text
/usr/bin/gpg --no-options --batch --no-autostart --disable-dirmngr
  --homedir WORK/gnupg --with-colons --with-fingerprint
  --with-subkey-fingerprint --show-keys IN/keys/<source>.asc
/usr/bin/sqv --keyring IN/keys/<source>.asc --signatures 1
  --cleartext --output WORK/verified/<source>.Release
  IN/<source>/dists/<suite>/InRelease
```

按每个文件核对恰好一个预期主证书，记录所有 subkey 及完整指纹；新增主钥、未知格式或仅短 ID 相等均拒绝。签名必须来自该源对应主证书或其有效绑定子钥；不能将 Docker key 用于 Debian。sqv 非零时不得消费可能已产生的输出；零退出也必须核对产物存在、大小、源角色、日期与状态。默认要求一个批准证书签名有效，不因 Debian 同时有其他签名而自动导入新证书；不得将未知签名者自己提供的 key 加入信任集。

GPG 采用独立空 homedir、空环境及无自动 agent/dirmngr 参数，不读用户配置或私钥；[GPG 文档](https://manpages.debian.org/trixie/gpg/gpg.1.en.html)是参数依据。sqv 的密码策略须固定为目标现有默认策略，核对其配置存在性/hash，拒绝继承 `SEQUOIA_CRYPTO_POLICY` 或回拨 `--policy-as-of`；策略不满足时停止，不换验证器或降低算法要求。离线 key 只能反映获取时携带的撤销信息，最终执行前必须核对官方轮换/撤销公告和本次输入的时效，不声称能发现尚未取得的撤销。

### Debian 版本候选与准备空间再核算

以下条目均来自固定 trixie 主索引；updates/security 没有相同包名条目。仅摘录索引，不调用或自写依赖求解器。

| 静态新增候选 | Version / Architecture | 归档 bytes / Installed-Size KiB | 归档 SHA-256（尚未下载归档） |
| --- | --- | --- | --- |
| git | `1:2.47.3-0+deb13u1` / arm64 | 8665568 / 49556 | `8c6b1e96b226211260d7814472215a8a1ed38ee37400c421d454391c1807cb5a` |
| iptables | `1.8.11-2` / arm64 | 353592 / 8438 | `441a3c4b202f83cb1c2609c9eff768229ce991c2f49bea37416168028bc23e95` |
| git-man | `1:2.47.3-0+deb13u1` / all | 2204692 / 2251 | `b58306b60e1dff920e1e18bc7e1e499f2ef75184190ab3d98657b165969bf7c9` |
| libip4tc2 | `1.8.11-2` / arm64 | 19552 / 98 | `e2d86b0b1b5d06b529cf60f3876970b02c1ae1147555bfcf1c5b17bfdae992ca` |
| libip6tc2 | `1.8.11-2` / arm64 | 19800 / 98 | `3ab7581ae06d0b7109ec60907a063ef167446e492f30918dcb20faed810d172d` |
| liberror-perl | `0.17030-1` / all | 26872 / 71 | `06110a972bdc52f6c6d6615dddbe97f836c61d0e36c685ef4107c2eaa81f871f` |

上述六包合计归档 11290076 bytes、声明安装 60512 KiB。连同原四个 Docker deb，静态候选为 **10 个 deb，归档 82342052 bytes、声明安装 358391 KiB**；加 Go 归档为 **146153457 bytes**。这不是 APT 闭包、安装占用、最低所需磁盘或 768 MiB 可行性结论。

iptables 新揭示的 `netbase=6.5`、`libnetfilter-conntrack3=1.1.0-1`、`libnfnetlink0=1.0.2-3` 已在旧基线；Git 的 `git-man` 双版本约束、`perl:any` 及其他依赖仍必须由原生 APT 处理。当前只核对存在/条目，没有用字符串或自建版本比较证明满足。

只读介质只需含约 10 MiB 元数据，不导入 146 MB 软件归档。128 MiB 暂存候选中，一份展开 Debian Packages 约 55.345 MiB，两份共 116066726 bytes，尚未计入 Docker 列表、原 status、认证 Release、APT 内存/磁盘 cache 与元数据。因此实施必须避免多份展开副本、关闭磁盘 pkgcache/srcpkgcache，并先核算列表实际编码与峰值；不能由压缩索引小于 256 MiB 推断暂存必然够用。128 MiB 仍只是待证明候选，未调整运行五域额度。

### 离线实施清单与精准验证方案

以下为 `0b589cc` 提交时的实施方案；随后获准的离线实现与实际覆盖范围见[离线实施与回归](#离线实施与回归2026-10-13)。仅扩展已有准备采集职责，不新增 I5 运行入口：

| 文件/职责 | 拟实施内容 | 必须覆盖的离线验证 |
| --- | --- | --- |
| `scripts/inspect-sw-i5-guest.py` | 新独立 preparation-apt scope/schema，绑定输入 manifest/nonce/UUID；校验程序归属、原包库与架构；调用固定工具，结果始终 `i5_ready=false` | 旧 inventory/details 逐字兼容、错 scope/nonce/hash 拒绝、基线变化拒绝 |
| 候选内部模块 `scripts/sw_i5_apt.py` | 隔离 manifest/Release/配置/结果校验与分阶段执行职责，避免继续堆入采集器；无独立 CLI、不实现 OpenPGP 或 Debian resolver | 重复字段、路径穿越/symlink、压缩炸弹、错指纹/过期/验签失败、未知源拒绝 |
| `scripts/sw_i5_utm_result.js` | 为新 scope 固定时限与严格返回合同；原 case 的 55 秒/原限额不变；一次 execute、同句柄回收 | 超时不重发、丢结果不默认成功、未知 process 状态拒绝 |
| `scripts/sw_i5_utm_control.py` | 新合同绑定介质前后状态、运行源、阶段截止；总期限大于 guest 清理期限；失败保留并回收 | 基线失败不启动、超时/异常回收、旧 nonce 拒绝、恢复失败不可 PASS |
| 现有 guest/control 测试及拟新增 `test_sw_i5_apt.py` | 注入工具输出和合成子进程，仅测控制/拒绝与资源边界 | 不能把模拟 GOODSIG 或假 APT 输出当作真实验签/依赖结果 |

新模块只在已有准备入口内调用；若新增模块必要性或接口在实施时变化，应在该实施包中说明，不先改现有受合同摘要绑定的文件。可参考 `sw_i5_build.py` 的独占进程组回收，但它的 build 身份/挂载假设不能直接作为通用 APT 隔离证明；本轮不重构它。

APT 方案固定四个本地仓库树：`IN/debian/dists/trixie`、`IN/debian/dists/trixie-updates`、`IN/security/dists/trixie-security`、`IN/docker/dists/trixie`，每树保留原签名文件和原索引字节，组件分别为 main/main/main/stable。介质构建仅重排文件位置，不编辑 Release、不手工签新仓库、不合并或裁剪 Packages；public key 置于只读 `IN/keys`。介质本身的实现/挂载仍待绑定，不启用共享目录。

本地树同时提供固定索引常规路径与 `by-hash/SHA256/<digest>` 路径，二者须逐字一致；若介质实现无法共享同一数据块，就把双份占用计入制作/介质峰值，不能忽略。只导入完整 Packages，关闭 PDiffs，避免本地索引构建意外请求未打包的 `.diff`；不关闭签名、摘要或日期核验。

专用配置由 `APT_CONFIG` 首先载入，空环境至少固定 `PATH=/usr/bin:/bin`、`LC_ALL=C`、WORK 内的 HOME/TMPDIR；不继承代理或用户 APT/GPG 变量。拟固定设置如下，之后用 `apt-config dump` 验收实际展开值：

| 配置范围 | 精确设计要求 |
| --- | --- |
| `Dir::Etc::main` / `parts` | `/dev/null` / WORK 内专属空目录；在 APT_CONFIG 中设置，防止系统配置先执行 |
| `sourcelist` / `sourceparts` | WORK 内生成且核对的 sources / 专属空目录；只接受四个 `file:` 源、`Signed-By` 对应只读 key；拒绝 trusted=yes |
| `preferences` / `preferencesparts` | WORK 内固定版本 pin 文件 / 空目录；不读系统 pin |
| `trusted` / `trustedparts` / `netrc` / `netrcparts` | 空的专属信任位置或 `/dev/null`，不加载全局 key 或凭据；信任只经每源 Signed-By |
| `Dir::State`、`lists`、`status`、`extended_states` | 全在 WORK，status/extended_states 为目标原库的受限副本；缺文件须显式处理，不能生成全空 status |
| `Dir::Cache` / `archives` / `Dir::Log` | 全在 WORK；`pkgcache`、`srcpkgcache` 设空字符串，禁用这两种磁盘 cache；不声称消除了内存峰值 |
| 架构/推荐/日期 | `APT::Architecture=arm64`；只批准 native arm64，发现 foreign architecture 停止重评；Recommends/Suggests=false，Check-Date/Check-Valid-Until=true |
| 附加索引与 hooks | Languages=none，不请求 Contents/Translations/源码；禁用并核查所有 APT/DPkg hooks、未知 Binary 子树和额外索引目标 |

对每个原已安装包，生成精确版本优先级 1001 的条目，后接同包其他版本优先级 -1；四个 Docker 请求版本和上述 Git/iptables 版本同样固定。条目顺序及架构 all/arm64 的匹配须按 [APT pin 语义](https://manpages.debian.org/trixie/apt/apt_preferences.5.en.html)测证；生成过程只从原生包记录转录，不解析依赖。模拟后再核对零升级/降级/删除/重装，不能仅凭 pin 或 `--no-remove` 判定。

先仅在专属状态目录内执行本地 `apt-get --error-on=any update` 建立索引，使临时索引错误也失败，参数见 [apt-get 手册](https://manpages.debian.org/trixie/apt/apt-get.8.en.html)；网络不可达不替代源白名单。之后以初稿所列 `-s --no-download --no-install-recommends --no-remove` 模拟六个精确请求，保存真实退出码和完整结果，再核对原库 hash 不变。APT 缺包或包冲突即保留原错停止；不补 deb、不安装、不联网补源。

每个 guest 工具使用独占进程组、空 stdin、关闭继承 FD；对 stdout/stderr 以流式读写前预算限制，deadline 使用单调时钟。达到时间/字节上限后终止该次进程组、wait 并验证后代回收；RLIMIT_FSIZE 只能补充单文件上限，不能冒充总空间硬限制。父包装器须有独立 guest 截止，即使 JXA 返回丢失也能触发回收；宿主外层超时不证明 guest 已死。空间/内存、取消通道及准备期全局写入边界未实现前，不提交可执行授权包。

### 续接验证、失败与剩余条件

- 已核对本地 13 个完整输入的摘要、三份索引压缩/展开字节与 Release 记录、包架构计数、六条 Debian 候选记录和既有包版本；没有进行密码学验证或 APT 求解。
- 首次沙盒 curl 退出 7（现有本机代理不可达），获准后同 URL 成功；主索引首次 60 秒下载退出 28，仅取得 9205294/9614192 bytes，保留为 `debian-trixie.Packages.xz.timeout`，排除于输入 manifest。对同一 by-hash URL 以 180 秒上限重新完整下载成功，不覆盖原失败。其余输入使用每份 60 秒上限。
- 网页工具无法直接读取 PGP MIME、部分原始文档与 Debian 公告（403），未将它们当作 key/文档不存在；原始公钥与 Docker 固定提交原文通过受限 curl 保存。搜索中的第三方转载和用户 Issue 没有用作信任根。
- 剩余执行前缺口：公钥工具核对与验签、原生 APT 差量、原 status/架构绑定、离线采集/取消实施、介质/暂存/系统写入硬边界与精确回收。不能靠输入齐备跳过这些条件，也未改变 768 MiB 或 I5-R STOP。
- 续接文档的 `./scripts/check-repo.sh` 通过（193 文件），`git diff --check` 通过；13 份输入及 manifest 摘要/字节总数再次核对通过。仅提交了续接前的 `e16ee48`；本节及当前状态/准备入口更新保留为未提交改动。未 push、未新增后台进程，未下载软件归档、导入系统 key、安装依赖或启动 VM/I5-R。

## 离线实施与回归（2026-10-13）

上述三份文档已按所有者要求提交为 `0b589cc`，未 push。随后获准实施验签/APT 准备入口、有界输出和取消回收及离线测试；该授权明确排除启动 VM、安装依赖和 I5-R。以下八文件实现随后提交为 `7fdecbf`，不改变历史合同、候选包版本或 768 MiB 运行预算。

### 实现范围与入口

- [内部准备模块](../../scripts/sw_i5_apt.py)承载独立 v1 输入/结果合同、介质文件白名单、原包库/工具基线、完整指纹列表检查、固定 GPG/sqv 调用、认证 Release 日期和 SHA256 检查、有界解压摘要、独立 APT 配置/pin 生成及原生模拟结果的只新增检查；不实现 OpenPGP 或 Debian 依赖求解。Docker 按 `Suite`、Debian 按 `Codename` 绑定源身份。只有 sqv 退出成功且回收无错，才读取它的认证输出；非零退出留下的文件不会被消费。
- [现有采集器](../../scripts/inspect-sw-i5-guest.py)新增宿主离线 `--validate-preparation-input` 和 `--validate-preparation-apt`，从 stdin 读取合同，绑定 `--nonce`，结果校验还要求 `--manifest-sha256`。它们不读取 guest、不调用工具、不生成授权包。`--preparation-apt`、`--collect-utm preparation-apt` 和[生命周期入口](../../scripts/sw_i5_utm_control.py)的 `--scope preparation-apt` 均在任何 UTM/guest 操作之前返回 exit 2、`I5_PREPARATION_ISOLATION_REQUIRED`。
- 输入 `scope=i5-preparation-apt-input`、结果 `scope=guest-preparation-apt`、操作 `scope=i5-preparation-apt-operation` 均为 `schema_version=1`，不扩张旧 inventory/details。旧结果限额、55 秒适配层截止及旧生命周期行为保持不变。旧 review-only manifest 不兼容新执行输入，不会自动补成授权或真实基线。
- 新输入固定 `nonce`/UUID、11 个原始源/公钥文件的 bytes/SHA256，以及原生 `status`、可缺失的 `extended_states`/默认 crypto policy、arm64/空 foreign architectures、六个工具的包归属/版本/二进制摘要。介质另外必须有四个逐字相同的 by-hash 索引；拒绝未知文件、重复 JSON 字段、非规范路径、symlink、摘要变化与压缩尾随/截断。日期只从认证 Release 读取；不回拨策略时间或关闭有效期。
- 阶段执行函数要求显式注入 runner 和合成基线路径，本版本仅供离线编排验证，产出 `evidence_kind=synthetic`；`signature_verified`、`apt_resolved`、`install_authorized`、`i5_ready` 均保持 false。`passed=true` 仅表示全部合成阶段及后置校验通过，结果校验器拒绝把它升级为真实证明。真实生命周期尚未接通，不存在通过一个 JSON 布尔值启用执行的开关。
- 新操作合同的纯校验函数绑定全部七个源文件、base revision、manifest、UTM 配置/二进制及只读介质路径/bytes/SHA256，并与独立观测值逐项比较。当前没有真实介质观测/挂载或新生命周期执行适配器；测试中的前后观测变化拒绝不能替代实际挂载、恢复或 VM 回收证明。

### 输出、时间与取消

[内部执行器](../../scripts/sw_i5_apt.py)使用空 stdin、关闭继承 FD、全新进程组、非阻塞双流读取和单调时钟。每步 stdout 最多 2 MiB、stderr 最多 64 KiB，读取最多剩余额度加 1 byte，超限标记失败且保留量不越界；工具流累计最多 7 MiB，另留结果 framing 空间。stderr 对 APT/dpkg 操作严格拒绝，GPG/sqv 的诊断单独留存，退出码仍必须为 0。

超时、取消回调、SIGINT/SIGTERM、流超限及启动失败都保留首个原因；回收针对该次 PID 对应的独占进程组，SIGKILL、wait 后再验证组消失。leader 已退出但后代仍在也失败；无法查询、wait 超时、仍可见的僵尸/后代都是 `cleanup_errors`，不能 PASS。保存退出码及有界原始流，不把非零退出解释为成功。

新 scope 的 guest 本地总截止固定 540 秒，适配层 600 秒，宿主候选阶段 620 秒；启动 60 + readiness 候选 60 + 宿主阶段 620 + 关机 120 共 860 秒，留在 900 秒包预算内。工具单步最多 30 秒，APT 建索引/模拟各最多 150 秒，且都受剩余 guest 总时间约束。超时不重发 execute，只轮询同一个 process handle；适配层不把宿主取消/丢结果视为 guest 已结束。新 guest 流/transport 限额分别为 2/6 MiB。

这只实现本地截止检查、子进程计时及普通信号取消。输入读取/文件系统阻塞、包装器被 SIGKILL、后代 `setsid` 逃逸、guest/宿主失联、存储/内存总量和挂载全局写入范围，仍需要独立 supervisor/cgroup/只读挂载及精确设备回收证明；进程组和 `RLIMIT_FSIZE` 都不是其替代品。新 scope 继续 STOP，因此不存在用这些离线测试放行真实包的路径。

### 本轮验证与未覆盖项

- `python3 -B scripts/test_sw_i5_apt.py`：20 个测试方法通过，包含四源完整合成编排、阶段失败矩阵、签名失败后不消费认证文件、不调用 APT、基线前后变化、旧 nonce/源摘要/介质变化、错指纹与额外证书、配置 hooks/额外索引、原包变更/删除/缺根包拒绝，以及输入路径/压缩/日期拒绝。
- 同一测试集实际启动短寿命合成 Python 子进程，验证双流恰好限额、持续输出溢出、非零退出、超时、回调取消、SIGTERM 包装器回收、关闭管道后残留后代及回收错误。没有执行 GPG、sqv、APT、网络、VM 或真实设备操作。
- 原 `test_sw_i5_guest.py` 45 项、`test_sw_i5_utm_control.py` 4 个测试方法通过；纯 Node vm context 执行适配层自测 29 项通过，无 Application/ObjC/UTM 调用。新适配层测试覆盖独立截止、错绑定、超限、未知返回状态和丢结果只执行一次。
- `./scripts/check-repo.sh` 通过（195 文件），`git diff --check` 通过；该轮测试无失败。当时 `dev` 相对本地 `origin/dev` 为 ahead 2，新增实现和配套记录共 8 个文件未提交；随后按所有者要求提交为 `7fdecbf`。没有 push 或其他远程写入，没有遗留该轮后台进程。
- 真实密钥/策略核对与密码学验签、APT 3.0.3 实际配置展开/arm64 与 all pin 行为/求解输出、完整原始包库与工具二进制基线、介质制作及挂载、硬容量/内存与全局写入隔离、外部取消和真实回收均未执行或未闭合。已有 metadata review 输入保持原样，没有制造可执行 manifest 或再次使用历史授权。
- 当前改动会使依赖这些脚本摘要的旧操作合同不再匹配当前源码；历史记录和旧操作目录不改写。未来真实包必须重新绑定全部源与输入、证明上述硬边界，并取得当次授权。I5 shell preflight/run 和 Go synthetic-run 停止代码未修改。

## 准备期隔离与独立监督离线续接（2026-10-13）

所有者要求先提交前轮八文件，再继续准备期硬隔离、独立监督与失联回收的离线实现；仍禁止启动 VM、安装依赖和运行 I5-R。`7fdecbf` 已提交且未 push；本节所述续接实现随后按所有者要求提交为 `63f98d4`，亦未 push。这里记录内部准备机制及离线证据，不声明目标 VM 已具备这些条件。

### 硬边界实现

[准备隔离模块](../../scripts/sw_i5_preparation_isolation.py)沿用已有 mountinfo 解析，新增独立 `i5-preparation-isolation` v1 合同，绑定 nonce、UUID、输入 manifest 摘要、固定准备路径及无特权 uid/gid。Linux 内核后端与观测代码均已实现，但本轮没有调用真实 syscall、修改 cgroup 或配置系统。

| 边界 | 实现及拒绝条件 |
| --- | --- |
| 存储 | 只读 iso9660/squashfs 输入 ≤256 MiB；WORK 为 128 MiB/32768 inode、RESULT 为 8 MiB/4096 inode 的独立 `noswap` tmpfs。核对实际 fstatvfs 总容量、设备、根 inode、挂载选项与 superblock；拒绝嵌套、别名、叠挂和 shared/slave propagation |
| 域外写入 | 在准备子进程内创建私有 mount/network/IPC namespace，以递归 `mount_setattr` 将现有挂载只读，再建立两个固定 tmpfs；其他任何可写挂载均拒绝。需要事先准备好、root 所有且无 symlink 的精确空挂载点，不自动创建系统目录 |
| 权限与 IPC | 清空 supplementary groups、capability bounding/ambient/effective/permitted/inheritable，固定 real/effective/saved/filesystem uid/gid，设置 `no_new_privs`。seccomp 检查 ABI，拒绝 socket/Unix socket 建立、ptrace/process_vm、额外 namespace、clone3、io_uring 等路径；允许普通 fork/线程，拒绝 clone namespace flags。没有失败后的降级策略 |
| 进程与输出 | 启动时只保留 stdio 和受控 admission 管道，工作代码拿不到租约写端或 cgroup FD。stdin 指向 `/dev/null`，wrapper stdout/stderr 写到 RESULT 的独占文件，不能无限写入 guest-agent capture；文件限额只是补充，目录总量由 tmpfs 限制 |
| cgroup v2 | 独占父域 512 MiB/48 tasks，worker 子域 384 MiB/32 tasks，supervisor 子域 64 MiB/8 tasks；三者 `memory.swap.max=0`。CPU 配额分别为每 100000 μs 最多 200000/100000/25000 μs；这是准备期候选限额，不改 I5 运行额度。父域无进程，两个子域分离且禁止再 delegation；拒绝其他子域、计数器异常和任何 max/OOM/pids 拒绝事件 |
| 绑定与回收 | cgroup2 类型、目录 owner/mode、设备/inode 和 nonce 路径均核对；读写经固定目录 FD，替换/短写直接失败。回收使用绑定域的 `cgroup.kill`，不枚举进程名，不用 leader 退出或空 `cgroup.procs` 冒充完整回收；population 与 subreaper 回收分别验证 |

依据为 [cgroup v2 内核接口](https://docs.kernel.org/admin-guide/cgroup-v2.html)、[tmpfs](https://docs.kernel.org/filesystems/tmpfs.html)、[mount_setattr](https://man7.org/linux/man-pages/man2/mount_setattr.2.html) 和 [seccomp 过滤接口](https://docs.kernel.org/userspace-api/seccomp_filter.html)。syscall 数值按 Linux v6.12 的 [x86-64 表](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/syscalls/syscall_64.tbl)和 [asm-generic 表](https://github.com/torvalds/linux/blob/v6.12/include/uapi/asm-generic/unistd.h)绑定；未引入第三方实现或依赖。seccomp 不是完整 sandbox，不能脱离挂载、身份、FD 与 cgroup 边界单独放行。

### 独立监督与失联回收

[独立监督模块](../../scripts/sw_i5_preparation_supervisor.py)将 supervisor fork 为独立 session，纳入单独 cgroup，Linux 上启用 subreaper。worker 先阻塞在启动管道：确认 cgroup admission 后才允许隔离设置；隔离设置返回且有效状态核对通过后，才通过第二次屏障执行工具。设置阶段卡住也受监督，失败不能运行工具。内核观测从受控 child 的 procfs 读取真实 uid/capabilities/namespace/FD/cgroup，检查该 uid 没有域外进程；不接受输入 JSON 自称隔离成功。

租约帧固定 v1、UUID、nonce、manifest SHA256、严格递增 sequence 和 renew/cancel；单帧最多 512 bytes。guest 与 host 使用不同 scope，不能串用；重复字段、重放、跳号、错绑定、拼接帧、超限及半帧停滞都失败。只有独立控制端可以续约，工作进程不能自续；租约最长静默 15 秒，持续续约也不能延长 540 秒 guest / 620 秒 host 绝对截止。guest 回收另限 20 秒，仍低于 600 秒适配层截止。超时、管道 EOF、SIGINT/SIGTERM、wrapper 被杀及结果消费者失联都不会触发重新执行。

宿主 watchdog 单独轮询租约和结果管道，流式接受最多 6 MiB；不等待阻塞的采集调用返回才判断失联。缺失、超限、错误结果或取消进入[宿主回收函数](../../scripts/sw_i5_utm_control.py)：仅当本包记录启动前 stopped、已尝试 start，且 nonce/UUID/config/media 身份仍一致时，才允许对固定 VM 发一次正常关机，必要时至多一次 force。所有观测/命令带子期限，整体回收不超过 120 秒；身份变化或未知状态拒绝扩大操作。即使最终确认 stopped，原失联失败仍保留，`passed` 永远不会因回收成功变为 true。

准备操作合同新增 v2，额外绑定隔离合同摘要、15/20 秒时限及全部十个相关源文件；v1 原字段和原七文件集合保持独立，不能混入新字段。公开 `--preparation-apt`、`--collect-utm preparation-apt` 和生命周期新 scope 仍在第一次外部调用之前 STOP；v2 是离线校验合同，不是授权开关。

### 验证与仍关闭的门

- `python3 -B scripts/test_sw_i5_preparation.py`：20 个测试方法通过，包含挂载/容量/权限/cgroup 拒绝矩阵、真实观测代码的合成 procfs 输入、BPF 分支解释、每一隔离设置步骤失败、双屏障、短写/身份替换、租约重放/失效与 guest/host scope 隔离、残留后代及回收错误、宿主正常/强制/失败回收。
- 其中使用真实短寿命 Python fork/pipe/session 测试独立监督：worker 睡眠阻塞、worker 被 SIGKILL、隔离设置异常、控制管道关闭、结果消费者消失均回收已知合成 child；内核 cgroup、namespace、seccomp、subreaper 和 UTM 动作注入替身，不将 macOS 合成 PID 回收等同于 Linux `cgroup.kill` 或逃逸后代实测。
- 原准备 20 项、guest 45 项、control 4 个方法、资源/build helper 20 项、纯 JavaScript 29 项回归通过。资源套件首次误用 `--self-test` 参数，退出 2 并报告缺少 action；改用该入口已有的 `self-test` 子命令后通过，未修改脚本掩盖错误。其余本轮测试无失败。
- `./scripts/check-repo.sh` 通过（198 文件），`git diff --check` 通过；该轮检查时续接改动共 7 个文件未提交，`dev` 相对本地 `origin/dev` 为 ahead 3；随后提交为 `63f98d4`。没有 push，没有遗留本轮后台进程；I5 shell 和 Go synthetic-run 停止代码未修改。
- 截至该轮仍须完成（后续离线接线见下节）：精确 cgroup/挂载点/独占身份的受授权初始化、guest-agent 到租约通道的真实接线、worker RESULT 在 namespace 销毁前的有界导出与失败证据持久化、宿主独立 watchdog 的实际启动/收尾接线，以及 Linux quota/OOM/域外写入/setsid 后代/监督器自身被强杀或 guest 停摆的真实拒绝与回收测试。supervisor 被 SIGKILL 或 guest 冻结时依靠独立宿主路径；没有声称进程内 finally 能处理这些情况。
- 上述实现只覆盖准备 worker/supervisor 候选边界；guest 启动日志、系统盘、全局 swap、宿主 backing 和 UTM 日志的完整物理硬额度仍未证明。现有原生 APT、密码学验签、真实介质及 768 MiB I5 批次条件均未通过；没有执行 VM、安装、配置变更、I5-R 或远程写入。

## 租约通道与有界导出离线接线（2026-10-13）

所有者要求先提交前轮七文件，再推进租约通道、结果有界导出和宿主 watchdog 的离线接线与测试。前轮提交为 `63f98d4`，没有 push；本节的新实现随后按所有者要求提交为 `acb654d`，亦未 push。未启动 VM、安装依赖或运行 I5-R；没有修改任何公开入口的 STOP，也没有系统配置或远程写入。

### 接线与结果归属

新增[准备通道模块](../../scripts/sw_i5_preparation_channels.py)，连接已有准备编排和监督器。控制端持有唯一 host 租约写端；独立 watchdog 校验帧后转换 guest scope，guest supervisor 确认接收后才返回绑定 UUID/nonce/manifest/sequence 的 ACK。控制端收到 ACK 才发送下一帧，不能预存未来续约。取消、断流、重放、错 ACK、半帧停滞与绝对截止仍失败；worker、transport 和回收子进程都关闭无关 FD，不能自行续约。

watchdog、transport、guest supervisor、worker 和回收适配器为分离的短寿命进程，离线测试使用真实 fork/pipe/session。guest 继续按两个 admission 屏障执行：有效隔离核对后，监督器在放行 worker 之前打开 RESULT 目录 FD，并把设备/inode 与隔离观测绑定。worker 完整回收、population 为空且 reaping 通过后，才能读取证据；目录 FD 保持挂载引用，不依赖退出后的 `/proc/<pid>/root` 再打开路径。没有声称 macOS 临时目录测试证明了 Linux mount namespace 的实际生命周期。

准备编排新增显式 `evidence_root`，可将阶段 stdout/stderr 和 `result.json` 写入已准备的 RESULT；APT 工作目录使用 WORK 内的新子目录。原未传此参数的调用仍写入 WORK。证据文件使用排他创建，不覆盖旧证据或跟随 symlink；没有将 WORK 的 cache、原始包表或其他任意文件导出。

导出 v1 只接受固定文件清单，通过目录 FD 相对打开，拒绝 symlink、hardlink、FIFO、设备、跨设备与读前后变化；域外目录和尚存活的 worker 均不能导出。原始大小、保留大小、保留内容 SHA256、base64 与截断标志一起返回。限额为：

| 对象 | 固定上限及结果 |
| --- | --- |
| 单个阶段或 wrapper 输出 | 64 KiB；超限保留前缀并标记失败 |
| 准备 JSON 摘要 | 256 KiB；超限不接受为有效摘要 |
| 全部导出原始内容 | 1 MiB；超限明确记录截断，不能 PASS |
| 序列化 guest 导出 | 2 MiB，沿用既有 guest 结果上限 |
| 宿主采集流 / 最终报告 | 分别为 6 MiB / 3 MiB；最终报告包含有效导出、监督与回收结果 |

这些是传输限额，不提高已有 RESULT 8 MiB、WORK 128 MiB 或准备期内存限额。现有工具流最多 7 MiB，因此可能在工具成功后因导出额度不足判失败；没有丢弃内容后继续声称完整通过。缺失已完成阶段的诊断、损坏摘要、摘要与工件不一致及未知字段均不能 PASS。坏摘要的有界原始 bytes 仍可作为失败工件保留，不升级为有效 APT 结果。

宿主先验证导出及其绑定，再检查采集进程退出和回收状态。guest 在最后结果到达前关闭控制通道时，不再续约或发 ACK，仅在现有宿主截止内收完结果；只有有效完整导出与正常采集退出共同满足时才允许成功。消费者关闭、写入阻塞或结果超限均失败，不重启工作。失败结果保留原监督失败与回收结果，回收成功不能改成准备成功。

### 截止、回收与兼容

host/guest 租约仍为最长静默 15 秒，绝对截止分别 620/540 秒。guest 清理最多 20 秒，报告写入最多 2 秒；宿主采集进程收尾最多 25 秒，必要时针对该次新建 session 发 SIGKILL，另以 2 秒确认 reap。宿主最终写入最多 2 秒。回收适配器本身也放入独立进程，最多 120 秒、报告最多 64 KiB；卡住、非零退出、非法结果及遗留后代都失败，至多启动一次回收。真实 VM 回收仍必须使用既有精确身份 ticket 和独立观测，不能由此内部 API 推导启动或强制关机授权。

包括候选启动/readiness 各 60 秒、host 阶段 620 秒、恢复 120 秒及以上收尾，最坏候选时间为 891 秒，仍在 900 秒包预算内；实际环境尚未验证。内核阻塞、不可杀进程或回收身份无法确认时只能报告未闭合，不能强称回收完成。

内部 operation v3 绑定全部十二个源文件和固定导出额度；v1 原七文件、v2 原十文件及其字段继续各自严格校验，旧版本不能接受新字段。新的 guest export/ACK/host report 使用独立 v1 scope；I5 运行 evidence schema、profile、shell/Go 停止代码均未修改。新代码仍只产生 `evidence_kind=synthetic`，`i5_ready`、`install_authorized`、`signature_verified`、`apt_resolved` 不会被离线成功开启。

### 验证、失败记录与未覆盖项

- `python3 -B scripts/test_sw_i5_channels.py`：14 个测试方法通过，包含完整四源合成准备编排 → RESULT → 监督回收 → 有界导出 → 独立 watchdog 的真实管道链；另覆盖目录替换、文件类型/身份变化、缺失/损坏证据、单文件/累计额度、摘要篡改、租约断开/静默/取消/重放、错 ACK、采集或 worker 阻塞、监督设置失败、SIGTERM、结果超限/消费者消失、正常收尾竞态和回收适配器阻塞/错误。内核隔离、密码工具、APT、UTM 全部未实际执行。
- 新套件首次引用了不存在的 fixture 测试方法，退出 1；修正为已有 fixture 并避免导入测试类导致重复发现。随后真实管道暴露 host 确认早于 guest 接收而堆积续约帧的问题，退出 1；增加 guest 到控制端的逐帧 ACK 后完成相应用例。增加启动时间余量时，静默用例曾在到期前正常完成却仍预期失败，退出 1；改为明确阻塞 worker 后验证到期回收，没有放宽产品截止。
- 曾在新套件的 200 ms 窗口及并行回归的旧监督器 200 ms 窗口观察到启动调度超时，均保留为失败记录。真实 fork 测试给予调度余量，严格时间边界仍由既有假时钟负例覆盖；不把单次重跑成功解释为没有出现过不稳定性。
- 原监督隔离 20 个方法、guest 45 项、control 4 个方法、准备编排 20 项、资源/build helper 20 项和纯 JavaScript 29 项回归通过；JavaScript 使用纯 vm context，无 Application/ObjC/UTM 调用。
- `./scripts/check-repo.sh` 通过（200 文件），`git diff --check` 通过；六个相关 Python 文件经 AST 语法检查通过，未生成 bytecode。该轮检查时九文件未提交，`dev` 相对本地 `origin/dev` 为 ahead 4；随后提交为 `acb654d`，没有 push。
- 本次只闭合离线内部接线。真实 UTM guest-agent 如何承载两个独立方向的通道、启动/收尾适配、受硬额度约束的宿主证据持久化、Linux tmpfs/cgroup/namespace 实测，以及监督器或 watchdog 自身被 SIGKILL 后的外部恢复机制仍未验收。现有公开 UTM 执行入口未接入这些 API。
- guest 启动日志、系统盘、全局 swap、宿主 backing/UTM 日志的完整硬额度仍缺；没有真实验签、原生 APT 求解或 768 MiB I5 条件通过的证据。没有遗留本轮测试后台进程；临时合成目录随测试清理。

## UTM 传输与证据持久化离线续接（2026-10-13）

所有者要求先提交前轮九文件，再推进 UTM 传输适配和证据持久化的离线实现与测试。九文件已提交为 `acb654d`，未 push；本节十一文件实现随后按收尾要求提交为 `b0ca919`，亦未 push。以下是候选内部接线和本机合成证据，不是新的单次 UTM 操作包或真实运行授权。

### UTM 适配与控制文件

本轮只读核对已安装 UTM 的 `UTM.sdef`，没有查询 VM 或调用 Application/Apple event。该接口提供 `execute` 的一次性 stdin、同一 process handle 的 `get result`，以及 guest file 的 open/read/write/close；没有将一次性 stdin 当成运行期间可追加的管道。

[传输模块](../../scripts/sw_i5_preparation_transport.py)将现有 watchdog 的控制/ACK/结果管道映射到有界 RPC；[UTM 原生映射](../../scripts/sw_i5_utm_result.js)仅作为内部函数存在。控制路径固定为 `/run/radishlink-i5-preparation/<nonce>/control/lease.slot` 和 `ack.slot`，各 1024 bytes；文件必须提前准备且保持 owner、0600、单链接、设备/inode 和长度绑定，不由 transport 创建。宿主以 `reading + updating` 打开已有 lease 文件，ACK 只读；读写均明确 offset 0、固定长度和 `closing=false`，最终关闭已取得的两个 handle，不使用 append、truncate、整文件 pull/push 或默认读至 EOF。

控制槽 v1 用固定头、长度、标准 SHA256 和零填充封装已有 ≤512 bytes 的租约/ACK。摘要只检测撕裂写入，不是密码身份认证。撕裂/未完成更新不会续约，也不会重置静默或绝对截止；重复看到同一槽不产生新租约。有效内容仍由原 Lease 严格检查 UUID、nonce、manifest、scope 和 sequence。supervisor 直接轮询固定 FD，并写 ACK，不增加可自行续约的 worker FD 或额外 bridge 进程；worker 继续关闭这些 FD。

RPC v1 绑定 UUID、nonce、manifest、递增调用 sequence 和 action；guest program 原始 bytes 与摘要由宿主验证。每个调用只允许 identify/open/read/write/execute/result/close，原生映射的 Apple event timeout 为 2 秒，调用者还须施加整个 RPC 的外部进程截止。准备 guest 只 execute 一次，之后仅轮询同一个 PID/handle；执行结果丢失、错误字段、错 ACK、readback 不符、stderr/退出码/信号不符、超限或 close 失败均保留上下文并失败，不重新 execute。一次 open/execute 已生效但返回丢失时，未知 handle 不猜测，不通过重新操作制造成功，交给既有租约和精确 VM 回收路径。

结果到达后仍验证完整导出，`exit_code=0/2` 必须与通过/失败一致。transport 异常可通过独立失败 envelope 到达 watchdog，原失败文字和后续回收结果一起进入宿主报告。RPC 总截止候选 600 秒，close 总预算另限 4 秒，仍受外层 host 620 秒阶段及其独立回收约束。

### 持久化与重开

[证据模块](../../scripts/sw_i5_preparation_evidence.py)要求调用者提供明确、规范化且私有的宿主目录；没有默认写入位置或扫描发现。启动候选工作前先排他创建 nonce 子目录并写 `attempt.json`，已存在的失败、中断或完成目录都不覆盖、不续跑。单次逻辑写入总量 ≤4 MiB，原始 `host-report.bin` ≤3 MiB，attempt/receipt 各 ≤8 KiB；这不是宿主物理 quota 已生效的证据。

固定文件按排他创建 `.partial`、有界写入、文件 fsync、非覆盖 hardlink 发布、目录 fsync、移除临时链接及再次目录 fsync 的顺序保存；hardlink 发布不复制第二份 payload。`receipt.json` 最后写入，绑定 nonce/manifest、原始报告 bytes/SHA256、宿主退出码、`accepted`、`passed` 与错误。write/fsync/link 的异常直接返回失败，部分文件保留在已消费目录，不静默回滚或重试。

落盘可在独立子进程执行，最多 6 秒；fsync 或写入卡住时由调用者终止该次子进程，另限 2 秒确认 reap。失败/超时始终报告结果未确认，保留已消费目录，不以可见的部分文件推断成功；生命周期调用方须据此保持失败并回收，真实总包时间仍须在接入时复核。

`accepted=true` 只表示有效宿主报告已保存并与退出码一致；报告本身失败时仍是 `passed=false`。坏 JSON、进程/报告退出码矛盾等保留原始有界 bytes，回执为拒绝；不伪造准备结果。重开独立验证目录和文件身份、权限、单链接、固定文件集合、大小/摘要、schema、停止标志及宿主/guest 结果一致性，缺回执、额外/部分文件或篡改均拒绝。读回通过只证明当次可读状态；本轮没有实际断电、存储故障或物理介质持久性验收，I/O 报错后的发布结果仍需按失败/结果未确认处理。

### 版本、验证与停止线

内部 operation v4 绑定全部十六个源文件、guest program SHA256、1024-byte slot 及 4 MiB evidence 逻辑额度；v1/v2/v3 的字段和源文件集合保持独立严格验证。未修改既有运行 evidence schema、I5 shell/Go 停止代码或历史已消费操作包。新的 RPC、控制槽、attempt/receipt 均独立版本化；内部成功仍为 synthetic，不能开启 `i5_ready`、验签、APT 求解或安装授权。

- `python3 -B scripts/test_sw_i5_transport.py`：15 个测试方法通过。覆盖 UTM RPC 正负例、同一进程句柄且最多一次 execute、全部已知 handle 关闭、槽撕裂/重复/权限/替换/短写、真实 mailbox → 独立 guest supervisor、watchdog → RPC 替身 → 报告持久化、错误传播、重开、磁盘写满/同步失败及真实子进程中卡住的 fsync、短写/零写、报告篡改/退出码不符、hardlink 与中断拒绝。
- `node scripts/test_sw_i5_utm_rpc.js`：21 个纯 JavaScript 用例通过，直接检查原生映射的路径、模式、offset、length、base64、超时、handle 和执行参数；Application/ObjC 未调用。既有适配层 29 项纯 JavaScript 自测通过。
- 既有通道 14、监督隔离 20、准备编排 20、guest 45、control 4 个方法与资源/build helper 20 项回归通过。一次新增测试编辑把 hardlink 测试的尾部误放入相邻方法，`test_sw_i5_transport.py` 退出 1，报告 `NameError: store is not defined`；移回对应方法后通过，未删除断言或改变实现来掩盖失败。
- `./scripts/check-repo.sh` 通过（204 文件），`git diff --check` 和六个相关 Python 文件的 AST 语法检查通过；该轮检查时十一文件未提交，`dev` 相对本地 `origin/dev` 为 ahead 5；随后提交为 `b0ca919`。前轮九文件提交 `acb654d` 后没有 push；本轮短寿命测试进程已回收，无遗留后台进程。
- 没有启动 VM、安装依赖、运行真实 APT/验签或 I5-R，没有系统/设备/远程修改；UTM CLI、guest `--preparation-apt` 和 JXA `--collect` 的 preparation scope 仍在首次外部调用前 STOP。没有开启 RPC 的公开命令行入口。
- 未覆盖：控制文件所在 guest 文件系统及 QEMU agent 写入的完整硬额度、独占身份/隔离初始化、实际 source/介质/program 的受授权交付、Python 与原生 JXA RPC 的受监督进程启动/I/O 桥、UTM 同句柄/写入/readback 行为实测及宿主证据 backing 的硬容量和掉电行为。guest-agent 接口只按本机声明做映射，不宣称跨 UTM 版本兼容；物理 768 MiB 和真实 Linux 回收门仍未通过。

## 受监督 RPC 与单次生命周期离线接线（2026-10-18）

所有者明确要求先完成 RPC 进程桥并独立验收，再继续生命周期整合、离线验证与文档同步；禁止启动 VM、安装依赖、提交或 push。主持 Agent 负责设计、实际 diff 审阅与关键行为独立复验，两个实现包串行委派给 `gpt-6.1-sol / high`；这是工程验收，不替代专业安全审计或 Linux/UTM 实测。验收时本节实现保留在本地未提交工作区；随后所有者明确要求提交已验收更改、不 push，本节实现和记录随本次提交保存，不改写 10 月 13 日及更早记录。

### RPC 进程桥

[进程桥](../../scripts/sw_i5_preparation_rpc.py)维持 `rpc(request, timeout, limit) -> bytes` 接口，每次调用创建一个子进程，以非阻塞管道同时推进 stdin/stdout/stderr；不用 shell，不把请求或 guest 程序放入 argv，也不重新提交 execute。子进程继承 transport 的 session/process group，关闭无关 FD，供外层监督统一收尾。直接子进程的终止和 reap 已包含在最大 2 秒调用截止内，内部预留至多 250 ms；预算不足即失败，不增加额外固定清理时间。

RPC v1 继续绑定 UUID、nonce、manifest、sequence 和 action；请求至多 96 KiB、响应至多 6 MiB、stderr 至多 64 KiB。响应必须是单个合法 UTF-8 JSON，重复字段、错误身份、半帧、多帧、超限、非零退出、信号和非空 stderr 都不能成功。已执行但丢失响应时，transport 保留失败，只关闭已取得的 handle，不猜测未知 handle、不重试 execute。

JXA 增加内部有界字节驱动；原生源最多 128 KiB，按精确源摘要和 stdin 字节绑定，在私有临时目录中独占创建、读回核对并清理。`JXAProcessRPC` 没有默认 launcher，未显式注入即拒绝；原公开 `run()` 未增加可执行 RPC 参数。离线测试使用真实 Python/Node 子进程和合成 Foundation/Application API，未调用真实 osascript、Apple event 或 UTM。临时源清理失败与 RPC 初始失败同时保留，清理完成后再次检查原绝对截止。

同步进程创建、文件系统调用被内核阻塞，以及调用方被 SIGKILL 或关闭全部管道的遗留后代，不能仅靠此桥确认回收；必须由外层生命周期监督处理。继承 process group 不是 sandbox，逃离 session、不可杀进程和原生 UTM 的真实行为仍未验证。

主持 Agent 独立复跑 RPC、transport、纯 JavaScript 新旧适配测试，并另行运行三个公开 preparation STOP 子进程与四种非法预算的启动前拒绝检查。收尾补测时曾出现一次 SIGTERM 整组取消竞态：管道先报 BrokenPipe，测试未收到预期的取消诊断而失败。修正后同时保留 I/O 首因和取消信号，并补齐测试自身失败收尾；11 个 RPC 测试方法和该信号用例 20 次针对性复验通过。保留该首次失败，不因复验通过抹去时序问题。

### 生命周期整合与最终验收

本轮按以下边界实施[内部生命周期](../../scripts/sw_i5_preparation_lifecycle.py)：

- 调用控制端只持有专属 liveness/cancel 管道；独立 owner 持有 start、readiness、watchdog、唯一 shutdown/recovery 和最终持久化的职责。控制端在活动期被杀或断开时取消；owner 自身被 SIGKILL 仍需外部恢复，不宣称由进程内 finally 解决。
- start/readiness/shutdown 全部要求显式注入，分别在有界子进程执行并检查 UUID、nonce、manifest、action、mode 和结果状态。启动与停止均至多一次；启动返回丢失也按已尝试处理，不能重启。
- transport 建立独立 session 后先登记 PID，收到 owner 的单次 admission 才可进入 RPC。watchdog 的失败恢复只返回固定的显式委托状态，不能声称 stopped，也不再调用恢复 callback 或为委托另 fork 子进程；实际停止 callback 只由 owner 执行。收尾检查已登记的 session，leader 退出不自动等于后代已消失。
- 独立证据 worker 持有既有 `EvidenceStore`，先排他创建并读回 attempt，再允许启动；最后只接收一次报告和冻结的生命周期事实，执行原有写前计费、非覆盖发布与重开校验。owner 不同步执行可能阻塞的证据文件 I/O。
- 内部 synthetic receipt v2 增加生命周期事实；v1 默认语义保持。整体成功要求有效宿主结果、正常停止确认、必要进程清理和持久化完成。冻结前的取消必须失败；停止完成、最终事实冻结后的消费者丢失只影响交付，不能重跑或覆盖已写证据。持久化超时或证据 worker 的退出/reap 未确认仍报告未确认，不能仅凭文件可见推断完成。

默认保守账本为 **897 秒**：初始化 6、启动 60、readiness 60、活动期 600、watchdog 清理 25、watchdog 报告 2、停止 120、持久化 6、最终输出 2，另加八个各 2 秒的回收槽。八槽分别对应证据初始化失败、启动、readiness、watchdog 内部 transport kill、watchdog、transport 组、停止和证据持久化；初始化与持久化由同一个证据 worker 承担，两个失败收尾槽属保守预留。

全链从调用最初取得一次 monotonic 起点，以至多 900 秒绝对截止约束全部阶段；阶段上限还需为后续停止、持久化和回收保留时间。活动期 600 秒是本内部链的更紧上限，不扩张旧 host 620 秒；transport 工作窗最多 594 秒，为原 close 4 秒和输出 2 秒留在活动期内。guest 540 秒、租约静默 15 秒、RPC 2 秒及物理 768 MiB 不变。数字是代码拒绝边界和离线核算，不是实际 UTM 时限保证。

### 验收记录与剩余缺口

本包补测曾在 16 个方法中失败 1 项：长 Unicode callback 异常尚未登记时，清理阶段出现 `start kill: [Errno 1] Operation not permitted`，先占用了首因。实现改为在清理之前保存 action/host 原始异常，并在 kill 前先 poll/reap 已退出的直接子进程；真实清理异常仍保留并使整体失败，没有过滤 EPERM 或将回收失败改成通过。修复后针对性用例通过；实现 Agent 的 17 个生命周期方法通过，最后取消额外委托回收进程的修改另经七模式负例确认。主持 Agent 在最终代码冻结后独立复跑完整生命周期 17 个方法通过。

主持 Agent 实际审阅最终 diff 与新增文件，并完成以下独立检查（全部外部 UTM/密码/APT 行为均为合成替身）：

- `python3 -B scripts/test_sw_i5_rpc_process.py`：11 个方法通过；覆盖进程双向 I/O、有界输入/输出/stderr、退出/信号/取消、错误绑定、非 UTF-8、半帧/多帧、超时、JXA 源绑定及清理失败。SIGTERM 竞态修复另有 20 次针对性通过记录。
- `python3 -B scripts/test_sw_i5_lifecycle.py`：17 个方法通过。覆盖完整 owner → watchdog → transport → 真实 RPC 子进程链、execute 生效但返回丢失、启动/readiness/停止失败与卡住、控制端 EOF/SIGKILL、watchdog 登记前后 SIGKILL、无管道后代残留、初始化 fsync/readback 失败、重复 nonce、落盘卡住、异常首因、Unicode 诊断限额、冻结前后取消、report 消费者关闭及 receipt v2 篡改。冻结后消费者关闭时 owner exit 2，原 receipt 保留、execute/shutdown 均一次；它不是向消费者成功交付的证明。
- `python3 -B scripts/test_sw_i5_channels.py`：14 个方法通过；`python3 -B scripts/test_sw_i5_transport.py`：16 个方法通过，保留 standalone watchdog 与 receipt v1 的回归覆盖。
- `node scripts/test_sw_i5_utm_rpc.js`：33 项纯 JavaScript 检查通过；原适配层 29 项纯 JavaScript 自测通过，无 Application/ObjC/UTM 调用。
- 控制器 4、guest 45、APT/资源 helper 20、准备编排 20 个方法回归通过。三个公开 preparation 入口独立子进程检查均 exit 2 并包含 `I5_PREPARATION_ISOLATION_REQUIRED`；四类非法 RPC 预算在 launcher 前拒绝。额外 24 组早/晚阶段截止核对通过，所有阶段均同时受局部上限和后续清理预留约束。

内部 operation v1–v4 的字段与源文件集合不变；本轮没有生成新的可执行 operation 版本，也没有把新增 RPC/lifecycle 模块悄悄塞入旧合同。未来真实执行必须绑定包含新增模块在内的完整执行源、实际基线/介质/program、精确初始化与恢复适配器，并重新核对零占位符清单。synthetic receipt v2 不是 operation v4 已可承载新执行链的证明。

仍未执行或未关闭：真实 JXA/UTM guest-agent 行为与身份回收、控制槽和隔离环境初始化、原生基线/验签/APT 求解、全部宿主与 guest 写入硬额度、Linux 进程/namespace/cgroup 实测及物理介质掉电行为。owner 自身 SIGKILL、后代逃离已知 session 或内核不可杀任务只能保留外部恢复缺口。公开 preparation、I5 shell/Go 入口及 I5-R STOP 不变；768 MiB 不变，旧单次授权不延续。

收尾检查：`./scripts/check-repo.sh` 通过（209 文件）、`git diff --check` 通过，8 个新增/修改 Python 文件 AST 解析通过，未生成 bytecode。验收时 `dev` 保持 HEAD `4384656`，相对本地 `origin/dev` 无 ahead/behind，15 个任务文件（其中 4 个新增）未暂存、未提交；没有 push 或其他远程写入。未启动长期服务或 VM，测试短寿命进程按精确 PID/登记 group 收尾，临时合成目录随测试清理；这不扩大前述外部恢复保证。


## 初始化合同与容量账本离线评审（2026-10-18）

前轮 RPC 与生命周期实现已按所有者要求提交为 `17a142e`，未 push。随后所有者授权本第一包的离线设计、纯校验、测试及文档同步，继续由主持 Agent 负责设计和独立验收、`gpt-6.1-sol / high` 实施；不授权实际初始化、VM、依赖安装、提交或 push。以下面向环境实施者和证据复核者，只表达可评审的计划与声明一致性，不是容量验收、操作授权或可执行命令清单。

### 设计边界

初始化计划与容量账本使用独立的 review-only 合同；旧 operation v1–v4、resource config v1、准备结果与 receipt 的既有语义保持不变。校验仅消费显式提供的 JSON bytes 和绑定参数，不查询文件系统、账号、VM 或内核，不执行任何创建、挂载、格式化、限额设置或清理动作。

`review_passed` 只表示计划结构、合成观测和声明算术符合本版本要求。真实执行、安装、I5 就绪及物理验证标志始终为 false，执行阻塞项始终保留。语法、版本、未知字段、绑定或矛盾数据直接拒绝；草案显式缺失的观测与容量信息形成逐项阻塞，不能以零值、默认成功或自动补齐掩盖。

入口位于[纯校验模块](../../scripts/sw_i5_preparation_plan.py)，没有 CLI。两份输入均为至多 256 KiB 的 UTF-8 JSON bytes，拒绝重复字段、非有限值、额外帧及未知字段；使用独立 schema 1 和固定 UUID、32 位十六进制 nonce、manifest SHA256。计划的 `capacity_sha256` 绑定账本原始 bytes，连空白变化也须重新评审。

| 接口 | 输入 scope / 用途 | 结果边界 |
| --- | --- | --- |
| `validate_plan(raw, nonce, manifest_sha256)` | `i5-review-initialization`；检查固定初始化角色和合成身份读回 | 不单独证明关联账本有效 |
| `validate_capacity(raw, profile, nonce, manifest_sha256)` | `i5-review-capacity`；显式选择 `preparation` 或 `i5-runtime` | 检查该 profile 的覆盖与算术，不探测后端 |
| `review(plan_raw, ledger_raw, nonce, manifest_sha256)` | 仅联合评审准备期计划与账本 | 检查精确账本摘要、输入/源码/控制槽/证据副本预留和双方阻塞项 |

报告绑定本次 UUID、nonce、manifest，保留 `review_only=true` 和永久执行阻塞项；`authorized`、`install_authorized`、`i5_ready`、`physical_verified` 均固定为 false。`unknown` 容量行必须用 null 表达未知，不能用 0；报告中的金额仅是已知声明的小计，存在未知项时 `review_passed=false`，不得视为完整物理总额。测试 fixture 只提供合成填法，不是可直接运行的操作包。

### 初始化与阶段归属

- 宿主受控 JXA 暂存根、证据父目录及独占 attempt 的准备/读回归入既有 init 窗口；guest 准备根、WORK/RESULT 挂载点、cgroup 父域与两个子域、control 目录及两个固定 1024-byte 槽的准备/读回归入 readiness。
- 控制槽必须在 transport 打开前已准备完成，不能依赖同一次 execute 创建。JXA 每次 RPC 的源文件暂存、核对和清理仍发生于该次 RPC 的截止内；提前准备暂存根不等于提前生成了后续请求源。
- 对象明确创建者、使用者、所有者、权限、创建/绑定规则、独立读回及失败保留/清理条件。规范路径校验只是词法约束；真实无 symlink、无替换和实际身份一致性仍需未来独立观测。
- 时间子分配必须包含于既有阶段，不能把初始化子步骤另加到总账。默认 897 秒保守账本、900 秒绝对截止和所有原有清理预留不变；本包不调整生命周期实现。

固定 13 个对象包括宿主三项、guest root/WORK/RESULT、三个 cgroup、control、lease/ack 和只读输入。新对象必须声明原先不存在；已有输入和证据父目录按绑定策略保持身份，已消费 nonce、路径交叠、相同 realm 的 inode 别名、槽多链接、权限/长度错误或独立读回替换均拒绝。合成快照的 `independent-reader` 只是明确角色，不是已经有真实独立观察的证据。

### 容量口径

| 账本 | 固定边界 | 本包能检查的内容 |
| --- | --- | --- |
| 准备期 | INPUT ≤256 MiB、WORK ≤128 MiB、RESULT ≤8 MiB、宿主留存候选 ≤32 MiB | 还须显式列出环境写入、介质制作/暂存和副本峰值的候选包络；四项之和不能冒充完整预算，候选包络不构成额度授权 |
| I5 运行期 | build 256、daemon 160、evidence 240、diagnostic 64、node tmpfs 48 MiB，合计 768 MiB | 四磁盘域分别核算整盘 D 和本域外部开销 H，要求 D + H ≤ C；节点 48 MiB 不作为系统 tmpfs 的免费空间 |

整盘 D 已包含 guest 文件系统元数据；在 D 内的逻辑份额不再与 D 重复相加，但份额峰值必须能被 D 容纳。H 必须覆盖不含在 D 中的宿主额外硬预留，四域 backing 元数据分别绑定本域。不能用数据预计占用小替代设备上限，也不能将满额四盘的额外开销移出账本。

固定写入面必须覆盖 guest 系统/root-var、EFI/固件、swap 与系统 tmpfs，UTM/QEMU 日志和状态、宿主 backing、换出/崩溃、JXA 暂存及证据复制；I5 另覆盖构建、daemon/containerd/builder 和节点 tmpfs。独立副本计共存峰值；同一物理表示不得重复计费。未知 backing、没有归属或仅有 `du`/可用空间采样/逻辑文件长度的项，不能通过完整账本评审。只有 guest swap 与宿主 swap/crash 两个面允许按各自明确的禁用机制和离线来源声明计零，不能从 guest swap 禁用推导宿主无换出；其余固定面必须为有正预留的 bounded 或显式 unknown。

联合评审额外核对输入介质制作与暂存两份、JXA 拼装后源码、两个控制槽、证据导出源与最终留存两份。JXA 每份保守上界为 `source_bytes + 6 × REQUEST_LIMIT + 4096`：包含最长 96 KiB 请求的 JSON 转义与 wrapper，不能只预留原始 ≤128 KiB 的源码。控制槽数据下限为两份各 1024 bytes，证据源/留存各至少覆盖既有 4 MiB STORE_LIMIT；这些 payload 下限不证明文件系统元数据已满足。WORK/RESULT 分别按既有 128/8 MiB noswap tmpfs 的完整上限预留，不能填较小预计占用换取通过。所有 backing/硬机制仍只是本包的离线声明，必须在后续实际配置、独立读回和拒绝测试中证明。

### 验证与后续

主持 Agent 审阅新增模块与测试并独立验收；本包只新增[计划/账本校验](../../scripts/sw_i5_preparation_plan.py)和[合成测试](../../scripts/test_sw_i5_preparation_plan.py)，没有修改既有运行代码或旧 operation/resource 合同。

- `python3 -B scripts/test_sw_i5_preparation_plan.py`：19 个测试方法通过。覆盖两个 profile、13 个固定对象、缺失/未知项、版本与精确字节绑定、UTF-8/重复字段/非法类型、nonce 消费、路径与身份替换、槽权限/长度/链接、阶段预算、D + H 超额、整盘与小 payload 区分、副本漏算、JXA 拼装源峰值、swap 禁用、旧 schema 拒绝新合同，以及禁止文件系统/进程/环境查询的调用检查。
- 主持 Agent 额外执行 12,368 次结构/类型变异：结果仅为保留全部停止标志的离线报告或 `ValueError`，无意外异常、无执行标志开启。该检查不宣称所有无效输入都已穷尽。
- 本任务基线回归：`python3 -B scripts/check-sw-i5-resources.py self-test` 20 项、`python3 -B scripts/test_sw_i5_preparation.py` 20 个方法通过；收尾 `python3 -B scripts/test_sw_i5_utm_control.py` 4 个方法和 `python3 -B scripts/test_sw_i5_guest.py` 45 个方法通过。旧运行代码未修改，不重复宣称执行了前轮完整生命周期矩阵。

实现 Agent 首次运行新增测试 exit 1：17 个方法中两个方法产生 21 个失败断言，20 个来自测试将原本 null 的字段再次改为 null，另一个将 D 设为恰好等于份额而误期望超限。修正为实际改变字段和低于份额的边界后通过，没有放宽实现的拒绝规则。主持审查另外修正了错误套用 guest 范围的 host GID、bytes JSON 对 UTF-16 的隐式接受、JXA 包装请求漏算，并补齐报告绑定；最终 19 个方法由主持 Agent 独立复验通过。实现 Agent 另有一次资源自测命令遗漏 `self-test` 参数，退出 2；按现有用法补齐动作后 20 项通过，该用法错误没有引发源码修改。

真实初始化编排、受限暂存接线、新执行合同及真实准备证据版本、物理后端选择和 Linux/UTM 验收仍属于后续工作包；全部真实入口与 I5-R 保持 STOP。现有 `JXAProcessRPC` 仍使用原暂存机制，新计划不会自动替它设置根目录或 quota。不得把测试 fixture、声明机制名或 `review_passed=true` 当作实际路径、硬限额或当前操作授权。

离线验收时收尾：`./scripts/check-repo.sh` 通过（211 文件），`git diff --check` 和两个新增 Python 文件的 AST 检查通过；最终代码冻结后主持 Agent 再次独立运行新增 19 个方法通过。`dev` 保持 `17a142e`、相对本地 `origin/dev` ahead 1；本包 8 个文件（6 份文档、2 个新增脚本）未暂存、未提交。没有启动 VM、安装依赖、真实 Application/UTM 调用、远程写入或遗留本任务后台进程。

随后所有者明确要求将本包 8 个文件提交到 `dev`、不 push；本节实现与记录随本次提交保存。该提交授权不包含第二包实施或真实环境操作，后续梳理仍保持全部 STOP。

## 初始化、受控暂存与收尾内部接线（2026-10-18）

第一包已提交为 `e6d50ff`，未 push。所有者随后明确授权第二包的初始化实施、受控 JXA 暂存、生命周期收尾内部接线、离线测试及文档同步；继续由主持 Agent 负责设计与独立验收、`gpt-6.1-sol / high` 实施。本包不启动 VM、安装依赖、调用真实 Application/UTM，不提交或 push，不创建物理 quota、账号或介质，所有真实入口保持 STOP。

### 已批准的内部设计

- 第一步重验第一包原始计划/账本、源摘要和目标绑定。review-only 合同保持纯校验；其合成观测与 `review_passed` 不成为实际环境事实或执行许可。新路径必须显式注入 synthetic 初始化后端和 launcher，不提供真实 backend、默认启动器或命令行开关。
- 宿主在既有 init 窗口核对私有证据父目录、消费并读回 attempt，再独占准备 JXA nonce 暂存根。已有 attempt/root 不覆盖、不续跑；初始化返回丢失也不重试。身份核对使用本次实际观察，不能复用计划内预测的 inode。
- guest 初始化由固定步骤驱动注入后端，准备 root、WORK/RESULT 挂载点、三个 cgroup、control 和两份 1024-byte 全零槽，绑定既有只读输入并独立读回。暂存目录模拟后端只用于离线测试，模拟 guest UID/cgroup 与宿主实际 inode/文件属性分别表达，不冒充真实 root 权限或 cgroupfs。transport 必须消费同一初始化产物，不能分别使用互不关联的成功替身。
- 复用证据 worker 持有暂存根、对象登记和文件 I/O。RPC 客户端经真正 IPC 发送有界请求，worker 在写入前向独立 owner 登记 intent 与所得对象身份并取得 ACK；不依靠 fork 后的 Python 对象共享状态。登记或创建响应丢失时保守失败，身份未知的对象不得猜测删除。
- JXA 每次调用在同一绝对截止内完成完整拼装源码的预留、独占创建、读回、执行与清理；删除默认系统临时目录回退。worker 文件 I/O 卡住时，客户端截止仍有效，后续按未确认处理，不因源码文件可见而放行。登记必须有界，不能随 RPC 次数无限积累历史列表。
- transport 及已登记 session 收尾后，按 guest 清理、单次停止、宿主 source/root 清理顺序结束；三者共享原 shutdown 窗口，清理不能吃掉停止预留。路径或身份被替换、对象存活状态未知时保留并报告失败，输入与证据始终保留。owner 冻结事实后才持久化，原始失败与后续清理失败同时保存。

每阶段只建立一次绝对截止：init 共 6 秒、readiness 共 60 秒、单次 RPC 共至多 2 秒；新增工作和清理全部纳入原阶段与回收槽，不增加原 897 秒保守账本或至多 900 秒总截止。旧 operation v1–v4、review/resource v1 与 receipt v1/v2 的字段和语义不暗改；新增内部初始化/清理事实单独版本化，并继续标为 synthetic、非物理验证、非 I5 就绪。

### 实施与证据边界

[固定对象初始化](../../scripts/sw_i5_preparation_initialization.py)只提供 `SyntheticInitialization` 和 `MappedSyntheticGuest`。入口重新解析不可变计划/账本字节，重验源摘要与 nonce/manifest/UUID，并拒绝未知容量项、真实候选 kind、重叠路径和非精确 `JXAProcessRPC`；随后快照注入参数，不接受 fork 前被修改的派生状态。宿主文件使用实际 UID/GID、无符号链接的逐级目录打开、独占创建与独立读回。模拟 cgroup 只是普通文件，模拟 guest 身份与 host 实际属性分开；任何结果都不宣称已经存在 Linux 硬隔离或只读挂载。

[暂存 IPC](../../scripts/sw_i5_preparation_staging.py)绑定 scope/version、UUID、nonce、manifest、实际 root 身份、单调 sequence 与本次绝对截止。[RPC 桥](../../scripts/sw_i5_preparation_rpc.py)仅在显式 launcher 与 stager 均存在时继续，完整拼装源的预留包含请求包装开销；同一调用为执行和清理留出时间。worker 持有创建对象的 FD，写 payload 前向 owner 登记 intent/identity 并取得 ACK；丢失 ACK 不写 payload，丢失结果不重试。owner 只保留固定角色的当前登记与滚动摘要，已清理 source 不累积历史。进程死亡或文件系统阻塞时，无法确认的登记随失败结果保留；身份替换、额外目录项或未确认 session 都阻止猜测删除。

[生命周期 owner](../../scripts/sw_i5_preparation_lifecycle.py)和证据 worker 各司其职：worker 处理可能阻塞的文件操作，owner 维持取消、时钟、登记和唯一停止责任。新增 staging FD 只传给 transport，watchdog 的父分支随即关闭；RPC launcher 保持 `close_fds=True`。guest 初始化与 readiness 共用一次截止，暂存上传/登记/写入/读回/执行/清理共用单次 RPC 截止。shutdown 内先给 guest 清理固定小窗口，再执行一次正常或恢复停止，最后处理宿主 source/root；停止子进程的原回收槽也计入预留，未增加阶段或进程槽。

[证据模块](../../scripts/sw_i5_preparation_evidence.py)新增内部 attempt v2 与 receipt v3：attempt 先固定期望 receipt 版本及计划、账本、源码摘要，读回时逐项比对，删掉初始化字段降为旧 receipt 会被拒绝。v3 保存实际对象身份、准备状态、guest/host 清理状态、有界当前登记及其摘要，所有真实授权/安装/物理验证/I5 就绪标志保持 false。旧 attempt v1 仍只配 receipt v1/v2，旧字段语义和 operation v1–v4、review/resource v1 不改。receipt 是合成内部证据；真实准备的 result/export/report/receipt 与新执行源集合仍须另行设计，不能复用旧操作包启动新依赖链。

### 验证与后续

主持 Agent 审阅全部新增代码和既有接口差量后，独立执行以下离线验收：

- `python3 -B scripts/test_sw_i5_initialization.py`：16 个方法通过，覆盖完整 owner/worker/watchdog/transport/RPC 子进程链、同一暂存根与控制槽、已有 nonce/root、实际父目录/输入身份、符号链接和权限、短写/ENOSPC、读回卡住、取消/SIGKILL、execute 或初始化返回丢失、登记 ACK 丢失、替换保留、单次停止、版本降级及当前登记语义篡改拒绝。组合负例同时保留全部 11 个未清理角色和长 Unicode 首因/清理错误，仍能持久化并重开 ≤8192-byte receipt、返回 ≤16384-byte packet；输入和 attempt 保留。
- `python3 -B scripts/test_sw_i5_staging.py`：4 个方法通过，使用真实 socket/fork 验证身份/序号错误、超额上传前拒绝、上传阻塞、迟到/丢失回复及失败后不重试。
- `python3 -B scripts/test_sw_i5_rpc_process.py`：12 个方法通过；本轮新增退出/空 select 竞态的确定性回归，并额外对该项与 stderr/退出矩阵执行 40 次精准重复，全部通过。
- 既有接口回归：`test_sw_i5_lifecycle.py` 17、`test_sw_i5_channels.py` 14、`test_sw_i5_transport.py` 16、`test_sw_i5_preparation_plan.py` 19、`test_sw_i5_preparation.py` 20、`test_sw_i5_utm_control.py` 4、`test_sw_i5_guest.py` 45 个方法通过；`python3 -B scripts/check-sw-i5-resources.py self-test` 20 项及 `node scripts/test_sw_i5_utm_rpc.js` 33 项通过。另以 subprocess 核对公开 control、guest 和 collect 的三个 preparation-apt 入口均返回 2 与原 STOP 标记，未调用外部环境。

本轮保留如下失败记录，不用最终通过覆盖初次结果：

1. 实现 Agent 的首次旧 lifecycle 17 方法运行 exit 1：init 改为从全局起点计时后，150 ms 测试窗口在调度延迟下尚未创建 attempt，导致该存在性断言失败。仅把模拟 fsync 卡住/读回失败用例的 init 窗口设为 600 ms，使断言确实覆盖目标文件系统故障；产品 6 秒截止未变，最终 17 方法通过。
2. 新初始化首轮 14 方法 exit 1：模拟源读回卡住时，合成 lease silence=2 秒与 RPC 至多 2 秒竞争，首因实际为 `lease expired`，测试却只期望 RPC deadline。只把该故障用例的 silence 设为 5 秒并允许停止 callback 观察预期残留，产品租约/截止未变，后续通过。
3. 组合负例初次 exit 1：测试误把全部 pending 角色计为 10，实际为 host root 1 + guest 9 + source 1 = 11。主持首次新链回归也命中同一未修正断言；修正测试计数并合并重叠用例后复验，没有放宽实现限额。
4. 主持独立 RPC 回归首次 exit 1：一个 stderr 用例被过早报告为 `pipe still open after child exit`。子进程可能在 selector 空返回与 poll 之间退出，不能据此认定后代泄漏。修复为继续在原 I/O 截止内排空字节/EOF，仅到期仍未关闭时报告未确认后代；没有延长 RPC 总截止。新增确定性用例、完整 12 方法和 40 次精准重复通过。

主持审查还补齐了写入前父目录/已创建 inode 绑定、非阻塞证据通道等待 EOF、迟到回复拒绝、异常 shutdown 截止仍收尾、按编码字节截断诊断和 attempt/receipt 防降级，并为写入前父目录被替换为 symlink 的场景添加拒绝回归。上述均是合成临时目录和进程边界的验证。

物理后端和完整硬额度、真实输入、新执行源合同、真实准备证据与 Linux/UTM 验收仍为后续范围，离线接线不解除 STOP。owner 自身 SIGKILL、逃出已知 session 的后代、不可杀的内核工作以及未建立物理 quota 的写入仍不能由本包证明安全收尾；未知残留保留，不伪造已清理。

收尾验证：`./scripts/check-repo.sh` 通过（215 文件）、`git diff --check` 通过，10 个新增/修改 Python 文件的 AST 检查通过。`dev` 保持 `e6d50ff`，相对本地 `origin/dev` ahead 2；本包共 16 个文件（6 份文档、6 个既有脚本/测试、4 个新增脚本/测试）未暂存、未提交。没有启动 VM、真实 Application/UTM、安装依赖、系统配置或远程写入；本任务离线测试子进程已结束，无遗留后台任务。最新实测仍为 10 月 9 日记录，未通过状态查询暗中扩大本次授权。

随后所有者明确要求将本包已验收的 16 个文件提交到 `dev`、不 push；本节实现与记录随本次提交保存。提交前只同步当前提交状态，未改变已验收运行代码。后续只梳理剩余缺口与实施顺序，不包含下一包实现、VM 启动、依赖安装或入口放行授权。

## 执行合同与原生证据候选（2026-10-18）

上一包十六文件已提交为 `4281fb0`，未 push。随后所有者单独授权下一包的设计、纯校验、负例测试及文档同步，由 Astra 主持设计和独立验收，`gpt-6.1-sol high` 实施。新专题见[准备执行合同与原生证据候选](sw-g4-synthetic-i5-execution-contract.md)，集中维护源码闭包、原生证据模型和物理启动前置条件，不把本页继续扩展为完整 schema 参考。

该候选设计区分 bytes/声明一致性与真实来源、物理验证及当次执行授权。系统盘、EFI、swap、宿主 backing/日志与证据目录的硬边界必须在启动前落实；init 只核验已有条件，不能暗中执行环境配置。真实初始化后端、真实输入和物理拒绝/回收验收仍缺，全部真实入口 STOP；本包离线实施时未启动 VM、安装依赖、提交或 push；验收后所有者明确要求将十个文件提交到 dev，本包随本次提交保存，未 push。

本包离线实现与验收已完成：32 个新增测试、既有 plan/control/APT/guest 回归、33 个纯 JavaScript 用例及主持独立八项变异通过；失败与修正、接口限制和工作区状态见[离线验收记录](sw-g4-synthetic-i5-execution-contract.md#离线验收记录2026-10-18)。运行代码与旧合同消费者未修改，真实入口停止线不变。

## 原生初始化与 bootstrap 离线实施（2026-10-18）

第三包已提交为 `c232d9e`，未 push。所有者随后明确授权第四包的物理承载候选、真实初始化后端代码、bootstrap 组装及原生证据绑定离线实施，继续由 Astra 主持并委派 `gpt-6.1-sol high`；已完成离线实施与独立验收，完整设计与结果见[独立专题](sw-g4-synthetic-i5-native-initialization.md)。本包不改变旧执行合同或真实入口，离线实施时没有启动 VM、安装依赖、提交或 push；验收后所有者另行授权将十三个文件提交到 dev，本包随本次提交保存，未 push。物理硬边界和原生环境验收仍须另行关闭。

## 宿主写入裁决与原生生命周期离线接入（2026-10-18）

第四包已提交为 `b8fb2d5`，未 push。所有者随后明确授权先冻结宿主完整写入硬边界、父监督职责和独立库交付，再推进原生后端生命周期离线接入；设计、实现和验收见[独立专题](sw-g4-synthetic-i5-host-delivery.md)。本包复用既有容量 profile、897/900 秒时限与宿主证据存储，增加明确的新 scope，不扩大旧 48 KiB 通道或放行真实入口。

当前 Mac/UTM 为 `blocked-host-system-writes`，系统 swap、崩溃/日志及域外状态缺少完整硬上限。离线库交付和真实 fork/pipe 的注入生命周期只证明所覆盖的软件行为；真实 FD loader、物理承载及 Linux/UTM 验收仍缺。离线验收期间本包未提交，没有启动 VM、安装依赖或修改系统；验收后所有者另行明确授权将 28 个文件提交到 dev，本包随本次提交保存，未 push。下一步先解决此物理阻塞并固定真实交付/基线，再另行评审精确环境操作授权；本次提交后的缺口梳理不包含后续实现或环境操作。

## 宿主可行性与真实加载合同设计（2026-10-18）

第五包已提交为 `fa48743`，未 push。所有者随后只授权宿主可行性决策与真实 FD loader 合同设计；[设计草案](sw-g4-synthetic-i5-host-loader-decision.md)明确当前 Mac/UTM 在原完整写入合同下 NO-GO，区分正式 768 MiB 与未获批的准备期完整包络，列出专用 Linux、修订证据边界和暂停三条路线及待决策事项。可信基座 P 必须在加载前生效，N 消费固定 FD 得到的已验 bytes；跨启动稳定预期不能沿用历史 dev/inode/mount ID。

上述为设计候选，未修改现有 schema、代码或停止检查，未启动 VM、安装依赖、提交或 push；没有真实环境 PASS。后续所有者已选 A 并授权预算设计，当前状态见下节。

## 路线 A 的已有资源与完整准备预算设计（2026-10-18）

所有者要求保留现有完整边界、优先评估已有 Linux、暂不新增采购，并确认目前只有已记录的 Mac/UTM。[独立评估](sw-g4-synthetic-i5-linux-host-assessment.md)已列最低能力、保守容量筛选和差距；当前没有合格宿主，不能通过增加 guest 配额或换一个同底层 VM 放行。

完整准备候选上限为 3608 MiB：沿用 input/work/result/host-retention 合计 424，加 environment 子预留 3184，覆盖制作/暂存、系统与工具差量、恢复、系统 tmpfs/日志、控制源码、额外元数据、固件及可信加载增量。仅适用于复用已有 Linux 基线、不重装或整盘迁移；不是可信实测消耗、已批准额度或安装授权。缺少目标、闭包和硬机制时不能填写 bounded；正式 I5 仍为 768 MiB。

本次只改设计文档；没有连接设备、运行探针、启动 VM、安装、实现、提交或 push。A 和不采购已确认，下一条件是可用资源事实变化，再审预算与真实接口；全部真实入口继续 STOP。
