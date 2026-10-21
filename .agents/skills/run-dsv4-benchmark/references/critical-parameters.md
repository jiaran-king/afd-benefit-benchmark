# 关键参数与快照约定

## 参数及核查依据

每项记录期望值、请求值/实际生效值、来源和允许差异。按本次指定提交解析 CLI、环境变量、`additional_config` 与默认值的优先级；记录互斥、归一化与自动回退。当前实验批准的新值是比较目标，不能强套历史默认值。

| 条件 | 必须区分的内容 |
|---|---|
| 源码与运行时 | vLLM/Ascend/AFD commit、补丁或 dirty 文件指纹、实际模块路径、Python/Torch/torch-npu/CANN、设备型号及 native 文件身份；MRv1/MRv2 |
| 模型 | DeepSeek V4 具体型号、实际架构、W4A8/W8A8 等准确量化、模型与 tokenizer 配置；权重来源/修订和已有校验或分片清单。不得由 `dtype=auto` 或 `--quantization ascend` 推断量化类型 |
| 融合入口 | `enable_expert_parallel`、DP/TP/EP、`enable_fused_mc2` / `VLLM_ASCEND_ENABLE_FUSED_MC2`、`enable_prefill_mc2`；设备、模型/量化/激活、LoRA、CANN 组件及选择器支持条件 |
| MoE 子路径 | MegaMoE 与 `dispatch_ffn_combine` 不混称；`ascend_fusion_config.fusion_ops_gmmswigluquant` 等 FFN 子算子融合按相应提交核对；AFD/CAM 不由 fused_mc2=0 推断成普通非融合路径 |
| 并行与布局 | 实例数、A/F 角色及设备映射、FlashComm/SP、`enable_shared_expert_dp`、`multistream_overlap_shared_expert`、`enable_dsa_cp`；按实际使用检查 PCP/其他 TP 布局 |
| AFD | connector、CAM async、layered GMM、微批次数/切分、gate 所在侧、dynamicQuant、HCCL/CAM 缓冲；API 调度异步与 CAM 异步分别核对 |
| 缓存/执行 | prefix cache、CWS、checkpoint、block size、MBT、seq/model length、显存预算和实际 KV 容量；graph/DBO/MTP/PD、DSA overlap 的支持与回退按版本确认 |
| 测量 | profiler、功能 probe、逐步计时/设备同步、强制均衡路由、OMP/绑核及遗留环境；冻结输入、输出长度、到达/并发与缓存初态按批准方案记录 |

依据优先使用实际启动记录和生效配置。仅缺省而未解析的字段标记未知，不能填写期望值补齐；环境字符串按该版本的解析器转换，不能用 `bool("0")` 代替。补丁已合入 head 时避免重复应用；相同 commit 加不同补丁不属于相同源码。

## 已核实的版本陷阱

- 历史 [5cfb1697 的选择器](https://github.com/jiaran-king/vllm-ascend/blob/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46/vllm_ascend/ascend_forward_context.py#L306-L316)及[融合调用](https://github.com/jiaran-king/vllm-ascend/blob/5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46/vllm_ascend/ops/fused_moe/moe_comm_method.py#L458-L460)：fused_mc2=1 且组件可用等条件满足时选择 MegaMoE。
- [2bcf08d6 的配置校验](https://github.com/jiaran-king/vllm-ascend/blob/2bcf08d67968567ae7a41cf60aaa229f1e863d27/vllm_ascend/ascend_config.py#L703-L713)：输入 1 会禁用 MegaMoE 支持、回退 DFC；输入 2 才检测 MegaMoE 组件，并把最终融合字段归一化成 1。**只看最终值 1 仍不足以区分两条路径。**
- 以上是固定快照的事实，不是所有 0.26/0.30 版本的通用映射。新提交重新核对；参数同名/同值不证明实现相同。选择器可能依赖 token shape，是否与负载无关也需看相应分支。
- [已归档 EP4 证据](../../../../diagnostics/nonafd-ep4-moe-2026-10-20/README.md)只确认对应采样条件。历史压测与补采的配置关系见其版本记录，不扩大为所有历史实验的实际 kernel 证据。

## 只读比较输入

核对脚本使用两份同格式 JSON：`expected` 是本次批准的条件，`actual` 是独立采集/解析的记录。它校验以下必需字段并逐项比较；支持额外的本次关键字段，不内置历史版本默认值。

| JSON 字段 | 内容 |
|---|---|
| `sources` | 至少含 `vllm`、`vllm_ascend`；AFD 模式另含 `afd`。每个组件包含准确 `commit`（40 位 SHA）及 `patches_sha256` 字典（无补丁为 `{}`） |
| `model` | `name`、`architecture`、`quantization`，以及 `metadata_sha256` 字典（至少含 `config.json`、`tokenizer.json`、`tokenizer_config.json`）；可添加权重来源、分片/已有校验身份 |
| `runtime` | `runner`、`soc`、`cann`、`torch`、`torch_npu`；非空 `native_sha256` 字典。版本不等于所有模块均已确认；加载后核对实际库 |
| `moe` | `mode`（`nonafd`/`afd`）、`enable_expert_parallel`、`dp`/`tp`/`ep`、`requested_fused_mc2`、`effective_fused_mc2`、`enable_prefill_mc2`、`cann_mega_moe_available`、`implementation`、`selection_sources_sha256` |
| `parameters` | 本次其他关键条件的字典，例如 prefix cache、CWS、MBT、FlashComm、shared-expert、graph/DBO、layered GMM、微批次及观察器状态。以解析后的值比较，原始 CLI/env/JSON 保存在证据中 |
| `evidence` / `deployment` | 可选的采集记录索引、实际导入/部署路径和端口。它们不参与值相等比较；身份仍以对应的 commit/hash/参数核对 |

`implementation` 是结合**该提交源码及生效配置**解析的具体路径，不是由旗标数值直接猜测的值，也不代替运行证据。`selection_sources_sha256` 记录选择器和算子调用文件指纹；Non-AFD 至少包含 `vllm_ascend/ascend_forward_context.py` 与 `vllm_ascend/ops/fused_moe/moe_comm_method.py`，AFD 至少包含实际 `afd_plugin/` 实现文件。`requested_fused_mc2` 是按优先级选出的用户输入，`effective_fused_mc2` 是版本校验/归一化后的值。`cann_mega_moe_available` 记录版本门控后的可用状态，不能仅由包已安装推断；需要时另记组件存在性。

必需身份不能为缺失、null 或 unknown；AFD 不适用的 prefill MC2/组件条件可以填 `not_applicable` 并在 evidence 说明旁路依据。metadata/source/native 指纹均为 64 位 SHA256。量化写准确类型，不能写泛化的 `auto`、`ascend` 或目录猜测。

脚本只读取 JSON、验证完整性并比较声明字段，不采集真实机器、不解析任意版本源码、不决定发布或设备权限。实际证据未取得时保留待核对状态；不能复制 expected 冒充 actual。返回码：0=`config_match`，1=存在差异，2=输入不完整/无效；后二者均为 `needs_review`。布尔值与整数严格区分，额外/缺失的关键字段也会报告。`parameters` 内未解析的 null/unknown 值需要补齐证据；其他顶层字段会报错，避免漏比较。正常的端口/输出路径变化不参与比较；导入路径需在 evidence 核对到对应源码和库。
