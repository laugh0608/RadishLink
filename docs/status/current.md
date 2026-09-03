# RadishLink 当前状态

更新日期：2026-09-03

## 当前阶段

项目处于 `D0：产品定义、法规预检与三节点 POC 准备`。当前目标不是立即设计量产 PCB，而是先证明四件事：目标地区可以合法测试选定无线方案、三节点能够稳定形成并恢复路径、端到端加密文字可以跨中继送达、实时媒体在明确距离和码率下具备可行性。

## 已确定

- 项目与仓库名：`RadishLink`；标语：`无网亦可达`。
- 每台正式设备必须具备终端能力和中继能力，中继是否启用由电量、温度、用户策略和网络状态决定。
- 设备必须脱离手机独立完成联系人选择、文字收发、按键通话和基本状态查看。
- 手机是附近的伴侣终端，不是系统存在的前提，也不能仅靠软件获得手机硬件不具备的 HaLow 射频能力。
- 主系统基线为嵌入式 Linux；ESP32-S3 只保留为电源、按键、低功耗待机或辅助显示控制器候选。
- 长距承载首选评估 Wi-Fi HaLow；近距接入使用独立 2.4 GHz Wi-Fi / BLE。
- 应用层端到端加密与无线链路加密分层实现；中继节点不得获得消息、附件或媒体明文。
- POC 至少使用三台节点；正式外场距离测试前必须通过无线电合规门。
- 仓库原创内容采用 `RadishLink Source-Available License 1.0`；该许可证允许个人参考和学习范围内的查看与阅读，但不是开放源码许可证，完整条款以根目录 `LICENSE` 为准。
- 仓库采用 `topic -> dev -> master -> dev` 治理闭环；`master` 是稳定主线，`dev` 是常态集成分支。
- GitHub 公开仓库 `laugh0608/RadishLink` 已完成初始化；`master` 是 GitHub 默认稳定主线，`dev` 是常态集成分支。merge commit 与 rebase merge 已开启、squash merge 已关闭；仅匹配 `master` 的 active Ruleset 已要求 PR、解决会话和 strict `Candidate Quality`，并禁止删除与 non-fast-forward 更新。
- GitHub Private Vulnerability Reporting 已启用；安全漏洞按根目录 `SECURITY.md` 使用私密入口报告，不通过公开 Issue 或 Pull Request 披露。
- `PLAN-G0`、`SW-G0` 与 `SW-G1` 已于 2026-08-24 接受，`SW-G3` 与 `SW-G4/SW-V0` 已于 2026-08-28 接受并完成；`mls-rs 0.56.0` 单元 D 的固定 94-package 图保留正式历史 `STOP`，A2/A3 已形成 clean revision。2026-09-02 单元 D2 对同一固定图形成 schema 2/v2 正式 Phase A `PASS`，仓库 lockfile 已提升并与 seed/evidence 一致；11 个 package 的随包许可证证据仍不足以覆盖全部声明正文及适用 copyright/NOTICE。首次 R1 与 R1b 因不同 raw 文件 `TimeoutError` 形成有效传输负向 evidence；R1c-I 随后改用同一 tree entry blob SHA 与 Git Blobs API，R1c-R 完成 6 commit/11 package mapping 并以有效 `STOP/license-evidence` 收口：9 个 `mls-rs` package 覆盖 Apache-2.0/MIT，`debug_tree` 缺 MIT 正文，`r-efi` 只覆盖 MIT、缺 Apache-2.0/LGPL-2.1-or-later 完整正文。该结果是固定 tree 的工程证据缺口，不是许可证不存在、法律违规或候选淘汰结论；R2 前置不满足，Phase B 禁止。OpenMLS 0.9.0 的 A6 已由 `ac01b4d` 收口；2026-09-01 单元 E 在固定 264-package 图上形成 schema 4/v4 正式 `STOP`：source/audit/feature 为零，`cargo-audit` 未发现 vulnerability 但报告一个 unmaintained 信息项，当前许可证门拒绝三个 `MPL-2.0` crate。OpenMLS 0.9.0 不进入 Phase B，`SW-G2` 未通过；`SW-V0 PASS` 只接受 harness 有效，不代表 E2EE 路线、产品软件实现、P0 或其他证据轨通过。

## 关键风险

1. **区域法规风险**：MM8108 当前模块覆盖 850–950 MHz，HaLowLink 2 公布的支持地区不含中国大陆；不能把其他地区的免许可条件直接带入国内测试。
2. **Mesh 成熟度风险**：Morse Micro 当前将 HaLowLink 的 802.11s 标记为实验性功能，并提示多跳吞吐代价和区域限制。
3. **性能风险**：43.33 Mbps 是 8 MHz、最高调制下的 PHY 峰值，不代表 500 m、多跳、加密后的应用吞吐。
4. **功耗与体积风险**：Raspberry Pi 评估平台适合证明功能，不代表可以达到随身产品的续航和体积。
5. **媒体复杂度风险**：实时语音、视频、路由切换、拥塞控制和端到端加密必须联合验证，单独跑通 `iperf3` 不等于产品可用。
6. **设计漂移风险**：`SW-EXP-001` 探针早于已接受的消息语义、故障模型和证据格式；后续实现若直接继承探针 JSON、摘要 ACK 或 snapshot，会偏离 `SW-G1` 并把测试技术栈误当成产品协议。
7. **低成本硬件捷径风险**：直接用三块 MCU 重写 Core 会偏离嵌入式 Linux 基线，也无法覆盖目标媒体、持久化和升级边界；MCU 只进入交互与低功耗辅助域。
8. **E2EE 候选依赖风险**：`OpenMLS 0.8.1 + openmls_rust_crypto 0.5.1` 固定图已命中活跃 RustSec advisory，其中包含 AArch64 constant-time 错误；`hpke-rs* 0.6.1` 的 `MPL-2.0` 也未通过初始许可证门。OpenMLS 0.9.0 单元 E 的独立 audit 未发现 vulnerability，但报告 `proc-macro-error2 2.0.1` 的 `RUSTSEC-2026-0173` unmaintained 信息项，且当前许可证门正式拒绝 `hpke-rs* 0.7.0` 的 `MPL-2.0`。`mls-rs 0.56.0` D2 虽已通过固定图 Phase A，仍没有完整第三方安全审计；R1c-R 已确认固定 tree 对 `debug_tree` 与 `r-efi` 的声明许可证正文覆盖不足，目标分发义务和非实现者复核未关闭，不能直接进入场景验证。

