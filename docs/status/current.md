# RadishLink 当前状态

更新日期：2026-09-05

## 当前阶段

项目处于 `D0：产品定义、法规预检与三节点 POC 准备`。已有消息语义、确定性验证设计、harness 和密码候选依赖检查；尚无已验证的产品 E2EE 闭环、实体 Linux 台架、HaLow 距离或媒体能力。

本页只保存当前结论、关键风险、下一项决策与停止线。历史 run、hash、失败时间线和当时授权见[2026-09-03 状态与批次快照](2026-09-03-progress.md)及对应测试专题；本轮文档整理不重判历史结果，不代表重新执行实验或复核远程配置。

## 已确定的产品与工程基线

- 项目名 `RadishLink`，标语 `无网亦可达`；正式设备同时具备终端与中继能力，中继启用受电量、温度、用户策略和网络状态约束。
- 设备必须独立完成联系人选择、文字收发、按键通话和基本状态查看；手机是附近伴侣，不是运行前提。
- 主系统为嵌入式 Linux；ESP32-S3 只作为交互、电源、唤醒等辅助域候选。
- 长距承载首选评估 Wi-Fi HaLow，近距使用独立 2.4 GHz Wi-Fi/BLE；无线承载与覆盖层分离，不冻结量产器件、监管域或路由实现。
- 应用 E2EE 与逐跳保护分层，中继不得获得内容明文；三节点是中继验证的最低规模，替代路径恢复另需可用的替代链路。
- 产品阶段继续沿用已接受的 `D0/P0/P1/P2/E0`。首期场景、视频与可携带样机顺序、手机端点角色的修订候选见[项目执行计划](project-execution-plan.md)，尚未替代既有阶段退出条件。
- 原创内容采用根目录 `LICENSE` 的 `RadishLink Source-Available License 1.0`，不是开放源码许可证。
- 串行普通开发在 `dev`，`master` 为默认稳定主线；主题分支与 PR 适用条件见[仓库治理](../governance/repository-governance.md)。远程 Ruleset、合并选项和私密漏洞入口的既有核对记录不等于本轮实时复核。

## 各证据轨状态

| 证据轨 / gate | 当前结论 | 后续缺口与正式记录 |
| --- | --- | --- |
| `PLAN-G0 / SW-G0 / SW-G1` | 已接受计划、术语和消息交付语义 | [执行计划](project-execution-plan.md)、[软件计划](d0-t0-p0-plan.md)、[消息语义](../protocol/message-delivery-semantics.md) |
| `SW-G3` | 1.0 设计已接受 | [设计专题](../testing/sw-g3-deterministic-validation-design.md)新增待评审勘误；原参数和历史证据不变 |
| `SW-G4 / SW-V0` | 已完成；四个 canonical profile 各三次通过且归一化一致 | 只证明 harness；[正式记录](../testing/sw-g4-sw-v0-harness-authorization.md)不授权重跑或扩展 |
| `SW-EXP-001` | Docker/Ethernet 合成载荷探索成立 | 不是正式消息实现、E2EE 或 P0 验收 |
| OpenMLS `0.8.1` | Phase A `STOP`：advisory 与许可证门 | [历史授权与结果](../testing/sw-g2-openmls-spike-authorization.md)，Phase B 禁止 |
| OpenMLS `0.9.0` | 单元 E：固定 264-package 图 Phase A `STOP` | 独立 audit 未发现 vulnerability，但有 unmaintained 信息项；当前门拒绝三个 MPL-2.0 crate；[正式记录](../testing/sw-g2-openmls-0.9-phase-a-authorization.md) |
| mls-rs `0.56.0` | D2：同一固定 94-package 图 Phase A `PASS`；D 的旧 feature-gate `STOP` 保留 | [Phase A 记录](../testing/sw-g2-mls-rs-phase-a-authorization.md)；工具通过不等于分发义务或安全适配完成 |
| mls-rs 许可证证据 | R1/R1b 传输负向；R1c-R 为 `STOP/license-evidence`；R1d-L 为 `STOP/license-disposition` | [补证与复核包](../testing/sw-g2-mls-rs-license-notice-review.md)、[处置评审](../testing/sw-g2-mls-rs-license-disposition-review.md)；R2 前置未满足 |
| `SW-G2 / SW-V1..V3` | E2EE 决策未通过，后续正式场景未执行 | [决策包](../security/e2ee-sw-g2-decision-package.md)；没有已验证 E2EE 或产品软件闭环 |
| `HW` | 未进入实体台架；`HW-G0` 待评审 | [低成本验证计划](../hardware/hardware-validation-plan.md) |
| `RF` | 地区/SKU/配置未关闭，保持 `RF-R0` | [法规预检](../regulatory/radio-compliance.md)，采购与发射暂停 |

