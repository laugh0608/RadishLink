# Node 共享控制外发额度与责任轮转

- 日期：2026-10-28
- 范围：ADR 0007 D16 下的内部外发计费、责任轮转、数据 ACK 次数与显式迁移；L2 持久化/安全边界
- 授权：所有者要求提交上一批并继续下一步；业务政策批次已提交为 `62e0823`，本批完成离线实现、验证与文档，随后获所有者明确授权本地提交
- 面向：Node 状态拥有者、调度与恢复验证协作者；不替代真实签验、可信平台或传输验收

## 交付与使用条件

在现有 Store/SQLite 原子事务内增加 `process_outbound_batch`，合并已有 queue/control 批处理与两类 ACK；旧批处理接口委托至该入口，没有新线程、服务、数据库、runner 或依赖。一次最多 128 个输入事件，同责任、同坐标的观察先合并；矛盾链路观察、错误坐标或业务权限拒绝使整笔失败，不返回部分发送结果。调用者只能提供已认证的内部事件，不能把该接口直接暴露给网络或手机。

| 边界 | 当前行为 |
| --- | --- |
| 共享总额度 | receipt、kind 2/3 对象、数据 ACK 和控制 ACK 共用既有 `control_output_rate`：4 frames/s、8192 bytes/s，各同值 burst；毫秒余额以整数计，第一次活动及同 boot 重开均空桶，不补停机额度 |
| 字节计费 | kind 2/3 按 522 bytes，ACK 按 127 bytes；既有内部 receipt 缓冲按 `max(522, body.len()+10)` 保守计完整 frame，最长现有 4096-byte buffer 收费 4106 bytes。内部 buffer 不是合法 COSE wire；未来严格编码仍须执行 512-byte COSE 上限 |
| 次数与失败 | 候选发送才检查/扣总额度，待机、重复、暂停及断链不扣；被限流的既有重试机会仍消费、不补发。额度、retry、ACK 次数及轮转位置在同一事务提交，失败/提交未知不返回发送许可 |
| 优先与轮转 | 有效已验证退出先于其他输出；退出责任内部轮转，receipt/报告/两类 ACK 在另一个共享序列中轮转。稳定责任键排序，从上次成功消费位置之后开始，末尾回绕；只在实际取得额度时移动游标，单次输入顺序不能抢占位置 |
| 数据路径 | 数据继续使用原 I1 RetryState 与调用方提供的 Admission，不扣控制桶；有界混合批次还处理数据事件。没有新加数据速率参数，也未证明物理链路公平或吞吐 |
| 数据 ACK | 仅已持久接收的消息可申请；中继已释放 payload、起点自己生成的消息及未知 key 均不建立 ACK 权限。仍检查活动、精确邻居凭据、政策和原消息 deadline；每消息最多四个 participant 槽，每槽最多十次，邻居换凭据不返还 |
| 去重与历史 | 同批重复 ACK 合并，跨批重复受共享桶及持久十次上限约束；ACK 不创建交付事实、不删除 payload、不返还业务重试。ACK marker 留在原消息记录中，不因证明清理或重开重置 |
| 有界维护 | 混合批次执行既有每类 256 条清理；原控制批处理/控制 ACK 包装入口因委托而同样推进清理，停止的 intent 可能已在随后显式 maintain 前清除；已交付历史不变 |

轮转只覆盖调用者在同一轮提供的责任集合，退出优先仍可能推迟普通控制；不保证有限重试内一定获得发送机会或送达。未来状态拥有者须公平枚举超过 128 个就绪责任，汇总同坐标的所有控制类型，并在进入本批次前处理已验证退出/本机封禁及剔除已失效输入。不得反复只提交一个偏爱的子集来声称实现全局公平。旧 `advance_queue` 单责任接口也执行 receipt 共享扣费及游标更新，不能绕过速率；它本身不能调度未提供的其他责任。

`send=true` 只是本次已持久消费的内部决定，既不是 socket 写结果，也不是一次性或可重放 token。真实交接仍须在同一串行拥有者内复查政策、时间、精确通道与当前责任；写失败/交接前撤销不能返还次数。批次中的任意错误不会放行其他项；未来输入层必须显式处理拒绝，不以吞错或重放成功决定恢复发送。

## schema v7 与兼容

`migration_v7.sql` 在已有 `messages` 中增加有界 `data_ack_budget`，在 `control_output_rate` 中增加两个有界轮转游标。ACK 状态最多四项、序列化上限 1024 bytes；游标各上限 512 bytes。它们分别属于原消息元数据与原固定辅助记录，不创建新可无限增长的表或提高配置额度。应用逻辑记录/预留不等于 SQLite 文件与索引页的硬空间上限。

