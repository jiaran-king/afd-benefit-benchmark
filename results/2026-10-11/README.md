# 正式结果与复核入口

[主报告](REPORT.zh-CN.md) · [指标 CSV](metrics.csv) · [逐 DIE 显存](per-die-memory.csv) · [逐域容量](per-domain-capacity.csv) · [逐会话](per-session.csv) · [配对时延](paired-latency.csv)。

requests 下的四份压缩 CSV 是 HTTP 与原生 request_finished 唯一关联后的公开字段表，保留原时延、monotonic 时间、domain、缓存与 actual prefill。events 下保留全部准入/完成顺序，可重放检查 C16、依赖和冻结就绪优先级。summaries 保存原生域计数、restore、graph 证据摘要及完整统计。

这些是原始记录的字段筛选与关联导出，不是新的设备运行。正文、token payload、响应正文、机器账户与完整环境没有发布。来源与导出 hash 在 [sources.json](sources.json)；部分原生文件完整正文仍在原证据存储。

~~~bash
python3 scripts/recompute_results.py
~~~

在仓库根目录执行，重算并比较 metrics.csv 的全部数值，同时检查 36,312 条请求和 72,624 条准入/完成事件。restores 来自每域 native counter delta，KV 来自逐 DIE 独立 storage；其原始设备测量不能仅凭 CSV 重新获取。

四个保留 run：

- non_ep4-host-fixed-closeout-256sessions-v1
- non_ep8-workspace-fixed-256sessions-v1
- afd_eager-host-fixed-closeout-256sessions-v1
- afd_fgraph-host-fixed-closeout-256sessions-v1

EP8 是先前已验证的修复后完整 run，其余三组随后在统一 host 基线上完成。不是将多个部分 run 拼接成完整结果。
