# RadishLink 当前状态

更新日期：2026-08-30

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
- `PLAN-G0`、`SW-G0` 与 `SW-G1` 已于 2026-08-24 接受，`SW-G3` 与 `SW-G4/SW-V0` 已于 2026-08-28 接受并完成；`mls-rs 0.56.0` 静态门已接受但未执行；OpenMLS 0.9.0 A3 后依赖图可解析。首次固定审计工具构建因 evidence finalizer 失败而无效，A5 修正后 C2 已生成并复核成功 bundle `20260830-112214-39636.GpERrj`；精确 Phase A 授权包已形成但尚未执行，仍无正式来源、许可证/advisory 或 feature 结论，`SW-G2` 未通过；`SW-V0 PASS` 只接受 harness 有效，不代表 E2EE 路线、产品软件实现、P0 或其他证据轨通过。

## 关键风险

1. **区域法规风险**：MM8108 当前模块覆盖 850–950 MHz，HaLowLink 2 公布的支持地区不含中国大陆；不能把其他地区的免许可条件直接带入国内测试。
2. **Mesh 成熟度风险**：Morse Micro 当前将 HaLowLink 的 802.11s 标记为实验性功能，并提示多跳吞吐代价和区域限制。
3. **性能风险**：43.33 Mbps 是 8 MHz、最高调制下的 PHY 峰值，不代表 500 m、多跳、加密后的应用吞吐。
4. **功耗与体积风险**：Raspberry Pi 评估平台适合证明功能，不代表可以达到随身产品的续航和体积。
5. **媒体复杂度风险**：实时语音、视频、路由切换、拥塞控制和端到端加密必须联合验证，单独跑通 `iperf3` 不等于产品可用。
6. **设计漂移风险**：`SW-EXP-001` 探针早于已接受的消息语义、故障模型和证据格式；后续实现若直接继承探针 JSON、摘要 ACK 或 snapshot，会偏离 `SW-G1` 并把测试技术栈误当成产品协议。
7. **低成本硬件捷径风险**：直接用三块 MCU 重写 Core 会偏离嵌入式 Linux 基线，也无法覆盖目标媒体、持久化和升级边界；MCU 只进入交互与低功耗辅助域。
8. **E2EE 候选依赖风险**：`OpenMLS 0.8.1 + openmls_rust_crypto 0.5.1` 固定图已命中活跃 RustSec advisory，其中包含 AArch64 constant-time 错误；`hpke-rs* 0.6.1` 的 `MPL-2.0` 也未通过初始许可证门。OpenMLS 0.9.0 虽已稳定发布，但新传递图尚未审计；`mls-rs 0.56.0` 也没有完整第三方安全审计，二者均不能直接进入场景验证。

## 当前优先级与暂停线

