# Prefix-on / C12 / 128 完整会话：四组实测

[正式报告](REPORT.zh-CN.md)记录同一台 16 DIE 上的四次完整回放：AFD eager 940.08 秒，EP4 1,949.28 秒，EP8 1,005.92 秒，EP16 1,199.91 秒。AFD 分别少耗时 51.77%、6.54%、21.65%；每组 3,725 请求全部成功。报告提供 [PDF](REPORT.zh-CN.pdf) 和 [自包含 HTML](REPORT.zh-CN.html)。

这是不同于原 [256 会话 / C16 五组基线](../2026-10-12-ep16/README.md)的新负载，结果独立保存。每组一次，不宣称稳定收益、普遍优势或单一组件的因果贡献。

## 材料位置

| 材料 | 内容 |
| --- | --- |
| [metrics.csv](metrics.csv) | 四组未舍入的性能、缓存/prefill、容量和首轮/后续轮统计 |
| [requests](requests) | 四组共 14,900 条数值记录，HTTP 与原生计数一一对应后导出；无会话正文 |
| [events](events) | 29,800 条准入/完成事件，保留原始顺序，可验证 C12 与冻结就绪优先级 |
| [per-die-memory.csv](per-die-memory.csv) | 64 DIE 权重、profile、实际 KV、HBM 原值，未知字段留空 |
| [per-domain-capacity.csv](per-domain-capacity.csv) | 15 个 KV 域自然 profile 容量、checkpoint 预算和实际 storage |
| [summaries](summaries) | 完整原生计数、逐域计数和执行审计结论 |
| [audits/complete-runs.json](audits/complete-runs.json) | 输入身份、发压前记录、16 worker/加载 host、异步调度、冷 reset 和各域基线 |
| [native-metrics.json](native-metrics.json) | 各域 metrics 基线增量和阶段解释边界 |
| [simulation-vs-actual.json](simulation-vs-actual.json) | 模拟/实测缓存对照、N/B 和布局变化；EP4 误差如实保留 |
| [figures](figures) | 两张报告图的 PNG、SVG、PDF 和作图数值 |
| [review.json](review.json) | 实验设计、参数可比性、结论与归因审阅 |
| [run-history.json](run-history.json)、[cost-audit.json](cost-audit.json) | 四个成功 run、0 请求失败记录、用户批准的一次 AFD 补跑和原预算核对 |
| [evidence-archive.json](evidence-archive.json)、[sources.json](sources.json) | 原始完整证据包身份、公开文件 SHA256 和字段变换 |

负载复用现有 Release 的原始行，见 [frozen-128](../../datasets/frozen-128/README.md)；实际服务/客户端配置见 [实验定义](../../experiments/2026-10-14-c12-128/README.md)。原始机器日志、完整环境和 native 构建树在原归档保留，未直接公开。

## 离线复核

在仓库根目录执行，只需 Python 标准库，不需要模型、NPU 或数据正文：

~~~bash
python3 scripts/recompute_results.py --result-set 2026-10-14-c12-128 \
  --output /tmp/afd-c12-128-recomputed.csv
~~~

核对完整母集子集身份、全部会话轮次、输入 SHA、三/四域均衡路由、C12 准入与真实 HTTP 峰值、依赖/冻结优先级、输出/流完整性、缓存/prefill、延迟、64 DIE KV 及对 AFD 的逐请求缓存差异。HTTP/native 的一一对应在公开导出前核对；来源哈希保留。

该命令不重跑实验。原 256/C16 的默认复核入口保持不变：`python3 scripts/recompute_results.py`。
