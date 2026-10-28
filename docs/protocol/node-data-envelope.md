# Node 数据 envelope

日期：2026-10-24。状态：**D15 已由 [ADR 0007](../adr/0007-node-envelope-and-control-budget.md) 接受；完整实现与运行仍待验证**。面向协议与安全实现评审，补齐 [ADR 0006 D12](../adr/0006-node-identity-and-control-profile.md) 的数据核心、MLS AAD 和 receipt 摘要输入。本文不修改 SW-G1、历史 harness/profile、Node schema 或密码依赖，不宣告完整通信协议通过。

## 范围与已接受约束

只覆盖活动内一对一短文字，最多一个业务中继；状态说明可作为普通文字发送，不赋予独立远程控制语义。群组、媒体、附件、自动重新建组、手机授权、MLS 握手投递和逐跳安全协议另有职责，不能套用本文数据帧绕过其认证。

沿用 D1—D14：Node 正文上限 4096 UTF-8 bytes、完整应用 frame 上限 64 KiB、活动身份/用途分键、两端 MLS、中继无内容密钥、原消息 deadline、冷启动隔离和严格未知输入拒绝。4096 bytes 是当前 Node 首批上限，产品 16 KiB 目标没有被本稿改写。MLS 序列化/加密由候选库执行；本文只定义其外层应用格式。

## 线格式与界限

在**已认证且已授权的覆盖层邻接**上，应用记录为 `u32be body_length || body`。长度前缀为 4-byte 无符号大端整数；完整记录不超过 65536 bytes，即 `1 <= body_length <= 65532`。前缀只是 framing，不提供认证。没有合格逐跳安全通道时不得接入公网 socket；TLS/其他通道的选择与握手仍未放行。

数据帧 body 是固定七项 CBOR array，无 tag：

```text
DataFrameV1 = [1, 1, core_bytes, mls_message_bytes, message_binding,
               remaining_hops, remaining_lifetime_ms]
```

| 位置 | 类型、上限与含义 |
| --- | --- |
| 0、1 | uint，分别为 frame version 1、frame kind 1（数据） |
| `core_bytes` | bstr，最多 512 bytes；内部必须恰好是下列 CoreV1 |
| `mls_message_bytes` | bstr，1..61440 bytes；完整的标准 MLSMessage 序列化结果，不是仅提取其中 ciphertext 字段 |
| `message_binding` | bstr，32 bytes；按 D12 定义计算 |
| `remaining_hops` | uint，0..2，不能超过 core 的 initial_hops 或本机已观察到的剩余额度 |
| `remaining_lifetime_ms` | uint，1..3600000；只用于进一步缩短，不作为可信时钟或恢复依据 |

