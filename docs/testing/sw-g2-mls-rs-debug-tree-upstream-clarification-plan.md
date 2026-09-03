# SW-EXP-003 `debug_tree 0.4.0` R1d-U-P 上游澄清设计

- 日期：2026-09-03
- 基线 revision：`5de2a3fa746ede8fd48dfd1b03118b20195649be`
- 单元：`R1d-U-P`
- 状态：`Proposed`
- 当前结果：`STOP/upstream-clarification-not-sent`
- 前置：[R1d-L 独立许可证处置评审](sw-g2-mls-rs-license-disposition-review.md)

## 目的、范围与非目标

本单元只冻结一份可由项目所有者预审的公开上游问题、外部写入边界、回复证据要求和接受/停止条件。目标是询问 `debug_tree 0.4.0` 的维护者：Cargo metadata 声明的 MIT 是否追溯适用于固定 package/commit、应保留的完整 copyright/permission notice 是什么，以及是否存在第三方例外或 NOTICE。

本单元不联网、不检查当前 GitHub Issue 状态、不发送消息、不联系维护者、不创建或修改 evidence，也不补写通用 MIT 模板。它不修改 R1c 历史 `STOP`、helper/checker、许可证 gate、版本、provider、依赖 source、lockfile 或分发产物，不进入 R1d-E/R1d-D/R1d-V、R2 或 Phase B。本文不是法律意见，也不证明许可证不存在、使用违法或候选应淘汰。

## 冻结对象与已知缺口

| 字段 | 冻结值 |
| --- | --- |
| package | `debug_tree 0.4.0` |
| crates.io registry checksum | `2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57` |
| repository | `martypapa/debug-tree` |
| repository URL | `https://github.com/martypapa/debug-tree` |
| commit | `5b709de2d8872102b20b566c408d31d0662d7a9f` |
| tree | `edc1ea9120f5d4070eb0fa60c77ab0da4c8a3e92` |
| package path | `.` |
| Cargo declaration | `license = "MIT"` |
| R1c manifest | SHA-256 `f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203` |
| R1c mapping | `missing_license_texts = ["MIT"]`；`copyright_paths = []`；`notice_paths = []` |

R1c 已验证该 commit 的非截断 tree、`Cargo.toml` blob `6bf9ab3e7c684aae886d806d5355ebf7e60ef120` 和 `README.md` blob `84511aad0bd56132241dc7389d4013f986e85053`，但没有取得适用于上述固定源码的完整 MIT notice/holder。archive 中的 `doc/build/LICENSE.adoc` 是 Asciidoctor 文档构建资产，不是该 package 的 MIT 许可证。上游问题不得把这一缺口扩大表述为“无许可证”或“违规”。

## 外部写入合同

### 唯一目标与动作

后续执行单元暂命名为 `R1d-U-X`。它只允许在官方 repository `martypapa/debug-tree` 的公开 GitHub Issues 中新建一个 Issue，标题和正文必须与本文冻结文本逐字一致；不添加 label、assignee、milestone，不创建 Pull Request、Discussion、commit 或 Release，也不向邮箱、社交媒体或其他仓库发送副本。

执行前必须另行取得当前任务的 L3 外部写入授权，并只读确认：

1. repository 仍解析为同一 owner/name，固定 commit 仍可由官方 repository 读取；
2. Issues 已启用，当前登录账号与拟公开身份已由项目所有者确认；
3. open/closed Issues 中没有绑定同一 package/version/checksum/commit 且问题等价的现有条目；
4. 标题、正文 UTF-8 bytes 与本文冻结值一致，未含 token、cookie、私人邮箱、内部路径、未公开产品细节或安全漏洞；
5. 已冻结全新的 R1d-U evidence 目录、schema/checker、请求上限和失败保留合同。

任一项不满足时必须在外部写入前停止；Issue 不可用时不得自动改用邮件、Discussion、Pull Request 或其他账号。发现等价现有 Issue 时只记录候选 URL 并停止，由项目所有者另行决定是否只读补证或公开回复。

### 冻结标题

```text
License notice clarification for debug_tree 0.4.0
```

### 冻结正文

正文使用英文以面向上游维护者；发送时保留段落、列表、反引号和完整摘要，不附带本地 evidence 或用户信息。

<!-- R1D_U_ISSUE_BODY_BEGIN -->
```text
Hello, we are reviewing `debug_tree 0.4.0` for possible redistribution.

The published crate metadata declares `license = "MIT"`. We are looking specifically at:

- crate: `debug_tree 0.4.0`
- crates.io checksum: `2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57`
- repository: `https://github.com/martypapa/debug-tree`
- commit: `5b709de2d8872102b20b566c408d31d0662d7a9f`

We could not locate a complete MIT copyright and permission notice that states it applies to the published crate contents and that commit.

