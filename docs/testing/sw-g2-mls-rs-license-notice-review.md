# SW-EXP-003 mls-rs 0.56.0 许可证/NOTICE 补证与非实现者复核包

- 状态：Proposed（2026-09-03；R0、R1/R1b、R1c-I/R 与 R1d-P 已完成；R1c-R 以完整 schema 2 mapping 形成有效 `STOP/license-evidence`，R1d-P 已冻结固定 tree 缺口的独立判断、补证、上游澄清、分发与版本变更路径；没有执行这些路径；R2 与 Phase B 禁止）
- 日期：2026-09-02
- 证据编号：`SW-EXP-003`
- 前置结果：[mls-rs 0.56.0 实施与 Phase A 精确授权包](sw-g2-mls-rs-phase-a-authorization.md)的 D2 固定 94-package 图已正式 `PASS`
- 适用决策：[SW-G2 E2EE 与身份候选决策包](../security/e2ee-sw-g2-decision-package.md)

## 目的与结论边界

本文把 D2 后尚未关闭的两项门禁拆成可复核、可停止、逐单元授权的方案：

1. 为 crate archive 未携带足以覆盖 Cargo 声明及适用归属/NOTICE 的完整证据的 11 个 package，按 registry checksum、`.cargo_vcs_info.json` commit 与 `path_in_vcs` 收集不可变上游证据；
2. 由未参与 A2/A3、D2 runner 实施、D2 执行或本轮结果撰写的复核者，独立核对 D2 与许可证补证。

本文不判断组合、链接、商店发布或任何目标渠道在法律上合规，不把 Cargo license metadata 或 SPDX 表达式当作许可证正文，也不因 D2 四门全零推导完整第三方安全审计、候选采用、`SW-G2 PASS` 或 Phase B 授权。若目标分发方式需要法律意见，仍须由有资格的独立评审者给出；工程记录不得代替该结论。

## 授权单位

1. **R0：离线盘点与设计**：只读 D2 final evidence、固定 `Cargo.lock` 与保留 crate source，固定本包的 package、commit、网络来源、证据合同、判定和复核清单；只修改必要文档。2026-09-02 已按单次授权实施。
2. **R1：受限联网补证**：在 R0 形成 clean revision 后，仅访问本文列出的三个 GitHub 仓库和六个不可变 commit，产生新的许可证评审 evidence；不得修改 D/D2 evidence、依赖图、gate、provider 或 source。首次授权已于 2026-09-03 消费，因 `TimeoutError` 形成有效 `STOP/license-evidence`。
3. **R1b：单次全新补证**：只在首次 R1 结果已记录并形成新的 clean revision 后，使用同一 helper、host/commit/file selector 与资源边界从头产生独立 run；不得复用首次 run 的 partial 文件或隐藏其结果。单次授权已于 2026-09-03 消费，因另一个 raw 文件的 `TimeoutError` 形成第二份有效 `STOP/license-evidence`。
4. **R1c-P：替代传输设计**：记录 R1b 并精确设计以同一 commit tree blob SHA 和 Git Blobs API 取回同一文件正文；不改变 package、repository、commit、path selector、许可证判定或依赖 source。本单元仅修改文档，已按单次授权实施。
5. **R1c-I：离线实施与验证**：只在 R1c-P 形成 clean revision 后修改 helper/checker、schema 与 synthetic fixture；不得联网或创建 run。2026-09-03 已按单次授权完成并形成 clean revision `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7`。
6. **R1c-R：单次替代传输补证**：只在 R1c-I 经验证并形成新的 clean revision 后，以冻结 helper/checker SHA 和唯一命令从头产生第三个独立 run；不得复用前两次 partial。2026-09-03 的单次 L3 授权已消费，结果为有效 `STOP/license-evidence`。
7. **R1d-P：固定 tree 缺口处置设计**：只基于既有 R1c evidence，冻结独立许可证判断、不可变补证、上游澄清、分发清单、工程合同与版本/候选变化的分流条件；只修改本文、当前状态与文档索引。2026-09-03 已按单次授权实施，没有执行任一处置路径。
8. **R2：非实现者复核**：仅在某次 R1 或另行接受的后续证据合同形成有效完整 `PASS` 后，由符合独立性条件的复核者只读检查 D2、全部 R1 run 与仓库 lockfile，另存复核记录；当前执行者不能自我关闭该门禁。R1c-R 未形成 `PASS`，因此 R2 不具备前置条件且未授权。
9. **最终结果收口**：只有许可证证据轨与 R2 均有效 `PASS` 后，才可另行授权把候选结论同步到决策文档。中间 `STOP` 必须如实同步当前状态，但不构成候选采用或淘汰；Phase B 必须另建精确设计、实施与 L3 运行包。

笼统的“继续”“按计划做”或接受本文不授权 R1d-L/E/U/G/D/V 任一路径、第四次联网运行、R2、创建或修改 evidence、commit、push、Phase B、D2 重跑、gate/版本/provider/依赖 source/allowlist 变化、上游联系或其他候选。

## 固定 D2 基线

