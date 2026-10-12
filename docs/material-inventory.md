# 材料盘点与去向

| 材料集合 | 状态 | 本仓库位置 |
|---|---|---|
| 2026-10-11 closeout host-fixed | 最新正式主线；EP4 + 两组 AFD 完整 | results/2026-10-11 |
| 2026-10-11 followup EP8 workspace-fixed | 已验证独立完整 EP8，纳入同一主表 | results/2026-10-11/summaries/non_ep8.json |
| 异步实验配置包 | 原定义 + 三份必要补丁；实际值以正式记录为准 | experiments、environment |
| 原始 AgentInfer 客户端 | 实际源码保留；upstream commit 未知 | scripts/runner、vendor |
| 610 会话原始源数据 | 原始 JSON 无损压缩发布；独立身份和格式说明 | datasets/raw、数据集 Release |
| 256 会话冻结负载 | 精确 token 文件已发布；选择、路由、优先级和请求身份完整 | datasets/frozen-256、数据集 Release |
| 2026-10-12 F graph 诊断 | 新 host 基线，1,024 请求；带 profiler | diagnostics/f-graph-2026-10-12 |
| 旧 F graph 时间线 | 旧 host 基线，仅解释机制 | archive/old-f-graph-timeline.md |
| 旧异步三组与失败 EP8 | 旧基线和失败现场，不混入主表 | archive/pre-host-fix-async-report.md、历史索引 |
| 旧 16-token、1,952 请求及 609 会话提前终止实验 | 范围不同或不完整 | archive |
| EP16 与完整 CWS PR 精度工作 | 盘点时另项工作；不纳入本版正式结论 | 历史索引标注范围，无推断结果 |

结果证据公开导出采用字段白名单；数据集另按完整文件身份发布到 Release。原始日志、完整环境、进度轮询、控制进程记录、大体积 profiler、完整 source/native 构建树和原始数据仍按原目录保留，未移动或删除。public repo 不包含本工作区的管理聊天、鉴权或集群配置；原始数据本身包含作为实验输入的编码会话。

细粒度来源：results/2026-10-11/sources.json 记录选用材料的集合、文件名、原 SHA、公开路径、公开 SHA 和变换。发布工作目录另存完整本地路径索引；该索引不入 public Git。