- 暂停 HaLow 硬件采购、射频发射、量产硬件和生产技术栈冻结；
- 2026-08-20 的 Docker A—B—C 结果登记为 `SW-EXP-001`，不是 `SW-V*` 或 P0 阶段验收；
- [项目执行计划](project-execution-plan.md)的 `PLAN-G0`、[D0/P0 软件工作计划](d0-t0-p0-plan.md)的 `SW-G0`、[覆盖层消息交付语义](../protocol/message-delivery-semantics.md)的 `SW-G1` 与[确定性故障设计](../testing/sw-g3-deterministic-validation-design.md)的 `SW-G3` 已接受；[`SW-G2` E2EE 决策包](../security/e2ee-sw-g2-decision-package.md)仍为 Draft；OpenMLS 0.8.1 Phase A 在许可证与 advisory 门 `STOP`，prepared run 的 Phase B 禁止执行；
- [`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)已接受但未执行；OpenMLS 的[Phase A 精确授权包](../testing/sw-g2-openmls-0.9-phase-a-authorization.md)记录了历史 Phase A 执行与当前单元 D。A3 已关闭原 SQLite 解析冲突，最新历史 Phase A evidence 包含 264-package partial graph、唯一 `rusqlite 0.37.0` / `libsqlite3-sys 0.35.0` 和 evidence-only lockfile；但当时 `cargo-audit` 安装未在 45 分钟内完成，source、audit、deny、feature 门均无结果。A4/A5 将固定工具构建拆为独立 L3 单元并收紧 evidence finalizer；C2 成功 bundle 已复核。新的 Phase A 只允许以该精确 bundle ID 另行授权一次，当前未执行，Phase B 禁止；
- [`SW-G4 / SW-V0` Harness](../testing/sw-g4-sw-v0-harness-authorization.md)实施与 Docker 运行已分别授权并完成；当前没有重跑、修改 schema/profile 或扩展 `SW-V1/V2/V3` 的持续授权，也不安装密码依赖；
- [低成本硬件验证计划](../hardware/hardware-validation-plan.md)当前停在 `HW-G0`；未通过 `HW-G2` 不采购，未通过 `HW-G3` 不刷写或启动实体台架；
- 下一步只评审 E2EE/身份候选、`SW-V1/V2` 后续授权边界、硬件分层路线和已有硬件复用条件；获相应明确确认后才实施；
- 无射频软件计划不能替代首个测试地区的法规核对，二者可以并行研究但分别关门。

## 决策门状态

已通过：

1. `PLAN-G0`：接受产品阶段、`SW/HW/RF/EXP` 证据轨、依赖和停止线；
2. `SW-G0`：接受软件工作计划范围、探索性证据定位、工作顺序和暂停线；
3. `SW-G1`：接受消息身份、lifetime、hop budget、custody、delivery/read、去重、配额和崩溃恢复语义；
4. `SW-G3`：接受 profile schema、固定 seed、单变量故障矩阵、D0 数值、观察窗、证据和 `PASS/FAIL/INVALID` 判定。
5. `SW-G4/SW-V0`：授权清单内实现、无依赖单元门禁和 Docker harness 自检完成；四个 profile 各三次 canonical run 均通过且归一化一致。

## 今日推进（2026-08-30）

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

## 上一批次（2026-08-28）

1. **`SW-EXP-002` 静态收口已提交**：`7da9140` 收口脚本、隔离副本、lockfile 漂移、manifest schema 2 与 checksum；未运行 Docker/Phase A/Phase B。
2. **`SW-G3` 已接受**：`a5f5598` 形成 profile schema、固定 seed、单变量矩阵、D0 数值、证据 manifest 和 `PASS/FAIL/INVALID`，`eaf7ea6` 完成接受状态与下一门禁同步；不构成未列明实现或运行的持续授权。
3. **两个新候选门禁已接受但未执行**：`eaf7ea6` 形成 `mls-rs 0.56.0` 与 OpenMLS 0.9.0 静态门，`2436b9f` 接受 OpenMLS 0.9.0 静态门；`SW-EXP-004` 冻结 MSRV、JSON storage、0.8.1 迁移、`hpke-rs 0.7` feature 解析图，以及 crypto provider/storage 不继承主 crate 安全公告结论的停止线。
4. **`SW-G4/SW-V0` 已完成**：`67556fe` 实现四个 canonical profile、注入时钟、synthetic proxy、evidence finalizer 与正式入口；`7a4344b`、`674707a` 修复非 root 镜像权限，旧探索性状态机与 `go.mod` 未修改。
5. **Docker canonical run 已通过并归档**：两次权限前置失败分别保留为 `INVALID`；clean revision `674707a` 的 `sw-v0-20260828T131927Z-49781` 四个 profile 各三次均为 `PASS`，12 份 checksum 复核通过，退出码与残留均为零；`ab3a2fb` 同步正式结果与结论边界。
6. **保持暂停线**：今天未安装或构建密码依赖，除获授权的 `SW-V0` 外未重跑其他容器或三节点场景；不采购/刷写硬件、不发射射频，`SW-V0 PASS` 不升级为产品或 P0 能力。
7. **保留历史证据**：约 1.5 GiB `SW-EXP-002` ignored cache、三份本轮 `SW-V0` artifact 与其他历史 artifact 默认保留；未获单独清理授权不删除。
8. **`SW-EXP-004` 单元 A 已完成**：`8e5bd7b` 形成精确授权包，`bc9a6ff` 新增固定 `Cargo.toml`、`deny.toml`、拒绝 Phase B 的 `main.rs` 与受限 runner，`05c7337` 同步专题状态；首次 executable mode 负例以 `126` 暴露并修正，最终无参数/`run` 均以 `2` 拒绝，未创建 artifact、运行 Docker/Cargo 或联网。L3 单元 B 未授权。
9. **完成 11 个既有提交的代码—文档复核**：`SW-V0` 的 profile、seed、权限修复、证据口径与相关文档一致；`SW-EXP-004` 的依赖、镜像、容器权限、证据和清理边界与精确包一致。当时发现 45 分钟与 5 GiB 只有人工停止线且 runner 没有内建运行监控；该历史缺口已由 2026-08-30 的 A2 关闭为用户态周期监测。默认出站网络仍不实施域名 allowlist，已作为单元 D 的显式 L3 边界保留。

## 明日事项（2026-08-31）

1. **优先申请精确 Phase A 单元 D 的 L3 授权**：唯一入口固定为 `./scripts/run-sw-g2-openmls-0.9-spike.sh prepare 20260830-112214-39636.GpERrj`。执行前再次说明候选 crates/RustSec 默认出站网络无域名 allowlist、45 分钟与 5 GiB 五秒周期监测、工具链预检 `1 CPU/512 MiB`、依赖审计 `4 CPU/4 GiB`、可能新增仓库 lockfile、证据保留与精确容器清理；本次收口提交不授权执行。
2. **保持 bundle 信任与一次性授权边界**：只读消费两个固定二进制；不得自动选择 latest、替换 ID、重建 bundle、修补历史 evidence 或挂载任一 bundle `.work`。一次授权只执行一次，任一网络、source、license/advisory、feature、deadline、磁盘、证据或清理失败均 `STOP` 并保留真实 partial evidence，不自动重试。
3. **先复核 Phase A 再决定后续**：若单元 D `STOP`，只记录实际停止项并重新评审，不以换版本、放宽许可证、添加 advisory ignore 或延长时限绕过；若 `PASS`，也只接受 source/license/advisory/feature 门，Phase B 仍须形成新的精确授权包。
4. **保留并行低风险选项**：若明日不执行 OpenMLS，可评审 `SW-V1/V2` 最小实现与运行授权边界，或完成 `HW-G0/HW-G1` 已有设备/BSP 的只读预检；不新增 profile、不重跑容器、不安装依赖、不采购或刷写硬件、不产生射频发射。
5. **继续长期决策而不越级**：`SW-G2` 继续比较 mls-rs 0.56.0 与 OpenMLS 0.9.0 的 lockfile、许可证、advisory、状态安全和 Linux ARM64 实证；软件运行、硬件采购/执行与射频实验继续分别形成精确清单并单独授权。

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
