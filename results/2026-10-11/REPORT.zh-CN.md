# 统一修复基线：KV cache 四组部署实验

完成时间：2026-10-11T22:55:40+08:00。保留新EP8，新增Non EP4、AFD eager、AFD F FULL graph各一次完整回放。四组各256完整会话、9,078请求，合计36,312条全部成功；新增27,234条，零正式重试。输入、路由、优先级、C16依赖执行、HTTP与原生缓存/prefill记录均通过核对。

本次全程耗时最短为AFD eager：62.917分钟。AFD eager相对Non EP4的观测全程加速比为3.797×，相对Non EP8为1.331×。F FULL graph相对eager本次更慢0.91%。这些是每配置一次的整套部署比较，细小差异不作统计显著性结论。

## KV容量、缓存采用与实际计算

| 组 | 承载KV每DIE实际GiB | 全机实际KV GiB | Non/A每DIE HBM GiB | F每DIE HBM GiB |
| --- | --- | --- | --- | --- |
| Non EP4 | 14.210–14.213 | 227.381 | 56.924–57.188 | 不适用 |
| Non EP8（保留已验证 run） | 29.301–29.304 | 468.838 | 55.792–56.076 | 不适用 |
| AFD eager | 42.981–42.982 | 515.779 | 55.556–55.826 | 53.594–53.859 |
| AFD F FULL graph | 42.980–42.981 | 515.767 | 55.556–55.826 | 51.275–51.543 |

实际KV按tensor独立storage核算，全机物理总量包含TP驻留副本。AFD仅12个A DIE存KV，4个F DIE不存KV。HBM为正常启动/profile后的整DIE快照；独立graph分配没有测量，F HBM差不能直接解释成graph显存。checkpoint ratio0.25为共享池的checkpoint上限，未重复扣减25%。逐DIE原值、权重/profile日志、CPU亲和及来源见逐DIE记录（原始证据，见本目录 sources.json）；逐域N/B/R和checkpoint上限见逐域容量（原始证据，见本目录 sources.json）。

| 组 | 采用缓存tokens | 采用率 | 实际prefill tokens | restore次数 | 抢占次数 |
| --- | --- | --- | --- | --- | --- |
| Non EP4 | 338,255,872 | 45.1760% | 410,495,525 | 3989 | 0 |
| Non EP8（保留已验证 run） | 628,490,240 | 83.9384% | 120,261,157 | 7829 | 0 |
| AFD eager | 655,360,000 | 87.5270% | 93,391,397 | 8170 | 0 |
| AFD F FULL graph | 654,667,776 | 87.4346% | 94,083,621 | 8160 | 0 |

每组原始输入748,751,397 tokens；缓存采用率为cached tokens之和/原始输入，actual prefill来自原生request_finished并包含抢占重算。容量、缓存采用、实际prefill和耗时共同描述本次部署表现。没有无缓存对照；拓扑、专家布局、MBT及通信也随部署改变，不能将整套部署收益全归因于KV cache。

## 正式性能

| 组 | 全程分钟 | TTFT均值/P50/P95/P99秒 | E2E均值/P50/P95/P99秒 |
| --- | --- | --- | --- |
| Non EP4 | 238.924 | 24.993 / 15.376 / 79.615 / 147.311 | 24.994 / 15.377 / 79.617 / 147.312 |
| Non EP8（保留已验证 run） | 83.714 | 8.775 / 4.016 / 33.513 / 53.484 | 8.778 / 4.017 / 33.515 / 53.489 |
| AFD eager | 62.917 | 6.556 / 3.834 / 23.645 / 50.774 | 6.559 / 3.836 / 23.646 / 50.776 |
| AFD F FULL graph | 63.488 | 6.618 / 3.849 / 24.393 / 50.566 | 6.622 / 3.853 / 24.395 / 50.568 |

