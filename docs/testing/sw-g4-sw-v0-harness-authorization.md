# SW-G4 / SW-V0 Harness 最小实现与运行授权包

- 状态：Accepted（实施单元 A 与 Docker 运行单元 B 已分别授权并完成；`SW-V0 PASS`）
- 文档版本：0.2
- 日期：2026-08-28
- 适用 gate：`SW-G4`
- 前置决策：`SW-G0/SW-G1/SW-G3` 已接受，`SW-G2` 未通过

## 目的与结论边界

本文把已接受[`SW-G3` 确定性故障与证据设计](sw-g3-deterministic-validation-design.md)转换为第一个可审阅的实现授权单元：只实现并验证 `SW-V0` 的拓扑、fault hit、注入时钟和 evidence finalizer 自检。

它不修改正式消息状态机，不把 `tools/t0/` 的旧 JSON frame、摘要 ACK 或 snapshot 升级为产品协议，也不执行 `SW-V1/V2/V3`。`SW-V0` 通过只证明 harness 在记录条件下有效，不能证明三节点消息语义、E2EE、HaLow、距离、媒体、功耗或法规能力。

本文的实施单元 A 与 Docker 运行单元 B 已在 2026-08-28 分别获得明确授权并完成。该授权已经消费完毕，不构成未来重跑、扩展 `SW-V1/V2/V3`、安装依赖或修改产品状态机的持续授权。

## 实施与运行结果

- `67556fe` 实现授权清单内的 15 个新增文件；`7a4344b` 与 `674707a` 分别修复 `umask 077` 下 binary 和 profile 在非 root 容器内的读取/执行权限；旧 `t0node`、`go.mod` 与探索性入口未修改；
- 实施期 `go test ./...`、shell 语法、仓库基线与 `git diff --check` 通过；未新增依赖或触发 toolchain download；
- `sw-v0-20260828T131658Z-48803` 因 binary mode `0700` 在容器启动前判为 `INVALID`；`sw-v0-20260828T131816Z-49265` 完成拓扑探针后因 profile mode `0600` 判为 `INVALID`；两次失败证据均保留，且精确标签残留为零；
- 修复后的 `sw-v0-20260828T131927Z-49781` 基于 clean revision `674707a` 完成四个 profile 各三次独立 canonical run，全部 `PASS`；归一化事件摘要依次为 topology `49e9b6de…6424`、fault hit `34bcce5c…6dd6`、evidence `65095e68…a277`、clock `aabecc70…774c`；
- 12 份 `checksums.sha256` 已在运行后独立复核通过；总 manifest 为 `PASS`、退出码 `0`，精确 run label 下的 container/network/image 均为零；
- 结论只接受 `SW-V0` harness 在 `arm64`、Go `1.26.3`、OrbStack Docker 记录条件下有效，不外推产品消息语义、E2EE、P0、HaLow、距离、媒体、功耗或法规能力。

## 复用与隔离原则

- 继续使用现有 `tools/t0/go.mod` 和 Go 标准库，不新增 module、第三方依赖或第二套工具链配置；
- 新 harness 放在同一 module 的独立 `cmd/sw-v0-harness` 与 `internal/harness`，不修改 `internal/t0node` 的探索性协议行为；
- 新正式入口为 `scripts/run-sw-v0-harness.sh`，不把 `scripts/run-t0-three-node.sh` 改名或伪装为 `SW-V*`；
- 四个 canonical profile 使用版本化 JSON 文件，不从 shell 参数、当前时间、PID 或环境变量改变 seed 和断言；
- endpoint、proxy、clock 与 evidence 只处理 synthetic frame/event，不解析或记录产品正文；
- 构建和运行目录只位于本轮私有 artifact `.work/`，仓库不以可写方式挂入容器。

## 实施授权单元 A：文件与职责

获明确实施授权后，只允许新增以下文件：