所有 CBOR 遵循 [D12 严格规则](../security/node-identity-control-profile.md#d12cose_control_v1-候选字节格式)：定长、最短编码、固定类型/项数、无重复/未知/尾随数据。外层与 core 分别最多 4 层；不重编码收到的 core 后再验证原数据。声明长度在分配前检查，并受并发接收总预算限制。

CoreV1 是固定十五项 array：

```text
CoreV1 = [1, 1, activity_id, origin_id, origin_credential_ref,
          destination_id, destination_credential_ref, message_id,
          mls_group_id, mls_epoch, originated_at_ms, lifetime_ms,
          initial_hops, priority, content_type]
```

| 字段 | 唯一表示 / 规则 |
| --- | --- |
| 版本、数据类型 | uint 1、uint 1；只允许文字数据 |
| `activity_id` | bstr 32 bytes，当前活动 |
| origin/destination ID | 各 bstr 16 bytes，不同的本活动参与者 |
| origin/destination credential_ref | 各 bstr 32 bytes，精确匹配对应已核验绑定 |
| `message_id` | bstr 16 bytes，起点安全随机生成；重试不能更换 |
| `mls_group_id` | bstr 32 bytes，本次两端会话的 group ID；由标准库安全随机能力生成/配置并持久绑定两个端点 |
| `mls_epoch` | uint，0..18446744073709551615；必须等于 MLS 消息实际 epoch；不回绕 |
| `originated_at_ms` | uint，0..9223372036854775807；UTC Unix 毫秒，取起点可信当前时间下界的向下取整值，不取 UI/邻居自报时间 |
| `lifetime_ms` | uint，1..3600000；推荐默认及最大值均为 3600000（D15 已接受） |
| `initial_hops` | uint 1 或 2；直达或最多一个中继 |
| `priority` | uint 0；本期普通文字只有一个优先级，不接收自封的紧急等级 |
| `content_type` | uint 1，UTF-8 文字；未知值拒绝 |

所有相加、长度换算和数据库表示均检查溢出；`originated_at_ms + lifetime_ms` 必须不超过有符号 64-bit 上限。epoch 必须用无损表示，不能直接强转 SQLite signed INTEGER；将来的持久映射需明确版本与迁移。

CoreV1 在上述最大值下为 216 bytes。最大数据 body 为 61704 bytes，含前缀为 **61708 bytes**，小于 65536；512-byte core 校验上限不是额外字段的许可。61440-byte 密文上限是准入界限，不是正常开销估计或最低分配量。超过任何一层上限即拒绝，不隐式分片或提高总 frame 上限。

## 加密输入、绑定与验证顺序

明文应用内容为确定性 CBOR `[1, 1, text]`，text 是非空 tstr，编码后 1..4096 UTF-8 bytes。签验/去重以原始字节为准，不在认证前做 Unicode 归一化或替换非法编码。显示层安全呈现不得改变存储的认证内容。

创建顺序固定，消除摘要与密文的循环依赖：

1. 已授权发送动作选择当前两个端点的 group/epoch、新 message_id、可信创建时间与原始 lifetime，编码 CoreV1 得到 `core_bytes`。
2. 向 MLS 库传入应用明文，且 **MLS `authenticated_data` 精确等于 `core_bytes`**。由库产生 MLS PrivateMessage；只允许 application 类型，禁止拿 PublicMessage、Commit、Welcome 或 KeyPackage 充当数据。
3. 标准序列化结果为 `mls_message_bytes`。计算 `SHA-256(CBOR(["RadishLink.MessageBinding.v1", 1, core_bytes, mls_message_bytes]))` 得到 message_binding，两个 bytes 字段必须按 bstr 编码。
4. 按 T-A 联合提交新安全状态、原始 core/密文、摘要、消息/历史/动作幂等键与待发责任，提交后才输出。失败丢弃已推进 group/缓存，提交不确定则隔离。

group/epoch/authenticated_data 是标准 MLS 认证输入的一部分；应用仍需验证发送者身份及外部字段一致。依据 [RFC 9420 §6.3](https://www.rfc-editor.org/rfc/rfc9420.html#section-6.3)。本稿不重写库的 nonce、密钥派生、AEAD、重放窗口或 sender-data 处理。

中继执行严格结构、配额、逐跳授权、时间/hop 和可见摘要一致性检查。摘要不证明 origin 真实；恶意邻居可制造一组自洽的 core/密文/摘要，因此准入消耗始终计入**实际已认证邻居**及全局额度，不能只计自报 origin。中继的 custody 不等于完成 E2EE 验证。

目标端先找到本机已建立且映射匹配的 group，再让库验证/解密。在 T-C 提交前比较：实际 MLS sender 必须为 core.origin；实际 group/epoch、库返回的 authenticated_data 与 core 完全相等；destination 为本机当前凭据；两端绑定均可用；应用明文版本/类型/长度正确。group 任一成员有效签名不能代替 origin 匹配。任一失败均不提交推进后的安全对象、不创建历史或证明意图。

D12 receipt 的 `message_binding` 使用上面的唯一摘要。证明重试复用已提交意图，不能重新加密原消息生成不同密文。未知 epoch 不能触发自动外部加入、信任重建或换键；库允许的 prior_epoch 窗口仍须在实际接入包明确限额。

## 消息身份与内部持久映射

在协议 v1 中，D12 的逻辑消息身份为 `(activity_id, origin_id, origin_credential_ref, message_id)`；group/epoch/destination 属于该身份不可变且受认证的 core。跨 epoch 使用同一身份但改变 core 是 conflict，不作为新消息。活动/凭据范围与 group/epoch 检查共同实现 SW-G1 的 replay scope；不将同一个身份在新 epoch 再加密当作重试。

建议内部 `Message.key` 使用 `SHA-256(CBOR([1, activity_id, origin_id, origin_credential_ref, message_id]))` 的 64 位小写十六进制文本；保留完整复合身份并比较，hash 不是授权或永久无冲突证明。origin_ref 可映射为 credential_ref 的 64 位小写十六进制；完整端点/活动映射另行保存。core_binding 建议保存 32-byte message_binding，原始 core 必须同时持久，不能只存 hash 后从邻居重建。2026-10-28 已接续 [schema v5 数据持久化](../testing/node-data-persistence.md)：保存原始 core 与完整复合身份，epoch 用 8-byte big-endian BLOB；旧消息缺字段只保留可读事实与到期维护，禁止输出。当前内部 key 仍为有界引用，尚未计算建议的 SHA-256/CBOR key；严格认证映射仍未接线。

## D15：一小时寿命与保守时间判定

推荐文字默认/最长寿命 **60 分钟**，用于覆盖 30 分钟断连场景目标并留出返回证明余量；不是保证断连恢复后一定送达，也不修改 SW-G3 历史 30 秒测试或现有 I1 重试时槽。寿命不是持续重试保证；尝试额度可能先耗尽。剩余不足时到期，即使目标已经交付而证明未返回也不续期。

平台必须给出同一采样点的 BOOTTIME 值 `M`、当前真实 UTC 时间的可信区间 `[L, U]` 及 boot 标识。推荐允许区间宽度最大 **2000 ms**，超出即 TIME_UNCERTAIN；这是一项准入条件，不是已证明的设备时钟精度。NTP/邻居时间、自报创建时间或普通系统墙钟本身不构成可信区间。可信平台机制仍为停止线。

令 `N = originated_at_ms + lifetime_ms`。起点使用可信下界作为 originated_at，因此 N 不晚于实际创建时刻加 lifetime。接收时必须满足 `originated_at_ms <= U < N`；否则分别拒绝未来/不确定时间或到期。不因为允许 2000 ms 不确定性，再给 N 额外加 2000 ms。

新准入的剩余预算 `R = min(N - U, received_remaining_ms, local_lifetime_cap)`；起点无需 received 项。要求 R > 0，保守映射到同 boot 调度 deadline。之后任何副本、重试、custody 或路径变化只能缩短既有 deadline；同消息已有记录时再取旧 deadline 的更早值。输出的 remaining_lifetime_ms 不得大于当下保守剩余值。

每次 T-A/T-B/T-C/T-D 提交及实际输出都重新检查可信 UTC 上界、同 boot monotonic deadline、授权与状态；任一个已到点即禁止。不能只依靠建立队列时的一次转换来假设长期无漂移。平台必须验证采样新鲜性、漂移区间和检查到外部效果的时限；尚未得到该证据前不运行此协议。时钟回拨、来源丢失或跨 boot 继续按 D9 隔离，不能靠收到一个新帧解除。

迟到/重复帧不延长 tombstone 或发送预算。建议 Node 继续使用已接受的 7 天历史/去重保留方向；若无可信删除下界，宁可停止新准入也不提前删除拒绝旧消息所需的记录。数据寿命与历史保留不是同一个时间窗。

## Hop、逐跳确认与接收资源

起点存储 initial_hops；为一个下一邻接首次准备副本时减一，随后该邻接所有重试复用减值。中继首次转发再减一；目标可接收 0，中继不得转发 0。同消息之后收到较大 remaining 值不能恢复额度。该规则只约束诚实节点的覆盖层边数，不能证明恶意中继真实经过的物理跳数。

逐跳 custody 与控制对象接收确认采用[控制传播稿](node-control-propagation.md#逐跳确认与消息类型)的 frame kind 3；只有认证邻居在持久提交后产生。它不会使 UI 成为 destination delivered，也不会使上游删除唯一 payload。有效 COSE receipt 才能触发 T-D。

候选接收资源为每个已核验邻居最多 1 个待组装 frame、最多 4 个邻居，合计最多 256 KiB 应用 frame buffers；逐跳协议自身缓冲另计。每帧从读到前缀首字节起最多 10 秒完成，否则丢弃并关闭该应用流，不因零星输入重置期限。此超时与长度是 D15 的有界解析取舍，仍需真实承载验证。帧未完整或未提交前不得返回 custody。

发生撤销/到期后不继续写出未提交给 OS 的剩余 bytes；部分输出无法撤回，必要时关闭流使对端丢弃不完整 frame。接收端依然独立检查完整帧到达及提交时的授权/期限。

## 实施状态与待执行验证

2026-10-24 已实施 Node `framing::Ingress` 的前缀长度、分片/合并输入、四邻居缓存及 10 秒组装期限，12 项合成边界测试通过，见[离线记录](../testing/node-framing-and-graph-inputs.md)。模块不解码 CBOR/MLS，也没有接入真实承载或 Service；不证明以下完整协议矩阵通过。

| 输入 / 故障 | 预期结果 |
| --- | --- |
| 前缀 0、65533、超长 bstr 声明、截断/慢速分片 | 分配前拒绝或固定超时；没有 custody；4 邻居总缓冲不溢出 |
| core、MLS AAD、实际 sender/group/epoch 任一不一致 | E2EE 拒绝，原安全持久状态不变 |
| 同身份换 epoch/密文、重试重新加密 | conflict，保留原消息，不能再交付 |
| B 自造自洽 core/hash 或修改寿命/hop | B 的可见校验不冒充身份验证；C 拒绝认证不符；邻居配额不被冒名绕过 |
| N-1、N、N+1；区间宽 1999/2000/2001 ms | 边界明确；到点无发送/交付/证明；超宽区间隔离 |
| uint64 epoch > i64::MAX、not-after 加法溢出 | epoch 无损处理或显式未支持；时间溢出拒绝，不截断/回绕 |
| T-A/T-C 库状态推进后失败、撤销与部分输出交错 | 回滚并废弃内存对象；不提前产生外部成功，不续发旧权限 |
| 30 分钟断连后恢复、冷启动、旧库回放 | 同 boot 合格时间内只用剩余额度；冷启动/回放不自动恢复 |

字段、标准关系和静态大小已核对，外层 framing 已做上述有限离线实现；2026-10-28 的 [D15 批次](../testing/node-data-persistence.md)进一步覆盖完整字段持久化、UTC 区间/同 boot 期限、重复收紧及显式迁移，但不解码或认证原始字段。未生成密码向量、编译候选或运行网络。完整协议采用仍需逐跳安全、MLS 握手传输、prior_epoch 资源及可信时间输入的独立精确包。