mls-rs 当前实质缺口：R1c-R 已为 9 个 mls-rs package 取得 Apache-2.0/MIT 正文；`debug_tree 0.4.0` 缺绑定固定源码的 MIT notice/holder，`r-efi 6.0.0` 的 `AUTHORS` 含完整 MIT 正文与归属，但缺另两项声明 alternative 的完整正文。前者的 R1d-U-P/I 已完成澄清设计及离线 helper，公开发送 X 与只读收集 R 均未执行；后者等待独立法律评审后再分流。这是证据和处置缺口，不是许可证不存在、违法或候选淘汰结论。

## 当前优先级

具体产物、决策责任和关闭标准统一放在[项目执行计划的近期工作包](project-execution-plan.md#近期工作包与决策顺序)。当前顺序为：

1. 明确首个用户场景、首个测试/使用地区，以及视频是否阻挡首台可携带样机；不替用户选择地区或承诺日期。
2. 形成按实际渠道区分的许可证政策评审输入，分别处置 `debug_tree` 与 `r-efi`；保留全部现行 STOP 和 R2 条件。
3. 收敛 Node/手机身份、物理与覆盖层路由边界，以及安全状态、应用事务、relay-clear proof 的候选映射。
4. 评审 `SW-G3` 勘误和最小文字纵向切片；`SW-V1/V2` 的合成验证准备与硬件只读盘点可分别设计，不升级为 E2EE 或实体实测。
5. 规划已有离线测试的 CI 接入与重复实验工具维护，形成硬件复用及能量/体积/成本预算；本轮没有实施代码或 CI 修改。

## 关键风险

- **产品与地区尚未收敛**：使用场景跨度大；MM8108 覆盖范围与国外支持地区不能推导国内合法配置，地区问题可能改变产品路线。
- **安全适配未证明**：依赖图通过不能证明离线建组、分区并发、撤销传播、崩溃原子性或中继清理证明可实现；mls-rs 完整第三方安全审计缺口仍在。
- **架构与交互接口未冻结**：覆盖层 hop 不自动等于物理 hop，手机独立端点也不自动把会话延续给 Node。
- **工程样机预算缺少实测**：Linux、双无线、常开中继和媒体共同影响电池、温度、体积与成本；开发板和 PHY 峰值不能替代产品数据。
- **验证和维护成本偏重**：`SW-EXP-001` 不能继承为产品协议；已有脚本重复和长文件需要在后续相关实施中收敛，当前 CI 仍只检查仓库卫生。

## 当前停止线

- 不采购 HaLow、不射频发射、不做量产 PCB、不冻结生产技术栈；`HW-G2` 前不采购，`HW-G3` 前不刷写或启动实体台架，无线操作另受 `RF-R*` 约束。
- OpenMLS 两个固定图的 Phase B 禁止；mls-rs D2 的 `PASS` 不授权 Phase B。许可证证据轨和 R2 未完成，`SW-G2` 未通过。
- 不自动第四次运行 R1、不扩展 selector、不补写或重判 R1c evidence、不改 gate/allowlist/advisory ignore、版本、provider、source 或 lockfile；新证据与策略变更须另行明确范围。
- `debug_tree` X/R 继续遵循[已冻结的精确澄清合同](../testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md)。公开账号和逐字消息须预审；发送、收集、回复接受性分别按合同处理，不自动监控、追问、编辑或关闭 Issue。
- `r-efi` 的 MIT alternative 须独立法律评审；R1d-L 不能替代 R2。R2 仅在新证据轨有效完整通过后，由所有者指定符合条件的复核者执行。
- 既有 `SW-V0`、审计 bundle、D2 和其他实验运行的单次授权不延续；不重跑、扩展 profile/schema、安装密码依赖或清理旧 evidence/cache。
- 本轮只完善文档。待评审候选不构成接受决定、实现授权、运行授权或外部写入授权；无射频证据与地区法规分别关门。

## 验证入口与结论边界

默认文档/仓库检查：

```bash
./scripts/check-repo.sh
git diff --check
```

已有 Go 工具的离线单元测试方法见[软件工作计划](d0-t0-p0-plan.md)。单元测试与仓库卫生通过只覆盖对应代码和文本，不代表 harness 的正式 Docker run 或产品验收。

探索性 `./scripts/run-t0-three-node.sh` 与正式 harness `./scripts/run-sw-v0-harness.sh run` 都不是默认重跑入口。前者的历史 `T0 PASS` 仅对应未加密合成探针，后者只验证 topology、fault hit、clock 与 evidence；均不证明 P0、HaLow、E2EE、距离、媒体、功耗或法规能力。
