# RadishLink 低成本硬件验证计划

- 状态：推进顺序已获所有者确认；详细验证计划仍为 Draft，待 HW-G0/G1 评审
- 更新日期：2026-10-24
- 当前 gate：`HW-G0`
- 目标读者：系统、硬件、嵌入式、测试与产品协作者

## 目的

软件模拟之后需要实体硬件验证，因为独立供电、真实文件系统、不同系统时钟、接口枚举、掉电、热、资源限制和部署过程无法由单机容器完整覆盖。

但硬件验证必须继续验证既定架构，而不是为了便宜把 Linux 主系统改写成 MCU 主系统。本计划采用“三台实体 Linux 节点先验证核心，一块 MCU 后验证交互与低功耗域”的顺序。

## 当前结论

- 2026-10-09 所有者接受复用/借用优先、三台 Linux 有线台架、单台交互 Demo 的推进顺序；缺少合适设备时优先评估三台同型号 Radxa ZERO 3E 2GB，B 补足第二个独立有线接口；型号仍须通过 BSP/接口预检，不是采购或生产选型决定。
- 同日所有者确认没有可复用设备，当前直接比较同型号三节点全新增 BOM，不等待复用清单或假定借用可得；
- `HW1` 使用三台独立 Linux 节点和纯有线拓扑，不需要 HaLow，也不需要任何射频发射；
- `HW2` 只制作一台带按键、显示、电量和唤醒能力的 Demo，另外两台继续 headless；
- ESP32-S3 只作为 UI、电源、按键、唤醒和看门狗辅助 MCU，不承载完整消息、E2EE、存储转发或媒体主栈；
- 在 `HW1` 通过前不买三块 MCU，不做自定义 PCB；在法规门完成前不买 HaLow 套件。