```text
scripts/run-sw-v0-harness.sh
tools/t0/Dockerfile.sw-v0
tools/t0/cmd/sw-v0-harness/main.go
tools/t0/internal/harness/clock.go
tools/t0/internal/harness/clock_test.go
tools/t0/internal/harness/evidence.go
tools/t0/internal/harness/evidence_test.go
tools/t0/internal/harness/profile.go
tools/t0/internal/harness/profile_test.go
tools/t0/internal/harness/proxy.go
tools/t0/internal/harness/proxy_test.go
tools/t0/profiles/sw-v0-clock-001.json
tools/t0/profiles/sw-v0-evidence-001.json
tools/t0/profiles/sw-v0-fault-hit-001.json
tools/t0/profiles/sw-v0-topology-001.json
```

不修改 `tools/t0/internal/t0node/`、`tools/t0/cmd/t0node/`、`tools/t0/go.mod`、现有 Dockerfile 或探索性运行脚本。若实现证明必须修改这些文件，原授权失效并回到评审。

### 组件职责

| 组件 | 只负责 | 不负责 |
| --- | --- | --- |
| `profile.go` | schema 1、字段上限、固定 ID/seed/hash、unknown critical 拒绝 | 产品配置、任意用户 profile |
| `clock.go` | 进程内 monotonic test clock、前进/回拨事件、自检结果 | 修改宿主/容器系统时钟 |
| `proxy.go` | length-prefixed synthetic frame、方向、event index、hit count、相邻 1/2 交换能力的自检底座 | MLS/JSON 产品 frame 解析、`NET_ADMIN` |
| `evidence.go` | 原子写 manifest/events/assertions/residuals/checksum，归一化三次 run 比较 | 收集 plaintext、密钥或宿主绝对路径 |
| `main.go` | `endpoint`、`proxy`、`probe`、`finalize` 四个最小子命令 | 产品节点、通用测试框架或 daemon 安装 |
| shell 入口 | 私有 run 目录、构建、精确 Docker label、四 profile 顺序、残留盘点 | 下载、端口映射、后台长期服务 |

### Profile 固定值

四个 JSON 必须逐字实现 `SW-G3` 的 canonical ID、seed 与 `10000 ms` 观察窗：

| Profile | Seed | 最小断言 |
| --- | --- | --- |
| `SW-V0-TOPOLOGY-001` | `0x524c535747330101` | A/C 双向不可直连；B 到 A/C 可达 |
| `SW-V0-FAULT-HIT-001` | `0x524c535747330102` | 指定方向第 2 个 synthetic frame 只命中一次；其他方向零命中 |
| `SW-V0-EVIDENCE-001` | `0x524c535747330103` | 必需证据可解析、互相引用、checksum 完整；篡改副本被拒绝 |
| `SW-V0-CLOCK-001` | `0x524c535747330104` | monotonic test clock 不回拨；wall-clock rollback 事件可见且不修改系统时钟 |

每个 profile 连续运行三个独立 canonical run。归一化事件流只移除 wall time、PID、容器 ID 和本轮临时路径；顺序、fault hit 和 assertion 必须一致。为通过测试而忽略额外事件、排序事件或重写失败证据属于 `FAIL`。

## 实施期验证（不启动 Docker）

实施授权应同时允许在仓库内运行以下精确验证：

```bash
gofmt -w \
  tools/t0/cmd/sw-v0-harness/main.go \
  tools/t0/internal/harness/clock.go \
  tools/t0/internal/harness/clock_test.go \
  tools/t0/internal/harness/evidence.go \
  tools/t0/internal/harness/evidence_test.go \
  tools/t0/internal/harness/profile.go \
  tools/t0/internal/harness/profile_test.go \
  tools/t0/internal/harness/proxy.go \
  tools/t0/internal/harness/proxy_test.go
GOCACHE=/tmp/radishlink-sw-v0-go-cache GOTOOLCHAIN=local go test ./...
bash -n scripts/run-sw-v0-harness.sh
./scripts/check-repo.sh
git diff --check
```

`go test` 从 `tools/t0/` 运行。当前 `go.mod` 无第三方 module；命令不得触发 `go get`、`go mod tidy`、toolchain download 或网络访问。`GOTOOLCHAIN=local` 因本机版本不满足而失败时保留错误并停止，不修改 `go.mod` 或下载工具链绕过。

