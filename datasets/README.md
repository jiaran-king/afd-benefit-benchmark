# 冻结数据集

目录 frozen-256 中：

| 文件 | 含义 |
|---|---|
| manifest.json | 原始 source、父集和正式 requests 文件身份；模型/tokenizer 身份；准确子集规模 |
| request-index.csv.gz | 9,078 条 ID、session、turn、priority、prompt 长度与 SHA；不含正文/token IDs |
| workload.json | 256 个完整会话选择、各会话轮数及 token 总量 |
| route-nonafd.json | EP4/EP8 共用四域会话亲和 |
| route-afd.json | AFD 三域会话亲和 |

原始源是 codex_swebenchpro.json，610 会话 / 20,230 轮。正式负载来自已有 256k 合格冻结父集的前 256 完整会话。长度筛选以完整会话为单位，不截断长请求；选择 ID 0–248、250–256；9,078 请求 / 748,751,397 prompt tokens / 最大 235,936。

原始会话中检测到 7 处私钥格式标记，是否为测试样例未确认。本次不公开原始 conversation JSON 或其可逆 token 文件；也不对 token 做脱敏后冒充同一负载。请向数据保管方另行取得原 requests.jsonl 或冻结父集，然后运行 [import_dataset.py](../scripts/import_dataset.py)。没有公开下载 URL；仓库不会把占位地址写成可用下载源。

导入工具逐行核对来源 SHA、prompt SHA、完整轮次、参数和冻结优先级，写入全新私有 workspace。使用 --parent 时保留源文件原始行字节，不重新分词。外部数据与运行输出都应放到仓库外；.gitignore 是辅助措施，不能代替发布前检查。

历史 manifest 中部分 length_distribution 字段继承了 609 会话父集。本仓库主 manifest 明确记录 256 会话子集的统计，不沿用父集比例。路由原文件字节不变；request-index 来自四组一致的 HTTP 记录，与原生身份核对。