| 项目 | 固定值 |
| --- | --- |
| D2 run | `20260902-130415-49997.8P5Td6` |
| D2 clean revision | `64cf079a7b14a3ce90be92b93e56e2ad80555d80` |
| evidence 路径 | `artifacts/sw-g2-mls-rs/20260902-130415-49997.8P5Td6/` |
| manifest | schema `2` / `sw-g2-candidate-phase-a-v2`；SHA-256 `b42b4bd34142e71f44c020ec3c84ab0c329b2865b0e822efbf0adb53f0440a5f` |
| checksums | `32` 项；清单 SHA-256 `922ce41492cd7911a7be8c2c4f3aedf70e42116bce1b5fb0b03b6bdbdbbb4baa` |
| lockfile | `94` package；SHA-256 `c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7`；repository、D seed 与 D2 三份逐字一致 |
| gates | source/audit/deny/feature 均为 `0` |
| advisory | RustSec revision `5a0ebedfe8bdd2e295b171f4162f8c977bcad9a5`；1239 条；vulnerability 与 warning 均为零 |
| fixed graph | `lockfile_seeded: true`、`lockfile_written: true`、`mutable_cache_reused: false` |
| runtime | `completed`；`40525 ms`；峰值 `229278 KiB`；退出码 `0`；精确 run label 残留 `0` |

R1/R2 开始前必须重新只读复核上述值。任一摘要、package 数、gate、outcome/stage、seed contract、repository revision 或工作区预期不一致即 `INVALID`，不得用当前网络结果覆盖或解释漂移。

## R0 离线许可证缺口盘点

D2 固定图含 1 个本地 path package 与 93 个 crates.io package。93 个 registry package 的 Cargo license metadata 均非空，`cargo-deny 0.20.2` 的 licenses/advisories 结果为 `ok`；这只证明固定 metadata 表达式通过当前工具门。保留 archive 的精确复核表明，下列 11 个 package 都缺少足以覆盖其 Cargo 声明及适用 copyright/NOTICE 的完整随包证据；其中 9 个 archive 没有名称匹配 `LICENSE`、`LICENCE`、`NOTICE`、`COPYING`、`COPYRIGHT`、`AUTHORS` 或同类形式的文件，另有两个必须单独解释：

- `debug_tree 0.4.0` 的 `doc/build/LICENSE.adoc`（SHA-256 `56cd47a25f2bbb4f2f870c933aa04c47a2b68dea497f974c5c9c215583dec3dc`）是归属于 Asciidoctor Project 的文档构建资产 MIT 正文，不是 `debug_tree` package 自身的许可证证据；
- `r-efi 6.0.0` 的 `AUTHORS`（SHA-256 `d027e91dbc9cdbb2f1190068e498bd6b61cff022b6a032b191021ba658d96111`）包含项目 MIT 正文、copyright/作者清单及 Apache-2.0/LGPL-2.1-or-later 短告知，但没有后二者完整许可证正文。

表中 registry checksum 来自已提交的固定 `Cargo.lock`；repository/license 来自 D2 `cargo-metadata.json`；commit 与仓库内路径来自每个 archive 自带的 `.cargo_vcs_info.json`。commit 是发布包的本地 provenance，R1 仍须通过对应官方仓库的不可变 commit API 验证；浮动 tag、branch 或仓库默认分支不能替代。

