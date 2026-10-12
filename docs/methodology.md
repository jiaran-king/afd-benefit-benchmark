# 测试方法

## 研究问题与比较单位

研究相同 16 DIE 预算下，AFD 的专家与注意力布局如何影响可用 KV、缓存采用、实际 prefill 和完整会话负载耗时。每个配置独占一台 16 DIE，独立启动、正常 profile、冷 reset，然后完整回放一次。两台机器可分别顺序运行 Non 两组与 AFD 两组，不能在同一 16 DIE 上争用。

| 组 | 拓扑 | KV 域 | MBT | 执行 |
|---|---|---:|---:|---|
| non_ep4 | 4 × DP1/TP4/EP4 | 4 | 8192 | eager |
| non_ep8 | 2 × DP2/TP4/EP8 | 4 | 8192 | eager |
| afd_eager | A DP3/TP4，F DP4/TP1/EP4 | 3 | 32768 | A/F eager |
| afd_fgraph | 同上，12A + 4F | 3 | 32768 | A eager，F FULL |

共同：maxlen 262144，seq8/域，utilization 0.9，block32，checkpoint ratio 0.25，OMP4 与 CPU 绑定，全局 HTTP C16，显式异步调度，APC/CWS/hybrid KV/chunked prefill 开启。无 PD、MTP、DSA CP、DSA overlap 或强制负载均衡。

Non 开 FlashComm1 和 prefill/fused MC2；AFD A 开 FlashComm1、F 关闭，fused MC2 关闭。AFD 使用 CAM async、两份 token 微批次、gate 在 A、dynamicQuant=1，两个 F 组同设 layered GMM=1。shared expert DP 保持开启；新版 AFD 共享专家实际在 A。AFD A/F 通信缓冲分别 1024/4096 MiB。完整实际参数以 [记录配置](../experiments/2026-10-11-async/recorded-configuration.json) 为准。

## 冻结负载与调度

原始 610 会话 / 20,230 轮中，先按 256k 限制保留完整合格会话，得到 609 / 20,130；再按源顺序取前 256 个完整会话，即 ID 0–248、250–256。保留全部 9,078 轮，748,751,397 输入 tokens，最大 prompt 235,936。不能混用父集的长度分布。

原 token IDs、原始历史、每轮依赖和就绪优先级固定。每轮生成 1 token、temperature=0、seed=7、ignore_eos=true；输出不回填下一轮。20260928 是既有就绪优先级种子，不能与生成 seed=7 混淆。

调用链是 AgentInfer runner → planner → 原生依赖图 → streaming transport。256 会话可以进入图，HTTP 准入独立限制为 C16。优先级仅在当前图上已就绪的请求间比较；完成时间不同，实际就绪顺序和组批仍可能变化。不设置轮次屏障，不添加人为到达等待，不自动重试。

会话固定亲和到 KV 域。Non 共用四域映射；EP8 的域必须同时落实到实例和实例内 DP rank。AFD 使用三域映射。端点请求带 X-data-parallel-rank；不能仅轮询 HTTP 实例来代替域亲和。

## 启动、冷基线与证据

1. 记录代码、依赖、模型/tokenizer 身份和全部服务命令与环境。
2. 正常启动/profile，确认 16 worker、实际容量、异步类、SP/shared expert 生效及实际加载 native 路径。
3. 对 Compressor 角色核对 corrected host、API 和 kernel；F 的 AFD plugin 保持原字节。不能因为库同名就覆盖 F vendor。
4. 在两组 AFD 压力前后对称只读记录实际 graph 状态；正式压力内不启 profiler。
5. 确认服务空闲；每个唯一 HTTP 端点 reset 成功，并保存每个原生 KV 域的 observer offset、计数及 metrics。
6. 完整回放一次；核对所有请求、SSE 完成、依赖、C16、就绪优先级、域落点与原生计数。
7. 保留失败现场；不拼接、不静默降参、不自动重跑。仅清理本次明确拥有的 PID/start_ticks 对应进程。

## 指标定义

| 指标 | 定义与边界 |
|---|---|
| 全程 | 第一条 HTTP send 至最后一条 SSE 完成；排除启动/profile/reset，包含期间准入与等待造成的空隙 |
| TTFT | 客户端 send 开始至第一条生成 token；不含 send 前依赖和准入等待 |
| 单请求 E2E | 同一 send 开始至完整 SSE 结束 |
| 缓存采用率 | 所有实际采用 cached tokens 之和 / 所有原始 prompt tokens 之和 |
| 实际 prefill | 原生 request_finished 记录，含抢占重算；本轮抢占为 0 |
| KV | tensor 独立 storage 的实际字节数；全机总量包含 TP 驻留副本，AFD 仅 12 A DIE 存 KV |
| HBM | 正常启动/profile 后整 DIE 快照；不能用 F 的 HBM 差推导独立 graph 显存 |
| checkpoint 预算 | 共享 KV 池内 0.25 的块上限，不额外从显存扣除 25% |

分位数采用排序后线性插值：索引 (n−1)×q。逐请求配对是描述性比较，不能消除组批、排队与缓存状态变化。

## 结论限制

每配置只有一次正式运行；没有无缓存对照。拓扑、MBT、专家布局、计算与通信也改变，不能把收益全部归于缓存。AFD 两组实际 prefill 相差 0.74%，不将总时长 0.91% 差异解释成独立 graph 因果效应。旧 profiler 和新诊断不能代替正式全量结果，也不能把 CPU 同步等待直接加到设备时长上。
