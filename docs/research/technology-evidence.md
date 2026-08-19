# RadishLink 技术证据

## 用途

本文记录 2026-08-19 用于形成首版方案的主要一手资料、能支持的结论和不能外推的边界。链接内容更新后需要重新核对版本。

## 无线与硬件

| 来源 | 支持的事实 | 项目含义与限制 |
| --- | --- | --- |
| [IEEE 802.11ah-2016 页面](https://standards.ieee.org/ieee/802.11ah/4960/) | 标准为 Sub-1 GHz 免许可 WLAN 定义 PHY/MAC 修改，目标传输范围最高 1 km、最低数据率至少 100 kbit/s | 是标准设计目标，不是任意地区、模块、天线和环境的产品保证；该 amendment 已并入后续 802.11 版本 |
| [MM8108 产品简介](https://www.morsemicro.com/resources/product_brief/MM8108-Product-Brief.pdf) | 1/2/4/8 MHz、最高 43.33 Mbps PHY、USB/SDIO/SPI、WPA3、850–950 MHz | 证明芯片能力候选；不证明应用吞吐、Mesh 性能或特定地区合法性 |
| [MM8108-MF15457 数据表](https://www.morsemicro.com/resources/datasheets/modules/MM8108-MF15457_Data_Sheet.pdf) | 11 mm × 10 mm 模块、850–950 MHz、最高 26 dBm 芯片能力、USB/SDIO/SPI | 最终可用功率、频率、带宽和天线受地区与整机认证限制 |
| [MM8108-EKH01-01 产品简介](https://www.morsemicro.com/resources/product_brief/MM8108-EKH01-Product-Brief.pdf) | Raspberry Pi 4、Linux/OpenWrt、MM8108、HDMI/USB/Ethernet/音频和可选相机 | 适合应用与媒体 POC；不代表随身产品功耗与体积 |
| [MM8108-EKH19 产品简介](https://www.morsemicro.com/resources/product_brief/MM8108-EKH19-Product-Brief.pdf) | MM8108 USB 2.0 适配器、GL-MT3000 路由器和多地区能力 | 适合桥接和 USB 路线；完整内容以具体 SKU 与当前软件为准 |
| [HaLowLink 2 产品简介](https://www.morsemicro.com/resources/product_brief/HaLowLink-2_Product-Brief.pdf) | MM8108、2.4 GHz 802.11n、OpenWrt、32 MB NAND；列出美/加/澳/英/欧/日 | 适合快速拓扑 POC；未列出中国大陆，不能假设国内可用 |
| [HaLowLink 用户指南](https://morsemicro.com/resources/user_guides/HaLowLink%20-%20User%20Guide%20-%202.11.2.pdf) | 802.11s 是分布式多跳 Mesh；当前文档将其标记为 beta/实验用途 | 原型可评估，量产不能只依赖该功能当前状态 |
| [Morse Micro 802.11s 应用说明](https://www.morsemicro.com/resources/appnotes/MM_APPNOTE-32_How_to_configure_802.11s_Mesh.pdf) | 展示 HaLow 802.11s 与 2.4 GHz 接入/回传拓扑 | 支持双无线 POC 思路，不证明所有监管域可启用 |
| [ESP32-S3 数据表](https://documentation.espressif.com/esp32-s3_datasheet_en.pdf) | 2.4 GHz 802.11b/g/n、Bluetooth LE、双核 240 MHz、外设与有限片上/外接内存 | 没有 HaLow；适合辅助 MCU，不作为视频 Mesh 主控 |
| [ESP-IDF OTA 文档](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/ota.html) | OTA 可通过运行中固件接收更新，安全模式需要双 OTA 槽和 OTA Data 分区 | 首次可信固件仍需预烧录/有线；产品还需签名、安全启动与回滚策略 |
| [ESP32-S3 Secure Boot v2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/secure-boot-v2.html) | 启动和 OTA 镜像可验证签名并在验证失败时回退 | 支持辅助 MCU 的签名无线升级设计 |

## 手机接入

| 来源 | 支持的事实 | 项目含义与限制 |
| --- | --- | --- |
| [Android Wi-Fi Aware 概览](https://developer.android.com/develop/connectivity/wifi/wifi-aware) | Android 8/API 26 起提供附近发现与直接连接；硬件支持不是必然，运行时需检测 | 可做机会式手机直连，不能作为所有 Android 手机的基础中继 |
| [Apple iOS Wi-Fi API 概览](https://developer.apple.com/documentation/technotes/tn3111-ios-wifi-api-overview) | iOS 26 引入 Wi-Fi Aware，支持 iPhone 12 及以后机型；另有 Apple peer-to-peer Wi-Fi | 可评估新系统的跨厂商近距连接，不能等同 HaLow |
| [Apple Multipeer Connectivity](https://developer.apple.com/documentation/multipeerconnectivity) | 使用基础设施 Wi-Fi、Apple P2P Wi-Fi 和蓝牙发现/通信；进入后台会停止发现并断开会话 | 不适合承诺无人值守、全天后台中继 |

## 安全与媒体

| 来源 | 支持的事实 | 项目含义与限制 |
| --- | --- | --- |
| [RFC 9420：MLS](https://www.rfc-editor.org/info/rfc9420/) | 为异步群组提供连续认证密钥交换、前向保密和失陷后安全 | 是群组候选；仍需选择认证、投递、持久化和实现库 |
| [RFC 9750：MLS Architecture](https://www.rfc-editor.org/rfc/rfc9750.html) | 定义 MLS 的系统与信任架构 | 用于约束不可信投递服务和群组元数据边界 |
| [RFC 9605：SFrame](https://www.rfc-editor.org/rfc/rfc9605.html) | 为实时媒体帧提供与传输解耦的端到端认证加密 | 适合不可信中继媒体；密钥管理仍由应用完成 |
| [RFC 6716：Opus](https://www.rfc-editor.org/rfc/rfc6716.html) | Opus 支持低时延、宽码率范围、FEC 与 DTX | 支持实时语音首选；实际总带宽需加入包头、反馈和冗余 |
| [RFC 9000：QUIC](https://www.rfc-editor.org/info/rfc9000/) | 基于 UDP 的安全多路复用传输 | 是消息/附件与地址迁移候选，不自动解决离线寻址和 E2EE |

## 中国大陆法规材料

| 来源 | 支持的事实 | 项目含义与限制 |
| --- | --- | --- |
| [工信部公告 2019 年第 52 号](https://www.miit.gov.cn/zwgk/zcwj/wjfb/gg/art/2020/art_4f2c890530cc4837b2113cf977e249c4.html) | 微功率短距离设备必须符合具体目录与技术要求，不得擅自扩频、加功率或改天线 | 不能只凭“Sub-1 GHz 免许可”宣传在国内试射 |
| [工信部《无线电发射设备管理规定》](https://www.miit.gov.cn/zcfg/wxdl/art/2023/art_4ef6b3a619f0444697197ae33a901ce3.html) | 规定生产、进口、销售和使用的设备管理要求 | 采购评估板与未来整机应分别确认进口、型号和使用义务 |
| [900 MHz RFID 技术要求](https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20243/0259e612a2424f0faf87ea6c8d170bd0.pdf) | 920–925 MHz RFID 的占用带宽不大于 250 kHz，并有信道、功率和跳频条件 | 不能把 RFID 条件扩大解释为 1–8 MHz 802.11ah 通用许可 |

## 尚缺证据

- 目标测试地区对精确 MM8108 SKU、802.11s、信道宽度、功率和天线的书面结论；
- 500 m 和 1 km 下的 RadishLink 自有应用吞吐、时延、丢包、功耗与温升；
- MM8108 当前 OpenWrt 在三节点与双无线并发时的稳定性；
- 选定 Linux SoM 的硬件视频编码、可信启动、待机功耗和长期供应；
- 一对一与 MLS 实现库的许可证、审计和崩溃恢复测试；
- Android/iOS 在具体机型上的后台、热点并发和本地网络体验。

缺少这些证据时，相关内容保持“目标”或“候选”，不提升为产品能力。
