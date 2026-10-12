# AFD 收益实验：方法、证据与复现

在相同 **16 DIE** 资源与真实多轮会话负载下，比较 Non-AFD EP4、Non-AFD EP8、AFD eager 和 AFD F FULL graph 的 KV 容量、缓存采用、实际 prefill 与端到端性能。

**主线：2026-10-11 完成的统一 Compressor host 修复基线。** 四组各 256 完整会话、9,078 请求、输出 1 token，合计 36,312 请求全部成功。每配置一次，结论是整套部署的描述性比较。

| 配置 | 全程分钟 | 实际 KV GiB | 缓存采用率 | 实际 prefill tokens |
|---|---:|---:|---:|---:|
| Non EP4 eager | 238.924 | 227.381 | 45.1760% | 410,495,525 |
| Non EP8 eager | 83.714 | 468.838 | 83.9384% | 120,261,157 |
| AFD eager | 62.917 | 515.779 | 87.5270% | 93,391,397 |
| AFD A eager + F FULL graph | 63.488 | 515.767 | 87.4346% | 94,083,621 |

AFD eager 对 EP4 / EP8 的观测全程加速为 **3.797× / 1.331×**。本轮没有观察到 F FULL graph 的端到端收益。拓扑、MBT、计算与通信随部署变化，不能把整套加速全部归因于缓存；两组 AFD 实际 prefill 也不完全相同，不能把 0.91% 的时长差视为 graph 导致退化。

## 从哪里开始

- **看结论**：[正式报告](results/2026-10-11/REPORT.zh-CN.md)、[完整指标](results/2026-10-11/metrics.csv)、[证据字段说明](results/2026-10-11/README.md)。
- **复核数值**：直接运行下面的离线命令，不需要 NPU、模型或原始会话正文。
- **获取数据**：[原始会话与正式冻结负载](datasets/README.md)、[数据集 Release](https://github.com/jiaran-king/afd-benefit-benchmark/releases/tag/datasets-20261012-v1)。两份文件分开发布，提供下载、校验和导入命令。
- **复现实验**：[测试方法](docs/methodology.md) → [环境与补丁](environment/README.md) → [执行步骤](docs/reproduction.md)。
- **扩展测试**：[新增实验与可比性规则](docs/extending.md)。
- **了解边界**：[材料盘点](docs/material-inventory.md)、[公开材料范围](docs/publication.md)、[历史实验](archive/README.md)、[F graph 专项诊断](diagnostics/f-graph-2026-10-12/README.md)。

~~~bash
python3 scripts/recompute_results.py
python3 -m unittest discover -s tests -v
python3 scripts/benchmark.py plan \
  --group afd_fgraph --workspace /tmp/afd-reproduction --run-name example
~~~

离线核对覆盖请求身份、会话依赖、路由、C16 就绪优先级、缓存/prefill 算术、时延分位数与逐 DIE KV 总量。plan 只输出命令，不启动模型。

## 仓库结构

| 目录 | 职责 |
|---|---|
| docs | 测试方法、复现步骤、扩展规则与材料索引 |
| environment | 实际版本、必要补丁、host 加载修复、部署路径模板 |
| experiments | 冻结实验定义及实际记录的参数；不是新环境默认值 |
| scripts | 可移植入口、原 AgentInfer 执行器及离线统计工具 |
| datasets | raw 与 frozen-256 分层说明、下载清单、9,078 请求索引、冻结优先级和路由；正文见 Release |
| results | 最新正式结果与可重算的逐请求、准入事件、容量数据 |
| diagnostics | 明确标注范围的机制诊断，独立于正式性能结果 |
| archive | 旧结果及其限制，不参与最新主表 |

## 复现范围

公开仓库可独立复核全部正式指标。原始会话 JSON 与正式冻结 token 文件已通过本仓库 Release 分别发布，保留原字节及 SHA256，见 [数据说明](datasets/README.md)。设备回放还需要匹配的模型、原生算子运行时和设备环境。

整理后的启动命令和公开数据已经离线核对；本次整理没有重新启动设备实验，不能把迁移检查称作新的硬件验证。原环境的完整客户端 pip lock 与 AgentInfer upstream commit 未记录，已知部分和未知部分分别列明。

第三方代码保留来源与许可声明，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。报告、配置与本项目新脚本没有额外授予模型或原始数据的再分发许可。