## 当前优先级与暂停线

- 暂停 HaLow 硬件采购、射频发射、量产硬件和生产技术栈冻结；
- 2026-08-20 的 Docker A—B—C 结果登记为 `SW-EXP-001`，不是 `SW-V*` 或 P0 阶段验收；
- [项目执行计划](project-execution-plan.md)的 `PLAN-G0`、[D0/P0 软件工作计划](d0-t0-p0-plan.md)的 `SW-G0`、[覆盖层消息交付语义](../protocol/message-delivery-semantics.md)的 `SW-G1` 与[确定性故障设计](../testing/sw-g3-deterministic-validation-design.md)的 `SW-G3` 已接受；[`SW-G2` E2EE 决策包](../security/e2ee-sw-g2-decision-package.md)仍为 Draft；OpenMLS 0.8.1 Phase A 在许可证与 advisory 门 `STOP`，prepared run 的 Phase B 禁止执行；
- [`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)与[精确实施/Phase A 包](../testing/sw-g2-mls-rs-phase-a-authorization.md)已执行到单元 D2。run `20260901-135918-13430.mvBCS2` 的 94-package 图 source/audit/deny 为零、feature 为一，保留正式历史 `STOP/feature-gate`；A2 已依据保留 metadata/source 把后续 gate 改为固定 package/version、精确解析集合、alias 展开和 provider dependency edge 联合判定，只接受 core 的 `rfc_compliant -> x509` 与 `fast_serialize -> mls-rs-codec/preallocate` 既有展开，不接受顶层同名 feature 或 provider defaults。A3 固定只读 seed lock SHA-256 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`，拒绝 D `.work`、重新解析与旧 mutable cache。D2 run `20260902-130415-49997.8P5Td6` 对同一 94-package 图形成 schema 2/v2 正式 `PASS`：source/audit/deny/feature 全零，RustSec revision `5a0ebedfe8bdd2e295b171f4162f8c977bcad9a5` 下未发现 vulnerability 或 warning，32 项 checksum、运行控制和零容器残留已复核；仓库 lockfile 已提升且与 seed/evidence 摘要一致。工具许可证门通过不等于人工分发义务完成；11 个 package 的 archive 证据不足以覆盖全部声明正文及适用 copyright/NOTICE，非实现者 evidence 复核也未完成，Phase B 禁止。OpenMLS 的[Phase A 精确授权包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)记录历史单元与 2026-09-01 单元 E。仓库与 evidence lockfile SHA-256 均为 `850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49`；单元 E run `20260901-123158-75973.3gVtsH` 的 schema 4/v4 manifest、26 项 checksum、独立 audit 与零容器残留已复核，正式结论为许可证门 `STOP`。OpenMLS 0.9.0 的重跑、Phase B、allowlist/advisory ignore 变更、bundle 重建和 evidence 清理均未授权；
- [`SW-G4 / SW-V0` Harness](../testing/sw-g4-sw-v0-harness-authorization.md)实施与 Docker 运行已分别授权并完成；当前没有重跑、修改 schema/profile 或扩展 `SW-V1/V2/V3` 的持续授权，也不安装密码依赖；
- [低成本硬件验证计划](../hardware/hardware-validation-plan.md)当前停在 `HW-G0`；未通过 `HW-G2` 不采购，未通过 `HW-G3` 不刷写或启动实体台架；
- mls-rs [许可证/NOTICE 与非实现者复核包](../testing/sw-g2-mls-rs-license-notice-review.md)的 R0/helper 已固定 11 个 package、3 个 repository、6 个不可变 commit、受限网络来源、证据合同和独立复核清单。首次 R1/R1b 的 raw `TimeoutError` run 原样保留；R1c-I 已在 clean revision `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7` 实施 schema 2 blob identity 链，R1c-R run `20260903-124253-90340.y7_6lakz` 的 38 次请求全部成功并完成 11 行 mapping，但因 `debug_tree` 与 `r-efi` 的固定 tree 未覆盖全部声明正文形成有效 `STOP/license-evidence`。不得自动第四次运行、扩大 selector 或修改 evidence；R2 前置不满足。D2 重跑、Phase B、gate/版本/provider/依赖 source 变化仍须分别精确授权；`SW-V1/V2` 后续授权边界、硬件分层路线和已有硬件复用条件继续只读评审；
- 无射频软件计划不能替代首个测试地区的法规核对，二者可以并行研究但分别关门。

## 决策门状态

已通过：

1. `PLAN-G0`：接受产品阶段、`SW/HW/RF/EXP` 证据轨、依赖和停止线；
2. `SW-G0`：接受软件工作计划范围、探索性证据定位、工作顺序和暂停线；
3. `SW-G1`：接受消息身份、lifetime、hop budget、custody、delivery/read、去重、配额和崩溃恢复语义；
4. `SW-G3`：接受 profile schema、固定 seed、单变量故障矩阵、D0 数值、观察窗、证据和 `PASS/FAIL/INVALID` 判定。
5. `SW-G4/SW-V0`：授权清单内实现、无依赖单元门禁和 Docker harness 自检完成；四个 profile 各三次 canonical run 均通过且归一化一致。

## 今日推进（2026-09-03）

1. **R1 helper 已离线实施**：新增 Python 标准库 helper 与综合 checker，固定 11 package/3 repository/6 commit、R0/D2/三份 lock/retained archive 前置复核、匿名 HTTPS 动态 allowlist、40 请求/50 MiB 下载/100 MiB evidence/600 秒边界、无 retry 及 schema 1 finalizer；无参数和不匹配 revision 在 artifact/network 前拒绝。
2. **archive 事实已精确修正**：9 个目标 archive 没有 license-like 文件；`debug_tree` 的 `doc/build/LICENSE.adoc` 是 Asciidoctor 文档构建资产而非 package 许可证，`r-efi` 的 `AUTHORS` 含 MIT 正文及 Apache/LGPL 短告知但缺后二者完整正文。11 个 package 仍都需要 R1 上游补证，但不能再表述为“11 个 archive 完全没有同名文件”。
3. **离线 checker 通过**：D2 32 项 checksum、固定 manifest/lock/metadata、11 个 archive checksum/Cargo/vcs 与两个同名文件事实通过；synthetic fixture 覆盖正确 mapping、错误 commit、截断 tree、不安全 path、redirect/HTML/NUL/LFS/可执行文件与 checksum 篡改。没有联网、创建 R1 evidence、运行 Cargo/Docker、进入 Phase B、修改 D/D2 evidence、commit 或 push。
4. **R1 helper 已形成 clean revision**：用户另行授权后以 `feat(security): prepare mls-rs license evidence review` 提交为 `30a5665ee74d04e20d94c05280747ef8ec2b9df0`；提交后离线 preflight 对该 revision、D2/三份 lock、94-package metadata 和 11 个 archive 返回 `PASS`，未 push。
5. **首次 R1 单次授权已消费**：唯一命令在 `30a5665` 上创建 run `20260903-120514-82051.tt412fp1`，完成 5/40 次匿名请求并下载 `142464` bytes；前四次取得固定 commit、非截断 tree、根 manifest 与 Apache 正文，第五次读取同 commit `LICENSE-mit` 时发生无 HTTP status/body 的 `TimeoutError`。runner 按合同不重试，以 `STOP/license-evidence`、退出码 `20` 在 `34408 ms` 收口。
6. **首次 R1 是有效传输负向 evidence**：schema 1 manifest SHA-256 为 `9fc406d7411c491dfaec6c1c171441bee7fb17f39b81d621fe3df4c760173fc9`，9 项 checksum 清单 SHA-256 为 `e6722f2e374faae491f2c610ff1bf7220013107cf59bdcd053c2362e461848fe` 且逐项通过，final 普通文件共 `164108` bytes、后台进程为零。package mapping 为空，因此该结果不是许可证、NOTICE、候选淘汰或 `SW-G2` 结论。
7. **首次 R1 结果与 R1b 方案已形成 clean revision**：用户另行授权后以 `docs(security): record mls-rs license review stop` 提交为 `443ed446f37b34cc035fe288d4788b1776dd1da4`；该 revision 与 `30a5665` 之间只修改三份结果文档，helper/checker SHA-256 保持不变，未 push。
8. **R1b 单次 L3 授权已消费**：唯一命令在 `443ed446f37b34cc035fe288d4788b1776dd1da4` 上创建 run `20260903-121508-84631.nx_b_jte`；前两次请求取得与首次 R1 相同的固定 commit 和非截断 tree，第三次读取 raw `Cargo.toml` 时发生无 HTTP status/body 的 `TimeoutError`。runner 不重试，以 `STOP/license-evidence`、退出码 `20` 在 `35014 ms` 收口，共完成 3/40 次请求并下载 `131504` bytes。
9. **R1b 是第二份有效传输负向 evidence**：schema 1 manifest SHA-256 为 `b0ed5c9e1c523d39f1e98e4d92accc1983f2cf27045323697221c5f66788f530`，7 项 checksum 清单 SHA-256 为 `465e3b7eb937397fa93c52c0451eba25780c39541484e5f6465a4117ca23c523` 且逐项通过，final 普通文件共 8 个、`150028` bytes、后台进程为零。首次 R1 已成功取得同一 raw `Cargo.toml`，两次失败点不同且 mapping 均为空，因此结论仍限于 raw 传输不稳定，不能形成许可证、NOTICE、候选淘汰或 `SW-G2` 结论。
10. **R1c 替代传输设计已冻结**：仍从同一官方 repository、六个 commit、验证后的非截断 tree 与既有 path selector 定位文件，只把文件正文请求从 raw URL 改为由 tree entry blob SHA 派生的 Git Blobs API，并增加 envelope、base64、decoded size、Git blob SHA-1 与文本校验；旧 run 原样保留，新 run 使用 schema 2，checker 同时兼容历史 schema 1。
11. **R1c-I 已离线实施并形成 clean revision**：只修改 helper/checker，以 `feat(security): use Git blobs for license evidence` 提交为 `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7`；helper/checker SHA-256 分别为 `e9e3c68c566993fda09a4822023537c3a3d4310719a1aa68ef64a3359f03b40b` 与 `78cd343d89db1c1d5303cc7a085de93d0ba176ee59387d55f9598c7a56bc5092`。离线 self-test、综合 checker、仓库门禁和差异检查均通过，未 push。
12. **R1c-R 单次 L3 授权已消费**：唯一命令在 `f9f02b3` 上创建 run `20260903-124253-90340.y7_6lakz`，从头完成 6 个 commit、11 个 package mapping 和 38/40 次匿名 GitHub API 请求；所有请求成功，下载 `676608` bytes，运行 `23526 ms`，未重试且后台进程为零。
13. **schema 2 identity/checksum 链完整**：tree entry mode/type/SHA/size/URL、blob envelope `.sha`/base64/size、Git blob SHA-1、decoded SHA-256 和 evidence checksum 全部通过。manifest SHA-256 为 `f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203`，69 项 checksum 清单 SHA-256 为 `ea356f519af8a3a1bb7c4a0859bc8f862d27673b4fcd602de5a1fe5b271c7db4`；final 共 70 个普通文件、`968673` bytes。
14. **R1c-R 形成实质证据缺口 `STOP`**：9 个 `awslabs/mls-rs` package 覆盖 Apache-2.0/MIT 正文；`debug_tree 0.4.0` 的固定 tree 未检测到声明的 MIT 正文，`r-efi 6.0.0` 只检测到 MIT，缺完整 Apache-2.0 与 LGPL-2.1-or-later 正文，六个 commit 均无 NOTICE。该结果排除了本次传输失败，但不证明其他来源不存在许可证、不判定违法且不自动淘汰候选。
15. **R2 与 Phase B 继续阻断**：R1c-R 为有效 `STOP/license-evidence` 而非 `PASS`，不满足 R2 前置；不得自动第四次运行、扩大 selector、改变版本/source、补写 evidence 或进入 Phase B。

## 上一批次（2026-09-02）

1. **mls-rs A2 包限定 gate 已离线实施**：旧 gate 按 feature 名称扫描全部 `mls-rs*` package，混淆了顶层聚合 feature 与 core alias；新 gate 固定六个关键 package/version、各自解析集合、core/codec/X.509 alias 和 provider normal dependency edge。
2. **安全边界未放宽为名称 allowlist**：仅接受 `mls-rs-core 0.27.0/rfc_compliant -> x509` 与 `fast_serialize -> mls-rs-codec/preallocate` 的既有展开；顶层 `mls-rs` 同名 feature、AWS-LC/SQLite provider defaults、FIPS、post-quantum、SQLCipher、FFI、第二 provider 与非 crates.io source 仍拒绝。
3. **离线门禁通过**：两个 shell 语法检查、综合 checker、D 保留 metadata 的只读 gate 回归、仓库门禁与 `git diff --check` 均通过；历史 evidence 未修改。
4. **A2 授权边界保持**：A2 实施时没有调用 Docker、Cargo 或网络，没有生成/提升 lockfile、重跑 D、进入 Phase B、清理 evidence、commit 或 push。D 的正式历史 `STOP` 不变；D2 设计随后才单独形成。
5. **A2 已形成 clean revision**：用户另行明确授权后，以 `fix(security): qualify mls-rs feature gate` 提交为 `26bb86d`；提交前门禁通过，未 push。
6. **D2 固定图路径已形成 clean revision**：Proposed 方案以 `docs(security): define mls-rs fixed graph rerun` 提交为 `cd5d846`；只读消费 D final `Cargo.lock`，固定 SHA-256 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7` 与 94-package 图；拒绝重新解析和复用 D `.work`，新 run 只用全新 Cargo home/target 重新获取 locked crates 与当前 RustSec DB。A3 已实现 seed 验证、locked consumer、schema 2/v2 与离线负例并形成 clean revision；方案形成时 D2 尚未授权，后续执行事实见第 10–15 项。
7. **A3 固定图消费合同已离线实施**：runner 在 bundle/artifact/Docker/网络前验证 D final 五项文件与历史字段，仓库 lockfile 必须不存在；隔离副本只复制 seed lock，删除 `cargo generate-lockfile`，仅保留 `cargo fetch --locked`，并复核固定 lock 摘要与 94-package 数。
8. **schema 与负例已升级**：未来 D2 manifest 使用 schema 2 / `sw-g2-candidate-phase-a-v2`，记录 `dependency_graph_seed`、`lockfile_seeded` 和 `mutable_cache_reused: false`；checker 覆盖缺失、symlink、五项篡改、历史 gate 漂移、schema 1 假通过、重新解析/旧 mutable cache 禁止线，并对 D metadata 返回 package-qualified feature gate 零。
9. **A3 边界保持**：没有调用 Docker、Cargo 或网络，没有创建 D2 artifact、生成仓库 lockfile、修改历史 evidence、重跑 Phase A、进入 Phase B、commit 或 push。设计文档中的 gate JSON 摘要已按现场文件与历史 checksum 更正为 `64526a2beb6feff1ec70eef81d9eb03e7d26013b96f39b4111d2960b210c45d3`。
10. **D2 单次 L3 授权已消费**：在 clean revision `64cf079a7b14a3ce90be92b93e56e2ad80555d80` 上执行唯一 `prepare` 命令，run `20260902-130415-49997.8P5Td6` 正常退出 `0`；没有重试或进入 Phase B。
11. **固定图 Phase A 正式 `PASS`**：schema 2 / `sw-g2-candidate-phase-a-v2` 证明 D final seed 合同、lock 摘要与 94-package 数未漂移，`lockfile_seeded: true`、`lockfile_written: true`、`mutable_cache_reused: false`；source/audit/deny/feature 全零。
12. **advisory、证据与运行控制闭合**：`cargo-audit 0.22.2` 在 RustSec revision `5a0ebedfe8bdd2e295b171f4162f8c977bcad9a5` 的 1239 条 advisory 中未发现 vulnerability 或 warning；`cargo-deny` 三类检查均为 `ok`。manifest SHA-256 为 `b42b4bd34142e71f44c020ec3c84ab0c329b2865b0e822efbf0adb53f0440a5f`，32 项 checksum 已独立复核；monitor 记录 `40525 ms`、峰值 `229278 KiB`，精确容器残留为零。
13. **固定 lockfile 已提升**：`tools/spikes/sw-g2-mls-rs/Cargo.lock` 与 seed/evidence 逐字一致，SHA-256 为 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`；本轮约 `254556 KiB` evidence/`.work`/cache 与既有 fixed image、bundle 保留。
14. **人工许可证/NOTICE 门仍未关闭**：93 个 crates.io package 均有非空 license metadata，工具许可证门通过；但 11 个 package 的 archive 证据不足以覆盖全部声明正文、适用 copyright/NOTICE 与目标分发义务。它们不是据此判定“无许可证”；非实现者 evidence 复核也未完成。两个 archive 内同名文件的精确范围在 2026-09-03 离线 helper 实施时进一步修正。
15. **D2 边界保持**：没有编译或运行候选、生成密钥/数据库、修改历史 evidence、清理、commit 或 push。D 的历史 `STOP` 不被改写，D2 `PASS` 不等于候选采用、完整安全审计、`SW-G2` 通过或 Phase B 授权。
16. **许可证/NOTICE R0 已离线形成**：从固定 lock、D2 metadata 与保留 `.cargo_vcs_info.json` 固定 11 个随包证据不足 package 的 registry checksum、Cargo license、repository、commit 与 `path_in_vcs`；它们收敛为 `martypapa/debug-tree`、`awslabs/mls-rs`、`r-efi/r-efi` 三个仓库和六个不可变 commit。
17. **R1 网络与证据合同已冻结**：只允许匿名 HTTPS 访问六个固定 GitHub commit API、其验证后的非截断 tree 和同 commit raw manifest/license/NOTICE 类文本；禁止 token、cookie、浮动 branch/tag、crates.io、Git/Cargo/Docker。新 evidence 使用 schema 1 / `sw-g2-mls-rs-license-review-v1`，10 分钟/100 MiB、失败不重试并保留真实结果。
18. **R2 独立性与复核清单已冻结**：复核者必须未参与 A2/A3、D2 实施/执行和本轮结果撰写；须独立复核 D2 manifest/checksum/lock/gates/runtime/零残留及 R1 provenance/license/NOTICE mapping。当前执行者不能自我关闭该门禁。
19. **R0 边界保持**：没有联网、创建 R1 evidence、修改 D/D2 evidence、运行 Cargo/Docker、进入 Phase B、commit 或 push。R1/R2 均未授权，`SW-G2` 继续未通过。

## 上一批次（2026-09-01）

1. **单元 D 授权已消费**：唯一命令使用固定 bundle `20260830-112214-39636.GpERrj` 执行一次；run `20260901-120714-65631.D9JlZx` 退出 `20`，未自动重试、进入 Phase B、commit、push 或清理。
2. **依赖图与 lockfile 已形成**：Cargo 生成 264-package 图并原子新增 `tools/spikes/sw-g2-openmls-0.9/Cargo.lock`；仓库与 evidence lock SHA-256 均为 `850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49`，source/feature gate 返回零。
3. **许可证 partial 负向结果已保留**：`cargo-deny` 的 sources/advisories 正常，许可证门拒绝 `hpke-rs`、`hpke-rs-crypto`、`hpke-rs-rust-crypto` 0.7.0 的 `MPL-2.0`；不放宽 allowlist，也不据此选择候选。
4. **独立 audit 未执行**：固定 `cargo-audit 0.22.2` 需要 `audit` 子命令，runner 的直接 `cargo-audit --json` 被 Cargo CLI 拒绝，audit 退出 `2` 且报告为空；不得形成完整 advisory 结论。
5. **Phase A finalizer 使 run 无效**：内联 jq 的 `read-only` 引号被 shell 剥离，manifest 为 0 字节；后续 `mv` 遮蔽 renderer 失败并生成空 manifest checksum。正式 evidence contract 不完整，单元 D 整体登记为 `INVALID`。
6. **运行与清理事实闭合**：monitor 在 `36323 ms` 正常停止，记录峰值 `192079 KiB`；25 项 checksum 从仓库根复核匹配，精确 Docker label 残留为零。约 218 MiB 本轮 evidence/cache、fixed image 与成功 bundle 默认保留。
7. **A6 离线修复已实施**：调用改为 `cargo-audit audit --json`；新增独立 Phase A manifest filter 与 self-test，单元 E 证据使用 schema 4 / `sw-exp-004-phase-a-v4`，记录 filter 摘要与固定 audit invocation。
8. **证据终结重新收紧**：renderer 失败、空/无效 manifest、既有 final/tmp 路径和 checksum 自校验失败均传播非零；只有非空有效 manifest 原子完成、checksum 自校验且 264-package/四门/运行控制/零残留 `PASS` contract 全部复核后才打印唯一 `PASS`，失败 fallback 不留下可误认的 final evidence。
9. **离线精准验证通过**：两个 shell 语法检查与 `./scripts/check-sw-g2-openmls-0.9-phase-a.sh` 通过，覆盖固定 invocation、唯一 post-finalization `PASS`、schema 4/v4 渲染、`read-only` 字符串、filter 摘要和 renderer/空/无效 JSON 拒绝；没有调用 Docker、Cargo 或网络，也未修改历史 evidence。
10. **A6 已形成 clean revision**：`ac01b4d` 提交 runner、schema 4/v4 filter、offline self-test、固定仓库 lockfile 与单元 D 结果文档；提交前门禁通过，未 push。
11. **单元 E 授权已消费**：在 clean revision `ac01b4d` 上只读消费同一固定 bundle，唯一 run `20260901-123158-75973.3gVtsH` 退出 `20`；全新 Cargo home/target 重新生成的 264-package lockfile 与仓库版本逐字一致，source/audit/feature 为 `0`、deny 为 `4`。
12. **独立 advisory 结果已取得**：`cargo-audit 0.22.2` 以固定 `audit --json` 调用成功执行，基于 RustSec revision `72f8b23d78ea6c4c9ded301a4c6ec4260e8b4c27` 未发现 vulnerability；同时报告 `proc-macro-error2 2.0.1` 的 `RUSTSEC-2026-0173` unmaintained 信息项。该零漏洞结果只覆盖本轮固定图与数据库 revision，不构成安全审计或候选通过。
13. **许可证门形成正式 `STOP`**：`cargo-deny` 的 sources/advisories 为 `ok`，当前 allowlist 正式拒绝 `hpke-rs`、`hpke-rs-crypto`、`hpke-rs-rust-crypto` 0.7.0 的 `MPL-2.0`。不放宽 allowlist、不添加 ignore、不自动更换 provider 或版本，OpenMLS 0.9.0 禁止进入 Phase B。
14. **单元 E 证据闭合**：非空 schema 4 / `sw-exp-004-phase-a-v4` manifest、26 项 checksum、固定输入/工具摘要、`35452 ms` 运行控制和 `268724 KiB` 峰值均复核通过；工作区前后干净，精确 Docker label 残留为零。约 262 MiB evidence/cache、fixed image 与 bundle 保留，未重试、commit、push 或清理。
15. **单元 E 文档已形成 clean revision**：`dfc5e34` 同步正式 `STOP`、audit/unmaintained 边界、Phase B 停止线与 mls-rs 就绪差异；提交前仓库门禁通过，未 push。
16. **mls-rs 精确包已接受**：冻结候选无关 `sw-g2-rust-audit-tools-v1` 与 `sw-g2-candidate-phase-a-v1` 合同设计，拆分离线 A0/A1 与 L3 C/D；明确不修改 OpenMLS 历史脚本、不直接消费其候选资源、不运行 placeholder bundle ID，也不由接受文档推导相邻授权。
17. **共享运行资源 A0 已离线实施并提交**：新增候选无关运行 monitor、固定 audit bundle builder、schema 1 manifest filter 与综合 checker；deadline/disk/父进程信号、参数提前拒绝、renderer/JSON/final/tmp 负例、checksum 篡改和唯一 post-finalization `PASS` 均通过。OpenMLS 四个历史脚本摘要保持不变；没有执行 `prepare`、创建 bundle/artifact、查询 Docker、调用 Cargo/网络或 push。
18. **mls-rs Phase A 骨架 A1 已离线实施并提交**：新增七个固定依赖、无例外 deny 门、始终拒绝 Phase B 的 Rust 入口、只允许精确 bundle ID 的受限 runner、schema 1 renderer 与 checker；精确 TOML/feature/source、`fips`、第二 crypto provider、git source、参数/selector、容器/finalizer 合同均通过。没有生成 `Cargo.lock`、执行 `prepare`、创建 candidate artifact、调用 Docker/Cargo/网络、编译/运行候选或 push；提交动作另获明确授权，A1 已形成 clean revision。
19. **L3 通用审计工具 bundle 单元 C 已 `PASS` 并记录**：clean revision `c6e3a43a530f4af18cef9ab26a925a241649a16f` 的唯一 run `20260901-134500-6665.ARcd4F` 构建并无网络验证 `cargo-audit 0.22.2` / `cargo-deny 0.20.2`；schema 1 合同、11 项 checksum、两个 `0555` 二进制与固定镜像身份均复核通过。运行 `206562 ms`、峰值 `1358459 KiB`，工作区前后干净且精确 label 残留为零；约 `1337960 KiB` evidence/cache 与 fixed image 保留。没有重试、下载候选、生成候选 lockfile、执行 D/Phase B、push 或清理；结果文档另获提交授权并形成 clean revision。
20. **mls-rs Phase A 单元 D 正式 `STOP` 并记录**：clean revision `36765755154dc88f8bd21605cbc25f5abf6bb828` 的唯一 run `20260901-135918-13430.mvBCS2` 解析 94-package 图；source/audit/deny 为 `0`、feature 为 `1`。顶层 feature 与唯一 provider 均匹配，但两个 provider 的 `mls-rs-core 0.27.0` 默认依赖启用被 gate 禁止的 `fast_serialize` / `rfc_compliant`，退出 `24` 且未提升仓库 lockfile。RustSec revision `72f8b23d78ea6c4c9ded301a4c6ec4260e8b4c27` 未发现 vulnerability；25 项 checksum、`55761 ms`、峰值 `228844 KiB`、工作区前后干净和零容器残留均复核。约 `254512 KiB` evidence/cache 保留；没有重试、编译/运行候选、进入 Phase B、push 或清理，结果文档另获 commit 授权并形成 clean revision。

## 更早批次（2026-08-30）

1. **运行控制单元 A2 已提交**：`af14ef9` 新增 Python 标准库 monitor 并接入 OpenMLS 0.9 runner；固定 45 分钟用户态 deadline、5 GiB 每 5 秒 apparent-size 监测、受控子进程终止和退出复核。当时的 Phase A manifest 为 schema 2；monitor 的独立 runtime-control JSON 为 schema 1，A4 后当前 Phase A manifest 已升级为 schema 3。
2. **离线门禁已通过**：deadline、磁盘越界、信号收口、shell 语法、参数拒绝、manifest 渲染、仓库基线和 diff 检查均通过。
3. **受限环境前置尝试已停止**：`20260830-085136-79099.fY2Gf7` 在 Docker/Cargo/网络前因 `/dev/fd` process substitution 被环境拒绝，以 `STOP/preflight` 结束；该尝试不是候选证据。
4. **获批准的 Phase A 已在依赖解析门停止**：clean revision `af14ef9` 的 `20260830-085316-79789.Pc2ZKb` 验证固定 ARM64 image 与 Rust/Cargo 1.96.1 后，Cargo 因两套不兼容 `libsqlite3-sys` 的 `links = "sqlite3"` 冲突退出 `101`；未生成 lockfile，未进入来源、许可证/advisory 或 feature 门。
5. **证据与清理已闭合**：有效运行 checksum 全部通过，monitor 在 `15029 ms` 正常停止，目录峰值 `4428 KiB`，容器残留为 `0`；两份 ignored evidence 与原有 fixed image 保留，未 push、未进入 Phase B。
6. **A3 静态修订已完成**：实际 sparse index metadata 证明 storage backend 要求 `rusqlite ^0.37 + bundled`；直接依赖已精确对齐为 `=0.37.0`，runner manifest 与专题口径同步。没有调用 Docker、Cargo 或网络，没有生成 lockfile。
7. **A3 后 Phase A 已按 deadline 停止**：clean revision `851f3bb` 的 `20260830-091344-87309.iyw1Dm` 已生成 264-package partial graph；evidence lock SHA-256 为 `850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49`，只有 `rusqlite 0.37.0` / `libsqlite3-sys 0.35.0`，确认 A3 关闭原解析冲突。
8. **正式审计门尚未开始**：`cargo-audit 0.22.2` 安装期间 crates.io 多次出现传输 EOF；monitor 在 `2704774 ms` 触发 deadline，最终 `STOP/runtime-deadline`、退出 `124`。source、audit、deny、feature 均无退出码，仓库 `Cargo.lock` 未写入，不得形成许可证/advisory 结论。
9. **证据与清理已闭合**：最新 run checksum 全部通过，目录峰值 `337380 KiB`，容器残留为 `0`；三份 `SW-EXP-004` ignored evidence 与 fixed image 保留，工作区干净，未自动重试、未进入 Phase B、未 push。
10. **deadline 后停止线已遵守**：在 A4 形成前没有直接复用未校验 `.work`、放宽工具版本、跳过审计门、延长 Phase A deadline 或重跑；`SW-G2` 仍未通过。
11. **A4 运行资源修订已实施**：新增独立 fixed-image 审计工具 bundle builder，冻结 `sw-exp-004-audit-tools-v1` manifest/checksum 合同、90 分钟与 5 GiB 构建上限和无网络运行验证；Phase A 改为显式精确 bundle ID、在 artifact/Docker 前验证并只读挂载两个固定二进制，不再安装工具或消费 bundle `.work`。
12. **partial evidence 收口已修正并离线验证**：deadline/signal cleanup 只从已经落盘的 Cargo.lock、metadata、advisory DB 和退出码回填 manifest，不补跑或伪造 feature/source/license/advisory 门，也不提升仓库 lockfile。语法、六个参数/bundle 负例、monitor 自检、既有 evidence 的 264-package/lock SHA 回填探针、仓库基线与 diff 检查通过；没有构建 bundle、调用 Docker/Cargo/网络、重跑 Phase A 或 push。
13. **首次 L3 bundle run 无效**：clean revision `39641eb` 的 `20260830-103454-21213.oL36gJ` 已在固定 Linux ARM64 image 中构建并无网络验证 `cargo-audit 0.22.2` / `cargo-deny 0.20.2`；运行 `1472554 ms`，目录峰值 `1358445 KiB`，工作区前后干净且容器残留为零。但 jq shell quoting 使 manifest finalizer 失败并留下 0 字节 `manifest.json`，旧脚本错误打印 `PASS`、生成空 manifest checksum 且返回 `0`；Phase A consumer 以退出码 `2` 拒绝该 ID。整个 run 登记为 `INVALID`，原样保留且不得消费，不自动重试或进入 Phase A。
14. **A5 evidence finalizer 已离线修正**：jq contract 移入独立固定 filter 并记录摘要；因新增 consumer 必需字段，未来成功合同升级为 schema 2 / `sw-exp-004-audit-tools-v2`，不兼容的无效 v1 不得消费。manifest/checksum 只有在非空有效 JSON、核心字段和精确摘要复核后才可原子完成，失败传播为非零并不得提前打印 `PASS`。新增无 Docker `self-test` 覆盖正向渲染、renderer 失败、空/无效 manifest 拒绝；既有无效 run 前后文件大小与 mtime 一致。语法、filter 渲染、自检、仓库基线和 diff 检查通过；没有调用 Docker/Cargo/网络、重跑 bundle、修改历史 artifact 或 push。
15. **A5 后固定审计工具 bundle 已 `PASS`**：clean revision `cf340d3` 的 C2 run `20260830-112214-39636.GpERrj` 在同一获授权命令内经历可恢复的 crates.io TLS/DNS/timeout 告警后完成 `cargo-audit 0.22.2` / `cargo-deny 0.20.2` 构建与无网络版本验证。schema 2/v2 manifest、11 项 checksum、两个 `0555` 二进制/摘要、三个固定输入摘要均独立复核通过；monitor 以 `completed` 在 `1844010 ms` 停止，峰值 `1366495 KiB`，工作区前后干净且精确容器残留为零。该结果不构成候选 Phase A 结论；没有自动重试、运行 Phase A/Phase B、commit 或 push。
16. **今日代码—文档收口复核完成**：逐项审阅 `af14ef9`、`29fce44`、`851f3bb`、`8f9c2af`、`39641eb`、`cf340d3` 与 `c1810cf`，并以当前 monitor、runner、bundle builder、manifest filter 和 `Cargo.toml` 为准复核相关文档。45/90 分钟监测、5 GiB 周期预算、schema 3 Phase A、v2 bundle/11 项 checksum、精确只读消费、source/feature lockfile 提升门、默认出站网络无域名 allowlist、精确残留清理和 Phase B 硬阻断均一致；本次只修正文档中的历史时态、前置顺序与容器资源拆分，不修改代码或历史 evidence。

## 更早批次（2026-08-28）

1. **`SW-EXP-002` 静态收口已提交**：`7da9140` 收口脚本、隔离副本、lockfile 漂移、manifest schema 2 与 checksum；未运行 Docker/Phase A/Phase B。
2. **`SW-G3` 已接受**：`a5f5598` 形成 profile schema、固定 seed、单变量矩阵、D0 数值、证据 manifest 和 `PASS/FAIL/INVALID`，`eaf7ea6` 完成接受状态与下一门禁同步；不构成未列明实现或运行的持续授权。
3. **两个新候选门禁已接受但未执行**：`eaf7ea6` 形成 `mls-rs 0.56.0` 与 OpenMLS 0.9.0 静态门，`2436b9f` 接受 OpenMLS 0.9.0 静态门；`SW-EXP-004` 冻结 MSRV、JSON storage、0.8.1 迁移、`hpke-rs 0.7` feature 解析图，以及 crypto provider/storage 不继承主 crate 安全公告结论的停止线。
4. **`SW-G4/SW-V0` 已完成**：`67556fe` 实现四个 canonical profile、注入时钟、synthetic proxy、evidence finalizer 与正式入口；`7a4344b`、`674707a` 修复非 root 镜像权限，旧探索性状态机与 `go.mod` 未修改。
5. **Docker canonical run 已通过并归档**：两次权限前置失败分别保留为 `INVALID`；clean revision `674707a` 的 `sw-v0-20260828T131927Z-49781` 四个 profile 各三次均为 `PASS`，12 份 checksum 复核通过，退出码与残留均为零；`ab3a2fb` 同步正式结果与结论边界。
6. **保持暂停线**：今天未安装或构建密码依赖，除获授权的 `SW-V0` 外未重跑其他容器或三节点场景；不采购/刷写硬件、不发射射频，`SW-V0 PASS` 不升级为产品或 P0 能力。
7. **保留历史证据**：约 1.5 GiB `SW-EXP-002` ignored cache、三份本轮 `SW-V0` artifact 与其他历史 artifact 默认保留；未获单独清理授权不删除。
8. **`SW-EXP-004` 单元 A 已完成**：`8e5bd7b` 形成精确授权包，`bc9a6ff` 新增固定 `Cargo.toml`、`deny.toml`、拒绝 Phase B 的 `main.rs` 与受限 runner，`05c7337` 同步专题状态；首次 executable mode 负例以 `126` 暴露并修正，最终无参数/`run` 均以 `2` 拒绝，未创建 artifact、运行 Docker/Cargo 或联网。L3 单元 B 未授权。
9. **完成 11 个既有提交的代码—文档复核**：`SW-V0` 的 profile、seed、权限修复、证据口径与相关文档一致；`SW-EXP-004` 的依赖、镜像、容器权限、证据和清理边界与精确包一致。当时发现 45 分钟与 5 GiB 只有人工停止线且 runner 没有内建运行监控；该历史缺口已由 2026-08-30 的 A2 关闭为用户态周期监测。默认出站网络仍不实施域名 allowlist，已作为单元 D 的显式 L3 边界保留。

## 下一步事项

1. **收口 R1c 结果记录**：把 R1c-I revision/helper/checker SHA、schema 2 identity/checksum 链、11 行 mapping 与有效 `STOP` 边界形成 clean revision；不提交、修改或清理 ignored evidence。
2. **另行设计 R1d-P 固定 tree 缺口处置**：只形成文档，分别评估不可变官方补充来源、上游澄清/修复、目标分发包携带适用正文及独立法律评审边界；不联网、不联系上游、不修改 evidence、selector、版本、依赖 source、gate 或分发产物，也不预设候选淘汰。
3. **禁止自动第四次运行**：任何额外取证、上游联系、依赖/分发修改或候选切换必须另行精确授权，不能以扩大 selector 或补写 evidence 制造 R1 `PASS`。
4. **完整 R1 后才能安排非实现者 R2**：只有后续工程证据达到有效完整 `PASS` 后，才由项目所有者指定符合独立性条件的评审者，只读复核 D2 与全部 R1/R1b/R1c run；当前执行者不能代替。
5. **继续阻断 Phase B**：D2 已对固定图形成 Phase A `PASS`，但完整 R1/R2 未完成，不存在 Phase B 设计、实现或执行授权；`SW-G2` 继续未通过。
6. **并行保留低风险规划**：继续评审 `SW-V1/V2` 授权边界、硬件分层路线和已有硬件复用条件；不重跑容器、不采购/刷写硬件、不产生射频发射。

## 尚未冻结

- 量产无线芯片、模块、天线、频段和目标销售地区；
- 802.11s、EasyMesh、其他 L2 Mesh 或 L3 路由的最终选择；
- 消息与群组密钥协议的具体密码套件和实现库；
- 实时媒体使用 WebRTC、定制 RTP/QUIC 或其他传输；
- 最终应用处理器、操作系统发行版、UI 框架和升级系统；
- 定位能力、GNSS/UWB 配置和“寻找设备”产品范围；
- 发布渠道和兼容性承诺。

## 当前验证入口

默认仓库门禁：

```bash
./scripts/check-repo.sh
```

探索性探针入口（非默认，不代表当前已授权重跑）：

```bash
./scripts/run-t0-three-node.sh
```

`SW-V0` 正式入口（已完成的授权不代表当前可重跑）：

```bash
./scripts/run-sw-v0-harness.sh run
```

探索性入口只产生 Docker/Ethernet 探针证据，使用未加密合成载荷；脚本打印的 `T0 PASS` 是历史内部输出。`SW-V0` 入口只验证 topology、fault hit、clock 与 evidence harness。两者都不构成 P0、HaLow、E2EE、距离、媒体、功耗或法规验证。

仓库治理与远程状态边界见[仓库治理](../governance/repository-governance.md)。