2026-10-24 已补齐[三节点全新增 BOM 项目表](poc-purchase-list.md#三节点全新增-bom-评审2026-10-24)、公开价格观察与下列 BSP 预检；部分配件已绑定 SKU/人民币参考价，镜像与驱动已有下述版本证据；可供三台的完整到手报价和测试 manifest 仍缺，HW-G0/G1 不据此标为通过。整套目标 2000–3000 元、累计硬上限 3000 元；首轮有线台架新增支出评审上限 1000 元保持不变。进入 P1 时给两个通话端补音频输入输出，单台交互 Demo 不替代双端语音验证。

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
| Radxa ZERO 3W/3E 2GB+ | Cortex-A55、1–8GB RAM；3W 有无线及 eMMC 选项，3E 有 Gigabit Ethernet、使用 microSD | 不把系列 eMMC 配置套到 3E；三台 3E 仍需 B 的第二 USB Ethernet，先核对支持周期 |
| ESP32-S3 开发板 | 按键、显示、I2S、USB、SD/MMC、低功耗控制、安全启动和看门狗实验 | 512KB 片上 SRAM、最高 16MB 模块 PSRAM、仅 2.4 GHz Wi-Fi/BLE；不作为 Linux Core 或 HaLow 证明 |

主要官方资料：

- [Raspberry Pi Zero 2 W 产品页](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
- [Orange Pi Zero 3 产品页](https://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-Zero-3.html)
- [Radxa ZERO 3 文档](https://docs.radxa.com/en/zero/zero3)
- [ESP32-S3 官方规格](https://www.espressif.com/en/products/socs/esp32s3/docs)

资料核对日期：2026-08-20。价格、可用 SKU 和本地供货在实际采购前重新核对。

### 本轮候选与 BSP 预检（2026-10-24）

本次只核对公开资料，没有下载/安装镜像或驱动、启动板卡、查询真实设备。厂商声明不等于 RadishLink 实测；未列出的旧候选沿用历史资料，不假装已经刷新。

| 候选 | 本轮比较 | 判断 |
| --- | --- | --- |
| ZERO 3E 2GB，三台同 revision | 板载有线 + B USB Host 网卡可构成目标拓扑；无板载无线；完整 BOM 已计配置/救援工具。官方规格见[ZERO 3](https://docs.radxa.com/en/zero/zero3) | 保留首选评审顺位；库存、到手价、BSP 和实际恢复仍未关闭，不是采购决定 |
| ZERO 3E 4GB，三台同 revision | 作为同板型内存更大备选；Arace 4GB 标价低于 2GB 但同样缺货，详见 BOM 的 variant 记录 | 只保留报价比较，不能把缺货低价当省钱方案；换 SKU 后仍须复核镜像/内存和预算 |
| Orange Pi Zero 3 2GB | 仓库已有历史候选；本轮官方产品页读取超时，未取得可靠的当前报价、镜像和供货复核 | 暂不替换首选；板载无线须在首次启动前安排禁用与核验，不能先启动后再关闭以满足无射频边界 |
| Raspberry Pi Zero 2 W | [官方规格](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)仍列 512MB、USB OTG 和无线；三节点有线需更多网卡/扩展 | 可作既有低资源 smoke 候选，不作为当前 2GB 同型号三节点方案的等价替代，不能只比较板价 |

| 预检项 | 已有文档依据 | 尚缺与验收边界 |
| --- | --- | --- |
| SKU / revision / 存储 | `RS109-D2E0H1` 是带排针 2GB 的商店 variant；[官方资源](https://docs.radxa.com/en/zero/zero3/download)列出 3E V1.2 硬件资料；BOM 已列高耐久 microSD 候选型号 | 卖家实际 PCB revision、三台一致性、microSD 实际交付 SKU 待确认；不把可下载原理图当交付版本证明 |
| OS / BSP | 下节已定位 Bookworm KDE b1 的精确资产、配置/包表、内核和 U-Boot；配置与包表摘要已核对 | 镜像本体未下载/校验，来源签名、实际 DTB/模块与维护差量仍待核对；桌面镜像不是 headless 生产镜像 |
| 系统许可与维护 | 已取得包清单；[厂商产品简报](https://dl.radxa.com/zero3/docs/hw/3e/radxa_zero_3e_product_brief.pdf)承诺至少供应至 2030 年 9 月 | 供货承诺不等于当前库存或 BSP 安全维护期；kernel、bootloader、固件及包图的许可/归属、更新评审仍缺 |
| B 双接口 | 目标版本的 config/源码包含 RTL8153 支持，3E DTS 启用 gmac1，共享 DTSI 启用 USB Host，见下节 | 镜像内模块、实际 USB VID/PID、网口命名、热插拔/掉电枚举和同时供电待验证；源码支持不等于实机通过 |
| 初次配置 / headless | 官方有[UART 调试入口](https://docs.radxa.com/en/zero/zero3/hardware-design/hardware-interface)及[microSD 安装流程](https://docs.radxa.com/en/zero/zero3/getting-started/install-os)；[BOM](poc-purchase-list.md#公开来源与价格证据)已列 CH343 type A / 21442 与读卡器 FIT0548 候选 | CH343 厂商规格覆盖 3.3 V 与 1.5 Mbaud 所需范围，但 Mac 版本/驱动/工具和实际串口速率仍待验；默认控制台与权限、无外网配置、默认凭据/重复身份清理、镜像更新范围待 HW-G3 固定 |
| 恢复 / 持久化 | 可移除 microSD 与串口提供候选诊断路径 | 逐台首次启动、关机、掉电、只读/满盘与故障原卡留存需精确 manifest；能重写启动盘不代表消息、安全状态或升级恢复通过 |
| USB / 功耗扩展 | HW1 的 B Host 被网卡占用，A/C Host 可留作后续接口评审 | P1 音频、近距与长距无线若争用 Host，需有供电与 hub 成本预算；HW1 的 5 V 供电规格不是产品功耗实测 |

本表是设计/资料评审输入，不新增正式测试参数。HW-G1 关闭时应把“可先用资料确认的条件”和“HW-G3 授权后才可执行的验收项”分开，避免要求未买板先出实测，也避免有文档就宣称硬件通过。2GB 节点用于 HW1；它不满足 I5 路线 A 的既有宿主证据要求，HW1 设备到位也不能直接重开 I5。

### 镜像与接口版本证据（2026-10-24）

[官方下载页](https://docs.radxa.com/en/zero/zero3/download)推荐 Bookworm KDE b1。[发布页](https://github.com/radxa-build/radxa-zero3/releases/tag/rsdk-b1)与[发布 API](https://api.github.com/repos/radxa-build/radxa-zero3/releases/tags/rsdk-b1)本轮对应 `rsdk-b1`，发布日期为 2025-07-15；“当前推荐/最新 Release”不等于包版本最新或安全更新齐全。本次只读取元数据、配置、包表及源码，没有下载镜像、deb 或执行安装。

| 对象 | 固定候选与核对结果 |
| --- | --- |
| 镜像资产 | `radxa-zero3_bookworm_kde_b1.output_512.img.xz`，资产 ID `272946966`，压缩大小 1454086428 bytes；arm64 / Debian Bookworm / KDE |
| 发布者给出的镜像 SHA-256 | `47b70ec81377f618505951fc9b4c40784e983c7fdff9706fdf79c13b6cd20730`；仅记录 API 值，未对镜像本体复算，不是签名验证 |
| [构建配置](https://github.com/radxa-build/radxa-zero3/releases/download/rsdk-b1/radxa-zero3_bookworm_kde_b1.config.yaml) | SHA-256 `1c3610dd16c9c0222ca18c74098517f24697d73f7d2837e5b6c9e7bc28828cab`；本次读取正文复算与 API 一致；`rsdk_rev` 为空，不能据此宣称已绑定完整 RSDK 构建源码 |
| [镜像包清单](https://github.com/radxa-build/radxa-zero3/releases/download/rsdk-b1/radxa-zero3_bookworm_kde_b1.manifest) | SHA-256 `637199a067990e9f93375eb9b87edca3298939e9ae0f1133cd7f3a07c995e7e1`，本次正文复算一致；它是发布者清单，不是挂载镜像后的独立盘点 |
| 内核 / 引导 | `linux-image-6.1.84-10-rk2410-nocsf` 与 `linux-image-radxa-zero3` 均为 `6.1.84-10`；`u-boot-radxa-zero3=2017.09-51-4db083c`，`u-boot-rk2410=2017.09-51-f7a5177` |
| 相关系统包 | `radxa-bootutils=0.2.5`、`radxa-firmware=0.2.22`、`firmware-realtek=20241210-1`、`radxa-system-config=0.6.16`、`rsetup=0.4.16`；包表含 `kernel-cmdline-ttyfiq0` 配置包，实际控制台与登录行为仍需验证 |

源码路径核对：

- [内核打包 tag 6.1.84-10](https://github.com/radxa-pkg/linux-rk2410-nocsf/tree/6.1.84-10)定位到打包 commit `317ea1500020f5c3e7ecdebc77a672146a968ace`，`src` 指向 Radxa kernel commit `e6d12a77c8bc0ea6decbd3e4604ec131d4032c30`。打包采用 `defconfig radxa.config`；[Radxa 配置补丁](https://github.com/radxa-pkg/linux-rk2410-nocsf/blob/317ea1500020f5c3e7ecdebc77a672146a968ace/debian/patches/linux/0001-feat-Radxa-common-kernel-config.patch)列 `CONFIG_USB_RTL8152=m`、DWC3/XHCI 平台支持。
- 该 commit 的 [r8152.c](https://github.com/radxa/kernel/blob/e6d12a77c8bc0ea6decbd3e4604ec131d4032c30/drivers/net/usb/r8152.c)包含 RTL8153 及 Realtek `0x8153` 设备项；[3E DTS](https://github.com/radxa/kernel/blob/e6d12a77c8bc0ea6decbd3e4604ec131d4032c30/arch/arm64/boot/dts/rockchip/rk3566-radxa-zero-3e.dts)启用 `gmac1` / `rgmii_phy1`，[共享 DTSI](https://github.com/radxa/kernel/blob/e6d12a77c8bc0ea6decbd3e4604ec131d4032c30/arch/arm64/boot/dts/rockchip/rk3566-radxa-zero3.dtsi)启用 USB Host。由此可保留“双接口驱动具备源码依据”的候选判断；尚未证明发布镜像加载了对应 DTB/模块，也未证明所购网卡就是这些 USB ID。
- [当前 Radxa APT 包索引](https://github.com/radxa-repo/rk3566-bookworm/blob/main/pkgs.json)本次已列 `linux-rk2410-nocsf 6.1.84-18`、`u-boot-rk2410 2017.09-62` 与 `rsetup 0.4.27`，不同于 b1。首次隔离启动拟保留可追溯基线；接入外网或处理真实数据前另审更新差量、来源与安全维护，不自动执行全量升级，也不把旧基线称为安全充分。

### 首次配置与评审收口

以下是后续操作包应覆盖的顺序，不是刷写/启动命令或已获授权的实验参数：

1. 采购前确定三台 PCB revision、microSD/电源/网卡交付型号；关闭镜像来源信任、镜像及固件许可/维护记录、Mac UART 工具和 1.5 Mbaud 支持的纸面缺口。供应商资料可支持预检，实际吞吐、热和掉电结果留待到货后，不要求未购设备先出实测。
2. HW-G3 包解析实际可覆盖的卡和节点、镜像下载/核验/写入命令、时长和恢复目标；逐台离线串口配置。核对 pin 8 TX、pin 10 RX、pin 6 GND 与 3.3 V TTL，禁止 VCC 双重供电；实际镜像登录路径未验证，不能假定默认 SSH 已可用。
3. 分别处理三台唯一机器身份、SSH host key、默认凭据及独立地址；不将克隆镜像身份当产品身份。移除 Mac 配置连接后再形成 A—B—C，回收实际 kernel/DTB、驱动、USB ID、接口与路由证据，验证 A/C 无旁路。
4. 依次安排干净关机、单节点故障、接口重枚举与原卡保留/备卡恢复，先冻结合成数据、样本数、时限、磁盘和日志边界。重写能启动只证明启动恢复；消息/密钥恢复必须依对应软件合同另验。

当前收口判断：板型接口、镜像版本、驱动源码和基本救援路径已有可审资料；完整报价、来源/许可维护、Mac 串口方案及精确 manifest 仍未关闭。详细 HW-G0/G1 尚未接受，不据本次资料核对放行 HW-G2/G3；I5 资源门、SW-G2 和 RF-R0 均不变。

### Mac 串口准备候选（2026-10-24）

本轮只读查询宿主版本、终端工具路径和公开源码：当前 Mac 为 ARM64、macOS 27.0.1（26A434），`screen -v` 返回 4.00.03；当前 PATH 未找到 `picocom` / `tio`，本次检查的辅助 Python 环境未找到 pySerial。这不是全盘软件盘点或驱动枚举，不能据此断言机器未安装任何串口驱动。没有连接、打开或发送数据到串口，没有安装依赖或修改系统。

| 层次 | 可审候选 / 依据 | 当前判断 |
| --- | --- | --- |
| 电气与板端 | [Radxa 接口文档](https://docs.radxa.com/en/zero/zero3/hardware-design/hardware-interface)规定 UART2_M0、pin 8 TX / pin 10 RX、1500000n8；GPIO 为 3.3 V | 保留 CH343 / 21442 候选，适配器 RX 接板 TX、适配器 TX 接板 RX，GND 共地；VCC、RTS/CTS 等其余线不接。UART2 保留调试用途，不启用普通 UART overlay |
| Mac 驱动 | [WCH 官方说明的固定 revision](https://github.com/WCHSoftGroup/ch34xser_macos/blob/09629694b207cdce66861b6fe821b68993507be9/README.md)列 CH343 与 macOS 11 及以上，提供 dmg/pkg 两条安装路径 | 对未使用 Rosetta 的新系统，文档指向 dmg 中的驱动应用；不能由“11 及以上”推断当前 27.0.1 已实测。安装包未下载，签名、兼容性与实际驱动绑定待核对，不因第三方教程先安装 Rosetta 或修改启动安全策略 |
| 现有终端 | [Apple 发布的 screen tty.c](https://github.com/apple-oss-distributions/screen/blob/727b822f02b9a625023e350276900911c0db04aa/screen/tty.c)通过固定 baud 表查找速率，没有 1500000 或 `IOSSIOSPEED` 路径；本机 Python 的 termios 也无 `B1500000` 常量 | 不将系统旧版 screen 作为 1.5 Mbaud 默认入口；公开源码未与本机二进制逐字绑定，这不是串口实测失败报告 |
| 终端候选 | pySerial `3.5`，tag commit `0e7634747568547b8a7f9fd0c48ed74f16af4b23`；[Darwin 后端](https://github.com/pyserial/pyserial/blob/0e7634747568547b8a7f9fd0c48ed74f16af4b23/serial/serialposix.py)通过 `IOSSIOSPEED` 设置自定义速率，[许可证](https://github.com/pyserial/pyserial/blob/0e7634747568547b8a7f9fd0c48ed74f16af4b23/LICENSE.txt)为 BSD-3-Clause | 仅作独立配置工具候选，不加入产品依赖。使用隔离工具环境，来源/包摘要与 Python 兼容性须在安装包中冻结；本轮未安装、运行或声称硬件支持通过 |

后续终端参数候选为 `serial.tools.miniterm`、实际唯一 `/dev/cu.*` 设备、1500000 baud、8N1、关闭硬件与软件流控；退出键为 `Ctrl+]`，见[工具文档](https://pyserial.readthedocs.io/en/latest/tools.html#module-serial.tools.miniterm)。设备路径必须绑定实际 USB VID/PID 和插拔对应关系，不使用通配符批量打开、不把 Linux 的 `/dev/ttyUSB0` 当 Mac 路径，也不使用网络串口 URL。终端显示的设定速率不是线速测量；后续需用适配器本地回环和板卡冷启动/交互共同验证，保留乱码、丢字或无法设置速率的原始失败。

安装与设备操作仍属后续 HW-G3 包：先保存已有驱动/工具状态、核对精确安装产物与卸载方式，再明确系统扩展授权、是否需要重启、预计时长和可恢复边界；不照抄厂商文档中的宽泛删除命令。连接节点时先接收启动日志，待登录提示再输入，避免串口输入中断 U-Boot；实际凭据不得记录到终端日志或文档。若必须改变启动安全策略才能使用，则重新比较适配器/配置路径，不自动降低宿主保护。

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
