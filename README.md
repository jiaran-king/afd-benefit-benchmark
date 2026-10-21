# AFD 收益实验：方法、证据与复现

在相同 **16 DIE** 资源与真实多轮会话负载下，比较 Non-AFD EP4、EP8、EP16、AFD eager 和 AFD F FULL graph 的 KV 容量、缓存采用、实际 prefill 与端到端性能。

**最新场景：2026-10-14，prefix-on / 128 完整会话 / C12，同机四组实测。** AFD eager 940.08 秒，比 EP4、EP8、EP16 分别少耗时 **51.77%、6.54%、21.65%**。四组各 3,725 请求，合计 14,900 请求全部成功。AFD、EP8、EP16 逐请求缓存采用相同，实际 prefill 均为 19,710,102 tokens；EP4 为 50,688,150 tokens。每配置一次，这是当前冻结负载和既定部署的描述性比较，不宣称稳定或普遍收益。

| 配置 | 全程分钟 | 实际 KV GiB | 缓存采用率 | 实际 prefill tokens |
|---|---:|---:|---:|---:|
| Non EP4 eager | 32.488 | 227.363 | 82.7933% | 50,688,150 |
| Non EP8 eager | 16.765 | 468.826 | 93.3092% | 19,710,102 |
| Non EP16 eager | 19.998 | 562.681 | 93.3092% | 19,710,102 |
| **AFD eager** | **15.668** | **515.770** | **93.3092%** | **19,710,102** |

[新报告 Markdown](results/2026-10-14-c12-128/REPORT.zh-CN.md)、[PDF](results/2026-10-14-c12-128/REPORT.zh-CN.pdf)、[证据与复核](results/2026-10-14-c12-128/README.md)。同机顺序、配置差异、模拟误差和一次 AFD 发压前失败/获准补跑均已记录。原 256 会话实验完整保留，未与新结果合并。

## 256 完整会话 / C16 五组基线

2026-10-11–12 五组各 256 完整会话、9,078 请求、输出 1 token，合计 45,390 请求全部成功。沿用统一 Compressor host 修复基线和同一冻结负载；旧四组数据原样保留。

| 配置 | 全程分钟 | 实际 KV GiB | 缓存采用率 | 实际 prefill tokens |
|---|---:|---:|---:|---:|
| Non EP4 eager | 238.924 | 227.381 | 45.1760% | 410,495,525 |
| Non EP8 eager | 83.714 | 468.838 | 83.9384% | 120,261,157 |
| **Non EP16 eager** | **54.416** | **562.675** | **91.7196%** | **61,999,653** |
| AFD eager | 62.917 | 515.779 | 87.5270% | 93,391,397 |
| AFD A eager + F FULL graph | 63.488 | 515.767 | 87.4346% | 94,083,621 |

该 256/C16 基线中 Non EP16 全程最短，比 AFD eager 少 **13.51%** 时间；AFD eager 对 EP4 / EP8 的观测加速为 **3.797× / 1.331×**。F FULL graph 未显示额外端到端收益。拓扑、MBT、计算与通信随部署变化，不能把整套差异全部归因于缓存；两组 AFD 实际 prefill 也不完全相同，不能把 0.91% 的时长差视为 graph 导致退化。新旧实验的负载、并发与子集路由不同，不能将收益反转归给单一参数。

## 从哪里开始

