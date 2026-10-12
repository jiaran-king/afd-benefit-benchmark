# 来源与许可

scripts/runner/vendor/agentinfer 保留实际执行过的 AgentInfer 源码快照及文件内 Apache-2.0 / Copyright contributors 声明。上游 commit 未记录，以 sources.json 中实际字节身份为准。Apache-2.0 许可全文见 [environment/Apache-2.0.txt](environment/Apache-2.0.txt)。

environment/patches 保留 vLLM-Ascend 和 AFD 相关代码的原许可头与上下文。对应公开基线分别为 jiaran-king/vllm-ascend、jiaran-king/afd-plugin；源码修复层与实验观测层的顺序见 environment/README.md。vLLM 为外部固定源码依赖。

本仓库整理不改变第三方文件许可。原始会话数据和正式冻结 token 文件按用户授权通过本仓库 Release 发布，来源与身份见 datasets；其中的第三方代码片段保留原内容和声明，不因压缩或分词改变其许可。模型权重和 native SDK/二进制不随此次发布，其取得和使用遵循各自条款。仓库未给整个材料集合添加统一再许可。