| package | registry checksum | Cargo license | repository / commit / `path_in_vcs` |
| --- | --- | --- | --- |
| `debug_tree 0.4.0` | `2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57` | `MIT` | `martypapa/debug-tree` / `5b709de2d8872102b20b566c408d31d0662d7a9f` / `.` |
| `mls-rs 0.56.0` | `4392c3b3ed7d835ca8f318f85ca65d3f0d3e879538d6e70679827a2f3af72029` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `8f1b43f447a792ff9307f1c2c7f54da63914870e` / `mls-rs` |
| `mls-rs-codec 0.7.0` | `45bd834f164dc06c1fed805540ae307a460b7ed7c2769a35a376f1de577a0dc1` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `3a185cd2cf4c89c3cd30adf294d7c18d2735725e` / `mls-rs-codec` |
| `mls-rs-codec-derive 0.2.0` | `c8b31fb579767147e96686889f1e7459d6bd41a131b11d7cd130776cffadb1c3` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `5224ee3afd6f9f026d579f3ed17a8fdda121946e` / `mls-rs-codec-derive` |
| `mls-rs-core 0.27.0` | `e282079e5bd2fe95a009ac8af6a8e510924d876234ee494cd97f15f52de53cb0` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-core` |
| `mls-rs-crypto-awslc 0.25.0` | `858ba8df345ebbda20868b503fda4fb46a921ca0e035025cbbaed0c8b5245da0` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-crypto-awslc` |
| `mls-rs-crypto-hpke 0.21.0` | `b53db9a20568dec53e4f280ec8152c862b98efe105894e378d996be3305f32f2` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-crypto-hpke` |
| `mls-rs-crypto-traits 0.22.0` | `49171fd5c7c77cd29ec452dcc6f537b8c568084b97023dcc5c0d41140da8ceb4` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-crypto-traits` |
| `mls-rs-identity-x509 0.21.0` | `ec1ecb6a61a296b8240cea19171477293663dcc6540353dc8cbcda2d9f61039b` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-identity-x509` |
| `mls-rs-provider-sqlite 0.23.0` | `e8e52c2b3b9c3421fe4bd96266016306595a66c1f4830ee2f1a19d50b209895e` | `Apache-2.0 OR MIT` | `awslabs/mls-rs` / `a0eb41def0cf227034bde19b7c11e62ab2a74a03` / `mls-rs-provider-sqlite` |
| `r-efi 6.0.0` | `f8dcc9c7d52a811697d2151c701e0d08956f92b0e24136cf4cf27b57a6a0d9bf` | `MIT OR Apache-2.0 OR LGPL-2.1-or-later` | `r-efi/r-efi` / `7e1b0322d31d625f81a5656096330934f9cd835d` / `.` |

这 11 项不是“无许可证”或工具 gate 失败。缺口是 crate archive 本身不足以独立覆盖 Cargo 声明的全部正文、适用 copyright/NOTICE 与目标分发义务；同一仓库/commit 的多个 package 可以共享上游文件，但 mapping 必须逐 package 明示，不能只用仓库级推断替代。文件名命中、第三方资产正文或短告知均不得自动计为 package 的完整许可证正文。

## R1 受限联网补证方案

### 前置与允许外部范围

R1 只有在 R0 形成 clean revision、工作区干净、上述 D2/lock/source 摘要再次匹配且单独说明 L3 副作用后，才可申请一次执行授权。只允许匿名 HTTPS `GET`，不携带 token、cookie、GitHub 登录态或用户数据，不使用浏览器会话，不调用 Git/Cargo/Docker，不下载 crate/source archive，不访问 crates.io，也不创建远程状态。

允许 host 仅为：

- `api.github.com`：验证六个固定 commit，取得对应 tree SHA 和非截断 tree；
- `raw.githubusercontent.com`：只下载由已验证 tree 返回、且满足下述选择规则的同 commit 文本文件。

固定 commit API URL：

| repository | 固定 URL |
| --- | --- |
| `martypapa/debug-tree` | `https://api.github.com/repos/martypapa/debug-tree/git/commits/5b709de2d8872102b20b566c408d31d0662d7a9f` |
| `awslabs/mls-rs` | `https://api.github.com/repos/awslabs/mls-rs/git/commits/8f1b43f447a792ff9307f1c2c7f54da63914870e` |
| `awslabs/mls-rs` | `https://api.github.com/repos/awslabs/mls-rs/git/commits/3a185cd2cf4c89c3cd30adf294d7c18d2735725e` |
| `awslabs/mls-rs` | `https://api.github.com/repos/awslabs/mls-rs/git/commits/5224ee3afd6f9f026d579f3ed17a8fdda121946e` |
| `awslabs/mls-rs` | `https://api.github.com/repos/awslabs/mls-rs/git/commits/a0eb41def0cf227034bde19b7c11e62ab2a74a03` |
| `r-efi/r-efi` | `https://api.github.com/repos/r-efi/r-efi/git/commits/7e1b0322d31d625f81a5656096330934f9cd835d` |

每个 commit 响应的 `.sha` 必须逐字等于请求值；随后只允许访问同 repository 的 `https://api.github.com/repos/<owner>/<repo>/git/trees/<validated-tree-sha>?recursive=1`。tree 响应的 `.sha` 必须匹配且 `.truncated` 必须为 `false`。tag 只可作为响应外的附加说明，不作为 selector，也不允许请求 `main`、默认分支、`latest` 或浮动 release URL。

### 文件选择规则

对每个 package，只允许从对应 commit 下载：

1. `path_in_vcs` 的 package `Cargo.toml`，以及从该目录向仓库根逐级祖先中的 `Cargo.toml`，用于解析 workspace 继承；
2. 仓库根、上述祖先目录及 `path_in_vcs` 中 basename 不区分大小写匹配 `LICENSE`、`LICENCE`、`NOTICE`、`COPYING`、`COPYRIGHT`、`AUTHORS` 及其带后缀/分隔符变体的文件；
3. 上述目录下 `LICENSES/` 或 `licenses/` 目录内的普通文件；
4. 只有前述 `Cargo.toml` 明确引用 `license-file`、`readme` 或相邻归属文件时，才允许增加该精确相对路径，并在 mapping 中记录引用字段。

raw URL 必须按 `https://raw.githubusercontent.com/<owner>/<repo>/<fixed-commit>/<validated-tree-path>` 确定；path 必须逐字来自已保存的非截断 tree，拒绝 `..`、绝对路径、symlink/submodule、tree 外路径和重定向到其他 host。只接受非空普通文本；HTML、可执行文件、archive、LFS pointer 或二进制响应立即 `STOP`。

### 新 evidence 与资源边界

R1 只能新建私有目录：

```text
artifacts/sw-g2-mls-rs-license-review/<run-id>/
├── inventory.json
├── commits/
├── trees/
├── upstream/
├── package-license-mapping.json
├── http-observations.json
├── manifest.json
├── checksums.sha256
└── run.log
```

`manifest.json` 使用 schema 1 / `sw-g2-mls-rs-license-review-v1`，至少记录 R0 clean revision、D2 run/manifest/checksum/lock 摘要、11 个 registry checksum、六个 repository commit/tree SHA、每次请求的 method/host/path/status/content type/byte count、下载文件的 raw URL/SHA-256、package mapping、是否发现 NOTICE、网络/资源边界、开始/结束时间、outcome/stage/exit code。`checksums.sha256` 覆盖所有 final 文件并从仓库根自校验；finalizer 失败不得留下可误认的 `PASS` manifest。

