# RadishLink 当前状态

更新日期：2026-08-28

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
- `PLAN-G0`、`SW-G0` 与 `SW-G1` 已于 2026-08-24 接受，`SW-G3` 已于 2026-08-28 接受；`mls-rs 0.56.0` 静态门已接受，OpenMLS 0.9.0 静态门 Draft 已形成，但 `SW-G2` 仍未通过；消息与验证语义已冻结，不代表 E2EE 路线、软件实现、P0 或其他证据轨通过。

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
- [`mls-rs 0.56.0` 静态门禁](../testing/sw-g2-mls-rs-spike-authorization.md)已接受；[OpenMLS 0.9.0 静态门禁](../testing/sw-g2-openmls-0.9-spike-authorization.md)Draft 已形成。两者均未生成 RadishLink lockfile、未审计、未构建、未运行，也不得继承 OpenMLS 0.8.1 的授权或结论；
- 除已提交的 `SW-EXP-002` 静态收口外，`SW-G2` 未完成、`SW-G4` 未获授权前，不再扩展测试代码、不实现新故障 profile、不安装密码依赖，也不重新运行场景；
- [低成本硬件验证计划](../hardware/hardware-validation-plan.md)当前停在 `HW-G0`；未通过 `HW-G2` 不采购，未通过 `HW-G3` 不刷写或启动实体台架；
- 下一步只评审 E2EE/身份候选、验证设计、硬件分层路线和已有硬件复用条件；获相应明确确认后才实施；
- 无射频软件计划不能替代首个测试地区的法规核对，二者可以并行研究但分别关门。

## 决策门状态与下一步

已通过：

1. `PLAN-G0`：接受产品阶段、`SW/HW/RF/EXP` 证据轨、依赖和停止线；
2. `SW-G0`：接受软件工作计划范围、探索性证据定位、工作顺序和暂停线；
3. `SW-G1`：接受消息身份、lifetime、hop budget、custody、delivery/read、去重、配额和崩溃恢复语义；
4. `SW-G3`：接受 profile schema、固定 seed、单变量故障矩阵、D0 数值、观察窗、证据和 `PASS/FAIL/INVALID` 判定。

下一步：

1. 评审并决定是否接受[`OpenMLS 0.9.0` 静态门禁](../testing/sw-g2-openmls-0.9-spike-authorization.md)；即使接受，也只允许未来提交独立 Phase A 精确授权请求，不自动下载、构建或运行；
2. 评审[`SW-G4 / SW-V0` Harness 最小实现与运行授权包](../testing/sw-g4-sw-v0-harness-authorization.md)；实施单元 A 与 Docker 运行单元 B 必须分别授权，当前不修改 `tools/t0/`；
3. `SW-G2` 继续比较 mls-rs 0.56.0 与 OpenMLS 0.9.0 的 lockfile、许可证、advisory、状态安全与 Linux ARM64 实证；未通过前不执行 `SW-V3`；
4. 接受硬件分层路线并完成已有设备/BSP 的只读预检（`HW-G0/HW-G1`）；
5. 再分别提交软件运行、硬件采购/执行和射频实验的精确清单与授权；继续独立推进地区、SKU、频段、功率、带宽和天线核对。

## 今日推进（2026-08-28）

1. **`SW-EXP-002` 静态收口已提交**：`7da9140` 收口脚本、隔离副本、lockfile 漂移、manifest schema 2 与 checksum；未运行 Docker/Phase A/Phase B。
2. **`SW-G3` 已接受**：`a5f5598` 形成的 profile schema、固定 seed、单变量矩阵、D0 数值、证据 manifest 和 `PASS/FAIL/INVALID` 已冻结；不构成实现或运行授权。
3. **两个新候选门禁已分流**：`mls-rs 0.56.0` 静态门已接受但未执行；OpenMLS 0.9.0 的 `SW-EXP-004` 静态门 Draft 已形成，新增 MSRV、JSON storage、0.8.1 迁移和 `hpke-rs 0.7` 传递图停止线。
4. **`SW-G4/SW-V0` Draft 已形成**：只覆盖 topology、fault hit、clock 和 evidence 自检，冻结新增文件、无依赖单元验证、Docker 副作用与分段授权；未实施或运行。
5. **保持暂停线**：今天不安装/构建密码依赖、不运行容器或三节点场景、不采购/刷写硬件、不发射射频。
6. **保留历史证据**：约 1.5 GiB `SW-EXP-002` ignored cache、历史 artifact 与 fixed Rust image 默认保留；未获单独清理授权不删除。

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

第二个入口只产生 Docker/Ethernet 探索性证据，使用未加密合成载荷；脚本打印的 `T0 PASS` 是历史内部输出，只代表内部断言通过，不构成 `SW-V*`、P0、HaLow、E2EE、距离、媒体、功耗或法规验证。

仓库治理与远程状态边界见[仓库治理](../governance/repository-governance.md)。