全程由首个HTTP发出至最后SSE完成，包含期间排队与准入，排除启动/profile和reset。逐请求TTFT/E2E由客户端发送开始，不含发送前的依赖及准入等待。异步就绪优先级固定，但不同部署的完成时间会影响实际就绪顺序和组批。完整数值与同输入逐请求描述性比较见性能指标（原始证据，见本目录 sources.json）和配对比较（原始证据，见本目录 sources.json）。

## F FULL graph与A/F时间线

新统一基线的性能结论来自上表。两个AFD组使用同一正式观测流程，均不带profiler；FFN状态只在正式压力前后只读采集。FULL组4个F worker的实际NPUGraph与Tensor对象、native replay计数递增均已核实，未以启动参数代替实际回放证据。见新graph实际证据（原始证据，见本目录 sources.json）。

同一冻结输入在两种模式下形成的实际组批与缓存采用仍有差异。本次FULL组实际prefill比eager多692,224 tokens（0.74%）；全程差异同时包含这部分实际工作量变化，不能将其全部解释为graph提交本身的快慢。

旧基线诊断解释了提交节省为何可能很难转化为端到端节省：每F worker完整采样记录989次graph回放替代3956次单内核提交，省去约0.46秒workspace规划及大部分81–89毫秒launch调用；两段GMM、CAM接收/发送和A侧工作仍然存在。989为完整F采样数，完全落在A/F共同窗口内的事务为984–989，不能混用统计边界。

eager提交领先设备开始的中位值约27–28毫秒，部分主机开销原本就与设备工作重叠。生产 F 循环每 43 个 connector 工作项同步，graph更早提交后转为在同步点等待，不能把DeviceSynchronize等待再次加到设备耗时。共同窗口中F接收内核97.4%–98.7%与A其它设备算子重叠，支持A供给、TP/CAM依赖及F计算继续影响完成时刻；接收时间包含poll和搬运，不能全归为纯通信或A等待。

这些时间线来自旧host基线、256首轮冷prefill诊断，有profiler开销且没有逐CAM job/批次配对；它们提供机制解释，不能代替新全量性能或给出修复后精确瓶颈比例。此次没有新增profiler、全面精度、独立graph显存或归因扫描。旧机制证据见A/F时间线解释（原始证据，见本目录 sources.json）与实际时间线图（原始证据，见本目录 sources.json）。

## 参数、版本与调整点

唯一原包SHA256：bef89ebbbd8450d27f94116f84c853f315114af8c35e9e2350864dc41f6e693c。vLLM d02df748bf9efd99022f1a062597dc3cb3808485；Ascend52411eb0dec8b3b3d05e8bdf5a9adb7698fb80c5及PR4 5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46加原包补丁；AFD cda849a5e0a54576472096c0073f00c7095726f5。Python3.12.13、Torch2.10.0+cpu、torch_npu2.10.0.post4、CANN9.1.0、driver25.5.1.1。

源码以已核对归档和文件内容确认，现场vLLM目录不含Git元数据，2,041个Python文件与指定归档一致，生成的_version.py单列。vllm_ascend.__version__未提供有效值，以固定源码及补丁记录为准。AFD的CANN安装明细复用本轮发压前已有的同机记录；本轮发压前worker加载路径与driver已记录，结束后install.info内容、路径和修改时间均与旧记录相同。通用version.cfg旧路径查询失败的输出保留，不将事后核对冒充事前采集。见安装版本证据与采集时点（原始证据，见本目录 sources.json）。

Non EP4为4×DP1/TP4/EP4、EP8为2×DP2/TP4/EP8；AFD为12A+4F（A DP3/TP4、F DP4/TP1/EP4）。Non MBT8192、AFD32768；maxlen262144、seq8/域、utilization0.9、block32、checkpoint0.25、OMP4及原绑核、异步调度、C16、输出1、seed7。CWS/APC/hybrid KV/chunked prefill、Non/A的SP及shared expert DP按包；AFD两份token微批次、F layered GMM=1不变，AFD共享专家在A。无PD/MTP/DSA CP/overlap/force balance。AFD A均eager，两组仅F eager/FULL及必要graph配置不同。

