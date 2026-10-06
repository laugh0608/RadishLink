# I5 专用环境准备评审包

- 更新日期：2026-10-06
- 状态：来源候选与权限/容量边界已细化；安装清单和宿主硬容量证明未闭合，禁止据此执行环境操作
- 目标读者：环境准备、I5 后端实现与证据复核者
- 范围：承接有效 guest 盘点，收敛工具输入、身份分工、写入归属和下一离线实施顺序
- 非目标：启动 VM、安装或更新依赖、改变身份/系统配置、创建磁盘、运行构建/daemon/I5-R

## 本轮结果

所有者要求“提交工作区更改，继续推进下一步”。四份实测结果文档已提交为 `c7b0aa1`，未 push；本轮随后只读核对源码、公开发布/安全资料及官方包索引，形成本文和[候选来源清单](../../tools/t0/i5-environment-candidates.json)。没有下载候选软件包或执行 guest 命令。

目标仍为 `RadishLink-I5-Debian13-ARM64`，UUID `B86E1A47-9A67-4ECF-A51F-2B2F29CDB726`。已验证事实见[实测记录](sw-g4-synthetic-i5-resource-isolation.md#宿主回收与第二次盘点实测结果2026-10-06)，不在本文复制完整盘点。最近一次已验证状态为正常关机、无网卡及共享；本轮没有重新调用 UTM 状态接口，不能把历史状态称为本轮实时复核。

当前需要关闭三个具体问题：

1. 发行版包和官方包不是同一依赖图。Debian trixie 的 `docker.io` 不包含独立 `docker-cli`；仅安装原盘点清单中的名称不构成完整环境。
2. agent 为 root，而现有 Go 构建 helper 要求非 root、无 capabilities、单线程及域外只读挂载；安装工具不能自动满足这些前置。
3. 四域上限 720 MiB 加节点 tmpfs 48 MiB 已占满总额。四个满额 guest 盘加未计费的 backing/系统日志不能作为合格后端；完整物理占用边界仍未证明。

## 工具来源与固定输入

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

## 本轮验证与限制

- `c7b0aa1` 提交前，仓库检查（186 文件）和 `git diff --check` 通过，提交后工作树干净；随后才产生本包文件。
- 机器可读候选清单与抓取的 Packages 精确版本/架构/大小/SHA-256 对照；共四个 deb 候选及一个 Go 归档。清单不被运行入口消费，不等于依赖安装或锁定通过。
- 本包完成后，`./scripts/check-repo.sh` 通过（188 文件），`git diff --check` 通过；新增 JSON 解析及其四个包条目与原始索引的独立逐项对照通过。
- 首次沙盒内 curl 退出 7，原因是无法连接本机代理 `127.0.0.1:10808`；获准后同 URL/目标在沙盒外读取成功。InRelease 随后只读取得；网页工具的 containerd 下载页及原始 Packages 页面曾报 Internal Error，不将网页读取失败当成软件包不存在。
- 验签工具查找未找到，未执行密码学验证；这是尚未关闭的证据缺口，不用摘要匹配替代。
- 未运行 Go/Python 实现测试、构建或 VM：本轮没有改实现、依赖、系统或设备。本文只完成设计/来源细化，不代表新的环境验收。
