# Node 身份绑定、撤销与 COSE profile

日期：2026-10-24。状态：**D11—D14 已接受，见 [ADR 0006](../adr/0006-node-identity-and-control-profile.md)；实现与运行未通过**。面向协议、安全与 Node 实现评审者；承接 [ADR 0005](../adr/0005-node-security-integration.md)，不改变其 D6—D10，不代表 SW-G2、R2 或 Phase B 通过。本文定义已接受的公共绑定与控制消息评审基线；不定义手机配对传输、完整消息 envelope、网络发现或生产密钥存储实现。

## 设计边界

- A/C 的内容会话只包含 A/C；B 持有公开信任映射并转发密文，不进入该私聊 MLS group。
- 可信配对确认“眼前的人所持 Node 在本次活动使用哪些键”；签名、自报昵称、IP/MAC 或自带证书均不能单独建立该信任。
- 同一活动中的 MLS 签名键、交付证明键、撤销控制键分别生成，禁止复用或从一个公开标识推导。加密、随机数、摘要与签名均调用通过评审的库，不自研密码算法。
- 公开控制消息泄露活动内标识、消息关联、交付或退出事实；不携带正文、正文摘要、全局设备标识或真实姓名。活动内仍可关联，不能宣传匿名通信。

## D11：活动内直接绑定

推荐 3–5 人入场前逐对验证；共有 3–10 对关系，每对双向确认。全队使用同一个随机 32-byte `activity_id`，每个 Node 为本次活动生成随机 16-byte `participant_id`，冲突拒绝。活动标识不是授权令牌；没有队长替其他成员背书的权限。

公开绑定包使用下列固定顺序的 CBOR array，不携带私钥：

```text
BindingV1 = [1, activity_id, participant_id, credential_generation,
             mls_signature_public_key, receipt_public_key, control_public_key]
```

| 字段 | 候选约束 |
| --- | --- |
| `activity_id` | bstr，恰好 32 bytes |
| `participant_id` | bstr，恰好 16 bytes；同活动唯一 |
| `credential_generation` | uint，1..4294967295；从 1 起，替换递增，不回绕、不复用；不是 MLS epoch |
| 三个公钥 | 各为 32-byte Ed25519 raw public key，彼此不同；由库验证格式/使用条件 |
| `credential_ref` | `SHA-256(确定性编码的 BindingV1)`，恰好 32 bytes；指纹显示完整 64 个十六进制字符 |

所有编码采用下文严格 CBOR 规则。绑定包最长 160 bytes；这是字节预算计算，不是硬件扫码测试。指纹只用于公开绑定确认，不对正文计算可公开猜测的摘要。

推荐基线为在双方 Node 或可信本地界面核对完整指纹，再由双方本机所有者确认；可由已授权伴侣手机直接扫描对方展示的完整绑定包减少输入，但不能把手机或相机变成设备运行前提。扫描网络转发的图片、仅比较同名或短验证码不算完成。手机界面的既有授权必须独立成立，不用尚待确认的通信键反过来证明手机已经可信。二维码只承载公开数据，不执行 URL 或导入授权令牌。

本机保存 `(activity_id, participant_id, credential_ref)` 到完整绑定包、配对确认状态与本机策略修订的映射。联系人昵称只保存在本机显示层。新绑定先为 Pending；人工核验后才能成为 Active。替换需重新核验并在同一事务中封禁旧引用、激活新引用，不能因同名或更大代数自动信任。

