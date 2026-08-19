# RadishLink

> 无网亦可达。

RadishLink 是 Radish 家族中的离线自组网通信项目。它面向没有互联网、蜂窝网络不可用或不希望依赖中心服务的近远距离场景，使每台随身设备既能作为独立通信终端，也具备在策略允许时为其他节点转发数据的能力。

首期目标包括文字、受限图片与语音留言、实时语音，以及受限的一对一中低码率视频。手机在附近时可以作为更便利的界面和媒体终端；手机不在时，RadishLink 设备仍必须能够独立完成核心操作。

## 当前结论

- 主系统采用嵌入式 Linux；ESP32-S3 只作为可选低功耗控制器，不承担视频、完整路由和主应用。
- Wi-Fi HaLow / IEEE 802.11ah 是首选长距无线候选，Morse Micro MM8108 是首个评估对象，但不是已冻结的量产器件。
- 每个节点采用“长距回传 + 近距接入”双无线思路：HaLow 负责节点间链路，2.4 GHz Wi-Fi / BLE 负责手机接入和配网。
- 802.11s 可用于原型验证，但当前厂商实现仍有实验性边界；应用协议不能与单一 Mesh 实现绑死。
- WPA3 只保护无线链路，消息和媒体仍必须实施端到端加密。
- 三台节点是验证中继的最低数量；两台只能证明直连，不能证明自组网。
- 在目标销售与测试地区的频率、功率、带宽和设备合规得到确认前，不进行外场 HaLow 发射测试。

## 文档入口

- [当前状态](docs/status/current.md)
- [产品定义](docs/product-definition.md)
- [系统架构](docs/architecture/system-architecture.md)
- [网络与路由](docs/architecture/network-and-routing.md)
- [安全架构](docs/security/security-architecture.md)
- [硬件策略](docs/hardware/hardware-strategy.md)
- [原型采购清单](docs/hardware/poc-purchase-list.md)
- [媒体与 QoS](docs/protocol/media-and-qos.md)
- [手机接入方案](docs/mobile/companion-app.md)
- [无线电合规前置条件](docs/regulatory/radio-compliance.md)
- [外场验证计划](docs/testing/field-validation-plan.md)
- [路线图](docs/roadmap.md)
- [技术证据](docs/research/technology-evidence.md)
- [仓库治理](docs/governance/repository-governance.md)
- [参与贡献](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 仓库检查

```bash
./scripts/check-repo.sh
```

Windows PowerShell：

```powershell
pwsh ./scripts/check-repo.ps1
```

当前仓库处于定义与可行性验证阶段，尚未冻结许可证、量产硬件、射频区域版本、应用开发栈或兼容性承诺。仓库内的 Ruleset 与 workflow 是待远程实例化和验证的治理声明，不代表 GitHub 远程状态已经配置。