批准时应固定一次性命令或临时 helper 的全文与 SHA-256。预计 1–10 分钟、HTTPS 请求不超过 40 次、下载不超过 50 MiB、evidence 不超过 100 MiB；10 分钟或 100 MiB 为用户态停止线。没有后台服务、端口、容器、系统设置或远程写入；成功与负向 evidence 默认保留，不修改/清理 D/D2 或其他历史 evidence。HTTP、rate limit、tree 截断、摘要、解析、资源、finalizer 或零后台进程检查失败时保留真实 `STOP/INVALID`，不自动重试、不改用 token、mirror、branch、tag 或搜索引擎。

### R1 helper 冻结状态

2026-09-03 首版 schema 1 helper/checker 的 SHA-256 分别为 `a980c2953a3dd3c1feb7780d534f2875fa14588fe0a2acb0054995a212fe1b54` 与 `0e6cb4017cf17791deea27954951df8377c38a76f6fb23e23e9eee6afa8a87a8`，对应首次 R1/R1b 历史运行。R1c-I 在 clean revision `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7` 上把 `scripts/run-sw-g2-mls-rs-license-review.py` 与 `scripts/check-sw-g2-mls-rs-license-review.sh` 的当前 SHA-256 冻结为 `e9e3c68c566993fda09a4822023537c3a3d4310719a1aa68ef64a3359f03b40b` 与 `78cd343d89db1c1d5303cc7a085de93d0ba176ee59387d55f9598c7a56bc5092`。helper 在任何 artifact 或网络请求前仍要求显式 40 位 clean revision、R0 revision 为其祖先，并逐项复核 D2 manifest/checksum/三份 lock、94-package metadata、11 个 archive checksum/Cargo/vcs provenance 和上述两个 archive 内文件事实。

当前 helper 只允许关闭 proxy/redirect 的 Python 标准库匿名 HTTPS 访问 `api.github.com`，按验证后的 tree entry blob SHA 派生 Git Blobs API URL；严格复核 `100644`/`blob`、entry SHA/size/URL、envelope `.sha`/`.encoding`/`.content`/`.size`、严格 base64、decoded size、Git blob SHA-1、decoded SHA-256 与 evidence checksum。新 run 使用 schema 2 / `sw-g2-mls-rs-license-review-v2`，checker 按 schema 分派并继续复核两份历史 schema 1 `STOP`；synthetic fixture 覆盖 R1c-P 冻结的 blob identity、encoding/base64/size/Git SHA-1、URL/mode、响应类型、decoded 内容、checksum 篡改与 schema 1 回归负例。无参数、未知 action、非法 revision 和不匹配 revision 均在 artifact/network 前拒绝。

### 首次 R1 结果

首次 R1 在 clean revision `30a5665ee74d04e20d94c05280747ef8ec2b9df0` 上执行唯一命令，run `20260903-120514-82051.tt412fp1` 于 `2026-09-03T12:05:14Z` 开始、`12:05:49Z` 结束，以 schema 1 / `sw-g2-mls-rs-license-review-v1` 的 `STOP/license-evidence`、退出码 `20` 收口。它完成 5/40 次匿名请求、下载 `142464` bytes，运行 `34408 ms`，未启动后台进程；前四次取得 `awslabs/mls-rs` commit `3a185cd2cf4c89c3cd30adf294d7c18d2735725e`、非截断 tree `062619fcb6fb7ee67e76172700dcdb7a12fe62d7`、根 `Cargo.toml` 与 `LICENSE-apache`，第五次读取同 commit `LICENSE-mit` 时发生 `TimeoutError`，没有 HTTP status、响应 body 或自动重试。

final evidence 位于 `artifacts/sw-g2-mls-rs-license-review/20260903-120514-82051.tt412fp1/`；manifest SHA-256 为 `9fc406d7411c491dfaec6c1c171441bee7fb17f39b81d621fe3df4c760173fc9`，9 项 checksum 清单 SHA-256 为 `e6722f2e374faae491f2c610ff1bf7220013107cf59bdcd053c2362e461848fe`，逐项自校验全部通过，final 普通文件总大小 `164108` bytes。该 run 是完整收口的有效负向运行证据，不是 `INVALID`；但 package mapping 尚为空，失败发生在证据采集未完成时，因此它只证明一次传输超时，不能证明 `LICENSE-mit` 或其他许可证正文不存在，不能形成许可证、NOTICE、候选淘汰或 `SW-G2` 结论。

### R1b 单次方案

R1b 仅用于区分首次 run 的瞬时传输失败与可重复来源缺口，不修改 helper、每请求 30 秒 timeout、判定、schema、host、六个 commit、文件选择、40 请求/50 MiB 下载/100 MiB evidence/600 秒上限或失败分类。首次 run 必须原样保留并在后续 R2/结果记录中并列出现；R1b 从头请求并新建独立 run，不消费首次 run 文件、不续传、不使用 token/cookie/proxy/browser session，不调用 Cargo/Docker/crates.io，不自动进行第三次运行。

本结果记录另获 commit 授权并形成 clean revision 后，R1b 的唯一候选命令形状为 `python3 scripts/run-sw-g2-mls-rs-license-review.py collect <R1b-clean-revision>`；该 revision 与 `30a5665ee74d04e20d94c05280747ef8ec2b9df0` 之间只允许包含本次结果文档，helper/checker SHA-256 必须仍为 `a980c2953a3dd3c1feb7780d534f2875fa14588fe0a2acb0054995a212fe1b54` / `0e6cb4017cf17791deea27954951df8377c38a76f6fb23e23e9eee6afa8a87a8`。形成完整 SHA 后，还必须连同 1–10 分钟预计时长、外部读取和新 evidence 副作用、结果保留与无自动重试边界单独申请一次 L3 授权；本方案不授权 commit 或执行。

