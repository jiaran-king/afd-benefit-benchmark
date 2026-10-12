# 统一修复基线四组实验

实验定义见 [方法](../../docs/methodology.md)，唯一配置来源是 [recorded-configuration.json](recorded-configuration.json)。它包含 10 个模型服务与 4 个回放客户端的正式命令，以及筛选后的性能环境变量。

公开导出将 Python、模型和 run 目录替换为路径参数，去掉机器身份与非性能环境。模型服务 argv 中的性能参数保持不变；新启动器直接读取该文件，避免文档与脚本维护两套数值。

新增入口对路径、run 名、进程记录和依赖核对进行了适配。原 AgentInfer 回放、SSE、准入与图执行模块保留实际源字节，见 [适配记录](../../environment/runner-adaptations.json)。新环境未进行硬件全量重跑。

改变 MBT、微批次、输出长度、路由或并发属于新实验；先复制实验定义并按 [扩展方法](../../docs/extending.md) 命名，不直接覆盖本目录。