MLS 候选映射为 Basic credential 的 identity bytes 等于 `credential_ref`，`SigningIdentity.signature_key` 等于绑定包里的 MLS 公钥；IdentityProvider 同时检查两者与本机 Active 映射。建议首期仅评审 MLS ciphersuite `0x0001`，不协商降级；这是新增候选选择，不修改历史 spike。MLS 证书/凭据仍依赖应用的身份认证规则，不能由库默认身份 provider 代替。[RFC 9420 §5.3](https://www.rfc-editor.org/rfc/rfc9420.html#section-5.3)、[§17.1](https://www.rfc-editor.org/rfc/rfc9420.html#section-17.1)。

配对不以自签名作为信任根；持钥使用由标准 MLS KeyPackage/消息签名及 COSE 签验验证，不新造挑战应答握手。缺少可用的本机可信确认入口时停在 Pending。

按 D9，冷启动后旧绑定与会话保持隔离。推荐重新开始活动，重新生成活动标识、参与者标识和三组键，并重新配对；各相关对端明确停用旧活动。只复制历史联系人、旧数据库或重新解锁均不能恢复信任。该方案仍不提供硬件防克隆或跨设备全局防回滚保证。

## D12：COSE_Control_V1 候选字节格式

本节为已接受的 RadishLink 应用 profile 评审基线；各项严格限制由本项目选择，不声称 COSE 标准要求所有应用同样限制。

| 项目 | 唯一允许的表示 |
| --- | --- |
| 外层 | CBOR tag 18，随后恰好四项的 COSE_Sign1 array |
| protected | bstr，内容恰好为 `{1: -19, 3: "application/vnd.radishlink.control+cbor", 4: kid}` |
| unprotected | 空 map `{}`，不允许附加头 |
| payload | 内嵌 bstr，包含下列固定 array；不接受 detached/null |
| signature | bstr，恰好 64 bytes |
| `kid` | bstr，恰好 32 bytes，等于 `SHA-256(所需用途的 raw public key)`；不作为授权依据 |
| `external_aad` | 固定 UTF-8 bytes `RadishLink.Control.v1`，由本机提供，不接受对方覆盖 |
| 算法 | 仅普通 Ed25519，COSE `alg=-19`；不接受 `-8`、Ed25519ph、Ed25519ctx 或其他算法 |

RFC 9864 为 Ed25519 注册了完整指定的 `-19`，并弃用多义的 EdDSA `-8`；弃用不等于标准全面禁止旧实现。本项目新 profile 不设置旧编号兼容分支。[RFC 9864 §2.2](https://www.rfc-editor.org/rfc/rfc9864.html#section-2.2)。

标准 `Sig_structure` 和签验输入交给 COSE 实现构造；Ed25519 对该完整输入签署，不先把它替换成自定义摘要。签验必须使用收到的原始 protected/payload bytes，不能先规范化再假称原字节签名有效。签名有效之外仍检查身份和动作权限。[RFC 9052 §4.4](https://www.rfc-editor.org/rfc/rfc9052.html#section-4.4)。

严格 CBOR 规则：定长容器、整数和长度最短编码、map 键按确定性顺序；拒绝重复键、未知字段、额外 array 项、尾随数据、不定长、浮点、非预期类型及其他 tag。protected 的键顺序为 `1, 3, 4`。外层、protected 和 payload 各只解析一个完整对象；递归深度分别最多 4 层（以该对象根容器为第 1 层，tag 也计一层）。所有长度在分配前检查；不能用先无限制解码再检查长度满足本要求。[RFC 8949 §4.2.1](https://www.rfc-editor.org/rfc/rfc8949.html#section-4.2.1)。

完整 COSE 对象上限为 **512 bytes**，不含未来逐跳传输头。该上限不能替代传输入口总容量、连接数与验签速率限制。现有 Node 4096-byte 控制预留保持不变，不因草案较小而回收已承诺容量。版本、算法、字段或语义变化使用新 profile 并另审兼容性；v1 不猜测未知版本、不静默降级。

### 交付证明 `kind=1`

```text
ReceiptV1 = [1, 1, activity_id, origin_id, origin_credential_ref,
             message_id, destination_id, destination_credential_ref,
             message_binding]
```

`origin_id`、`destination_id`、`message_id` 均为 16-byte bstr；活动标识与三个引用/摘要均为 32-byte bstr。message_id 由起点安全随机生成，消息身份为 `(activity_id, origin_id, origin_credential_ref, message_id)`，同一身份出现不同内容拒绝。签名者必须是消息预期目标，使用 receipt key；不接受起点、中继或 control key 代签。

候选摘要输入为确定性 CBOR array `["RadishLink.MessageBinding.v1", 1, immutable_core_bytes, ciphertext_bytes]`，后两项是 bstr，`message_binding = SHA-256(该编码)`。长度封装避免拼接歧义。不可变核心必须覆盖版本、活动、双方身份/凭据、message_id、原始寿命与 hop 上限、业务类型/优先级、MLS group/epoch，并作为 MLS authenticated_data 绑定；密文为原始完整 MLS 加密消息 bytes。逐跳剩余 hop、邻居、各机 monotonic deadline 不进入不可变核心，避免转发修改破坏一致性。

**仍未关闭的依赖：**[数据 envelope 评审稿](../protocol/node-data-envelope.md)已补齐 `immutable_core_bytes` 的逐字段编码、MLS AAD 与非循环摘要顺序；D15 数值已由 ADR 0007 接受，真实互操作/平台输入仍未通过，不能将本节提升为可运行协议。core 不含自身的 `message_binding`。现有 Node `Message.key` 字符串与 `core_binding` 是内部持久表示，后续需按明确映射/迁移接入，不在本轮迁移。

验证次序为：长度/严格解码 → 根据本机待办消息取预期目标 → 比对全部字段与摘要 → 按 receipt 用途取可信公钥及核对 kid → 标准验签 → 当前活动/授权/deadline 检查 → 同一状态事务 T-D 复核并接管返回责任。任何步骤失败均不清理 payload、不创建交付事实、不返还重试额度。没有对应责任的孤立证明不创建新消息。重复已接受证明语义幂等，不以原始签名字节的差异创建额外责任。

签名证明目标声称完成 T-C，不能证明恶意目标真正保存数据，也不是已读证明。T-C 意图、提交后签署、入队复核及原消息 deadline 继续遵循[已接受设计](node-security-integration.md#提交签署与返回)。证明不得依靠自报签署时间绕过已知撤销或到期。

### 撤销控制 `kind=2/3`

```text
ControlV1 = [1, kind, activity_id, issuer_id, issuer_credential_ref,
             operation_id, target_id, target_credential_ref, reason]
```

issuer/target/operation_id 为 16-byte bstr；活动与凭据引用为 32-byte bstr。`operation_id` 由发起 Node 随机生成；去重键为 `(activity_id, issuer_credential_ref, operation_id)`。同键不同载荷拒绝。`reason` 为 uint：0 未说明、1 设备遗失、2 怀疑凭据泄露、3 主动退出；不是权限字段，未知值拒绝。签名仅使用 issuer 的 control key。

## D13：撤销权限与顺序

| 输入 | 推荐权限及效果 |
| --- | --- |
| 本机所有者封禁 | 本机立即持久封禁目标凭据；无需对方同意，不代表全队已经封禁 |
| `kind=2` 自身退出 | issuer 与 target 的标识和凭据引用必须相同；验签及本机绑定检查通过后，接收方自动封禁这一凭据 |
| `kind=3` 他人遗失报告 | issuer/target 不同且都属于本次活动的已核验映射；只创建待确认提示，本机所有者确认后封禁；报告者不能替别人撤销 |
| 远程允许、换键、代队友退出 | v1 无此消息类型，全部拒绝；新凭据只能重新可信配对 |

自动接受自身退出是对 D8 的新增细化，已由 D13 接受。控制键泄露者能冒充该凭据退出，使其停止服务，但不能据此获得其他成员的撤销权。若不接受此取舍，替代方案为所有远端退出也要求本机人工确认，代价是已认证退出不能立即生效。

封禁以 `(activity_id, credential_ref)` 为不可逆状态；原因只作说明，不改变权限。已封禁后再次收到自身退出只作幂等处理；其 receipt 和业务不再接受。待确认报告合并到每个目标凭据一个提示，不因新 operation_id 无限堆积；不创建任意陌生身份记录。活动成员上限 5，当前代绑定最多 5，历史代数、报告、退出传播记录另须明确持久配额，满额拒绝新准入，不能删掉活动内封禁记录腾空间后重新信任旧键。

撤销事务更新授权修订、封禁映射和受影响责任的不可输出状态。业务入队、证明转换、界面响应及实际传输写入必须经过同一串行授权门；最终检查与把 bytes 交给传输的边界不得被撤销穿插。撤销提交后不再启动旧权限写入；提交前已交给 OS/对端的 bytes 无法召回。已提交的交付历史事实保留，未发证明/意图停止输出并按有界清理释放；不因清理改变过去已交付事实。

自身退出的原始已验证控制对象是唯一必要例外：可在持久封禁其 issuer 后继续转发该对象，以便传播封禁；不得重新签署、修改或借该通路发送普通业务/receipt。对来源已封禁且此前未验证的对象不再开放通用接收权。转发重试、队列配额与活动关闭清理须在控制传输合同中完成，不沿用消息 deadline 为永久控制提供无限预算。

接续的[控制传播预算稿](../protocol/node-control-propagation.md)已提出活动/代数、去重槽、速率与尝试次数，以及独立保留区和本机 Retiring 状态；其中 D16 容量取舍已由 ADR 0007 接受，不能回写为本节 D13 已实现事实。

重新连通时，已收到且有权处理的退出/撤销先于待发业务应用；报告仅提示。分区中的未知撤销不能即时全队生效，不以本机 revision 作为全队时间戳或全局胜者。控制消息只属于当前活动；旧活动和冷启动隔离状态不自动恢复，不依赖墙上时间 `issued_at` 判定新鲜性。封禁记录保留至活动停用；活动停用后整个范围拒绝。

2026-10-28 的[业务政策关联批次](../testing/node-business-policy.md)已有限离线实现精确凭据/活动检查、政策修订、撤销与 Retiring 的责任停止及证明清理；不包含真实签验、逐跳认证或 I/O 串行交接。

## 评审与验证清单

以下是待执行验收输入，**不是已通过的密码测试向量**。有效签名、损坏签名及编码向量须在获准实际候选后用成熟实现生成并交叉核验。

| 输入/交错 | 必须得到的结果 |
| --- | --- |
| 自签陌生绑定、昵称相同、从中继收到的替换键 | 不自动 Active；无可信确认不接受 |
| MLS identity 正确但 signature key 错、同键跨用途 | 拒绝，不推进安全状态 |
| alg -8/未知值、错误 AAD、缺 tag、附加头、重复键、未知版本/字段 | 严格拒绝，不尝试兼容算法 |
| 超长声明但短输入、无限容器、嵌套炸弹、尾随对象、非最短编码 | 在约定内存/深度/CPU 边界内拒绝；不得先大额分配 |
| origin/destination/credential/message/core/ciphertext 任一改变 | 不清理原责任；跨活动和跨用途重放同样拒绝 |
| 已撤销目标的有效旧签名、自报早于撤销的签署时间 | 拒绝新证明，保留既有历史事实 |
| 队友报告其他人、自己退出、伪造他人退出 | 分别提示、封禁自身凭据、拒绝 |
| 验签后撤销、签署后撤销、输出检查与撤销竞争 | 提交/输出复核拒绝旧权限；限定已在途 bytes 的边界 |
| 撤销提交前后崩溃、重复退出转发、恶意重复报告 | 不撤回持久封禁，不放大队列/提示或恢复旧额度 |
| 新 boot、旧数据库、停用活动、旧凭据代数回放 | 隔离或拒绝；不得作为自动恢复或换键路径 |

## D11—D14 接受记录

| 决策 | 已接受方案 | 已接受的代价 |
| --- | --- | --- |
| D11 首次信任 | 每活动逐对面对面核验完整绑定，三个用途分键；冷启动后新活动重配；MLS suite 0x0001 作为候选 | 3–5 人需要 3–10 对双向核验；无相机时完整指纹确认较繁琐，不能透明延续旧活动 |
| D12 控制 profile | 本文严格 COSE_Sign1 / Ed25519 -19 / 512-byte 上限及固定字段作为后续评审基线 | 无旧算法/宽松字段兼容；公开活动内控制元数据；数据 envelope 与真实向量仍须补齐才可冻结运行协议 |
| D13 退出权限 | 本机封禁 + 自动接受已认证自身退出；他人报告仅提示 | 控制键泄露可导致该身份退出；不提供队长远程封禁所有人的权力，分区内不能即时撤销 |
| D14 依赖评审方向 | 按[依赖准备包](node-control-dependency-review.md)优先评审 coset 0.4.2 / ciborium 0.2.2 与既有 aws-lc-rs 1.16.3 候选 | 需新完整图、严格解析/资源验证与独立复核；历史 94-package PASS 不继承 |

所有者于 2026-10-24 明确接受上述推荐方案并要求固化文档、ADR 和提交。此次接受只覆盖设计与评审方向，不放行安装、下载固定依赖包、重新解析 lock、生成密钥/签署、候选构建运行、R2/Phase B、平台或设备操作。这些选择新增身份信任、撤销权限和公共协议语义，接受范围遵循 [AGENTS.md](../../AGENTS.md) 的安全/身份/兼容性范围约束；证据缺口不能靠确认豁免。
