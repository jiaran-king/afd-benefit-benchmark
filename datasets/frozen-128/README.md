# 128 完整会话冻结负载

这是 [2026-10-14 C12 四组实测](../../results/2026-10-14-c12-128/REPORT.zh-CN.md)的同一输入：源会话 0–127，全部轮次保留，共 3,725 请求、294,584,470 prompt tokens，每会话 9–75 轮，最大 prompt 216,178，输出 1 token。

它直接取自本仓库已有 [frozen-256 Release](../frozen-256/README.md)，保留原始行字节、token IDs、历史和优先级；对子集事前重建三域/四域均衡亲和路由。无需另一个数据集仓库，无需下载或重新分词 raw。

## 获取精确输入

在仓库根目录执行：

~~~bash
# 已有并校验过同一 frozen-256 文件时直接复用，不必重复下载。
python3 scripts/download_datasets.py --dataset frozen --output-dir ../afd-data

# 输出必须是新目录；保留每一行原字节，不重新序列化 JSON。
python3 scripts/prepare_frozen_128.py \
  --parent ../afd-data/frozen-256/requests.jsonl \
  --output ../afd-data/frozen-128
~~~

子集正文为 **1,432,826,239 字节**，SHA256 `65e10b43838be7bdf1f7459a07d34f1a57b64d05fa75fbf2b94f46efed6e86a4`。派生脚本检查完整母集 SHA、每条选中原始行 SHA、请求覆盖和最终子集 SHA；全部通过才把 `.partial` 更名为 `requests.jsonl`。`subset-audit.json`记录结果；不同内容和已有输出目录均不会被覆盖。

| 仓库文件 | 含义 |
| --- | --- |
| [manifest.json](manifest.json) | 子集与母集文件身份、真实子集统计和模型/tokenizer 身份 |
| [request-index.csv.gz](request-index.csv.gz) | 3,725 条请求身份、长度、优先级、prompt SHA 和原始行 SHA |
| [priorities.json](priorities.json) | 正式冻结优先级，字节不变；仅用于已就绪请求，不代表到达时间 |
| [route-afd.json](route-afd.json) | AFD 三域亲和，43/42/43 会话 |
| [route-nonafd.json](route-nonafd.json) | EP4/EP8/EP16 共用四域亲和，每域 32 会话 |

准备时的原始清单有部分描述字段继承母集统计；该文件在原证据保留。这里的公开清单由实际 128 会话索引重算，未修改正文、输入身份、优先级、路由或性能参数。

设备复现还需要 [原环境](../../environment/README.md)和[本轮实际配置](../../experiments/2026-10-14-c12-128/README.md)。数据派生和公开数值复核已经离线验证；不能把数据准备命令当成模型已完成实跑。
