# I5 环境可行性收敛与下一次操作包

- 日期：2026-10-13，Asia/Shanghai
- 状态：Draft，可审阅；已取得固定 Debian 完整索引、公钥文件与官方指纹依据，并细化离线实施方案；签名/原生闭包及 768 MiB 后端可行性未通过，下一次操作尚不可执行
- 用途与读者：供所有者、环境实施者及复核者决定验签/解析范围、完整容量边界及后续实施前置
- 本轮授权：读取已保存证据、核算、形成文档并执行仓库检查；不启动 VM、不安装依赖、不运行 I5-R
- 非目标：新增解析器或运行入口、调整五域额度、接受安装锁、安全/许可证结论、修改旧 evidence 或授权记录

## 结论与证据基线

本轮已将安装需求归类，并把全部已知写入面逐项对应到原 768 MiB 合同。**当前 UTM 配置不具备 I5-R 条件；现有证据不能证明 768 MiB 对所有后端都不可行。** 下一次环境操作建议只做来源验签和原生 APT 离线模拟，结果回收后停止；安装、隔离配置、真实容量拒绝及冷构建仍是后续独立范围。

本轮是文档设计与证据核对；涉及的未来系统/依赖操作按 L3 评审，本轮不执行。未改变 [I5 资源合同](sw-g4-synthetic-i5-resource-isolation.md)、候选 JSON、入口 STOP、profile 或 evidence schema。

本页初稿及六处入口同步已按所有者要求提交为 `e16ee48`，未 push。随后获准继续补齐信任输入与离线实施方案；最新产物见[续接输入与实施方案](#续接可信输入与离线实施方案2026-10-13)，前面的静态包表不视为原生求解结果。

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

上述三份文档已按所有者要求提交为 `0b589cc`，未 push。随后获准实施验签/APT 准备入口、有界输出和取消回收及离线测试；该授权明确排除启动 VM、安装依赖和 I5-R。以下实现尚未提交，不改变历史合同、候选包版本或 768 MiB 运行预算。

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
- `./scripts/check-repo.sh` 通过（195 文件），`git diff --check` 通过；本轮测试无失败。最终 `dev` 相对本地 `origin/dev` 为 ahead 2，新增实现和配套记录共 8 个文件未提交；没有 push 或其他远程写入，没有遗留本轮后台进程。
- 真实密钥/策略核对与密码学验签、APT 3.0.3 实际配置展开/arm64 与 all pin 行为/求解输出、完整原始包库与工具二进制基线、介质制作及挂载、硬容量/内存与全局写入隔离、外部取消和真实回收均未执行或未闭合。已有 metadata review 输入保持原样，没有制造可执行 manifest 或再次使用历史授权。
- 当前改动会使依赖这些脚本摘要的旧操作合同不再匹配当前源码；历史记录和旧操作目录不改写。未来真实包必须重新绑定全部源与输入、证明上述硬边界，并取得当次授权。I5 shell preflight/run 和 Go synthetic-run 停止代码未修改。
