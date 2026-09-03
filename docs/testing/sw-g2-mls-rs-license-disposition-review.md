# SW-EXP-003 mls-rs 0.56.0 R1d-L 独立许可证处置评审

- 日期：2026-09-03
- 评审任务：`/root/r1d_l_independent_review`
- 基线 revision：`9d1341815bbb30de9ca7ac09f658139ab2346b17`
- 结果：`STOP/license-disposition`
- 适用范围：`debug_tree 0.4.0`、`r-efi 6.0.0` 与本文列出的六类渠道
- 前置：[许可证/NOTICE 补证与非实现者复核包](sw-g2-mls-rs-license-notice-review.md)的 R1c-R 与 R1d-P

## 资格与结论边界

评审任务 `/root/r1d_l_independent_review` 未参与 R1 helper/checker 实施、R1/R1b/R1c evidence 执行或此前结果撰写；本轮从冻结文件重新核对 checksum、mapping、package archive、Cargo metadata/lockfile 和仓库分发事实，满足 R1d-L 对当前两包处置评审的独立性要求。

本文是工程许可证证据处置评审，不是法律意见。本文可以区分已观察到的 package 身份、许可证 metadata、正文、归属、NOTICE、依赖适用条件和当前分发物，但不能代表版权所有者解释授权，也不能替项目决定组合、链接、商店、设备镜像、托管服务或源码分发在特定司法辖区的法律后果。需要许可证选择或渠道义务判断的项目保持 `STOP`，须由有资格且独立的法律评审者关闭。

R1d-L 不是 R2。它不修改 R1c evidence，不把 R1c-R 的 `STOP/license-evidence` 改写为 `PASS`，也不授权 R1d-E/U/G/D/V、R2 或 Phase B。

## 冻结输入与完整性复核

