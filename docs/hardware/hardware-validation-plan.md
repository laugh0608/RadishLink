# RadishLink 低成本硬件验证计划

- 状态：Draft，待评审
- 更新日期：2026-08-20
- 当前 gate：`HW-G0`
- 目标读者：系统、硬件、嵌入式、测试与产品协作者

## 目的

软件模拟之后需要实体硬件验证，因为独立供电、真实文件系统、不同系统时钟、接口枚举、掉电、热、资源限制和部署过程无法由单机容器完整覆盖。

但硬件验证必须继续验证既定架构，而不是为了便宜把 Linux 主系统改写成 MCU 主系统。本计划采用“三台实体 Linux 节点先验证核心，一块 MCU 后验证交互与低功耗域”的顺序。

## 当前结论

- 首选复用已有 Linux 设备；没有合适设备时才比较低成本 SBC；
- `HW1` 使用三台独立 Linux 节点和纯有线拓扑，不需要 HaLow，也不需要任何射频发射；
- `HW2` 只制作一台带按键、显示、电量和唤醒能力的 Demo，另外两台继续 headless；
- ESP32-S3 只作为 UI、电源、按键、唤醒和看门狗辅助 MCU，不承载完整消息、E2EE、存储转发或媒体主栈；
- 在 `HW1` 通过前不买三块 MCU，不做自定义 PCB；在法规门完成前不买 HaLow 套件。

## 明确非目标

- 不以低成本开发板数据推导量产成本、尺寸、续航、热或供应周期；
- 不把 2.4 GHz Wi-Fi、Ethernet 或 USB 数据表述为 HaLow 结果；
- 不要求 `HW1/HW2` 验证实时视频、公里距离或整机法规；
- 不在 MCU 上复制 Linux 路由、密码状态、附件和媒体栈；
- 不因 Demo 能发送文字就冻结公共协议、数据库、SoC 或操作系统。

## 验证层级

### HW0：只读盘点与方案评审

工作：

- 盘点已有 Linux 主机、SBC、电源、microSD/eMMC、USB Ethernet、显示、按键和 ESP32-S3；
- 核对 CPU 架构、RAM、存储、两个独立网络接口、Linux/BSP、USB/UART/I2C/I2S 和供电；
- 用同一评分表比较复用、借用和采购，不启动设备、不安装镜像；
- 明确 `HW1/HW2` 的测试 manifest、故障点、指标和清理方式。

退出条件：完成 `HW-G0` 计划评审和 `HW-G1` 设备/BSP 预检；此时仍可以零采购退出。

### HW1：三台实体 Linux 有线台架

拓扑：

```text
Linux A ── Ethernet/USB ── Linux B ── Ethernet/USB ── Linux C
```

- A/C 不共享交换机、Wi-Fi 或 host bridge；
- B 需要两个可独立控制的有线接口，是唯一物理下一跳；
- 三台设备分别供电、分别持久化、分别重启；
- 全程关闭未使用无线接口，不产生 HaLow 或 2.4 GHz 测试结论。

验证对象：

- 一致镜像/软件部署、版本识别和日志回收；
- A/C 直连负例与 B 双向可达；
- 单节点和整机断电、文件系统恢复、时钟偏差和接口重新枚举；
- CPU、RAM、持久队列、写放大、磁盘接近满和进程守护；
- 软件设计规定的去重、lifetime、hop budget、custody 与确认；
- 无风扇台架温度和输入功率只记录为候选平台数据，不外推产品续航。

精确消息数量、循环次数、观察时长和资源阈值由 `SW-G3/HW-G1` 的 manifest 冻结，不在采购前凭感觉设定。

### HW2：单节点交互与电源 Demo

推荐形态：

```text
按键 / 小屏 / 电量 / 唤醒
            │
        ESP32-S3
            │ USB / UART / SPI
       Linux Node A
            │
      B/C headless Linux
```

只做一套带交互外设的 A；B/C 继续复用 `HW1`。MCU 无线默认关闭，MCU 与 Linux 先用有线接口。

验证对象：

- 开机、关机、唤醒、主机心跳和看门狗恢复；
- 联系人选择、预设/短文字、发送中、目的端送达、失败和重试状态；
- Linux 未启动、接口断开、版本不兼容和升级失败时的明确 UI；
- 电量、充电、温度与中继策略的最小状态展示；
- MCU/Linux IPC 的版本、长度、超时、重放和错误边界；
- MCU 不保存消息正文、长期会话密钥或可伪造目的端确认的秘密。

`HW2` 是产品交互和双处理器边界 Demo，不是 MCU 版 RadishLink，也不代表随身功耗和体积目标已达成。

### HW3：三台集成原型