### R1b 结果

首次 R1 结果与 R1b 方案已在 clean revision `443ed446f37b34cc035fe288d4788b1776dd1da4` 上收口；该 revision 与 `30a5665ee74d04e20d94c05280747ef8ec2b9df0` 之间只包含 `docs/README.md`、`docs/status/current.md` 与本文，helper/checker SHA-256 保持不变。R1b 的唯一命令在该 revision 上执行一次且未重试，run `20260903-121508-84631.nx_b_jte` 于 `2026-09-03T12:15:08Z` 开始、`12:15:43Z` 结束，以 schema 1 / `sw-g2-mls-rs-license-review-v1` 的 `STOP/license-evidence`、退出码 `20` 收口。

R1b 完成 3/40 次匿名请求、下载 `131504` bytes、运行 `35014 ms` 且未启动后台进程。前两次请求取得与首次 R1 相同的 `awslabs/mls-rs` commit `3a185cd2cf4c89c3cd30adf294d7c18d2735725e` 和非截断 tree `062619fcb6fb7ee67e76172700dcdb7a12fe62d7`；第三次读取同 commit 的 raw `Cargo.toml` 时发生 `TimeoutError`，没有 HTTP status、响应 body 或自动重试。首次 R1 已从完全相同的 raw URL 成功取得 `788` bytes、SHA-256 `b0473b7ca82733c423c14c7345ea36e8c46e7669d0b4e7295abcbbda67815fde`，因此 R1b 不能解释为文件不存在。

final evidence 位于 `artifacts/sw-g2-mls-rs-license-review/20260903-121508-84631.nx_b_jte/`；manifest SHA-256 为 `b0ed5c9e1c523d39f1e98e4d92accc1983f2cf27045323697221c5f66788f530`，7 项 checksum 清单 SHA-256 为 `465e3b7eb937397fa93c52c0451eba25780c39541484e5f6465a4117ca23c523`，逐项自校验和离线 checker 全部通过，final 普通文件共 8 个、总大小 `150028` bytes。该 run 是第二份完整收口的有效传输负向证据，不是 `INVALID`；但 package mapping 仍为空，两次失败点也不同，因此只支持 `raw.githubusercontent.com` 传输不稳定判断，不支持许可证/NOTICE 缺失、候选淘汰或 `SW-G2` 结论。不得原样自动进行第三次运行。

### R1c 替代传输精确方案

R1c 的目标只是在不改变上游对象身份和文件选择的前提下隔离 raw 传输故障。固定 package、registry checksum、3 个 repository、6 个 commit、commit/tree API、非截断 tree 要求、`path_in_vcs`、文件选择、manifest/workspace 解析、SPDX 正文分类、NOTICE/copyright mapping、失败判定、30 秒单请求 timeout、40 请求/50 MiB 下载/100 MiB evidence/600 秒上限全部保持。依赖图、gate、crate provider、crate source 和候选版本不变；网络传输 host 从 `api.github.com` 加 raw host 收窄为仅 `api.github.com`，但这仍属于 helper、请求路径和证据 schema 变化，必须分单元授权。

对每个既有 selector 选中的 tree path，R1c-I 应要求 entry 为 mode `100644` 的普通 `blob`，`.sha` 为 40 位小写十六进制，`.size` 为非负整数且不超过单响应上限，并忽略任何未验证的外部定位。helper 仅可自行派生 `https://api.github.com/repos/<owner>/<repo>/git/blobs/<tree-entry-blob-sha>`；若 tree entry 自带 `.url`，必须与派生 URL 逐字一致。一个 commit 内按 union path 一次请求一个选中 path，不跨前两次 run 复用响应、不续传，也不因相同 blob SHA 隐藏 path 到 commit tree 的 mapping。

Git Blobs API 响应必须是 JSON object，`.sha` 与 tree entry blob SHA 逐字相等，`.encoding` 仅接受 `base64`，`.content` 必须是字符串；只允许移除 API 行包裹产生的 ASCII CR/LF 后以严格 base64 解码，`.size`、tree entry `.size` 与 decoded byte count 必须一致。helper 还必须按 Git 对象规则复算 `SHA-1("blob " + decimal-size + NUL + decoded-bytes)` 并等于 blob SHA，再对 decoded bytes 应用现有非空、UTF-8、NUL、HTML、LFS pointer、archive/可执行语义和许可证文本检查。Git SHA-1 只用于匹配 commit tree 的对象身份，不单独充当安全摘要；官方 HTTPS API 响应、decoded SHA-256 与 evidence checksum 共同保留。blob SHA、API URL、envelope SHA-256、decoded SHA-256、tree path、commit 与 package mapping 必须同时进入 manifest/checksum；原始 JSON envelope 保存到 `blobs/`，decoded 文件仍保存到 `upstream/`，HTTP 下载量按 envelope 原始 bytes 计，两类文件都进入 evidence 大小与 checksum。

R1c-I 应把新 run 升级为 schema 2 / `sw-g2-mls-rs-license-review-v2`，旧 R1/R1b schema 1 evidence 原样保留。checker 必须按 manifest schema 分派：继续逐项接受并复核两份既有 schema 1 `STOP`，对 schema 2 只允许 Git Blobs API transport，并验证上述 tree-entry/blob/envelope/decoded 链。synthetic fixture 至少覆盖正确 blob、错误 tree blob SHA、错误响应 `.sha`、非 `base64` encoding、非法 base64、decoded size 漂移、Git blob SHA-1 漂移、tree URL 与派生 URL 不一致、非普通 mode、API HTML/redirect/空 body、decoded NUL/HTML/LFS/binary、checksum 篡改和 schema 1 回归；self-test 继续禁止真实网络。

