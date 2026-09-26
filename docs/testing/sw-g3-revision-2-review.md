# SW-G3 实现前修订评审包

- 状态：Draft，待 SW-G3 专题评审；不是已接受参数或运行授权
- 日期：2026-09-26
- 目标读者：消息实现、测试与安全评审者
- 基线：[SW-G3 1.0 与勘误](sw-g3-deterministic-validation-design.md)
- 非目标：修改历史证据、SW-V0 输入、生产协议、密码方案或扩大运行范围

## 推荐决定与版本边界

本包把 2026-09-05 的五项勘误落实为候选规则。原设计和四个 SW-V0 profile 保持原样；本包尚未接受，不能用它执行正式场景或声称勘误已关闭。

| 对象 | 建议修订 | 兼容与消费者 |
| --- | --- | --- |
| 已接受 SW-G3 1.0、SW-V0 | 保持原文、schema 1、profile version 1 和历史 checksum | 现有 harness 继续只解释其已接受输入 |
| 后续 SW-V1/V2 的 retry | 明确初次发送、四次定时重试和一次恢复补发 | 采用该规则的既有 profile ID 提升到 version 2；seed 保持原值 |
| 后续 profile schema | 候选主版本 2，显式表达恢复额度、长度类别和子用例 | 旧解析器必须拒绝；不把新增关键语义塞进可忽略字段 |
| 后续 evidence schema | 候选主版本 2，记录语义模式、子用例、发送原因、预算消耗与提交点 | 比较器按 schema/profile ID/version/variant/子用例分组，禁止跨版本归一化为相同结果 |
| 新的边界子用例 | 以父 profile ID/version 加稳定 subcase ID 区分 | 三次重复按同一子用例比较，不以三个不同子用例代替三次重复 |

当前 `tools/t0/internal/harness/profile.go` 只接受四个 canonical SW-V0 ID、profile version 1、schema 1，并拒绝未知字段。上述 version 2 尚无实现；后续精确实施包需列出 decoder、validator、runner、clock、evidence writer/checker、归一化比较器和相应测试的变更，不复制另一套 runner 或放宽 V0 校验。

## 重试与 5 秒断链

### 预算和事件规则

以下是合成消息路径的测试策略，不是生产默认值：

- 预算按本地 message key 与覆盖层下一邻接计数；重启和 duplicate 不重置计数或起算点。
- 初次发送为一次，另有四次定时重试，退避依次为 `250/500/1000/2000 ms`。定时点从该队列首次发送事件累计，分别为 `0/250/750/1750/3750 ms`；`max_attempts` 明确包含初次发送，普通上限为 5。
- 断链恢复另有一次额度，总上限为 6；只响应同一邻接已观察到的 down→up 事件，初始 up、重复 up 通知、无待发对象均不触发。反复抖动不补充额度。
- 观察到 down 时的计划尝试也消耗定时额度，记录 `blocked_link_down`，不发送 frame；不得悄悄积累为恢复后的突发重传。
- 恢复补发与定时点相同时合并为一次尝试，同时消费到期的定时槽及恢复额度，禁止两次发包。恢复事件不得重启退避序列。
- 每次尝试须重新检查当前状态、配额、hop 和 deadline；时间达到或超过 deadline 时拒绝发送。验证 delivery 后取消剩余尝试；预算耗尽只表示停止本轮自动发送，不代表送达或允许删除 payload。
- `retry.deadline_ms = 30000` 从 origin 首次创建起算，接收节点按 SW-G1 转换为不晚于原截止点的本地 deadline；不从首次转发或恢复时重新起算。version 2 建议用 `timed_max_attempts = 5`（含初次）、`recovery_max_attempts = 1` 取代含义不清的单个 `max_attempts`；相应定时起点及剩余额度须持久化。
- A 验证 B custody 后暂停该消息的 A→B 自动重试并继续保留 payload；由 B 的 B→C 队列等待 destination evidence。C 对未到期 duplicate 重发已有 evidence。custody 丢失时 A 的重传由 B 幂等处理。
- receipt/控制队列沿用独立有界配额，不获得恢复额度绕过限速；本轮不把多条并发、组合丢包或多次断链混入单故障 profile。

### `SW-V1-DOWN-BC-001` version 2 事件表

run 观察窗仍为 `30000 ms`，origin lifetime 仍为 `30000 ms`。B custody 提交后，harness 在 B 首次 forward 前设置事件屏障：关闭 bc，随后释放发送动作，以此时刻为 `t_d = 0`。必须在 run 起点后 `1000 ms` 内到达屏障；已证明环境/屏障失效为 INVALID，环境有效但被测实现未按时提交 custody 为 FAIL，不能平移观察窗或把实现失败包装成准备失败。

