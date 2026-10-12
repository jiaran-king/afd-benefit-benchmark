# 运行环境与修复顺序

身份以 [versions.json](versions.json) 为准：Python 3.12.13、Torch 2.10.0+cpu、torch_npu 2.10.0.post4、CANN 9.1.0、driver 25.5.1.1。模型为原 W4A8 权重；模型 config、tokenizer 和 tokenizer_config 的 SHA 见 [数据 manifest](../datasets/frozen-256/manifest.json)。仓库不分发权重，三个元数据 hash 也不等同于完整权重校验。

## 源码

三个公开仓库与固定提交已核实可获取。使用独立目录，避免覆盖已有环境。

~~~bash
git clone https://github.com/jiaran-king/vllm.git /path/to/vllm
git -C /path/to/vllm checkout d02df748bf9efd99022f1a062597dc3cb3808485

git clone https://github.com/jiaran-king/vllm-ascend.git /path/to/ascend
git -C /path/to/ascend checkout 5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46
python3 environment/apply_patches.py --component ascend --source /path/to/ascend

git clone https://github.com/jiaran-king/afd-plugin.git /path/to/afd
git -C /path/to/afd checkout cda849a5e0a54576472096c0073f00c7095726f5
python3 environment/apply_patches.py --component afd --source /path/to/afd
~~~

Ascend 也可从 52411eb0… 基线开始，工具会先应用 PR #4，再应用预算/观测补丁；从固定 PR head 开始则跳过已合入的 PR 补丁。补丁应用只更新源码，不会编译 native。工具记录修改文件 SHA，启动前重新核对。AgentInfer 按实际 vendored 源码身份保留；upstream commit 未知。

## Native 运行时

正式实验使用匹配的 Ascend native、AFD plugin/CAM 产物。需要在固定工具链中编译、安装并核对真正加载的库；不能仅更新 Python 或 C++ 头文件。原阶段复用了已有 Ninja 对象，只重编 Compressor host，并通过原生成的 8 个 opc 脚本重编 Compressor device variants；这依赖原构建树，不是可以在任意空目录执行的通用 build 命令。

公开仓库保留必要源码补丁、准确产物身份和加载修复工具。完整原始 native 构建树与二进制属于另行取得的环境资产；拿不到这些资产时，可以复核结果，但不能宣称已恢复原始性能环境。重编译得到不同二进制时，记录为新构建并重新验证；不要篡改身份记录绕过校验。

Compressor host 加载修复必须在独立的 custom_transformer vendor 中进行：

~~~bash
python3 environment/materialize_compressor_host.py \
  --vendor /path/to/ascend/vllm_ascend/_cann_ops_custom/vendors/custom_transformer \
  --corrected-host /path/to/verified/libcust_opmaster_rt2.0.so
~~~

工具检查 API/host hash，备份原字节，实体化 API 文件并安装正确 host。仅 Non 和 A 使用修复后的 runtime；F 的 ASCEND runtime 保留原有版本，AFD plugin vendor 不替换。解释见 [host-loader-fix.md](host-loader-fix.md)。

## 部署路径与记录

[local.env.example](local.env.example) 中 ASCEND_SOURCE_DIR 指向已编译且实际加载 corrected host 的目录，FFN_ASCEND_SOURCE_DIR 指向原 F runtime；AFD_SOURCE_DIR 同时包含固定 Python 插件及其匹配 native vendor。

源码树可以包含编译产物，但 benchmark-source-identity.json 必须由固定源码与补丁生成，不能手工填写为“已验证”。完整 source export 缺 Git 元数据时，应携带原来源核对记录；当前入口要求可核对的源码记录。

新服务从调用 shell 继承 CANN/driver 的动态库路径。清除旧诊断环境，采用记录中的性能设置。启动前记录全部最终参数与环境；正式压力前检查每个 worker 的实际 libc environment、native maps 和分域容量。原生 kernel 的正式 SHA 在 versions.json；原包的 source 与完整 native 资产清单由原始证据存储保留。
