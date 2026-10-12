# EP16 与五组正式汇总

[五组报告](REPORT.zh-CN.md)纳入 2026-10-12 一次完整 EP16 正式运行。EP16 共 256 会话、9,078 请求，3264.947 秒（54.416 分钟），比 AFD eager 少 13.51% 时间。作为固定负载下的单次部署比较，执行与统计证据通过复核；不能外推为普遍优势或单一机制的因果收益。

报告另提供 [PDF](REPORT.zh-CN.pdf) 和 [自包含 HTML](REPORT.zh-CN.html)，均从同一 Markdown 生成。图表与排版的可选生成方法见 [报告脚本](../../scripts/report/README.md)。

## 材料位置

| 材料 | 内容 |
|---|---|
| [metrics.csv](metrics.csv) | 五组完整统计，旧四组值保持不变；新增 recompute_tokens 列仅 EP16 原汇总有值，其他组留空，图表按计数恒等式重算为零 |
| [requests/non_ep16.csv.gz](requests/non_ep16.csv.gz) | EP16 的 9,078 条数值记录；冻结身份、HTTP 时序、SSE 完整性与一一对应的 native 缓存/prefill |
| [events/non_ep16.csv.gz](events/non_ep16.csv.gz) | 18,156 条准入/完成事件，保留事件顺序，可验证会话依赖与就绪优先级 |
| [summaries/non_ep16.json](summaries/non_ep16.json) | 正式汇总、逐域计数、执行审计；原 native audit 状态为 complete，执行审计状态为 passed |
| [per-die-memory.csv](per-die-memory.csv)、[per-domain-capacity.csv](per-domain-capacity.csv) | 五组共 80 DIE、18 域的原值；排除机器路径和 PID |
| [paired-ep16.csv](paired-ep16.csv) | 同请求 ID 的描述性延迟比较，不能把请求当成独立重复试验 |
| [figures](figures) | 三张报告图的 PNG、SVG、PDF 和作图数值 CSV |
| [audits/frozen-input.json](audits/frozen-input.json)、[audits/prepressure.json](audits/prepressure.json) | 输入身份、16 worker host/API、四域异步类、一次端点冷 reset 与四域基线 |
| [review.json](review.json) | 发布前独立复核范围与结论边界 |
| [sources.json](sources.json) | 来源文件 SHA256、公开文件 SHA256 及导出变换 |

旧四组逐请求与事件文件继续放在 [2026-10-11](../2026-10-11/README.md)，不复制、不替换。EP16 共用已有 [冻结数据集](../../datasets/frozen-256/README.md)，无需重新获取另一份数据。

## 离线复核

~~~bash
# 默认复核全部五组，共 45,390 请求、90,780 事件
python3 scripts/recompute_results.py --output /tmp/afd-five-group-recomputed.csv

# 保留原四组的复核入口
python3 scripts/recompute_results.py --result-set 2026-10-11
~~~

脚本核对逐请求身份、路由、会话完整与顺序、C16 就绪优先级、缓存/prefill 算术、时延和容量，并复算 EP16 配对比较及作图数值。EP16 的 HTTP/native 一一对应核查在导出前完成，来源哈希与导出关系保留。

容量归因仍有限制：F 承载专家会释放 A 侧权重空间，不能用“F 不存 KV”单独解释整机 KV 差异；HBM 减去权重和 KV 的差额也不是独立测得的 activation/workspace。正式性能结果不混入后续已停止的显存归因诊断。本次复核确认执行和统计一致性，未新增硬件回放或全量数值精度测试。