R1c-P 只记录方案，不修改 helper/checker。后续 R1c-I、commit 与 R1c-R 已按独立授权依序完成；R1c-R 从头新建独立 run，没有读取前两次 partial 作为输入，没有使用 token/cookie/proxy/browser session，也没有调用 Cargo/Docker/crates.io。其结果见下节；不得自动进行第四次运行。

### R1c 实施与结果

R1c-I 只修改 helper/checker，并完成离线 self-test、综合 checker、仓库门禁与差异检查，以 `feat(security): use Git blobs for license evidence` 形成 clean revision `f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7`。R1c-R 的唯一命令 `python3 scripts/run-sw-g2-mls-rs-license-review.py collect f9f02b3a8d1e3cc438a2a20bc404bfbb9273b1a7` 随后按一次性 L3 授权执行一次且未重试，创建 run `20260903-124253-90340.y7_6lakz`，以 schema 2 / `sw-g2-mls-rs-license-review-v2` 的有效 `STOP/license-evidence`、退出码 `20` 收口。失败消息为 `upstream evidence does not cover every declared SPDX alternative`。

该 run 完成全部 6 个 commit、11 个 package mapping 和 38/40 次匿名请求；38 次请求均成功，下载 `676608` bytes，运行 `23526 ms`，没有启动后台进程。Git Blobs API transport、tree entry identity、envelope/base64/size、Git blob SHA-1、decoded SHA-256 和 final checksum 链全部通过；写入 manifest 前 evidence 为 `846635` bytes，final evidence 位于 `artifacts/sw-g2-mls-rs-license-review/20260903-124253-90340.y7_6lakz/`，共 70 个普通文件、`968673` bytes。manifest SHA-256 为 `f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203`；69 项 checksum 清单 SHA-256 为 `ea356f519af8a3a1bb7c4a0859bc8f862d27673b4fcd602de5a1fe5b271c7db4`，逐项自校验全部通过。

9 个 `awslabs/mls-rs` package 的固定 tree 均同时覆盖 `Apache-2.0` 与 `MIT` 正文。`debug_tree 0.4.0` 声明 `MIT`，保存的 `Cargo.toml` 与其引用的 `README.md` 未检测到 MIT 正文；`r-efi 6.0.0` 声明 `MIT OR Apache-2.0 OR LGPL-2.1-or-later`，保存的 `AUTHORS`、`Cargo.toml` 与 `README.md` 只检测到 MIT 正文，缺完整 `Apache-2.0` 与 `LGPL-2.1-or-later` 正文。六个 commit 的 `notice_present` 均为 `false`；固定 tree 不含 NOTICE 本身不自动构成失败，后续仍需结合分发义务判断。

R1c-R 已排除前两次 run 的 raw 传输故障作为本次停止原因，并把缺口收敛为固定 commit/tree 与冻结 selector 下的实质工程证据不足。该结论不证明许可证在其他来源中不存在，不判定法律违规，也不自动淘汰候选；但按照冻结的 R1 合同不能形成 `PASS`，因此不得进入 R2 或 Phase B，也不得通过自动第四次请求、扩大 selector、改变版本/source 或补写 evidence 制造通过。

### R1 判定

`PASS` 必须同时满足：

- 11 个 package 的 registry checksum、repository、commit、`path_in_vcs` 与本表一致；
- 六个 commit 与 tree 均由对应官方 repository 的固定 API 验证，tree 未截断；
- upstream/ancestor manifest 能把 package 名称、版本、license 与 workspace 继承闭合到 registry metadata；
- 每个 SPDX alternative 的上游许可证正文都已保留，或明确记录上游固定 tree 中不存在及其影响；Apache-2.0 路径的 NOTICE 存在性也逐 commit 明示；
- 每个 package 到正文、copyright/NOTICE 和 commit 的 mapping 完整，无浮动来源、摘要漂移、互相矛盾或未解释缺口；
- manifest、checksum、资源控制和零后台进程合同全部通过。

固定 tree 中没有 NOTICE 不自动等于许可证失败；它必须被明确记录并交由 R2 判断是否存在随分发 NOTICE 义务。无法支持 Cargo 声明的许可证表达式、仓库/commit/path 不匹配、正文或归属含义矛盾、只能依赖浮动页面或无法解释适用范围时，R1 为 `STOP`。证据缺失、tree 截断、checksum/finalizer 失败或输入漂移时为 `INVALID`。R1 的 `PASS` 只表示上游证据采集完整，不是法律合规结论。

## R1d-P 固定 tree 许可证缺口处置设计

### 固定事实与不可越界结论

R1d-P 只消费 R1c-R final evidence、本文已固定的 R0/D2 输入及当前仓库文档，不重新解析依赖、不联网，也不把本轮文档写入 evidence。以下事实保持不变：