| 输入 | 复核值 |
| --- | --- |
| R1c-R run | `artifacts/sw-g2-mls-rs-license-review/20260903-124253-90340.y7_6lakz/` |
| R1c manifest | schema `2` / `sw-g2-mls-rs-license-review-v2`；`STOP/license-evidence`；revision `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7`；SHA-256 `f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203` |
| R1c checksums | `69` 项逐项通过；清单 SHA-256 `ea356f519af8a3a1bb7c4a0859bc8f862d27673b4fcd602de5a1fe5b271c7db4` |
| R1c mapping | `11` package / `3` repository / `6` commit；38 次 Git Blobs API 请求；无 retry；全部 tree 未截断，所有 mapping 的 tree/blob/base64/size/Git SHA-1/decoded SHA-256/checksum 链通过 |
| D2 lock | repository 与 D2 evidence 两份逐字同 SHA-256 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`；94 package |
| `debug_tree` archive | SHA-256/registry checksum `2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57` |
| `r-efi` archive | SHA-256/registry checksum `f8dcc9c7d52a811697d2151c701e0d08956f92b0e24136cf4cf27b57a6a0d9bf` |

复核路径包括 R1c `manifest.json`、`checksums.sha256`、`inventory.json`、`package-license-mapping.json`、两包对应 commit/tree/blob envelope 与 decoded `upstream/` 文件，D2 的 `cargo-metadata.json`、固定 `Cargo.lock` 和两份保留 archive，以及当前 Git tracked 文件、根许可证、产品定义、路线图、手机接入、安全架构与当前状态。没有读取外部页面或把浮动材料作为输入。

输入、独立性与 checksum 没有失真，因此本轮不是 `INVALID`。但适用授权、归属的下游表达和渠道义务尚未全部关闭，不能判为 `PASS`，最终结果为 `STOP/license-disposition`。

## 事实、推断与非结论

### 已复核事实

- 当前公开 Git 仓库只跟踪 spike 的 `Cargo.toml`、固定 `Cargo.lock`、拒绝 Phase B 的 `main.rs` 和评审脚本/文档；没有跟踪两包的 source、`.crate`、vendor directory、候选二进制、应用或产品镜像。`artifacts/` 被 `.gitignore` 排除，保留 archive/source/evidence 不属于公开仓库内容。
- D2 只完成固定图准备，没有编译或运行候选。保留的 candidate archive/source 位于 ignored evidence `.work`，没有形成包含 mls-rs 的内部 POC 产品镜像；文档中的 fixed Docker image 是评审环境，不是产品分发物。
- `debug_tree 0.4.0` 是 `mls-rs 0.56.0` 的 optional normal dependency，但固定配置启用 `mls-rs/std`，该 feature 展开包含 `dep:debug_tree`；D2 resolved graph 因此启用 `debug_tree`，依赖边无 target 条件。
- `r-efi 6.0.0` 由 `getrandom 0.4.3` 的 normal dependency edge 引入，但该 edge 只适用于 `cfg(all(target_os = "uefi", getrandom_backend = "efi_rng"))`。它出现在跨目标固定 lock/metadata 中，不等于会进入 Linux、Android、iOS 或普通服务端的最终二进制；最终 SBOM/构建产物仍须复核。
- 当前阶段没有 Android/iOS 应用、服务端部署、公开 Linux 设备镜像或正式源码包；这些是未来渠道。手机路线只冻结了“共享业务核心 + 原生适配层”的候选方向，E2EE 实现尚未选定。

### 有条件的工程推断

- 若未来 Linux、Android、iOS 或服务端构建继续使用当前 mls-rs `std` 配置，`debug_tree` 将是运行时构建图的一部分；是否被优化掉不应替代第三方组件清单与许可证处置。
- 若这些非 UEFI 渠道只分发最终二进制且不携带 vendor/source/cache，当前 target 条件表明 `r-efi` 不应进入该二进制；该推断必须由渠道对应的最终构建图、SBOM 与包内容验证，不能仅凭 lockfile 排除。
- 若源码包、SDK、构建容器或设备镜像携带完整 vendor directory、crate archive、registry source 或 build cache，则即使某个 crate 不进入目标二进制，也需要按实际复制内容重新判断其授权、正文和归属义务。

### 本文不作出的结论

- 不因 Cargo `license` 字段认定授权已经充分，也不因固定 tree 缺正文认定许可证不存在或使用违法；
- 不决定 `MIT OR Apache-2.0 OR LGPL-2.1-or-later` 中哪一条在法律上可选，也不把 SPDX `OR` 解释成必须同时履行全部分支；
- 不认定没有 `NOTICE` 文件就无 NOTICE/归属义务，也不从短告知补出缺失的完整 Apache-2.0/LGPL-2.1-or-later 条款；
- 不把当前仓库未携带 package payload 外推为未来产品渠道自动合规；
- 不淘汰 mls-rs 候选，不恢复 R2 前置，不形成 `SW-G2` 或 Phase B 结论。

## SPDX `OR` 与 R1 工程合同

`r-efi` 的 Cargo metadata、README 和 `AUTHORS` 均表达 `MIT OR Apache-2.0 OR LGPL-2.1-or-later`；这里的 `OR` 在表达式层面列出替代分支。R1 的冻结工程合同则有意要求收齐每个 declared alternative 的完整正文，以避免执行者在没有独立判断时自行选择分支。二者不是同一问题：前者描述上游声明，后者描述本项目历史 evidence 的通过条件。

因此，现有 `AUTHORS` 中完整 MIT 文本可能为后续“明确选择 MIT 分支”的工程路径提供输入，但本评审不据此作法律选择。若后续法律评审接受该选择，必须通过新的 R1d-G 合同记录 package、版本、commit、目标渠道、选择分支、适用正文/归属和负例；不得回写或重判 R1c-R。若仍坚持全部 alternative 合同，则缺失的 Apache-2.0 与 LGPL-2.1-or-later 完整正文仍须由新 evidence 轨闭合。

## `debug_tree 0.4.0` 处置

### 现有证据支持

- archive、Cargo metadata、固定 repository/commit/path 和 R1c tree/blob identity 相互一致；
- 固定 `Cargo.toml` 声明 `MIT`，记录作者 `Marty Papamanolis`、repository 与 README；
- 固定 README 描述功能，但没有许可证正文或适用授权说明；
- archive 中的 `doc/build/LICENSE.adoc` 属于 Asciidoctor 文档构建资产，不能作为 `debug_tree` package 的 MIT 许可证。

### 仍缺

- 明确适用于 `debug_tree 0.4.0`、commit `5b709de2d8872102b20b566c408d31d0662d7a9f` 源码的完整 MIT copyright/permission notice；
- copyright holder/年份与 Cargo author metadata 的关系，以及是否存在必须保留的第三方归属或 NOTICE；
- 各未来渠道应把正文与归属放在镜像、应用、容器或源码包何处的接受方案；
- 由有资格的独立法律评审者确认上述材料足以支持目标渠道。

### 推荐路径与精确前置

首选 `R1d-U`，不得用通用 MIT 模板或 r-efi 的材料代替。上游问题必须绑定 package `debug_tree 0.4.0`、registry checksum、固定 commit 和 repository，逐项询问：该固定源码是否全部以 MIT 授权、适用的完整 copyright/permission notice 是什么、是否有第三方例外或 NOTICE、回复是否明确覆盖该历史 release/commit。外部写入前须另行预审消息全文并取得授权；回复只有在维护者身份、适用对象和不可变引用均可保存时才可进入后续 `R1d-E` 新 evidence。

若上游不回复、无权确认、回复不追溯适用于固定对象或仍缺归属，则该包保持 `STOP`，转入 `R1d-V` 评估带完整材料的新版本/source/候选。只有适用授权与归属被接受后，才进入 `R1d-D` 设计逐渠道第三方清单与正文；`debug_tree` 没有 `OR` 分支，不适合用 R1d-G 的“选择一个 alternative”绕过缺口。

## `r-efi 6.0.0` 处置

### 现有证据支持

- archive、Cargo metadata、固定 repository/commit/path 和 R1c tree/blob identity 相互一致；
- Cargo metadata 与 README 都声明 `MIT OR Apache-2.0 OR LGPL-2.1-or-later`；
- 固定 `AUTHORS` 明示 triple-license，包含完整 MIT permission/warranty text、三个 copyright holder 范围和作者清单；archive 内同一文件 SHA-256 与固定 upstream decoded 文件一致；
- `AUTHORS` 只有 Apache-2.0 与 LGPL-2.1-or-later 短告知，没有后二者完整正文；固定 tree 没有 NOTICE；
- 对当前 Linux/Android/iOS/普通服务端目标，D2 metadata 中引入 `r-efi` 的唯一 edge 受 UEFI target 条件限制。

### 仍缺

- 有资格的独立法律评审者是否接受针对具体渠道选择 MIT alternative，以及完整 `AUTHORS` 中哪些内容必须随分发保留；
- 若不选择 MIT，绑定固定 package/commit 的完整 Apache-2.0 或 LGPL-2.1-or-later 正文及相应 NOTICE、源码、修改、重新链接或其他渠道义务；
- 每个最终构建/分发物是否实际包含 `r-efi` 的 SBOM 与包内容证据；
- MIT 分支被接受后，下游清单、正文和归属在设备镜像、应用、容器与源码包中的唯一生成和校验入口。

### 推荐路径与精确前置

首选在独立法律评审明确接受后进入 `R1d-G`，只为 `r-efi 6.0.0` 冻结 MIT alternative：必须绑定 checksum、commit、六类渠道的适用性、`AUTHORS` 完整文件/摘要、copyright 与作者清单、NOTICE 结论、未知渠道拒绝路径，并定义不回写 R1c 的新 schema/checker。R1d-G 通过后再进入 `R1d-D`，生成并验证实际包含该包的渠道所需第三方清单、MIT 正文与归属位置。

若独立法律评审不接受 MIT 选择，或项目决定保持“全部 alternative”工程合同，则先为 `r-efi` 单独设计 `R1d-E`，冻结能绑定该固定 package/version/commit 的官方不可变 Apache-2.0/LGPL-2.1-or-later 正文对象与新 evidence 合同；来源对象尚未在本轮读取，不能预先声称某个 URL 合格。仅在上游声明或归属本身有歧义时再使用 `R1d-U`。目标改为 UEFI、source/vendor 变化或固定版本不能关闭时进入 `R1d-V`，不得继承当前非 UEFI 适用性推断。

## Package × 渠道矩阵

表中 `PASS` 仅表示在当前可见分发物中已证明该 package payload 不适用，不是许可证合规结论；一旦进入列出的触发条件即转为 `STOP`。`STOP` 表示授权、归属、渠道义务或必要法律判断至少一项未关闭。

| package | 渠道 | 当前事实与适用条件 | 正文、归属、NOTICE、源码/修改处置 | 判定 |
| --- | --- | --- | --- | --- |
| `debug_tree 0.4.0` | 当前公开源码仓库 | tracked 内容只有 manifest/lock/stub 与评审材料；没有 package source/archive/vendor/binary，ignored evidence 不发布 | 当前无 package payload；若 Release/source snapshot 开始携带 vendor、cache 或二进制，须先完成 R1d-U/E 与 R1d-D | `PASS`（仅当前不适用性） |
| `debug_tree 0.4.0` | 内部 POC 镜像 | D2 是 prepare-only，未编译候选，也没有已记录的 mls-rs POC 产品镜像 | 当前无镜像内 payload；任何新内部镜像若用当前 `mls-rs/std` 构建，须按实际复制/二进制内容关闭 MIT 正文、归属和镜像内第三方清单 | `PASS`（仅当前不适用性） |
| `debug_tree 0.4.0` | 未来公开 Linux 设备镜像 | 当前配置的无条件 resolved edge 使其预计进入 Linux 构建；尚无最终镜像/SBOM | 缺适用 MIT notice 与 holder；须 R1d-U/E 后由 R1d-D 冻结镜像中的正文/归属入口，并复核 source/build cache 是否随镜像发布 | `STOP` |
| `debug_tree 0.4.0` | Android/iOS 伴侣应用 | 应用尚未实现；若共享 core 采用当前 `mls-rs/std`，该包进入构建图 | 除适用 MIT notice/holder 外，还缺应用内/随包第三方入口、商店渠道呈现和最终 SBOM 的独立判断 | `STOP` |
| `debug_tree 0.4.0` | 服务端部署 | 没有服务端实现；若服务端采用当前 `mls-rs/std`，该包进入构建图 | 缺适用 MIT notice/holder；还须区分仅内部托管、向客户交付二进制和分发 container/image 的实际模式，分别由法律评审与 R1d-D 关闭 | `STOP` |
| `debug_tree 0.4.0` | 源码包 | 正式源码包格式未冻结；若只含当前 first-party source+lock，不携带 package code，需由包内容清单证明；vendor/cache/full source 会复制该包 | vendor/full-source 路径缺适用 MIT notice/holder，必须先 R1d-U/E；任何 accepted source package 均需 R1d-D 定义第三方正文、归属、修改保留和校验 | `STOP` |
| `r-efi 6.0.0` | 当前公开源码仓库 | tracked 内容没有 package source/archive/vendor/binary，只在跨目标 lock 中出现；ignored evidence 不发布 | 当前无 package payload；若公开包开始携带 vendor/cache/二进制，必须重新按实际内容判断并应用已接受的 license branch | `PASS`（仅当前不适用性） |
| `r-efi 6.0.0` | 内部 POC 镜像 | D2 未编译候选且无 mls-rs POC 产品镜像；固定评审环境不是产品镜像 | 当前无镜像内 payload；后续非 UEFI 镜像须以 SBOM 证明排除，若携带 source/cache 或改为 UEFI 则先完成分支选择和 R1d-D | `PASS`（仅当前不适用性） |
| `r-efi 6.0.0` | 未来公开 Linux 设备镜像 | 当前唯一 edge 是 UEFI-only，预计不进入纯 Linux 最终二进制；尚无最终构建/SBOM，build cache/vendor 也未定义 | 若 SBOM 与包内容证明完全排除，可按不适用关闭；任何 source/cache/UEFI payload 都需要独立法律评审接受 MIT、R1d-G 与 R1d-D | `STOP` |
| `r-efi 6.0.0` | Android/iOS 伴侣应用 | 当前 UEFI-only edge 预计不进入应用二进制；应用与最终 SBOM 尚不存在 | 必须用 Android/iOS 实际构建图证明排除；若 source/vendor 随包或 target 条件变化，须完成 MIT 选择、AUTHORS 归属与应用内第三方入口 | `STOP` |
| `r-efi 6.0.0` | 服务端部署 | 当前 UEFI-only edge 预计不进入普通服务端二进制；部署/容器形式未冻结 | 必须用最终 SBOM 与 container 内容证明排除；含 source/build cache 或 UEFI 工件时须完成 MIT 选择、归属和分发/托管模式判断 | `STOP` |
| `r-efi 6.0.0` | 源码包 | 跨目标 lock 包含该 package；正式源码包是否 vendor 所有 lock package 未冻结 | 仅引用 lock 与实际复制 package source 必须区分；vendor/full-source 路径首选 MIT 分支法律判断 → R1d-G → R1d-D，若坚持全 alternatives 则先 R1d-E | `STOP` |

## 判定与下一步

R1d-L 最终判定为 `STOP/license-disposition`：独立性、输入和 checksum 有效，故不是 `INVALID`；但 `debug_tree` 的适用 MIT notice/holder 尚未取得，`r-efi` 的 MIT alternative 尚未由有资格的独立法律评审者接受，各未来渠道的最终 SBOM、分发物内容和第三方材料入口也未形成，故不能 `PASS`。

两包必须分流：

1. `debug_tree`：下一设计单元为 `R1d-U-P`，只起草并评审绑定 `0.4.0`/checksum/commit 的上游问题和回复接受标准；外部发送、R1d-E 收集与 R1d-D 实现均须分别授权。无有效追溯回复时转 `R1d-V`。
2. `r-efi`：先取得有资格的独立法律评审对“按渠道选择 MIT alternative、保留完整 `AUTHORS`”的明确结论；接受后设计 `R1d-G-P`，再设计 `R1d-D-P`。若不接受选择或仍要求全部 alternatives，则另案设计 `R1d-E-P`。
3. 六类未来渠道在实际构建前必须冻结 artifact 类型、目标 triple、是否 vendor/source/cache、分发对象、修改状态、SBOM 与正文/归属展示位置；未知字段或内容漂移必须拒绝，不能默认继承本矩阵。
4. R1c-R 永久保留历史 `STOP`；只有新证据/合同轨有效 `PASS` 后才恢复 R2 前置。R1d-L 不替代 R2，R2 前不得进入 Phase B。

本轮没有联网、联系上游、运行 Cargo/Docker、创建或修改 evidence、修改 helper/checker/gate/版本/provider/依赖 source/lockfile/分发产物、进入 R2/Phase B、清理 artifact、commit 或 push。