只在 P0 文字、安全和 `HW1/HW2` 证据成立后考虑：

- 三台同构 Linux 节点、稳定存储、电源、近距接入和必要 UI；
- 统一升级、恢复、设备身份和日志；
- HaLow 模块是否加入由 `RF-R*` 与采购门单独决定；
- 仍优先现成模块/载板，不在这一层直接设计量产 PCB。

## 候选平台定位

以下只用于 `HW0/HW1` 评分，不是采购决定。

| 候选 | 可验证内容 | 主要限制 |
| --- | --- | --- |
| 已有 Linux 主机/SBC | 成本最低，最适合先验证独立电源、存储和部署 | 型号不一致时性能数据不可横向合并 |
| Raspberry Pi Zero 2 W | 官方定位为 15 美元级 Linux 小板；64-bit Cortex-A53、512MB、2.4 GHz Wi-Fi、单 USB OTG，可做文字节点最低资源 smoke test | 512MB 和单接口余量很小，需要额外有线接口；不满足工程样机 2GB 起步候选门 |
| Orange Pi Zero 3 2GB/4GB | Cortex-A53、Gigabit Ethernet、Wi-Fi 5、USB 2.0 和 Debian/Ubuntu 候选，纸面上适合低成本实体 Linux 台架 | 必须先验证 BSP、内核、接口并发、镜像更新和稳定性，不能只看参数采购 |
| Radxa ZERO 3W/3E 2GB+ | Cortex-A55、1–8GB RAM、可选 eMMC；3W 有无线，3E 有 Gigabit Ethernet | 3W/3E 接口不同，严格 A—B—C 仍可能需要 USB Ethernet 或混合 SKU；先核对支持周期 |
| ESP32-S3 开发板 | 按键、显示、I2S、USB、SD/MMC、低功耗控制、安全启动和看门狗实验 | 512KB 片上 SRAM、最高 16MB 模块 PSRAM、仅 2.4 GHz Wi-Fi/BLE；不作为 Linux Core 或 HaLow 证明 |

主要官方资料：

- [Raspberry Pi Zero 2 W 产品页](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
- [Orange Pi Zero 3 产品页](https://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-Zero-3.html)
- [Radxa ZERO 3 文档](https://docs.radxa.com/en/zero/zero3)
- [ESP32-S3 官方规格](https://www.espressif.com/en/products/socs/esp32s3/docs)

资料核对日期：2026-08-20。价格、可用 SKU 和本地供货在实际采购前重新核对。

## Gate 与授权

### HW-G0：目标与非目标

接受 HW0–HW3 的目的、顺序、证据边界和 MCU 辅助角色。未通过时只修订文档。

### HW-G1：设备与 BSP 预检

形成候选矩阵，至少记录：实际 SKU、CPU/RAM/存储、接口、Linux 发行版、内核/BSP、更新来源、许可证、已知问题、供电和复用成本。不得用“能启动桌面”替代接口与恢复预检。

### HW-G2：采购/BOM 授权

优先顺序：复用已有设备 → 借用 → 购买三台一致的低成本 Linux SBC → 购买一块 ESP32-S3 与最少外设。提交精确数量、单价区间、卖家/地区、退换风险和替代方案后再授权；不夹带 HaLow、自定义 PCB 或三套 MCU。

### HW-G3：台架执行授权

执行前说明要刷写或修改的设备、镜像、接口、命令、预计时长、数据覆盖风险和恢复方式。用户已有设备上的数据默认不可覆盖。

### HW-G4：结果评审

分别记录 `PASS/CONDITIONAL/FAIL/INVALID`。只有 manifest、原始日志和负例完整时，才把相应能力写为“实体 Linux 有线台架已验证”或“单节点交互 Demo 已验证”。

## 成本控制原则

- 不为“看起来像产品”购买三套屏幕、相机、音频和电池；先让一台 A 完成交互闭环；
- 不用三块 MCU 重写 Core；重复实现成本高于板卡差价；
- 不为 HW1 购买射频模块；B 的第二接口优先使用已有 USB Ethernet；
- 不在低成本板上追求 P2 视频，资源不足应记录为平台边界而不是降低产品目标；
- 不因买了某款板而倒推生产技术栈，所有开发板都可被替换。

## 停止线

- `PLAN-G0/SW-G1/SW-G3` 未通过，不执行 HW1；
- `HW-G2` 未通过，不采购；
- `HW-G3` 未通过，不刷写、启动或覆盖实体设备；
- `RF-R1` 未通过，不启用任何 HaLow 发射；
- 密码 ADR 未通过，HW1/HW2 只处理合成不透明载荷，不宣称 E2EE；
- 任一候选需要修改监管域、绕过签名、使用不明镜像或覆盖用户数据时立即停止。