Could a maintainer please clarify:

1. Is all source distributed in this exact crate release and commit, except any explicitly identified third-party portions, offered under the MIT License?
2. What complete copyright and permission notice, including the applicable copyright holder name(s) and year(s), should redistributors preserve?
3. Are there any third-party code exceptions, additional attribution, or NOTICE requirements for this release?
4. Does this clarification apply retrospectively to the published `debug_tree 0.4.0` crate and the exact commit above?

If practical, could this clarification be recorded in an immutable commit in the official repository, for example by adding the applicable license notice and a note that identifies `0.4.0` and the commit above? A repository commit would give downstream redistributors a stable provenance reference.

This is a license-provenance and redistribution-documentation question, not a security report. Thank you.
```
<!-- R1D_U_ISSUE_BODY_END -->

发送正文的规范 bytes 是两条 HTML marker 之间 `text` fence 内的内容，不含 fence 行；使用 UTF-8、LF 换行，并在最后一行后保留一个 LF。标题 bytes 不含末尾 LF。标题 SHA-256 为 `aa627aa1f8c9da8cac0805c5a28744bb76a1b8e123e3fbefdac296648ab3f01a`，正文 SHA-256 为 `38fd3a3115c216ec5455a7b0abd550e92676dc1345b20870b1006305c8a1bdb8`；R1d-U-I 必须把两者固化为 preflight 常量。任何字符变化都须回到设计评审，不得在发送界面临场改写。

## 新 evidence 要求

R1d-U-X 不得写入 R1c run。它必须使用全新的 `artifacts/sw-g2-mls-rs-license-upstream-clarification/<run-id>/`，采用 schema `1` / `sw-g2-mls-rs-license-upstream-clarification-v1`，并由 R1d-U-I 的 checker/finalizer 拒绝未知 schema、未知字段、symlink、非普通文件、摘要漂移和已 final 目录修改。

R1d-U-X 只保存创建 Issue 的一次性 run；成功创建后立即以 `STOP/awaiting-upstream`、退出码 `20` final，不得在该目录追加回复。收到上游活动通知后，另行授权的 `R1d-U-R` 才可新建独立只读 run，引用 R1d-U-X manifest/Issue identity 并保存当时的 Issue、comments、events 与引用对象。R1d-U-R 不自动监控、不回复、不编辑或关闭 Issue。

R1d-U-X 的网络合同固定为仅访问 `api.github.com` 的 HTTPS 443：最多 20 次请求、恰好最多一次创建 Issue 的 `POST`、其余只允许 `GET`，单请求 timeout 30 秒、累计下载上限 5 MiB、final evidence 上限 20 MiB、墙钟上限 300 秒、零 retry、零后台进程。禁止 `PATCH`、`PUT`、`DELETE`、GraphQL mutation 和自动 follow-up。任何 `POST` 后的 timeout、连接中断或无法解析响应都属于外部状态不确定：必须 final 为 `INVALID/ambiguous-external-write`，不得重发；后续只能在新授权的只读 run 中按精确标题、正文 SHA、作者和创建时间核对是否已生成 Issue。

R1d-U-R 固定为零写请求、最多 10 次 `GET`、同样的 30 秒单请求 timeout、5 MiB 下载、20 MiB final、300 秒墙钟、零 retry 与零后台进程。若回复分页超出上限或引用对象需要额外请求，完整保留为 `STOP/evidence-limit`，不得扩大上限后在同一 run 续跑。

各 run 至少保留：

- 本文 revision、固定 package/version/checksum/repository/commit/tree 与 R1c manifest SHA-256；
- 发送前 repository/commit/Issues/重复条目只读检查的请求 URL、状态、响应 headers/body、GitHub object identity、获取时间和 SHA-256；
- 精确标题/正文 bytes、它们的 SHA-256、执行账号的公开 GitHub login/id，以及敏感 header 已排除的请求摘要；
- 创建 Issue 的 HTTP status、未重定向 API URL、原始 JSON response、issue number/node id/URL、author login/id、created/updated time 和 body SHA-256；
- R1d-U-R 中后续回复的原始 JSON、comment/node id、author login/id、created/updated time、正文及 SHA-256，以及回复引用的 official commit/tag/blob 对象；
- manifest、逐文件 checksum、请求/响应 byte count、timeout、退出码、无 retry 记录和零后台进程结果。

认证必须由项目所有者确认的既有 GitHub 客户端/session 提供；不得在命令参数、环境转储或日志中显示凭据。账号 preflight 只把 allowlisted 的公开 `login`、numeric `id` 与目标 host 写入 evidence，不保存认证账号 API response 中的私人字段。不得保存 Authorization、cookie、session、token、私人邮箱或浏览器 profile。Issue HTML 截图、搜索摘要、通知邮件、第三方镜像和可编辑网页文本不能单独充当许可证 provenance。公开 Issue/comment 可被编辑或删除，因此只保存其 API 响应与 checksum 仍不足以形成最终接受；有效回复还必须指向下节要求的官方不可变对象。

## 回复接受标准

只有以下条件全部满足，R1d-U 才可形成 `PASS/upstream-clarification`，并允许另案设计 R1d-E；该 `PASS` 仍不恢复 R2 前置，也不替代独立法律评审或 R1d-D：

1. 回复账号能够从官方 repository 的公开状态证明是 owner/maintainer，或回复明确说明其代表版权所有者/维护团队作出澄清的权限；仅凭同名账号、普通 contributor 或第三方转述不接受。
2. 回复逐项绑定 `debug_tree 0.4.0`、registry checksum、repository 与完整 commit，不只描述当前默认分支、未来 release 或泛指“项目”。
3. 回复明确说明固定 release/commit 中哪些源码受 MIT 授权，并提供适用的完整 copyright/permission notice，包括应保留的 holder 与年份；只回复 SPDX 标识、通用模板链接或“是 MIT”不接受。
4. 回复明确列出第三方例外、额外 attribution/NOTICE，或明确确认没有已知的此类额外要求；含糊的“不确定”保持 `STOP`。
5. 回复明确追溯适用于已发布的 `0.4.0` 与固定 commit，而不是仅承诺在新版本中添加许可证文件。
6. 官方 repository 中存在由回复引用的不可变 commit/blob，保存完整 notice，且 committed 内容本身明确建立它与 `0.4.0`/固定 commit 的追溯关系；Issue/comment permalink 本身不满足不可变对象要求。

满足 1–6 只说明上游澄清可进入 R1d-E，不直接授权复制材料或生成产品分发文件。新 R1d-E 必须从官方 host 重新取得上述对象，验证 repository/commit/tree/blob/text/checksum/mapping，且没有身份、正文、归属或适用范围矛盾；随后仍须由有资格的独立法律评审者判断材料是否足以支持具体渠道，再设计 R1d-D。

## `STOP`、`INVALID` 与转 R1d-V

- Issue 成功创建但尚无合格回复时为 `STOP/awaiting-upstream`；本设计不创建自动监控、deadline 或 follow-up。R1d-U-R 只在项目所有者已观察到上游活动或明确要求一次性检查时运行。
- 回复者权限无法确认、缺完整 notice/holder、遗漏第三方/NOTICE、只覆盖新版本、拒绝追溯适用、引用对象可变或内容矛盾时为 `STOP/upstream-unresolved`。
- 项目所有者结束等待、维护者明确无法为固定对象澄清，或官方渠道不可用且没有另获授权的等价渠道时，保持历史证据并转入 `R1d-V-P`；不得用通用 MIT 模板、其他项目文件或执行者推断制造通过。
- 发送到错误 repository、标题/正文漂移、重复发帖、身份/固定对象漂移、response/checksum 缺失、凭据进入 evidence 或 finalizer 失败时为 `INVALID`。若外部 Issue 已创建，必须如实保留 URL 和错误，任何编辑、关闭或删除都是新的外部写入，须另行授权。
- 维护者回复后需要追问时，不得自动发送；先保存本轮结果并冻结唯一追问全文，再取得新的外部写入授权。

## 后续单元与授权边界

R1d-U-P 形成 clean revision 后，最近的单元是 `R1d-U-I`：只离线实施独立的 schema 1 helper/checker、固定标题/正文摘要、preflight/finalizer 与 synthetic 正负例，不联网、不创建 Issue、不创建正式 evidence。synthetic 至少覆盖正确 X/R manifest、标题或正文漂移、错误 repository/commit/checksum/account、重复 Issue、零或多次 POST、POST 后歧义、redirect、HTML、分页/大小/时间超限、unknown field/schema、回复者无权、缺追溯适用、缺完整 notice/holder、可变引用、checksum 篡改、凭据字段和 final 后修改。

R1d-U-I 形成 clean revision且离线门禁通过后，才能另行精确授权 `R1d-U-X` 的一次性外部写入；该授权必须明确公开 GitHub 账号、唯一 Issue 标题/正文、目标 repository、网络读取、资源上限和证据目录。R1d-U-X final 后，R1d-U-R 的一次性只读检查与任何公开追问仍分别授权。

单独授权 R1d-U-I、R1d-U-X、R1d-U-R、回复/追问、R1d-E 收集、法律评审、R1d-D、R1d-V、commit 或 push，彼此均不自动包含。

在新的上游澄清与证据轨有效闭合前，`debug_tree` 保持 `STOP/license-disposition`，R1c-R 保持历史 `STOP/license-evidence`，R2 前置不满足，Phase B 禁止。
