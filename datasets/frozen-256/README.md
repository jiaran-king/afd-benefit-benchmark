# 正式实验冻结负载

这是 2026-10-11 原四组及 2026-10-12 新增 EP16 正式实验共用的精确输入：256 完整会话、9,078 请求、748,751,397 prompt tokens，最大 prompt 235,936，固定输出 1 token。EP16 没有重新选样或修改冻结文件。

[下载完整 token 文件](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/datasets-20261012-v1/frozen-256-requests.jsonl.gz)，或执行：

~~~bash
python3 scripts/download_datasets.py --dataset frozen --output-dir ../afd-data
python3 scripts/import_dataset.py \
  --source ../afd-data/frozen-256/requests.jsonl --workspace ../afd-work
~~~

解压文件大小为 3,634,051,974 字节，SHA256 为 d41cca12002e1b35d5fb801876b87439c070e1307a52d469245686802751c48a，与正式发压前记录一致。文件直接取自保留的实验输入，逐行字节未改写、未重新分词、未重新生成优先级。

每行是一个请求：id、session、turn、prompt_tokens、output_tokens、prompt_sha256、priority，以及 body。body.prompt 是整数 token IDs；body 还包含模型服务名、流式输出和采样参数。行顺序是源会话/轮次顺序，实际 HTTP 准入由依赖就绪、priority 和 C16 共同决定。

| 仓库内文件 | 含义 |
|---|---|
| [manifest.json](manifest.json) | 原始源、父集、正式文件和模型/tokenizer 的身份；子集规模 |
| [request-index.csv.gz](request-index.csv.gz) | 9,078 条 ID、session、turn、priority、prompt 长度与 SHA |
| [priorities.json](priorities.json) | 原正式优先级文件，字节不变；值也保留在 requests.jsonl 每行 |
| [workload.json](workload.json) | 完整会话选择、各会话轮数及 token 总量 |
| [route-nonafd.json](route-nonafd.json) | EP4/EP8 共用四域会话亲和 |
| [route-afd.json](route-afd.json) | AFD 三域会话亲和 |

请求 token SHA 的算法是 SHA256(json.dumps(token_ids, separators=(',', ':')).encode())。它与整个 JSONL 文件的 SHA 不同；导入工具同时检查二者。每轮历史来自原会话，当前回放生成的内容不影响下一轮输入。

取得数据后，按 [复现步骤](../../docs/reproduction.md) 配置匹配环境并运行。详细来源和原始数据准备方法见 [数据集总览](../README.md)。
