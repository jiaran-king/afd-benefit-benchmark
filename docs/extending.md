# 扩展实验与可比性

先明确新问题与变化轴，再建立新的 experiments/日期-名称 和 results/日期-名称 目录。最新正式主表保持冻结。

每个新实验至少记录：

1. 基线 commit、补丁与 native 身份；模型/输入身份。
2. 完整配置矩阵，区分性能参数、部署路径和观测开销。
3. 负载选择、会话完整性、输出长度、优先级、路由、并发与缓存起点。
4. 唯一 run ID、实际命令/环境、采集时间与校验结果。
5. 指标定义、失败/缺失数据，以及结论可适用的范围。

当前 benchmark.py 明确实现冻结四组，启动参数从 recorded-configuration.json 读取。新增 EP 数或拓扑时，需要同步新的 service/device 划分、endpoints DP rank、three_arm_topology/domain_worker、容量核对和新实验配置加载路径，并增加相应离线校验；不能只改标签沿用旧路由。扩展并发或输出长度时还需修改准入及 SSE 校验，单独保存执行器版本。

比较两组 graph 时保持 A eager、异步调度、CAM async、两份 token 微批次与 F layered GMM 一致，仅改变 F 执行模式及必要 graph 设置。测量应对称；profiler 运行进入 diagnostics，不直接替代无 profiler 正式全量。

对新数据集先生成独立冻结清单，记录完整会话选择和模型/tokenizer 版本。不要复用旧 request SHA，不将当前输出反馈后仍声称原负载；不要按缓存收益或完成情况挑样本。

异常 run 保留独立目录与失败说明。再次运行使用新 ID，不能删掉失败记录或拼接成功片段。若需要统计稳定性，另行设计重复次数和分析方法；现有每配置一次结果不提供显著性保证。
