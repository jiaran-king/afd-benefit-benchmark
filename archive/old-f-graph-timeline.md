> 历史材料：不作为最新正式性能结论，范围见 [历史索引](README.md)。

# F FULL graph：主机提交为何没有等额转化为端到端收益

旧完整正式实验：eager 3,851.912 秒、F graph 3,864.129 秒，相差0.32%。各只有一次运行，不能解释为统计显著的负收益。这两组A侧均有后来发现的旧host tiling部署问题；本文件解释原基线的执行机制，不宣称已得到统一修复基线的正式结论。

## 已验证的执行路径

新对齐诊断保持原12A+4F、模型参数、C16、原始token与路由，仅取冻结256会话首轮256请求。两组均256成功，模型均按所属run停止后才解析。A采样wait0/warmup0/active6，F active24；实际每F worker记录23×43=989个FFN事务、3956个设备内核。A与F共同窗口为eager 4.146619秒、graph 4.041917秒。它们的实际异步批次未逐一配对，不能把窗口差当严格加速比。

已将绝对设备时间与实际HTTP发送/完成时间交叉核对：两个共同窗口都位于真实冻结负载回放期间，晚于profiler启用及首个HTTP发送；窗口交叠的HTTP请求集合均为相同17个ID。这是窗口期间先后涉及的请求数，不是同时在途17条。两组256首轮实际输入各3,718,438 tokens、缓存采用均为0；未将请求完整prompt长度当作窗口内已执行tokens。详见窗口与真实回放关联证据（原始留存附件）。该核对排除将启动dummy/profile阶段当作真实回放窗口，仍不提供逐CAM job或逐批次配对。

Graph确实回放：989次 `aclmdlRIExecuteAsync`/`ModelExecute`，取代eager的3956次 `LaunchKernelV2`及每次GMM workspace规划。四个设备内核仍为 DispatchRecv → SwigluQuant GMM → down GMM → CombineSend，计算和CAM依赖仍存在。

## 关键路径证据

| 每个F worker、该次采样 | eager | F FULL graph |
|---|---:|---:|
| 两段GMM workspace规划 | 约0.46秒 | 回放中无此逐调用规划 |
| runtime LaunchKernelV2 | 81–89毫秒，3956次 | 无 |
| aclmdlRIExecuteAsync | 无 | 4.76–5.12毫秒，989次 |
| 接收内核占用，包含poll与搬运 | 1.56–1.78秒 | 1.64–1.74秒 |
| 两段GMM设备执行 | 1.66–1.73秒 | 1.67–1.73秒 |
| 发送内核 | 0.62–0.65秒 | 0.61–0.65秒 |
| 设备内核间隙占窗口 | 2.37%–5.27% | 0.62%–0.63% |
| 主机DeviceSynchronize等待 | 2.25–2.30秒 | 4.01–4.03秒 |

各行有包含、重叠及不同时间范围，不能相加。尤其DeviceSynchronize是主机等待上述设备工作，不能再加到设备耗时上；接收内核也不是纯通信时间。

`ffn_worker.py::_run_ffn_server_loop` 在每个43层connector-driven step后真实调用 `torch.npu.synchronize()`，两种模式相同。此前把F侧这项等待全部归为profiler开销不准确，现予更正。Graph更早交完工作后在同步点等设备完成，eager则在设备执行期间继续规划、提交后续算子。同步等待增加不是新增同等设备成本，而是CPU工作被已有设备工作覆盖的表现。

eager每个worker全部3956个内核均用trace `connection_id` 匹配到真实host `Node@launch`，无遗漏；设备开始时间相对host launch结束的中位提前提交量为27.3–27.9毫秒，P95为155–159毫秒。少量负值在约11微秒以内，属于调用尚未返回时设备已开始/时钟与记录精度，保留原值。提交队列在多数时刻已有后续工作，节省主机API时长不会使设备等额提前完成。

同一共同窗口内，代表三个DP域的A DIE0/4/8各有约3.62–3.70秒的非CAM、非TP集合算子占用，期间TP集合操作也大量重叠。F接收内核运行时间有97.4%–98.7%与至少一个A worker的其它设备算子重叠。这支持A侧供给及跨A/F依赖限制了流水线：F图提交提前，仍须等A产出、完成两段GMM并返回，A再继续下一层。此处是时间重叠证据；未捕获CAM job/sequence ID，不把邻近A发送强行配成一对，也不将全部接收时长称为A等待。

因此采样支持的解释是：graph主要减少F主机规划/提交并缩小设备间隙；原来相当一部分提交成本已与设备/A侧工作重叠，保留下来的A计算、TP操作、CAM握手与F计算仍决定完成时刻。局部主机节省不能直接从端到端总时间扣除。

## 结论边界与后续

Level2 profiler有观测开销，A/F独立采样的启动与收尾也会扰动流水线；仅使用共同窗口，不把窗口外A长等待或解析时间解释为正式通信瓶颈。这次首轮诊断以冷prefill为主，不能单独代表全部高缓存命中阶段。下文结合旧全量逐请求/实际prefill分层结果，说明局部观测和未证明的结论。单次正式0.32%差异不能证明graph必然更慢，更不能从这个采样推导修复后基线的确定收益。

证据：`../evidence/afd-aligned-profile-summary.json`、`afd-aligned-overlap-analysis.json`、`afd-eager-exact-host-device-flow.json`、`afd-aligned-submit-lead.json`、`afd-aligned-clipped-timelines.json`。原始trace/CSV保留在AFD任务各aligned-diagnostic-v1 run，完整量值与关联示例可复核。

## 旧全量逐请求分层核对

两组9,078条均按同一输入ID、prompt SHA和原生request_finished记录关联，9,003条实际prefill tokens完全相同。其中，graph/eager逐请求TTFT比值中位数为1.00346；平均TTFT为6.673与6.647秒。两组同时达到≥95%缓存命中的4,477条，比值中位数1.00086、各组TTFT中位数3.051与3.118秒。后者体现分位数可有局部改善，但并未显示一致的逐请求加速；并发队列及异步组批仍未控制，不能据此做因果或显著性结论。

这批≥95%缓存命中的请求仍平均需prefill约2,536 tokens。实际prefill≤256的相同分层只有21条，不能把本实验解释为大量纯decode/极小批次的CPU提交压力测试。全量输出固定1 token；F图的提交优化不能省掉A侧prefill或整层A/F依赖。75条实际prefill不一致，graph总prefill还少约598,016 tokens，均单列，不把这部分潜在缓存差异归为图本身加速。

详见逐请求分层数据（原始留存附件）与实际时间线图（原始留存附件）。图中同一窗口内A算子、F设备工作和CPU等待的重叠来自实际记录；两个面板是独立采样，不表示严格匹配的批次速度对比。
