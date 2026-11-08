# RadishLink 低成本硬件验证计划

- 状态：推进顺序已获所有者确认。HW1 评审材料已齐备，详细目标待 HW-G0 接受，设备与 BSP 缺口待 HW-G1 关闭
- 更新日期：2026-11-08
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

2026-10-24 已补齐[三节点全新增 BOM 项目表](poc-purchase-list.md#三节点全新增-bom-评审2026-10-24)、公开价格观察与下列 BSP 预检；部分配件已绑定 SKU/人民币参考价，镜像与驱动已有下述版本证据；所有者反馈已给价项目小计 2024 元，但精确到手价、赠送件/兼容性和测试 manifest 尚未闭合；查价已收口，HW-G0/G1 不据此标为通过。整套目标 2000–3000 元、累计硬上限 3000 元；首轮有线台架新增支出评审上限 1000 元保持不变。进入 P1 时给两个通话端补音频输入输出，单台交互 Demo 不替代双端语音验证。

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

## HW1 台架验收表（2026-11-08）

本次复核使用仓库已记录的 BOM、BSP 与 Node 验收要求。HW-G0 待接受的范围是三台独立 Linux 节点的纯有线平台验证，之后才做单台 HW2 交互 Demo。HW1 提供接口、部署、故障恢复与资源观测证据。端到端安全能力、无线性能和产品续航各由对应验收负责。预算路径与能取得的证据见[HW1 预算取舍](poc-purchase-list.md#hw1-预算取舍2026-11-08)。

### 采购前的纸面复核

| 项目 | 已有评审依据 | HW-G1 仍须核对 |
| --- | --- | --- |
| 设备与布线 | 三台 ZERO 3E 2GB 带排针，候选 `RS109-D2E0H1`。A 板载网口连 B 板载网口，B USB Host 经数据转接和 RTL8153 候选网卡连 C 板载网口。三套独立 5 V 电源，三张独立系统卡及一张共用恢复卡 | 交付的 PCB revision、配件料号与套装内容，三只电源、线材、固定件、供电和接口空间兼容性，B USB 网卡交付型号。整套到手额与预留纳入所选预算路径。见[物料清单](poc-purchase-list.md#完整物料范围与报价栏) |
| 镜像与 BSP | Bookworm KDE `rsdk-b1`、资产 `272946966`、`6.1.84-10-rk2410-nocsf`。已有发布者镜像摘要、已核对的配置和包清单、双接口驱动与 DTS 源码依据 | 记录可信发布与验真路径，以及 kernel、bootloader、固件的来源、许可与维护范围。镜像本体验真在写卡前完成，实际 DTB 和驱动装载在台架验证。见[镜像与接口版本证据](#镜像与接口版本证据2026-10-24) |
| 串口与恢复 | CH343 候选，UART2_M0、3.3 V TTL、1500000n8。Mac 依次配置与救援，一张备卡保留原故障介质 | 确定能以该速率工作的 Mac 驱动及终端来源、支持范围和恢复路径，必要的安装另列。现有单套 UART 只计逐台采集，若要求同时采集三台须补工具和成本。见[Mac 串口候选](#mac-串口准备候选2026-10-24) |

### 到货后的验收顺序

下列验收均待执行。实际刷写、接线、启动和故障注入须进入对应 HW-G3 操作包。单板预检分期只覆盖表中该节点的交付、镜像、串口和本地恢复部分，完整行按三台设备验收。平台基础验收通过后，再按[Node 接线准入](../testing/node-security-integration-acceptance.md#linux-arm64-接线准入)核对适配层、可信时间、资源、关停时限和原连接关闭。

| 用例 | 条件与步骤 | 通过依据及失败处置 |
| --- | --- | --- |
| `HW1-01` 到货核对 | 按 A/B/C 及部件清单核对交付板、排针、PCB revision、电源、系统卡和恢复卡。确认两条有线链路、B 数据转接和网卡的对应关系 | 留下料号、revision、数量和经脱敏的标签记录。缺件、替代 SKU 或电源不匹配时暂停上电，先核对退换或重新评审 |
| `HW1-02` 镜像与首次配置 | 写卡前绑定来源、镜像摘要与核验结果、目标卡、恢复卡和具体授权。逐台串口采集冷启动，再核对实际 OS、内核、DTB 与模块。使用独立节点身份与配置，移除默认凭据，配置完成后移除 Mac 配置连接 | 三台镜像一致、各自启动并使用独立存储，串口可访问并能从批准的恢复卡启动。记录摘要、版本、节点对应关系和脱敏的配置核对结果。镜像验真失败、串口不可用或身份重复时停在本项 |
| `HW1-03` 拓扑与直连负例 | A–B、B–C 使用两个独立网段。移除额外链路和默认旁路，确认 B 没有桥接或通用 IP 转发。先验证两条相邻链路分别双向可达，再尝试 A↔C 直接通信 | 记录四个接口的节点/端口/驱动映射、地址与路由、两边成功的探针及 A/C 双向拒绝。邻接探针失败时直连负例无效。A/C 出现直达路径时停止后续用例并保留拓扑证据 |
| `HW1-04` 断链和重枚举 | 分别断开 A–B、B–C 并复连，另覆盖 B 的 USB 网卡重枚举。每次只触发一个故障，检查另一条链路，再恢复初始布线 | 记录链路事件、接口名、USB VID/PID、端口映射和双边探针。受影响链路按 manifest 恢复，另一条链路保持可达，A/C 直连仍被拒绝。接口串位、无法恢复或出现旁路时暂停下一用例 |
| `HW1-05` 断电与存储救援 | 先逐台记录正常关机基线，再以合成数据的持久化检查点为界验证单节点断电和全台架断电。另用备卡演练逐台救援 | 记录故障触发位置、重启后 boot 标识、文件系统状态和重连情况，核对已确认持久化标记的摘要与未确认写入的预期。损坏或读不到原卡时保留原介质与失败证据，用备卡验证平台恢复。应用状态、去重和证明责任交给 `HW1-08` |
| `HW1-06` 时钟与资源 | 在固定观察窗口记录各节点 boot 坐标、单调时间和墙钟偏差。按审定的合成负载记录 CPU、RSS、磁盘及写入量，接近满额用例绑定独立可丢弃的测试范围 | 输出基线、峰值、触发点和失败原因。时间偏差记录供平台时钟评审。触及批准的磁盘、日志或温度停止线即结束并保留证据。软件队列与写入上限按所测用例单列 |
| `HW1-07` 输入功率与温度 | 功率计及共享第四条线到位后，按已评审的 5 V 串接路径逐台采集，记录工作模式、采样窗口和环境温度 | 留下 W/Wh、时段、接入路径、仪表限制和温度记录。暂缓仪表时标为待测。测量用于候选平台预算，见[功率计路径](poc-purchase-list.md#补充物料核对与测量边界) |
| `HW1-08` Node 接线与文字路径 | 平台基础验收及软件前置满足后，绑定明确的构建、适配层和合成输入。验证 A→B→C 的接纳、转发、确认、重连及故障恢复，按安全评审分别绑定实际签验和 B 的可见性用例 | 留下每跳事件、事务及恢复结果、已配置资源上限、超限拒绝和关闭回收。安全结论按固定候选及对应三节点实际用例复核。见[实际安全用例与接线准入](../testing/node-security-integration-acceptance.md#实际安全用例) |

每次执行前在 HW1 manifest 记录用例 ID、代码 revision、三节点与端口映射、镜像/二进制摘要、合成输入、故障位置、样本数、观察窗口、资源阈值和回收方式。样本数与阈值按既有 SW-G3/HW-G1 评审冻结，未填齐的用例留在待执行。执行后保存日志、指标、预期与实测对照、结束状态和校验值，失败时先保留故障证据并按对应操作包恢复，HW-G4 逐项裁决。

本次结论是 HW-G0 的 HW1 目标与验收材料可交所有者评审。HW-G1 待关闭交付、镜像来源/维护、Mac 串口和预算缺口，样本与阈值待按用途冻结。当前 gate 仍为 HW-G0，预算与采购决定由所有者另行确认。

## HW1 镜像、串口与恢复预检（2026-11-08）

适用于 ZERO 3E 2GB 候选的单板预检与完整三节点方案。复核范围为公开发行元数据、小型发布文本、源码说明和本机工具版本。镜像、驱动与 wheel 本体的核验和到货实测列入后续操作包。预算路径仍待决定。见[HW1 预算取舍](poc-purchase-list.md#hw1-预算取舍2026-11-08)。

### 镜像发布与 BSP 证据

| 对象 | 本次复核得到的依据 | 关闭条件 |
| --- | --- | --- |
| 标准 microSD 镜像 | `rsdk-b1` release ID `232385470`，公开 API 返回 `immutable: false`。`radxa-zero3_bookworm_kde_b1.output_512.img.xz` 资产 ID `272946966`、1454086428 bytes，API SHA-256 与先前记录一致。发布页标准镜像和 UFS 镜像分别列出。见[发布页](https://github.com/radxa-build/radxa-zero3/releases/tag/rsdk-b1)与[发布 API](https://api.github.com/repos/radxa-build/radxa-zero3/releases/tags/rsdk-b1) | 绑定标准镜像文件名、资产 ID、长度、SHA-256 与 SHA-512。任何字段漂移先重新评审 |
| 发布者校验文本 | `radxa-zero3_bookworm_kde_b1.sha512sum` 资产 ID `272947609`，1211 bytes，文本实算 SHA-256 为 `d24da388805952397ea7d5f5df3cbac88d5255ff71d451da4ea04a0101d1422d`，与 API 一致。标准镜像行的 SHA-512 为 `6f9f67df6f997bef41aac2cc568ebb4b7820216be1256a49ce472cb877684c08ad793ff726da3155a02f0eab60b2b2c9318168b3cf8fab81849ae91e8724f10d`，与发布正文一致。见[资产列表](https://github.com/radxa-build/radxa-zero3/releases/expanded_assets/rsdk-b1) | 后续对压缩镜像本体实算双摘要并对比固定值。两份摘要来自同一发布渠道，来源核验独立判定 |
| 镜像来源 | `rsdk-b1` 指向 commit `756ccb960867b08e29315fdad24c2dbba5557957`，GitHub 报告该提交签名有效。公开 attestation API 按上述镜像 SHA-256 查询返回 HTTP 404，资产列表也未找到镜像签名。当前只有提交签名和发布者摘要。见[提交](https://github.com/radxa-build/radxa-zero3/commit/756ccb960867b08e29315fdad24c2dbba5557957)和[证明查询 API](https://docs.github.com/en/rest/repos/attestations#list-attestations) | 取得能绑定镜像摘要的可验证发布证据，或由所有者对官方渠道加固定摘要能否作为有限隔离台架的信任依据作明确裁决。来源待定时停止写卡 |
| 内核与有线接口 | `6.1.84-10` 发行资产中，`linux-image-6.1.84-10-rk2410-nocsf_6.1.84-10_arm64.deb` 为 `272705121`，`linux-image-radxa-zero3_6.1.84-10_all.deb` 为 `272705123`。已定位的打包/内核 commit 包含 ZERO 3E 设备树、USB Host 与 `r8152` 的源码依据。见[固定内核发布](https://github.com/radxa-pkg/linux-rk2410-nocsf/releases/tag/6.1.84-10)与[版本证据](#镜像与接口版本证据2026-10-24) | 后续核对镜像内实际包版本、DTB、网卡 VID/PID 与驱动绑定，记录双接口并行与重枚举结果。发布资产目前只定位到元数据 |
| 引导与固件 | 在 `radxa-pkg/u-boot-rk2410` 的 `2017.09-51` 同一发布中，已定位 `u-boot-radxa-zero3_2017.09-51-4db083c_all.deb`（`272669737`）与 `u-boot-rk2410_2017.09-51-f7a5177_arm64.deb`（`272669738`）。该发布标签指向 `d849b92181d0e960d13d20e54e39c9c696c05dec`。复算 b1 包表摘要后，确认内核和两个引导包版本与发布条目一致，固件待核对象为 `radxa-firmware=0.2.22`、`firmware-realtek=20241210-1`。见[固定 U-Boot 发布](https://github.com/radxa-pkg/u-boot-rk2410/releases/tag/2017.09-51)与[发布 API](https://api.github.com/repos/radxa-pkg/u-boot-rk2410/releases/tags/2017.09-51) | 核对镜像实际引导组件与包中 payload，保留精确版本的来源、版权/许可文件与固件归属。发布标签只能定位分发入口，引导二进制与源码的映射及固件来源仍缺 |
| 更新与维护 | 公开 rk3566 包索引复核到内核 `6.1.84-18` 和 U-Boot `2017.09-62`，与 b1 包表不同。见[厂商包索引](https://github.com/radxa-repo/rk3566-bookworm/blob/main/pkgs.json) | 将 b1 固定隔离基线的用途和更新另案列清。更新评审须取得精确仓库签名链、包差量、对应许可材料、回退基线及维护责任。实际许可与维护范围仍待关闭 |

另读取 `radxa-zero3_bookworm_kde_b1.build-512-image` 的 3513 bytes 文本，实算 SHA-256 与发布 API 一致。脚本文本按文件系统和分区数据计算截断位置，写卡容量判断应使用实际解压后的镜像字节数。后续只按已核验的标准镜像制卡。见[构建文本发布条目](https://github.com/radxa-build/radxa-zero3/releases/expanded_assets/rsdk-b1)。

### Mac 串口的来源与判定

本机只读复核为 macOS 27.0.1（26A434）、arm64、Python 3.14.5。该解释器未找到 `serial` 模块，`termios` 未提供 `B1500000`。pySerial 固定源码的 Darwin 分支可通过 `IOSSIOSPEED` 请求 1500000 baud，驱动接受速率与有效收发仍需到货后验证。见[pySerial 固定源码](https://github.com/pyserial/pyserial/blob/0e7634747568547b8a7f9fd0c48ed74f16af4b23/serial/serialposix.py)。

| 步骤 | 来源与通过条件 | 停止条件 |
| --- | --- | --- |
| 固定工具 | PyPI wheel 候选 `pyserial-3.5-py2.py3-none-any.whl`，90585 bytes，SHA-256 `c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0`。独立工具环境在获准安装后核对 wheel 摘要、Python 版本、模块版本和终端入口。见[PyPI 文件记录](https://pypi.org/project/pyserial/3.5/#files)与[固定源码许可证](https://github.com/pyserial/pyserial/blob/0e7634747568547b8a7f9fd0c48ed74f16af4b23/LICENSE.txt) | 摘要、工具入口或解释器不符时停止，先核对固定输入 |
| 确认驱动绑定 | 到货后先辨认现有 macOS 驱动是否产生与适配器 VID/PID 一一对应的串口，再评审驱动增量。WCH 固定 revision `09629694b207cdce66861b6fe821b68993507be9` 列出 `CH34xVCPDriver.dmg`（3948032 bytes，Git blob `280ccbee87645ba1c4ffee2ac6fa3c88a03b75b7`）及 `.pkg`。如需安装，先绑定产物、独立 SHA-256、签名主体、公证状态、当前系统支持及精确卸载路径。见[WCH 固定目录记录](https://api.github.com/repos/WCHSoftGroup/ch34xser_macos/contents?ref=09629694b207cdce66861b6fe821b68993507be9)与[厂商说明](https://github.com/WCHSoftGroup/ch34xser_macos/blob/09629694b207cdce66861b6fe821b68993507be9/README.md) | 设备对应关系、来源或系统支持不清时停止。系统扩展与安装另走精确授权 |
| 适配器回环 | 先在适配器端验证 3.3 V 设置，板卡保持未连接。对唯一端口以 1500000、8N1、无硬件/软件流控进行受控回环，记录合成输入长度、摘要、收发计数与错误。回环应按 manifest 的观察窗完整返回输入 | 无法设置速率、回显不一致或错误不可解释时停在回环。回环结果只用于本适配器和当前驱动组合 |
| 板端冷启动 | 移除回环，再按 UART2_M0 接线，适配器 RX 接板 pin 8 TX、TX 接 pin 10 RX、共地接 pin 6，使用 3.3 V TTL，供电脚留空。先只收冷启动日志，出现预期登录提示后再在授权范围内交互。见[板端接口](https://docs.radxa.com/en/zero/zero3/hardware-design/hardware-interface) | 乱码、缺启动阶段、提示与预期不符或无法安全退出时保存脱敏诊断，停止该节点的后续用例 |

### 写卡前的核验与备卡救援

1. 来源判定通过后，未来操作包冻结下载位置、压缩镜像的固定长度和双摘要、解压及暂存上限。解压验证后记录原始镜像字节数及 SHA-256，确认授权目标卡的真实容量足够。压缩摘要漂移、解压失败或超额时停止。
2. 目标只允许选中经确认可覆盖的系统卡或恢复卡。写前用读卡器、物理标签与容量复核目标，插拔后重新确认路径。写后在首次启动前从目标介质回读原始镜像长度的范围，比对 SHA-256。目标不明或回读不符时保留原因，停止上电。
3. 原卡故障时先记录节点、故障点、卡的脱敏编号和最后已确认的持久标记，再隔离原卡。诊断原介质须先审定只读获取方式。备卡使用核验通过的基线镜像，逐台记录首次启动、串口、版本和重新配置结果。单板阶段只覆盖该板，三节点阶段复用备卡前重新确认目标和授权。
4. 恢复节点若无法安全重用原有应用状态，按 Node 的独立恢复验收处理身份与状态。备卡的启动结果归入 `HW1-05`，后续消息、去重和确认结果归入 `HW1-08`。见[到货后的验收顺序](#到货后的验收顺序)。

当前纸面结论为候选文件和对应验收步骤已定位。待关闭项包括镜像来源信任与固件许可/维护、交付版本和成本，以及串口驱动绑定与实测。当前仍为 HW-G0，以上供 HW-G1 复核及后续 HW-G3 操作包使用。

### 首轮范围与镜像信任评审（2026-11-08）

首轮暂按现有 1000 元上限与整套 3000 元上限评审。若选择单板，采购评审使用 748 元物料小计，距上限的 252 元须同时覆盖供电线缺口、实际价差、税运和预留。运行范围限该板的 `HW1-01/02`、本地关机与备卡启动。若选择首轮完整三节点，先明确新的首轮上限，再以暂缓功率计的 1824 元小计加实际费用核算。维持 1000 元且要求完整三节点时，先提交全套替代 BOM。见[预算取舍](poc-purchase-list.md#hw1-预算取舍2026-11-08)。

| 镜像路径 | 已取得的依据 | 待裁决与后续证据 |
| --- | --- | --- |
| 保留 Radxa b1 | 固定发行元数据、压缩镜像长度与双摘要，b1 包表、内核和引导候选已定位。提交签名与镜像证明分别记录。见[镜像发布与 BSP 证据](#镜像发布与-bsp-证据) | 优先取得绑定镜像摘要的可验证发布证据。若考虑用官方发布渠道与固定摘要作为有限隔离台架的信任依据，由所有者明确接受该用途，限该候选、纯有线隔离环境及合成数据。镜像本体双摘要、设备与软件前置仍按各自步骤核对 |
| 要求镜像本体签名，评审 Armbian 备选 | 官方 ZERO 3 页面列 `Armbian 26.8.1 Minimal (CLI)`、Debian 13、vendor 内核 `6.1.115`。通过官方入口取得对应的 `.sha` 与 `.asc` 小文件。见[板型发布页](https://armbian.com/boards/radxa-zero3)、[校验文本入口](https://dl.armbian.com/radxa-zero3/Trixie_vendor_minimal.sha)和[签名入口](https://dl.armbian.com/radxa-zero3/Trixie_vendor_minimal.asc) | 绑定本体、签名和获审签名者，按官方流程验签。再核对 3E 的实际 revision、设备树、双有线接口、UART、备卡恢复、BSP 许可及维护来源。候选核对结果供所有者决定是否改用该镜像。见[发布验签说明](https://docs.armbian.com/getting-started/choosing-an-image/#download-and-verification) |

Armbian 的校验文本指向 `Armbian_26.8.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz`，期望 SHA-256 为 `e78de9cb4b2d8ff1710c65c509d08faef1ba88c07fc3276b9dd637597e8234e8`。取得的 `.asc` 为 833 bytes，签名文件自身的 SHA-256 为 `559efd4683d27d533206509d68d7b318ce893551faf38399f047490c9a9137c3`。初次直连归档镜像的两次小文件读取均在 TLS 握手阶段超时，经官方下载入口复核成功。当前只核对小文件及标识，镜像本体与实际签名验证待执行。当前 PATH 可定位 `xz`、`shasum` 与 `diskutil`，未找到 `gpg`，备选验签还须绑定现有合格工具或单独评审安装。

所有者已选择首轮准备完整三节点，并优先评审 Armbian 的镜像签名路径。首轮新上限仍待明确，以暂缓功率计的 1824 元小计加实际费用和预留核算。下一份 BOM 复核逐项绑定三台交付 revision、赠送线数量、配件、税运、退换和预留。费用核齐后按 `3000 − 实际首轮支出` 核对后续余额，另列功率测量、交互、双端音频及携带供电的增量。

Armbian 官方下载入口的 HEAD 请求落到同名归档，响应长度为 394195116 bytes，供后续绑定压缩本体使用。验签评审先固定镜像长度、镜像和签名摘要、可用工具版本，以及从官方发布资料确认的签名主钥指纹。未来使用独立钥匙环，显式绑定 `gpg --verify <签名文件> <压缩镜像>` 的两个输入，核对实际签名键与获审主钥的关系。记录摘要、指纹、工具与验签结果。任何输入漂移、验签失败或身份不符时停止。通过后再核对 3E 设备树、双有线、串口和备卡路径，决定是否采用为台架基线。见[官方镜像入口](https://dl.armbian.com/radxa-zero3/Trixie_vendor_minimal)与[GnuPG 验签说明](https://www.gnupg.org/documentation/manuals/gnupg/Operational-GPG-Commands.html)。

当前为 HW-G0。HW-G2 采购评审等待实际到手额、首轮新上限和候选预检结论。写卡、首次启动及故障操作在具备设备和精确范围后进入 HW-G3。

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