| 相对 t_d 时间 | 事件 | 期望 |
| --- | --- | --- |
| 0 ms | bc down；B 初次发送槽 | 消耗槽 1，无外发；B 保留已提交责任，C 零交付 |
| 250 / 750 / 1750 / 3750 ms | 四个定时槽 | 总计 5 次尝试，均记录断链阻塞；无 custody/delivery 假成功 |
| 5000 ms | bc 恢复，消费一次恢复额度 | 发送同 key、同 payload、同 deadline 的原邻接副本；hop 不再次扣减 |
| 原观察窗结束前 | C 提交并返回 evidence，A/B 各自验证 | C 用户交付恰好 1 次；A/B 终态与 tombstone 提交后释放传输副本 |

`SW-V1-DOWN-AB-001` 使用 A 入队后、首次 A→B 发送前的相同屏障；断链期间 B 不得返回 custody。两者均只断链，不重启任何节点。

### 必须覆盖的重试边界

每一行是独立子用例；未列出的其他故障关闭。用注入单调时钟与确定事件驱动检查，不通过 sleep 或延长 run 掩盖失败。

| 子用例 | 断言 |
| --- | --- |
| 首次发送成功 | 1 次数据尝试，验证 evidence 后不再重试 |
| 恢复发生于 deadline 前 1 ms | 只在其他准入条件也通过时允许一次尝试；不承诺在剩余 1 ms 内交付 |
| 恢复恰在 deadline / 后 1 ms | 零恢复发送，明确到期，无新 delivery evidence |
| 重复 up / 第二次 down→up | 不增加恢复额度；总尝试不超过 6 |
| 恢复与定时点重合 | 同一副本只发送一次，两个触发原因均入证据 |
| evidence 与发送同一时刻 | 先处理已验证终态，再做发送准入；不得在已送达后发包 |
| 恢复时配额不足或 hop 不允许 | 显式拒绝，该恢复机会不积攒；payload 按原责任和 lifetime 处理 |
| 重启恢复 | 恢复已消费计数、保守 deadline；不能证明剩余寿命则隔离/到期，不续期 |

## 长度与拒绝路径

`SW-V2-LENGTH-001` version 1 的 16385 B 保留为历史设计输入。version 2 明确区分以下两条轨，不用合成载荷推导密码开销：

| 边界 | 合成 SW-V1/V2 候选 | 真实 E2EE 前置 |
| --- | --- | --- |
| 正文 | 发送动作编码后最大 16384 B；独立检查 16384 / 16385 B | 接收端解密后也检查正文上限 |
| 不透明测试载荷 | `synthetic_payload_max_bytes = 16384`；16385 B 拒绝 | `ciphertext_max_bytes` 必须由选定库、suite、epoch/认证开销证明，当前待定 |
| 完整测试 frame | 建议 `frame_max_bytes = 32768`，包含测试信封；只作合成资源边界 | 正式信封编码与上限另行评审，不继承此数值 |

上述建议数值须在评审后写入新 profile；当前不创建可执行 JSON。对每层分别检查刚好上限、上限加一、负数、长度整数溢出、声明与实际长度不符、截断和未知关键字段。frame 上限必须在完整缓存/解析前约束；内层长度在相应分配、认证或落盘前检查。错误不得产生 custody、推进安全状态或生成 delivery evidence。

版本 2 使用 `payload_kind = synthetic_opaque`、`security_mode = synthetic` 和各自显式长度字段；测试报告不得把这些载荷标成已认证密文。SW-V3 的长度 profile 需重新评审，不允许把 synthetic 改名后沿用。

## 故障、拓扑与覆盖

- `DOWN-BC` version 2 删除隐含的 B 重启断言；`SW-V2-RESTART-B-001` 独立验证提交后的重启恢复。断链加重启属于未来组合 profile。
- A—B—C 且 B 唯一时，只验证排队与原路径恢复，不声明替代路径恢复。D 中继或 A/C 直连必须另设拓扑、自检与授权，不改变 V0 的 A/C 隔离结果。
- `SW-V1-REORDER-001` 的窗口交换需要至少两个不同逻辑消息；version 2 明确 `message_count = 2`、两个不同 key，断言各交付一次。单条消息不能证明相邻对象乱序命中。安全 epoch 的窗口外拒绝另属 SW-G2/SW-V3，不用传输交换证明。
- 固定 seed 三次一致只证明当前 profile 的可重复性；并发、多 seed、组合故障和长期运行仍在后续独立范围。

## 接受条件与下一步

评审者须逐项确认：初次发送和恢复额度；custody 后责任/调度；deadline 同时事件排序；长度字段与数值；新 schema 与 profile 映射；单故障和乱序输入；消费者及兼容拒绝测试。接受记录应填写日期、责任人、所选规则和剩余阻塞；本包当前均待评审，不以文档检查通过代替接受。

随后才能根据[文字闭环设计](../architecture/minimal-text-slice.md)编制精确 SW-G4 实施包，固定文件、schema 全字段、错误分类、命令、资源上限、运行次数和清理。单元测试、正式 Docker run 与 SW-V3 分别受其前置约束；本轮不执行任何一项。