- 9 个 `awslabs/mls-rs` package 的固定 tree 同时保留 `Apache-2.0` 与 `MIT` 正文；
- `debug_tree 0.4.0` 的固定 commit/tree、`Cargo.toml` 与其引用的 `README.md` 未检测到声明的 `MIT` 正文；archive 内 `doc/build/LICENSE.adoc` 是文档构建资产，不得替代 package 许可证；
- `r-efi 6.0.0` 的固定 tree 在 `AUTHORS` 中保留 MIT 正文和 Apache/LGPL 短告知，但没有完整 `Apache-2.0` 与 `LGPL-2.1-or-later` 正文；
- 六个 commit 的 `notice_present` 均为 `false`；这要求目标分发复核，不能单独推导许可证失败；
- R1c-R 的 transport、identity、mapping 与 checksum 有效，其 `STOP` 不得改写、删除或追认为 `PASS`。

`MIT OR Apache-2.0 OR LGPL-2.1-or-later` 中的 `OR` 表达许可证选择分支，但当前冻结的 R1 工程合同更保守，要求保留每个 declared alternative 的正文。RadishLink 是否可以为特定分发物选择其中一条分支、选择后需要携带什么正文/归属，以及这能否替代“全部 alternative”工程合同，属于独立许可证与产品分发判断。R1d-P 不自行回答该问题、不变更 gate，也不以 SPDX metadata、通用许可证模板或执行者推断代替适用授权与归属证据。

### 处置路径

| 单元 | 目的与必要输出 | 前置与停止条件 | 本包是否授权 |
| --- | --- | --- | --- |
| `R1d-L` 独立许可证处置判断 | 由项目所有者指定、未参与 R1 helper/evidence/本结果撰写的适格评审者，只读形成逐 package × 目标分发渠道矩阵；明确可选择的许可证分支、正文/归属/NOTICE/源码或修改义务、仍缺的精确证据及法律意见边界 | 必须覆盖当前公开源码仓库、内部 POC 镜像、未来公开 Linux 设备镜像、Android/iOS 伴侣应用、服务端部署与源码包；不适用项须说明理由。无法从既有证据确认适用授权、归属或选择权时为 `STOP`。它不是 R2，也不能修改 R1c evidence 或直接形成工程 `PASS` | 否 |
| `R1d-E` 不可变官方补证 | 只在 `R1d-L` 明确指出所缺对象后，收集能绑定到固定 package/version/commit 的官方不可变记录，并保存请求、对象身份、正文、摘要与逐 package mapping 到全新 evidence | 必须先冻结 host、精确 URL/object、为何适用于固定 commit、请求/时间/大小上限、schema/checker 与失败保留；浮动页面、搜索摘要、第三方转载或仅有通用模板均 `STOP`。属于新的 L3 外部读取 | 否 |
| `R1d-U` 上游澄清或修复 | 向 `debug_tree` / `r-efi` 维护者提出最小公开问题，请其明确 package/version/commit 的许可证选择、适用正文、归属和 NOTICE；保存问题与回复的不可变引用 | 外部写入必须另行授权并预审不含隐私或凭据的消息全文；新 commit 本身不自动追溯覆盖旧 commit，回复未明确适用对象或授权范围时仍 `STOP` | 否 |
| `R1d-G` 工程证据合同修订 | 仅当 `R1d-L` 明确支持特定 `OR` 分支选择时，另案决定是否从“收齐全部 alternative”改为“冻结并证明一个可选分支及其全部义务”，定义新 schema、迁移、未知字段和负例 | 这是许可证 gate/证据合同变化，必须独立设计、评审与授权；不得回写 R1/R1b/R1c 或改变其历史 outcome。缺少逐 package 选择、目标渠道、正文/归属与 reviewer 依据时不得实施 | 否 |
| `R1d-D` 下游分发清单与正文 | 在许可证判断和来源证据关闭后，设计产品第三方清单、逐组件版本/来源/选择分支、完整正文、copyright/NOTICE 与安装包/源码包/应用内入口的一致生成和校验 | 复制标准正文不能单独建立其对固定 package 的适用性；没有已接受的 provenance、选择与义务矩阵时不得创建分发产物。实现会改变产品分发面，须另行授权和测试 | 否 |
| `R1d-V` 版本/source/候选变化 | 仅在固定基线无法关闭时评估带完整许可证材料的新版本、其他 source 或替代候选 | 必须固定新 version/commit/checksum/lock，重新执行适用 Phase A、advisory、license 与非实现者复核；不得继承 D2/R1c `PASS` 部分，也不得自动淘汰当前候选 | 否 |

`R1d-E`、`R1d-U` 与 `R1d-V` 是互斥选择还是组合路径，必须由 `R1d-L` 的逐 package 缺口决定，不预设全部执行。尤其是：`r-efi` 可能存在“明确选择 MIT 分支”的处置空间，但只有独立评审和后续合同决定可以接受；`debug_tree` 即使 metadata 声明 MIT，也仍需要把适用授权、正文与归属如何进入目标分发物说清。两者不得用同一条宽泛例外合并放行。

### 推荐顺序与判定

1. R1d-P 先形成 clean revision，保持 R1c run 和 helper/checker SHA 不变；
2. 下一最小单元为 `R1d-L`，只读既有 evidence 并形成独立处置矩阵，不联网、不联系上游、不创建分发文件；
3. 项目所有者依据矩阵逐 package 选择 `R1d-E`、`R1d-U`、`R1d-G`、`R1d-D` 或 `R1d-V` 的精确设计单元；每个单元分别授权，不能用一次授权包揽外部读取、外部写入、gate 和依赖变化；
4. 后续新 evidence/合同只有在 provenance、正文、选择、归属、NOTICE、目标渠道与 checksum 全部闭合时才可 `PASS`；不确定项为 `STOP`，输入/身份/checksum/独立性失真为 `INVALID`；
5. R1c-R 永久保留为历史 `STOP`。只有新的证据轨 `PASS` 后才恢复 R2 前置；R2 仍须由符合原独立性条件的复核者执行，且不等同于 `R1d-L`；R2 前不得设计或执行 Phase B。

