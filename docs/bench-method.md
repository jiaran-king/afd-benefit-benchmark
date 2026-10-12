# 五组部署实验的负载与调度方法

五组使用同一份冻结输入：按原数据源顺序选取前 256 个完整会话（会话 ID 0–248、250–256），保留全部 9,078 轮请求，共 748,751,397 个原始输入 token。请求直接携带冻结的原始 token ID，输出固定为 1 token；本轮生成不会写回下一轮输入。每个会话在一次实验中始终落在同一缓存域。Non EP4、EP8、EP16 复用同一四域路由；两个 AFD 组复用同一三域路由。EP16 的四域分别指向单实例内的 DP rank 0–3。

客户端使用真实 AgentInfer analyzer、planner、会话依赖图与 SSE streaming transport。源数据没有原始时钟，因此适配器只用人工递增的时间戳重建各会话轮次，并将回放间隔设为零；请求正文仍取自冻结记录。对同一会话，下一轮的发送与上下文依赖均指向上一轮完成。256 个会话同时进入依赖图；提示构建工作最多 8 个并发，不限制可进入图的会话数。

真正的 HTTP 准入是**全局最多 16 个未完成请求**，四域之间没有各自串行的客户端队列。有空位时，准入器在所有依赖已完成的请求中按冻结优先级选择最小者，优先级相同再按请求 ID；请求进入 SSE 发送后一直占用该名额，直到流结束。不同部署的完成时刻可能改变后续哪些请求已经就绪，因此实际发送顺序与组批可以不同。客户端在原始 AgentInfer transport 上发送 `/v1/completions`，附上相应 DP rank 请求头，并核对响应 ID、原始输入 token 数、单 token 输出及完整流结束标记；传输不自动重试。

服务端五组都使用显式异步调度、每缓存域 `max_num_seqs=8`、prefix caching、chunked prefill、block size 32、最大上下文 262,144、GPU memory utilization 0.9、checkpoint ratio 0.25 和 eager（仅 AFD F FULL graph 组的 F 侧例外）。Non 三组 `max_num_batched_tokens=8192`，AFD 两组为 32,768。各域启动日志和原生容量事件确认使用 `CompressorCheckpointAsyncScheduler`。客户端送来的请求进入对应 DP 域，由该域结合可用 KV、seq8 和 token 批量上限组织每步执行；异步调度可以让调度与既有设备工作流水化，但不会改变客户端的依赖图或全局 C16。全局 C16 与服务端各域 seq8 分别约束传输中的请求数和服务端组批，并非相同的并发参数。

正式回放前先确认所有 HTTP 端点空闲，再对每个独立端点调用 `/reset_prefix_cache`，保存成功响应、每个缓存域的原生观测文件偏移及计数基线、端点 metrics 基线，随后才开始请求。EP16 四个域共享一个 HTTP 端点，因此 reset 端点为 1 个、原生域基线为 4 份。正式运行不带 profiler。结束后对完整请求、依赖与准入事件、HTTP 响应和原生缓存/prefill计数做审计。

**全程耗时**从第一个请求进入 AgentInfer HTTP 发送，到最后一个 SSE 流完成；包含期间的依赖等待、准入排队与服务端处理，排除模型启动、profile 和冷 reset。逐请求 **TTFT** 从 AgentInfer 的发送开始（正文序列化前）至首个生成 token；**E2E** 从同一时点至完整 SSE 流结束。逐请求两项延迟都不包含该请求发送前的依赖等待与准入等待。吞吐及缓存采用率按全量 9,078 个请求计算，缓存采用率为原生采用缓存 token 总数除以 748,751,397 个原始输入 token；实际 prefill 为原生记录的计算 token 总数，包含可能的抢占重算。

方法实现及本次固定负载分别见 [AgentInfer 回放适配器](../scripts/runner/agentinfer_frozen_replay.py)、[正式入口](../scripts/runner/run_formal.py)、[EP16 域路由](../scripts/runner/topology.py) 和正式 run 的 `formal-start.json`、`formal-http/`、原生域观测文件。旧四组的原始记录继续以原归档为准。


公开的冷 reset 与逐域基线见 [EP16 发压前审计](../results/2026-10-12-ep16/audits/prepressure.json)，可重算请求和准入事件见 [五组证据说明](../results/2026-10-12-ep16/README.md)。公共执行器复用了上述真实 AgentInfer 核心，机器路径已参数化；整理后未新增设备实跑。
