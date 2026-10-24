# Node 控制证明依赖评审准备

日期：2026-10-24。状态：**D14 评审方向已接受；实际采用与执行未批准**。供依赖、安全及许可证评审者使用，承接[身份/控制 profile D14](node-identity-control-profile.md#d11d14-接受记录)。本文分开记录公开 API 信息、已留存固定源码核对与尚未获得的完整图证据，不是新的 Phase A PASS 或软件安装合同。

## 候选职责与版本

| 候选 | 职责/拟议范围 | 已有证据与限制 |
| --- | --- | --- |
| coset `=0.4.2` | COSE_Sign1 结构、标准签名输入与编解码；优先默认无 std feature | 版本文档列出 Ed25519 -19；签验通过调用方 closure 完成。并不自带可信身份服务、密码后端或本项目严格 profile 校验 |
| ciborium `=0.2.2` | coset 的 CBOR 后端；评审确定性编码与受限解析 | coset 声明范围允许该版本，但未解析新 lock。公开说明的宽松数值解码不能证明拒绝非规范输入；完整资源行为须读固定源码和执行负例 |
| aws-lc-rs `=1.16.3` | 候选复用既有 AWS-LC 生态的 Ed25519、SHA-256 和安全随机能力 | 此版本已存在于 D2 固定图；本轮只读 API/source 核对，不代表新增直接使用已审计或未来图已固定 |
| mls-rs `=0.56.0` + mls-rs-crypto-awslc `=0.25.0` | 原 MLS 候选与 non-fips provider；正式 storage traits 接入方向按 D6 | 原图及许可证停止线不变；产品图拟去除 mls-rs-provider-sqlite 0.23.0，以 Node 单库承载事务；必须另审新图 |

公开依据为 [coset 0.4.2 API](https://docs.rs/coset/0.4.2/coset/)、[算法枚举](https://docs.rs/coset/0.4.2/coset/iana/enum.Algorithm.html)、[crate 元数据](https://docs.rs/crate/coset/0.4.2)及 [ciborium 0.2.2 元数据](https://docs.rs/crate/ciborium/0.2.2)。coset 0.4.2 发布于 2026-03-02，声明 MSRV 1.81，使用 alloc；std feature 为兼容性空操作。这是维护与构建输入，不是稳定性或安全审计结论。ciborium 0.2.2 发布于 2024-01-24；发布时间较早本身不能证明弃养或无漏洞。

不采用自行拼接 COSE/自行实现签名的替代方案。仅换成 CBOR 编码库仍缺 COSE 结构与标准签名输入，不能减少安全责任；再引入一套密码后端会增加图与跨实现差异，目前没有足够收益。若 coset/ciborium 不能满足资源与严格字节要求，应重新选型，不以宽松解码加吞错补救。

## 固定源码核对与证据层级

既有证据沿用 [D2 Phase A 记录](../testing/sw-g2-mls-rs-phase-a-authorization.md)的归档及仓库 [Cargo.lock](../../tools/spikes/sw-g2-mls-rs/Cargo.lock)。本轮只读核对 aws-lc-rs 1.16.3 的 `Cargo.toml`、`src/ed25519.rs` 及 mls-rs-core/provider 相关源码；不修改留存对象、不运行其中代码。

| 对象 | 固定标识/核对事实 |
| --- | --- |
| aws-lc-rs 1.16.3 `.crate` | SHA-256 `0ec6fb3fe69024a75fa7e1bfb48aa6cf59706a101658ea01bfd33b2b248a038f`，既有 lock/留存归档一致 |
| aws-lc-sys 0.40.0 `.crate` | 仓库固定 lock checksum `f50037ee5e1e41e7b8f9d161680a725bd1626cb6f8c7e901f91f942850852fe7`；新使用范围仍待复核 |
| 签名错误路径 | 1.16.3 提供 `try_sign` 返回 Result；`sign` 内部 expect。拟使用前者保留错误，不用 panic 代替签署失败处理 |
| 私钥恢复 | 使用正常 `from_pkcs8` 入口及库内格式校验，不设计跳过校验的恢复路线；本轮未恢复或生成任何键 |
| 版本边界 | 不使用 latest 页面推断 1.16.3 的 API；不随文档检索升级依赖，不宣称 FIPS 合规 |

coset/ciborium 的版本页面可读，但部分固定 source URL 读取失败；本轮没有取得与新归档 checksum 绑定的完整源码证据。latest 源码页面只能帮助定位，不能替代固定归档。暂未核验新包归档摘要、完整 LICENSE/NOTICE、签名/来源或 advisory；不得填成 PASS。

## 依赖图与许可证输入

已知直接边来自公开版本元数据：coset 0.4.2 normal 依赖 `ciborium ^0.2.1`、`ciborium-io ^0.2.0`；ciborium 0.2.2 normal 依赖 `ciborium-io ^0.2.2`、`ciborium-ll ^0.2.2`、`serde ^1.0.100`。这些只是声明范围，不是锁定的闭包；其传递包、build/dev/target 边、feature 统一结果和 native links 均待解析。不得手写新 lock 或拿网页 dependency 表替代 cargo 的正式结果。

coset 与 ciborium 上游声明 Apache-2.0；aws-lc-rs 1.16.3 manifest 为 `ISC AND (Apache-2.0 OR ISC)`。声明只是检索线索；完整随包材料、第三方归属、构建生成物和复制/留存范围仍须逐对象审查，不能由“内部使用”推定无义务。旧 mls-rs 图的 `debug_tree` 与 `r-efi` 证据/处置缺口仍以[许可证专题](../testing/sw-g2-mls-rs-license-disposition-review.md)为准，不通过选型草案关闭。

新图必须同时记录目标 `aarch64-unknown-linux-gnu` 与实际准备宿主图，区分目标运行依赖、宿主构建工具、测试依赖和随包源码。拟复用 non-fips 方向，不沿用旧 SQLite provider；Node 现有 SQLite 依赖、native links、feature 合并和 ABI 必须一起审查。旧图从 94 个包增减到多少尚未知，不能预报通过。

## 采用前必须关闭的工程项

| 门 | 评审输入与通过条件 |
| --- | --- |
| 固定来源 | 每个精确版本/registry/checksum/归档与实际使用源码一致；列出修改、生成代码、工具链、目标和全部 feature |
| 图与漏洞 | 新完整 lock、cargo metadata/tree、target/build/dev 边和 native links 差异；独立 advisory 审核，不继承旧 PASS、不扩大 ignore |
| 许可证 | 固定源码的正文/NOTICE/holder、实际产物与材料复制范围、旧缺口处置及 R2 合格复核；未知不按排除处理 |
| 严格解码 | 保留原始 protected/payload；重复键、非最短编码、额外字段/尾随数据与未知算法一律拒绝；规范化再比较不能掩盖原输入歧义 |
| 资源 | 512-byte 外层限制之外，对超大声明长度、嵌套、容器元素数、分配与错误路径验证写前/分配前上限；不先构建无限 Value 再校验 |
| 密码接口 | Result 错误贯穿库与 Node；用途分键；完整 Sig_structure 的 Ed25519 签验与独立向量一致；不接受假签名示例或自造 prehash |
| 身份/撤销 | 默认 provider 不赋信任；验证期/提交期/输出期同一授权约束，撤销先行、旧活动拒绝、报告无越权、重复无资源放大 |
| 联合事务 | 正式 trait 编译接入后验证全部写点、跨线程/错代数/重入、COMMIT 未知、内存对象丢弃；不以现有合成 SecurityUpdate 结果替代 |

## 后续工作包的边界

本轮仅完成公开资料查询、既有源码只读核对和文档设计，没有新增 manifest/lock、下载 `.crate`、解析依赖、安装、构建/运行候选、生成签名、启动 VM/网络或改变远程状态。

所有者已接受 D11—D14 并授权补齐完整数据 envelope/控制传输预算、专业复核输入和以下精确准备合同；不能直接执行依赖操作：

1. 单独准备新图的静态来源/解析包：冻结候选 manifest、Rust/Cargo、registry/source、目标/feature、确切命令、输出与留存目录、网络域、硬容量/时长、清理和停止条件，申请当前任务授权后才下载/解析。旧 spike 与证据对象只读，不运行依赖 build script 或产品功能。
2. 在固定图证据齐备后完成来源、advisory、许可证/NOTICE 与独立复核；原 mls-rs R2/Phase B 条件不变。不能为取得新图方便修改现有 gate 或 allowlist。
3. 另行准备真实候选编译/签验/正式 trait 验收包，列出合成测试向量、负例、资源与清理合同；前置满足并获精确授权后才执行。

还不能提交可执行命令表的原因是实际新闭包、目标环境与硬容量尚未确定；填入猜测目录/额度会制造不可审阅的授权。D14 当前只决定值得推进哪组候选。专业评审人选、材料交接范围、许可证处置和运行合同是后续真实输入，不请所有者通过“接受推荐”替代这些证据。

## 本轮静态预算复核

按严格定长 CBOR 的头部宽度计算：BindingV1 在 generation 使用 uint32 最大值时 160 bytes；39-byte content-type 对应的 protected map 为 80 bytes；ReceiptV1 payload 为 190 bytes，完整带 tag COSE 对象为 343 bytes；ControlV1 payload 为 157 bytes，完整对象为 310 bytes。两种对象均低于候选 512-byte 上限。计算使用本机 Python 标准库整数运算，不生成签名、不实现产品 CBOR parser，不证明协议互操作或解析资源通过。初稿手算低估了绑定包和 content-type 长度，已按上述计算更正，没有用错误预算执行候选。

文档检查与工作区复核见本轮交接；既有 63 项 Node 测试属于上一实现批次，本轮未将其重标为密码验证。