R1d-P 的完成只表示处置路径、输出和停止条件已冻结，不表示任何许可证分支已选定、缺失正文已获得、分发方案已合规或候选已通过。本轮不创建新的 evidence/schema/checker，不修改 helper、gate、版本、provider、依赖 source、lockfile、分发产物或历史 run。

## R2 非实现者复核

### 独立性条件

复核者必须明确声明未参与 A2/A3 gate/runner/checker 实施、D2 执行以及 D2/R0 结果撰写；当前执行者不满足该条件。复核可以由项目所有者指定的人类评审者或单独任务完成，但不得把同一执行者换一个会话标签视为独立。复核记录只使用任务/角色标识与日期，不写入私人凭据、邮箱、token 或签名密钥。

### D2 清单

复核者必须从仓库根独立完成并记录：

1. D2 final 文件均为预期普通文件、非 symlink；manifest SHA、32 项 checksum 清单 SHA 与逐项 `shasum -a 256 -c` 匹配；
2. manifest 是 schema 2 / v2、`PASS/phase-a-prepared`、revision `64cf079...`、94 package、seeded/written true、mutable cache false、exit `0`；
3. repository、D seed、D2 三份 lockfile 逐字一致且 SHA-256 为 `c6dfa...50c7`；历史 D 仍为 `STOP/feature-gate`、`0/0/0/1`，没有被 D2 改写；
4. D2 source/audit/deny/feature 为 `0/0/0/0`；`cargo-audit.json` 的 vulnerability/warning 为空且 advisory revision 固定；deny/source 输出与 manifest 相符；
5. 输入、固定 audit bundle/image/platform/toolchain 摘要相符；runtime 为 `completed`、未超 45 分钟/5 GiB、退出码 `0`，精确 run label 残留记录为零；
6. git before 为空、after 只含预期 `Cargo.lock`，运行没有 Phase B、候选编译/执行、真实数据、重试、evidence 清理或 push。

摘要缩写只用于文档可读性；实际复核必须使用本包和 D2 manifest 中的完整值。

### 许可证/NOTICE 清单

复核者还必须验证：

1. R1 inventory 与固定 lock/metadata/vcs provenance 的 11 行逐项一致；
2. commit/tree/blob API 原始响应、tree entry 到 decoded 文件的 identity/SHA 链能从 manifest/checksum 复现，所有来源都落在对应 schema 允许的 host、repository 与 commit；
3. upstream Cargo manifest/workspace 继承与 registry package 的 name/version/license 一致；
4. package mapping 对每个 SPDX alternative、copyright 和 NOTICE 存在性给出证据或明确缺口；
5. 区分“archive 未随包携带文件”“上游固定 commit 有文件”“工程证据完整”和“目标分发法律结论”，不得把前一项自动推导为后一项；
6. 若许可证选择、归属、NOTICE 或目标渠道义务仍需法律判断，结果必须保留为待独立许可证评审，不能以工程 `PASS` 消除。

### R2 输出与判定

R2 不修改 D2/R1 原始 evidence，只在 R1 run 下新增独立 `review/` 目录，保存 reviewer qualification、逐项结果、引用路径/摘要、未决问题、最终 `PASS/STOP/INVALID` 与 checksum。复核者不满足独立性、未逐项验证或原始 evidence 漂移时为 `INVALID`；发现真实来源、许可证、NOTICE、checksum 或运行合同缺口时为 `STOP`；只有清单全部通过且所有保留法律问题明确隔离时才为工程证据 `PASS`。

## 当前停止点与最小后续单元

R0/helper 已固定 11 个 package、3 个 repository、6 个 commit、registry checksum、网络 allowlist、证据合同和独立复核清单。首次 R1 与 R1b 均因不同 raw 文件的 `TimeoutError` 形成有效传输负向 evidence 并原样保留；R1c-I/R 已完成，schema 2 的 blob identity 与 11 行 mapping 均有效，但固定 tree 对 `debug_tree` 的 MIT 及 `r-efi` 的 Apache-2.0/LGPL-2.1-or-later 正文覆盖不足，因此 R1 仍为 `STOP/license-evidence`。R1d-P 已冻结 `R1d-L/E/U/G/D/V` 的分流、证据和停止条件，但没有执行任一路径。

下一个最小单元是先使 R1d-P 三份文档形成 clean revision，再由项目所有者另行指定适格独立评审者执行 **R1d-L**。R1d-L 只读既有 evidence，必须先获得目标分发形态与渠道输入；不联网、不联系上游、不创建或修改 evidence、gate、版本、依赖 source 或分发产物，也不能代替后续 R2。

当前没有 R1d-L/E/U/G/D/V、自动第四次 R1、R2 或 Phase B 授权。只有后续新证据轨达到有效完整 `PASS` 后，项目所有者才可指定符合 R2 独立性条件的复核者执行 R2；许可证证据轨与 R2 均关闭前不得设计或执行 Phase B。