- **看结论**：[最新 128/C12 报告](results/2026-10-14-c12-128/REPORT.zh-CN.md)、[PDF](results/2026-10-14-c12-128/REPORT.zh-CN.pdf)、[证据](results/2026-10-14-c12-128/README.md)；原 [256/C16 五组报告](results/2026-10-12-ep16/REPORT.zh-CN.md)、[PDF](results/2026-10-12-ep16/REPORT.zh-CN.pdf)、[完整指标](results/2026-10-12-ep16/metrics.csv)与[原四组报告](results/2026-10-11/REPORT.zh-CN.md)独立保留。
- **看演示稿**：[AFD 收益 PPT v20](presentations/2026-10-12-afd-benefit/AFD-Plugin-TTFT-comparison-v20.pptx)、[内容与版本说明](presentations/2026-10-12-afd-benefit/README.md)。共 52 页：第 39–46 页为 256 会话／C16，第 47–52 页为 128 会话／C12；两组实验分别设置小节标题页，各页标明所属实验。
- **一页展示**：[Agentic 128 会话／C12 收益与 TTFT](presentations/2026-10-12-afd-benefit/AFD-Agentic-128-C12-one-page-with-TTFT-v6.pptx)，含各组实例数、DP／TP／EP 配置及测试条件。
- **复核数值**：直接运行下面的离线命令，不需要 NPU、模型或原始会话正文。
- **获取数据**：[原始会话与正式冻结负载](datasets/README.md)、[数据集 Release](https://github.com/jiaran-king/afd-benefit-benchmark/releases/tag/datasets-20261012-v1)；[128 会话子集](datasets/frozen-128/README.md)从同一已发布文件逐字节派生，无需另一份数据源。
- **复现实验**：[测试方法](docs/methodology.md)、[bench 并发与调度](docs/bench-method.md) → [环境与补丁](environment/README.md) → [执行步骤](docs/reproduction.md)、[EP16 入口](experiments/2026-10-12-ep16/README.md)。
- **扩展测试**：[新增实验与可比性规则](docs/extending.md)。
- **看 EP4 算子证据**：[历史 v0.26 Non-AFD EP4 的 MoE 实现](diagnostics/nonafd-ep4-moe-2026-10-20/README.md)、[一页 PDF](diagnostics/nonafd-ep4-moe-2026-10-20/EP4_MoE_report.pdf)及[完整原始 trace](https://github.com/jiaran-king/afd-benefit-benchmark/releases/tag/nonafd-ep4-moe-20261020-v1)。
- **了解边界**：[材料盘点](docs/material-inventory.md)、[公开材料范围](docs/publication.md)、[历史实验](archive/README.md)、[F graph 专项诊断](diagnostics/f-graph-2026-10-12/README.md)。

~~~bash
python3 scripts/recompute_results.py --result-set 2026-10-14-c12-128
python3 scripts/recompute_results.py
python3 -m unittest discover -s tests -v
python3 scripts/benchmark.py plan \
  --group non_ep16 --workspace /tmp/afd-reproduction --run-name example
~~~

离线核对分别覆盖新实验 C12 与原实验 C16 的请求身份、会话依赖、路由、就绪优先级、缓存/prefill、时延与逐 DIE KV。现有 benchmark plan 仍为原 256/C16 方案，只输出命令，不启动模型；新实验的设备适配范围见 [实验定义](experiments/2026-10-14-c12-128/README.md)。

## 仓库结构

| 目录 | 职责 |
|---|---|
| docs | 测试方法、复现步骤、扩展规则与材料索引 |
| environment | 实际版本、必要补丁、host 加载修复、部署路径模板 |
| experiments | 冻结实验定义及实际记录的参数；不是新环境默认值 |
| scripts | 可移植入口、原 AgentInfer 执行器及离线统计工具 |
| datasets | raw、frozen-256 与 frozen-128 的身份、索引、优先级和路由；128 子集从已有 Release 派生 |
| results | 最新正式结果与可重算的逐请求、准入事件、容量数据 |
| presentations | 对外演示稿及版本说明，关联对应的正式报告 |
| diagnostics | 明确标注范围的机制诊断，独立于正式性能结果 |
| archive | 旧结果及其限制，不参与最新主表 |

## 复现范围

公开仓库可独立复核全部正式指标。原始会话 JSON 与正式冻结 token 文件已通过本仓库 Release 分别发布，保留原字节及 SHA256，见 [数据说明](datasets/README.md)。设备回放还需要匹配的模型、原生算子运行时和设备环境。

整理后的启动命令和公开数据已经离线核对；本次整理没有重新启动设备实验，不能把迁移检查称作新的硬件验证。原环境的完整客户端 pip lock 与 AgentInfer upstream commit 未记录，已知部分和未知部分分别列明。

第三方代码保留来源与许可声明，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。报告、配置与本项目新脚本没有额外授予模型或原始数据的再分发许可。
