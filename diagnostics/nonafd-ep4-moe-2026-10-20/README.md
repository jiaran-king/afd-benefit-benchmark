# 历史 v0.26 Non-AFD EP4 的 MoE 算子证据

本次观测确认：**Non-AFD EP4 的路由专家分支实际使用 CANN MegaMoE 融合算子**。四个 rank 各记录到 129 次 `cann_ops_transformer::npu_mega_moe` CPU 调用与 129 次 `MegaMoe` NPU kernel，并具备 CPU 到 NPU 的关联。路由选择和共享专家不属于该融合体。

## 报告与原始 trace

- [一页 PDF](EP4_MoE_report.pdf)
- [完整原始 rank0 trace](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/nonafd-ep4-moe-20261020-v1/rank0.trace.json)
- [PDF + 原始 trace 转发包](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/nonafd-ep4-moe-20261020-v1/NonAFD_EP4_MoE_evidence.zip)
- [Release 与文件校验清单](https://github.com/jiaran-king/afd-benefit-benchmark/releases/tag/nonafd-ep4-moe-20261020-v1)

PDF 和转发包沿用已审核版本，原 trace 字节保持不变。文件大小、SHA256 与下载地址见 [release-manifest.json](release-manifest.json)。四个 rank 的结果保存在证据表中，完整 trace 按已审核交付范围发布 rank0。

## 固定条件

| 项目 | 实际条件 |
|---|---|
| 模型 | 历史 DeepSeek-V4-Flash W4A8 权重与 tokenizer |
| 软件 | vLLM 0.26 / `d02df748`；Ascend `5cfb1697` + 归档补丁；CANN 9.1.0 |
| 执行 | DP1 / TP4 / EP4，MRv1 / Eager，MBT 8192，block size 32，max seqs 8 |
| 缓存与采样 | prefix cache OFF，CWS ON；17,408 输入 / 1 输出 token；1 次预热 + 1 次正式采集 |
| MoE 开关 | `VLLM_ASCEND_ENABLE_FUSED_MC2=1`，`enable_prefill_mc2=true` |

完整参数见 [recorded-configuration.json](recorded-configuration.json)，固定源码、补丁与运行时身份见 [source-versions.json](source-versions.json)。路径参数使用占位符；其余记录保留本次实际值。

## 观测与解释

| rank | MegaMoE CPU 调用 | MegaMoe NPU kernel | 已关联的 MegaMoe kernel |
|---|---:|---:|---:|
| 0 | 129 | 129 | 129 |
| 1 | 129 | 129 | 129 |
| 2 | 129 | 129 | 129 |
| 3 | 129 | 129 | 129 |

源码在 `enable_fused_mc2 == 1` 且 `cann_ops_transformer` 可用时选择 `_apply_cann_mega_moe`。实际 CPU 调用与 NPU kernel 的关联确认了该路径在本次采集中执行。融合范围为路由专家的 token 分发、专家前馈计算和结果合并；不将整层 MoE 描述为单一融合算子。

## 可直接核查的证据

`rank0.trace.json` 为 JSON 根数组，以下索引从 0 起。

| 对象 | 原文件索引 | 内容 |
|---|---:|---|
| CPU 调用 | 1223 | `cann_ops_transformer::npu_mega_moe` |
| async_npu 起点 / 终点 | 241664 / 241665 | flow ID `1792501197968488973` |
| NPU kernel | 137025 | `MegaMoe`，Stream 47，时间戳 `1792501197968488.973 us` |

原事件字段与固定源码片段见 [selected-events.json](evidence/selected-events.json)；四 rank 计数与原文件身份见 [rank-summary.json](evidence/rank-summary.json)；516 条原始 MegaMoe 算子表记录见 [mega-moe-kernels.csv](evidence/mega-moe-kernels.csv)。[trace-validation.json](evidence/trace-validation.json) 摘录已有离线校验结果：rank0 的 7,065 条物理设备任务与算子表一致，时间戳差为 0，时长最大差为 0.0005 us（导出舍入）。

原 trace 保留重叠事件布局及少量外围 flow 告警，所引 MegaMoE 的 CPU 到 NPU 关联完整。校验结论不等于所有外围 flow 均无告警。

## 与历史性能测试的关系

历史 EP4 / EP8 压测与本次采样沿用相同的源码基线、归档补丁及 Non runtime；关键配置、平台和 MRv1 文件的 SHA 一致。但归档的 10 月 11 日、14 日正式压测启动配置开启了 prefix cache，本次按要求关闭。**本次是对历史环境的后续算子采样，不是旧压测当时的 trace，也不是旧压测的完整重放。**

本证据只回答已测 EP4 prefill 的 MoE 实现；不外推未采集的 EP8、独立 decode，也不据此比较性能收益。

## 版本与源码依据

- [历史版本与补丁清单](../../environment/versions.json)，本次固定的归档提交为 `3c403869fcadd3c4c7b238f0cd67413bd1ee871b`。
- [Ascend 固定源码](https://github.com/jiaran-king/vllm-ascend/tree/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46)；分支 `feat/compressor-checkpoint-async`。
- [MegaMoE 路径选择](https://github.com/jiaran-king/vllm-ascend/blob/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46/vllm_ascend/ops/fused_moe/moe_comm_method.py#L458-L460)与[调用适配](https://github.com/jiaran-king/vllm-ascend/blob/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46/vllm_ascend/ops/fused_moe/moe_comm_method.py#L360-L428)。
- [CANN 组件支持判定](https://github.com/jiaran-king/vllm-ascend/blob/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46/vllm_ascend/ascend_forward_context.py#L43)。

下载原始 trace 后，可在仓库根目录运行以下离线核对；不启动模型或设备任务。

~~~bash
python3 diagnostics/nonafd-ep4-moe-2026-10-20/verify_evidence.py --trace /path/to/rank0.trace.json
~~~
