# 原始会话数据

[下载原始 JSON 的 gzip 附件](https://github.com/jiaran-king/afd-benefit-benchmark/releases/download/datasets-20261012-v1/codex_swebenchpro.json.gz)，或在仓库根目录执行：

~~~bash
python3 scripts/download_datasets.py --dataset raw --output-dir ../afd-data
~~~

得到 raw/codex_swebenchpro.json：610 个会话、20,230 轮，共 40,460 条消息；218,648,292 字节。完整身份见 [manifest.json](manifest.json)。本文件是用户提供的实验会话源，文件名本身不代表某个官方 SWE-bench 数据集版本。

格式为 JSON 数组，每项包含 conversations 数组；每条消息含 from 和 value，from 交替为 human / gpt。一对 human/gpt 算一轮，source ID 是会话在原数组中的零基下标。value 包含原始任务描述、代码、命令输出和历史回复等文本。

该文件用于查看来源和准备新负载。复现正式性能应使用 [frozen-256](../frozen-256/README.md) 的精确 token IDs；不能把原始 JSON 直接传给正式回放器或重新分词后假定输入相同。

已核对的 7 处私钥格式内容属于测试上下文，见 [content-review.md](content-review.md)。压缩发布不改变正文，解压后 SHA256 与正式实验记录的 source_sha256 相同。
