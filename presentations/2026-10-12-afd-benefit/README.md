# AFD 收益演示稿

[下载完整 PPT v18](https://github.com/jiaran-king/afd-benefit-benchmark/raw/refs/heads/main/presentations/2026-10-12-afd-benefit/AFD-Plugin-TTFT-comparison-v18.pptx)

2026-10-12 整理，共 **45 页**。保留原演示稿的前 38 页，第 39–45 页为本轮五组正式实验的新增分析；已删除 v17 末尾的两页隐藏附录。

| 页码 | 内容 |
|---|---|
| 39 | 数据集、256 个完整会话、9,078 个请求与输入长度分布 |
| 40 | 会话依赖、就绪调度、固定路由、全局 16 个在途请求及各组参数 |
| 41 | 五组耗时与 TTFT，AFD 相对 EP4、EP8 的实测收益 |
| 42 | 单 DIE 显存构成与整机权重、KV 容量；AFD 的 A、F 角色分别展示 |
| 43 | 缓存复用与实际 prefill 工作量 |
| 44 | 当前 workflow 下 AFD 与 EP16 的容量、工作量及耗时差异 |
| 45 | AFD 在多份专家权重部署中的收益及适用条件 |

新增分析对应 [2026-10-11–12 五组正式报告](../../results/2026-10-12-ep16/REPORT.zh-CN.md)，数据见 [指标表](../../results/2026-10-12-ep16/metrics.csv) 与 [逐 DIE 显存](../../results/2026-10-12-ep16/per-die-memory.csv)。前 38 页沿用原稿的既有内容，各部分实验设置应分别阅读。

本轮为每配置一次的既定部署比较；Non 与 AFD 的单批 token 上限、拓扑及执行路径有差异。测得的整体收益不能全部归因于缓存或解耦，其他负载的收益仍需实测。

文件：`AFD-Plugin-TTFT-comparison-v18.pptx`（6,088,431 字节）。

SHA256：`8688886abed61f134739a77bf01219132f51ba851bf0d6e7a77e0e871f6a4706`。
