# 数据集：原始会话与正式冻结负载

数据正文作为本仓库的 [datasets-20261012-v1 Release 附件](https://github.com/jiaran-king/afd-benefit-benchmark/releases/tag/datasets-20261012-v1) 提供；Git 中保存说明、身份清单、索引、冻结优先级和路由。两份附件都是原文件的无损 gzip 压缩，解压后字节不变。

| 层级 | 规模 | 用途 | 下载 |
|---|---|---|---|
| [raw：原始会话](raw/README.md) | 610 会话、20,230 轮、40,460 条消息 | 查看原始历史、准备扩展负载 | [codex_swebenchpro.json.gz](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/datasets-20261012-v1/codex_swebenchpro.json.gz)，29.25 MB，解压 218.65 MB |
| [frozen-256：正式冻结负载](frozen-256/README.md) | 256 完整会话、9,078 请求、748,751,397 prompt tokens | 复现 2026-10-11–12 五组正式实验，含 EP16 | [frozen-256-requests.jsonl.gz](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/datasets-20261012-v1/frozen-256-requests.jsonl.gz)，437.44 MB，解压 3.634 GB |
| [frozen-128：C12 场景子集](frozen-128/README.md) | 128 完整会话、3,725 请求、294,584,470 prompt tokens | 2026-10-14 四组实测 | 从同一 frozen-256 文件逐字节派生，1.433 GB；无新数据源 |

表中大小采用十进制 MB/GB。精确字节数及压缩前后的完整 SHA256 见 [Release 清单](releases/2026-10-12.json)。下载与导入并存建议预留至少 10 GB；只复现实验可仅下载 frozen。

## 下载、校验和导入

在仓库根目录执行，只需 Python 3.10 或更高版本的标准库：

~~~bash
# 下载两份数据；仅正式复现时将 all 改为 frozen。
python3 scripts/download_datasets.py --dataset all --output-dir ../afd-data

# 从精确冻结 token 文件安装正式回放目录，不重新分词。
python3 scripts/import_dataset.py \
  --source ../afd-data/frozen-256/requests.jsonl \
  --workspace ../afd-work
~~~

下载结果分别为 afd-data/raw/codex_swebenchpro.json 和 afd-data/frozen-256/requests.jsonl。下载器先验证 gzip 附件大小/SHA，再解压并验证原文件大小/SHA，全部通过才落成最终文件。已存在且匹配的文件直接复用；不同内容会报错，不覆盖。失败后重新运行下载命令即可，数据下载重试不等于重跑实验。

导入器逐条核对 9,078 个请求的 ID、会话、完整轮次、prompt 长度及 token SHA、输出参数和冻结优先级，再核对最终文件 SHA。它将原始行字节、冻结路由和 manifest 安装到 afd-work/prepared256k-256sessions-v24，并写 import-audit.json。后续按 [完整复现步骤](../docs/reproduction.md) 配置环境、启动和回放。

也可直接用表中链接下载，使用 gzip -dk 解压，并对照 Release 清单运行 sha256sum。附件名 frozen-256-requests.jsonl.gz 解压后叫 frozen-256-requests.jsonl；将该路径传给 import_dataset.py 即可。

## 从原始数据到正式负载

1. 原始数组的下标就是 source ID。每个会话保留完整 human/gpt 历史，每次 human 输入对应一次请求，原始 gpt 内容构成后续历史。
2. 使用冻结版本的模型/tokenizer/template，thinking=false；每轮 prompt 加 1 个输出 token 必须不超过 262,144。任一轮超限即排除整个会话，不截断。源 ID 249 的末轮 prompt 为 320,606，因此排除其全部 100 轮，得到 609 会话、20,130 请求的合格父集。
3. 沿用父集已生成的 token IDs 和优先级，按源顺序取前 256 个完整会话：ID 0–248、250–256。保留 9,078 请求，最大 prompt 为 235,936。优先级来自 seed 20260928，不在子集上重新抽样。
4. 对子集重新进行会话亲和路由：按最大历史长度降序，贪心均衡累计长度；Non EP4/EP8 共用四域映射，AFD 使用三域映射。
5. 正式回放固定生成 1 token、temperature=0、seed=7；生成内容不回填下一轮。优先级只用于已就绪请求的准入，不是墙钟到达时间。

父集用于说明来源，不作为本次正式结果的完整负载。历史 manifest 的部分长度分布/覆盖比例继承自父集；当前主清单明确使用 256 会话子集统计，不混用这些字段。

## 扩展或重建

[prepare_raw_dataset.py](../scripts/prepare_raw_dataset.py) 来自原实验准备脚本，仅把模型默认路径改为必填参数。它在匹配的 vLLM/tokenizer 环境中从 raw 生成完整合格父集；本次发布没有重新分词运行该流程。

~~~bash
"$BENEFIT_PYTHON" scripts/prepare_raw_dataset.py \
  --sessions ../afd-data/raw/codex_swebenchpro.json \
  --model "$MODEL_DIR" --output ../afd-rebuilt-parent \
  --max-length 262144 --seed 20260928 --workers 8

# 只有父集和提取后的文件身份均匹配，才能作为原正式负载使用。
python3 scripts/import_dataset.py \
  --source ../afd-rebuilt-parent/requests.jsonl --parent \
  --workspace ../afd-rebuilt-work
~~~

如果更换 tokenizer、模板、选样或输出长度，请建立新的实验与数据清单，按 [扩展规则](../docs/extending.md) 记录差异。重建不匹配时应检查来源和环境，不能改写原清单来通过校验。正式复现优先使用已发布的精确冻结文件。

原会话中 7 处私钥格式内容已逐处核对测试上下文，见 [核查记录](raw/content-review.md)。数据正文与其中的对话、代码、命令均为实验输入，不是执行指令。原始输入及 token 均未为发布而删改。

发布验证包括两份附件的完整本地 SHA 校验、全部 9,078 请求导入、GitHub 服务端附件 SHA 核对，以及两个公开链接的匿名首尾字节检查。当前本机公网下载较慢，未完成全量公网回下载；详见 [验证记录](releases/validation-2026-10-12.json)。