新库初始化到 v7；普通 open 对 v1..v6 返回 `MigrationRequired`，由可信维护方按实际源版本调用 `migrate_v1/v2/v3/v4/v5/v6`。旧 SQL 未改，迁移在同一事务执行；错误源版本、重复迁移、损坏、时钟隔离及存储失败拒绝。v6 消息保留已有政策和业务/receipt 责任，数据 ACK 字段为 NULL，不凭空补建历史 ACK 预算，申请该类输出返回 `UnsupportedVersion`；新接纳消息从空 ACK 槽开始。更旧版本仍遵循 D15/政策迁移的输出隔离。

游标、ACK JSON 的结构/未知字段、四槽/十次、重复 participant 和绑定关联在重开/事务中检查。旧消息、已消费次数、原 retry 起点/时槽及活动截止均不重置。游标保留的历史责任键不要求责任仍存在，查找其后首个可用键并回绕；新活动生命周期仍未开放。

## 验证与限制

使用既有 macOS ARM64、Rust 1.97.1、本地缓存及合成临时库，无依赖下载或 manifest/lock 变化。新增 14 项调度测试（含子进程入口），覆盖四类混合控制的 4-frame 竞争、数据独立处理、8192-byte 拒绝、毫秒 refill、被限流 receipt 的 retry 消费、重复与非发送不计费、轮转顺序/跨重开延续、空桶、四 ACK 槽/十次及邻居换代不返还、未知/起点/失去 payload/撤销/到期拒绝、错误批次原子拒绝、v6 显式迁移/故障、损坏状态拒绝。受控进程在 COMMIT 前后退出，核对混合 receipt/控制/两类 ACK 计费、游标、retry 与 schema 同时提交或均不提交。

```bash
RUSTUP_AUTO_INSTALL=0 cargo +1.97.1 fmt --manifest-path node/Cargo.toml -- --check
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 clippy --offline --locked --manifest-path node/Cargo.toml --all-targets -- -D warnings
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::outbound_tests
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml store::data_tests::reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision -- --exact
RUSTUP_AUTO_INSTALL=0 CARGO_TARGET_DIR="$PWD/.cache/node/target" cargo +1.97.1 test --offline --locked --manifest-path node/Cargo.toml -- --test-threads=1
./scripts/check-repo.sh
git diff --check
```

开发失败均保留：

| 阶段 / 退出码 | 结果与处置 |
| --- | --- |
| 最初全量，101 | 121/126 库测试通过；两项旧 schema 断言、两项旧 receipt 空桶假设及一项控制路径清理时点断言不匹配，按新版本/计费/委托行为修正 |
| 新定向首轮，101 | fixture 调错既有 submit/send 参数，编译失败；修正调用与逐笔安全状态修订，不修改产品入口 |
| 随后定向，101 | 5/7 通过；两项未建立既有 action scope，补齐正常准备流程 |
| 增强定向，0 | 当时 13 项通过；邻居换代不返还用例随后加入全量 |
| 首次 Clippy，101 | 一个 collapsible-if，按建议合并条件，未关闭 lint；复验退出 0 |
| 增强全量并行，101 | 138/140 通过；一处无关清理断言被批量替换误改，恢复为 1；D15 `reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision` 重开出现 `Busy: store owner lock`，根因未确认，精确单测复验退出 0 |

并行 Busy 是既有未定位锁风险的再次出现；串行通过不能证明该风险修复。没有添加锁重试、延时、吞错或关闭测试。最终串行全量退出 0：**140 项库测试 + 2 项 CLI 测试通过**；fmt、Clippy、仓库卫生与 diff 检查通过。这些条件不覆盖 Linux、物理掉电、真实密码/通道、跨进程公平或网络表现。

## 接续与停止线

下一批优先推进已接受的入站限速与 16 对象验签等待队列的自有有界准入；新活动生命周期、超 128 责任的真实枚举、签验结果与政策/通道绑定、实际发送交接仍分别待接入。许可证/R2/Phase B、G1/G2、可信平台、I5 与硬件/射频停止线保持。

本批未启动服务、网络、VM、设备或正式实验，没有依赖安装、系统配置、采购、push 或远程修改。受控测试进程正常退出或按故障测试结束；临时库由测试清理，忽略目录保留本批构建缓存和测试日志。
