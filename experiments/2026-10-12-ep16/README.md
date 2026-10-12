# Non EP16 正式扩展

正式 run：`non_ep16-async-256sessions-v1`，2026-10-12 完成。一个实例独占 16 DIE，DP4/TP4/EP16；四个 KV 域分别路由至同一 HTTP 端点的 DP rank 0–3。正式负载为已有 256 完整会话、9,078 请求，输出 1 token，全局 C16。

- [记录配置](recorded-configuration.json)：服务与客户端参数；Python、模型、工作目录参数化，执行与性能环境采用字段白名单。
- [配置差异](configuration-comparison.json)：相对 Non EP4，DP1→DP4、可见设备 4→16 和记录路径变化；其余 argv 与所比较性能环境一致。实例数从四个变为一个。
- [冻结输入](../../datasets/frozen-256/README.md)、[共同环境](../../environment/README.md)、[发压前审计](../../results/2026-10-12-ep16/audits/prepressure.json)。
- [五组报告与逐请求证据](../../results/2026-10-12-ep16/README.md)。

Non 三组共用 MBT8192、seq8/域、maxlen262144、block32、utilization0.9、checkpoint ratio0.25、eager、显式异步、FlashComm1 和同一四域路由。没有为 EP16 更换数据集或修改生成长度。

## 复现入口

先按 [复现步骤](../../docs/reproduction.md) 下载并导入已有冻结负载、准备相同模型与 native 环境。预览不启动设备：

~~~bash
python3 scripts/benchmark.py plan \
  --group non_ep16 --workspace /path/to/afd-work --run-name ep16-repro-001
~~~

设备上依次执行同一入口的 `start`、`record`、`replay`、`audit`、`stop`，每次都使用 `--group non_ep16` 和相同 workspace/run-name。正常启动/profile 后才能 record；replay 在一次端点冷 reset 成功并保存四域计数基线后开始。不要重复 replay 或覆盖 run。

公开启动器已加入 EP16 的服务划分、DP rank 路由、域到 worker 映射和配置加载路径。真实 AgentInfer 核心未改动；本次仓库整理只做离线验证，没有新增设备实验。
