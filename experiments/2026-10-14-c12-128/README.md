# Prefix-on / C12 / 128 完整会话实验定义

2026-10-14 完成；同一物理节点、同一 Pod 顺序独占 16 DIE，EP8 → AFD eager → EP16 → EP4，各一次正式回放。每组 128 完整源会话、3,725 请求，输出 1 token；全局最多 12 条未完成 HTTP 请求。

| 部署 | 拓扑 | KV 域 | MBT | 模式 |
| --- | --- | ---: | ---: | --- |
| EP4 | 4×DP1/TP4/EP4 | 4 | 8192 | eager |
| EP8 | 2×DP2/TP4/EP8 | 4 | 8192 | eager |
| EP16 | 1×DP4/TP4/EP16 | 4 | 8192 | eager |
| AFD | 12A+4F；A DP3/TP4，F DP4/TP1/EP4 | 3 | 32768 | A/F eager |

公共配置为 prefix-on、chunked prefill、异步调度、maxlen262144、block32、seq8/域、utilization0.9、checkpoint ratio0.25、OMP4 和原绑核。AFD 保留 CAM 异步、两份 token 微批次、F layered GMM1、共享专家在 A。通信/MC2/缓冲保持各自既定配置；不是因素隔离或各部署最优调参比较。

- [recorded-configuration.json](recorded-configuration.json)：实际服务/客户端 argv、additional-config 和性能环境白名单，位置参数化；不是新环境默认参数。
- [configuration-comparison.json](configuration-comparison.json)：相对各自成功 C12 基线的规范化 argv、模型身份和允许变化；性能参数不变。
- [frozen-128](../../datasets/frozen-128/README.md)：与模拟冻结相同的请求、原优先级和对子集重新均衡的三/四域路由。
- [完整报告与证据](../../results/2026-10-14-c12-128/README.md)：16 worker、实际加载库/host、有效原生异步调度、各域冷基线、完整请求和结果。

## 复现口径

先取得精确 frozen-128，准备 [匹配的环境与补丁](../../environment/README.md)，再按记录配置逐组独立启动/profile、记录实际进程/库/环境、冷 reset 和各域基线，使用真实 AgentInfer 依赖与冻结就绪优先级按 C12 回放全部 3,725 请求，完整审计后停止自有服务。Non 共用四域映射；AFD 三域，同一会话固定到一个域。

现有公共 `scripts/benchmark.py` 的正式方案仍默认 256 会话/C16。仅换 run-name 不会切换到本轮实验；本目录提供本轮精确负载、实际配置及复核入口，没有宣称公共统一设备入口已完整适配并经过新的硬件验证。设备适配时必须同时更新 prepared 输入、C12、expected requests/sessions 和记录用途断言，不能只改一个并发参数。

公开数值可直接离线复核：

~~~bash
python3 scripts/recompute_results.py --result-set 2026-10-14-c12-128
~~~

首次 AFD 在记录断言处失败，0 正式请求；用户明确批准一次新 run ID 补跑，原 135 分钟截止不变。四个成功 run 和失败记录见 [运行历史](../../results/2026-10-14-c12-128/run-history.json)。整理期间没有重跑设备实验。