单元负例至少覆盖：未知 schema、seed 格式错误、重复 critical 字段、溢出/负数、路径穿越、symlink、partial evidence、checksum 篡改、fault 未命中/多命中、错误方向、clock rollback 和归一化差异。

## 运行授权单元 B：Docker SW-V0

实施与单元验证通过后，Docker 运行仍需独立 L3 授权。唯一计划入口为：

```bash
./scripts/run-sw-v0-harness.sh run
```

### 精确外部影响

- 在 `artifacts/sw-v/sw-v0-<run-id>/` 创建私有 evidence 与 `.work/`；目录使用 `mktemp -d` 和 `umask 077`；
- 用本机 Go、`CGO_ENABLED=0`、`GOTOOLCHAIN=local` 构建一个 Linux host-architecture 二进制；构建 cache 只位于本轮 `.work/`；
- 从 `scratch` 和本轮二进制构建 `radishlink/sw-v0:<run-id>`，`docker build --network=none`，不拉取 base image；
- 创建两张带精确 run label 的 internal Docker network，以及仅属于本轮的 endpoint/proxy 容器；
- 不使用 `--privileged`、`NET_ADMIN`、host network、端口映射、真实 home、宿主时钟修改或外部网络；
- 容器 `--read-only`、非 root、CPU 总上限 2 核、内存总上限 2 GiB；
- 预计 3–10 分钟；失败立即停止后续 profile，但保留已完成证据。

### 清理与恢复

- trap 只删除 container/network/image name 与 `org.radishlink.sw-v0.run=<run-id>` label 同时匹配的资源；名称相同但 label 不符时不得删除，并把结果判为 `INVALID`；
- evidence 与 `.work/` 默认保留供复核；删除任何 run 目录需另行确认精确路径，不使用宽泛 glob；
- `SIGKILL` 后只读盘点命令为：

```bash
docker ps -a --filter label=org.radishlink.sw-v0.run
docker network ls --filter label=org.radishlink.sw-v0.run
docker image ls --filter label=org.radishlink.sw-v0.run
```

- 发现其他项目或旧 run 资源时只报告，不自动删除。

## Evidence 与结果

每个 canonical run 使用：

```text
artifacts/sw-v/sw-v0-<run-id>/<profile-id>/<repeat>/
├── manifest.json
├── profile.json
├── topology.json
├── events.ndjson
├── assertions.json
├── residuals.json
├── checksums.sha256
└── logs/
```

本轮总 manifest 记录 Git revision/dirty、Go/host/daemon/container architecture、binary/image digest、profile hashes、三次结果、开始/结束时间、退出码和残留。checksum 在其他文件完成后生成；缺文件、篡改、profile 不一致或残留不可判定时为 `INVALID`。

本轮最终结果只能是：

- `PASS`：四个 profile 各三次均通过且归一化一致；
- `FAIL`：harness 有效，但任一 expected/forbidden assertion 违反；
- `INVALID`：拓扑、fault、clock、工具链、证据链或残留盘点不足以判断。

## 评审与授权停止点

接受本文前需要确认：

1. 新文件清单不修改旧探索性协议与状态机；
2. 标准库实现足够覆盖 `SW-V0`，没有新增依赖理由；
3. 四个 profile 与已接受 `SW-G3` 逐字一致；
4. 实施验证和 Docker 运行授权明确分离；
5. Docker 资源、预计时间、清理和证据可审计；
6. `SW-V0 PASS` 不会被升级为消息/E2EE/P0 能力；
7. `SW-G2` 未通过时不会进入 `SW-V3`；
8. 任何范围扩大都会回到评审。

本授权包已经执行完毕，当前没有重跑或扩大范围的持续授权。后续若进入 `SW-V1/V2`、再次运行 Docker、修改 profile/schema 或触及 `SW-G2/SW-V3`，必须形成新的精确授权单元；`SW-G2` 未通过前仍不得执行 `SW-V3`。
