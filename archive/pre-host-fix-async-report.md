> 历史材料：不作为最新正式性能结论，范围见 [历史索引](README.md)。

# 异步 KV cache 实验阶段结果

更新：2026-10-11T05:53:12+08:00。四组中三组完成256个完整会话和9,078请求，原生审计与独立复算通过。Non EP8因Compressor设备执行异常提前终止，558条成功、5条失败；本轮整体及四组目标尚未完成。失败run保留，没有重跑或拼接。

| 组别 | 覆盖与状态 | 全程分钟 | token加权缓存采用率 | 原生实际prefill tokens | 抢占 |
| --- | --- | --- | --- | --- | --- |
| Non EP4 | 9,078 / 256，完整 | 240.758 | 45.1093% | 410,995,237 | 0 |
| Non EP8 | 558成功、5失败，未完成 | 不作完整比较 | 不作完整比较 | 不作完整比较 | 0，失败前观测 |
| AFD eager | 9,078 / 256，完整 | 64.199 | 87.5216% | 93,432,357 | 0 |
| AFD F FULL graph | 9,078 / 256，完整 | 64.402 | 87.6014% | 92,834,341 | 0 |

AFD eager相对Non EP4全程加速3.750×，但2,588条相同请求的E2E更慢。AFD F FULL graph比eager慢12.217秒，约0.32%；两组各一次运行，且graph组有只读状态补采，补采开销未单独测量，不能把这点差异直接归因于graph模式。Non EP8的部分请求不参与完整负载比较。

## 显存和缓存

| 组别 | 全机实际物理KV storage GiB | 缓存采用tokens | restore次数 |
| --- | --- | --- | --- |
| Non EP4 | 227.369 | 337,756,160 | 3987 |
| Non EP8 | 468.826，仅启动分配 | 未作完整审计 | 302，失败前观测 |
| AFD eager | 515.761 | 655,319,040 | 8171 |
| AFD F FULL graph | 515.785 | 655,917,056 | 8180 |

完整组的逐DIE HBM、原生权重/profile分项、实际KV、绑核及源日志见逐DIE记录（原始证据，见本目录 sources.json）；EP8启动容量见actual-capacity.json（原始证据，见本目录 sources.json）。物理KV包含TP实际驻留副本；checkpoint ratio0.25为共享池上限，不从实际KV重复扣减。独立graph分配量未知；F侧graph组发压前总HBM较eager每DIE低2,374–2,375MiB，该差值不能当作graph独立分配量。

## 完整负载性能

| 组别 | TTFT均值 / P50 / P95 / P99 秒 | E2E均值 / P50 / P95 / P99 秒 |
| --- | --- | --- |
| Non EP4 | 25.171 / 15.246 / 80.454 / 160.449 | 25.173 / 15.247 / 80.455 / 160.451 |
| AFD eager | 6.699 / 3.975 / 23.596 / 51.847 | 6.702 / 3.979 / 23.598 / 51.849 |
| AFD F FULL graph | 6.719 / 3.987 / 23.376 / 51.980 | 6.723 / 3.989 / 23.386 / 51.982 |

| 比较 | 全程加速比 | 逐请求 E2E 更快 / 更慢 |
| --- | --- | --- |
| Non EP4 → AFD eager | 3.750× | 6,490 / 2,588 |
| Non EP4 → AFD F FULL graph | 3.738× | 6,504 / 2,574 |
| AFD eager → AFD F FULL graph | 0.997× | 4,462 / 4,616 |

全程从首个实际HTTP发送至末次SSE完成，包含期间准入和排队。逐请求TTFT/E2E从AgentInfer开始发送计时，包含发送后服务排队，未含发送前依赖/准入等待。缓存采用率为cached_tokens总和除以748,751,397个原始输入tokens；实际prefill来自原生request_finished审计，包含重计算。异步完成使实际就绪顺序可能不同，比较属于相同冻结请求各一次的描述性结果。Non和AFD的差异包括拓扑、MBT、专家布局和通信路径，不能称纯KV因果收益。

## 配置和数据

唯一材料为20261011异步实验包（原始证据，见本目录 sources.json），SHA256 `bef89ebbbd8450d27f94116f84c853f315114af8c35e9e2350864dc41f6e693c`。zip和权威解包内容未改动。四组14份服务/客户端实际启动配置已记录，发压前包内核对通过；配置记录齐全不代表EP8结果完整。

Non EP4为4×DP1/TP4/EP4，Non EP8为2×DP2/TP4/EP8，AFD为12A+4F（A DP3/TP4，F DP4/TP1/EP4）。Non MBT8192，AFD32768；共同maxlen262144、seq8/域、utilization0.9、block32、checkpoint0.25、OMP4及绑核、显式异步调度、独立全局C16、输出1、seed7。SP、两份token微批次、shared expert和layered配置按包执行。四组复用两台各16DIE机器，各机器内部顺序执行和独立冷reset。

固定vLLM d02df748bf9efd99022f1a062597dc3cb3808485；Ascend base52411eb0dec8b3b3d05e8bdf5a9adb7698fb80c5加PR4 head5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46及包内补丁；AFD cda849a5e0a54576472096c0073f00c7095726f5及匹配CAM/算子。公共Torch2.10.0+cpu、torch_npu2.10.0.post4、Python3.12.13、CANN9.1.0、driver25.5.1.1。基础vLLM的2,041个Python源文件与固定提交原归档一致，实际导出目录无Git元数据。

冻结会话ID为0–248、250–256，保留完整轮次、原始历史和token IDs，不回填生成；真实AgentInfer planner/依赖图/SSE链、就绪优先级seed20260928和会话亲和保持，无自动HTTP重试、真实等待或轮次屏障。

实际值见配置环境JSON（原始证据，见本目录 sources.json）、差异表（原始证据，见本目录 sources.json）和完整argv及环境记录位置（原始证据，见本目录 sources.json）。Non EP4和AFD eager的完整启动环境及/proc快照已在发压前保留，部分worker当前C环境于回放期间只读补采，性能变量一致；EP8和F graph已在发压前直接采集完整当前C环境。CANN实际安装版本文件的首轮补采发生于回放期间，EP8另有发压前记录，时间均保留原义。

EP8故障和最小后续方案见故障说明（原始证据，见本目录 sources.json）。两台资源、实际进程状态及部署/记录修复另见执行记录（原始证据，见本目录 sources.json）。只有四组完整审计和最终报告交付齐全才满足当前goal，未生成四组完成报告或completion-audit。