冻结ID 0–248、250–256，最大prompt235,936；request SHA256 d41cca12002e1b35d5fb801876b87439c070e1307a52d469245686802751c48a。真实AgentInfer链、原始历史/token、依赖、冻结就绪优先级和会话域亲和保持；生成不回填下一轮，不截断、不追加样本。

四组执行Compressor的角色统一加载已验证host 2e0fa08edea5cb0cc1bdbd076cf06f4bf2b0bbc7feb380dcc740f444e571d612；op API保持8b555cd6188876b15a8243456fcd17e05a69dd678765db97135809534bfb8dc2，设备kernel保持ac96a866542d1230e1a212453048deb77231e1c0acb6e6fa3d8c8c15d9fb7927。AFD F插件host保持b5ce0b3823b96ed84c226fc21738fd11726eec6f2bdd1ec1e979c1726788f1a2，与custom_transformer分开核对；F没有执行Compressor，不替换其原运行时中未使用的Compressor host。修复沿用此前workspace差异、两请求前后对照及47项回归证据，未新增计算改动。保留证据见修复后两请求复现（原始证据，见本目录 sources.json）与47项原生回归（原始证据，见本目录 sources.json）。

新增阶段只有已授权的host加载修复、独立路径/run标识及记录适配。collect_capacity接受新purpose标签；原远端未保留的两份既有源码核对脚本补齐路径后安装。第一次Non准备因缺失记录脚本退出时零模型、零正式请求，现场保留；其后一次启动及一次正式回放。没有静默降参、正式重试或结果拼接。全部调整和旧字节见执行记录（原始证据，见本目录 sources.json）及归档的closeout-staging、recording-label-adaptation、source-attestation-recording-adaptation。

正式结束后的Non EP4证据下载遇到输出截断，保留失败传输记录后缩小下载分块，并让远端归档读取进程刷出输出、等待一秒再退出，继续逐块及全包SHA256校验。这只调整证据传输，没有重启模型或回放；详情见传输适配记录（原始证据，见本目录 sources.json）。

| 组 | 发压前包匹配项 | worker数 | 冷基线域数 | 成功reset端点 | 记录时点 |
| --- | --- | --- | --- | --- | --- |
| Non EP4 | 147 | 16 | 4 | 4 | 通过，均早于发压 |
| Non EP8（保留已验证 run） | 75 | 16 | 4 | 2 | 通过，均早于发压 |
| AFD eager | 75 | 16 | 3 | 1 | 通过，均早于发压 |
| AFD F FULL graph | 75 | 16 | 3 | 1 | 通过，均早于发压 |

发压前完整记录覆盖全部实例/角色、worker与回放客户端，实际有效环境和加载库已核对，全部域reset成功并保存原生/metrics基线后发压。14个服务/客户端完整命令（原始证据，见本目录 sources.json）；最终配置和环境（原始证据，见本目录 sources.json）；四组完整配置矩阵（原始证据，见本目录 sources.json）；四组差异（原始证据，见本目录 sources.json）。凭据脱敏，性能值保留，未设置/未知分别标明。原始记录复核（原始证据，见本目录 sources.json）未发现包参数差异或worker有效环境事后采集问题，安装版本记录的复用来源如上说明。

四组新统一结果、旧三组结果与失败/诊断分开保留。两台资源和数据均保留，自有服务/回放/有限执行器已退出，最终16 DIE空闲核对通过；服务器状态及执行时点另见执行记录。完成标准与证据见完成核对（原始证据，见本目录 sources.json）。


> 公开整理说明：本报告保留正式数值和限制，原机器路径改为证据标签；“43 层”按后续源码核对修正为“43 个 connector 工作项”。新增诊断另见 [F graph 分析](../../diagnostics/f-graph-2026-10-12/README.md)。source-to-output 关系见 [sources.json](sources.json)。
