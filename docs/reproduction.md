# 复现步骤

以下设备入口针对原 256/C16 基线。新增 128/C12 的[负载派生](../datasets/frozen-128/README.md)、[实际配置与适配范围](../experiments/2026-10-14-c12-128/README.md)单独说明，不会仅因更换 run-name 自动切换。

## 先离线复核

~~~bash
python3 scripts/recompute_results.py --output /tmp/afd-recomputed.csv
python3 scripts/recompute_results.py --result-set 2026-10-11
python3 scripts/recompute_results.py --result-set 2026-10-14-c12-128
python3 -m unittest discover -s tests -v
~~~

只使用仓库内数值证据，不需要设备、下载原始数据或模型。保留输出与当前 Git commit。

## 准备设备回放环境

需要独占 16 DIE 的同类 Ascend 910C 环境。先完成 [环境步骤](../environment/README.md)，确认模型、tokenizer、源码和 native 身份。回放客户端依赖见 environment/requirements-client.txt；该文件是兼容依赖约束，原实验未保留完整 pip lock。新 run 必须记录实际安装版本。

从本仓库固定版本的 Release 下载正式冻结 requests.jsonl。下载和导入只需 Python 标准库，建议预留至少 10 GB；完整设备回放仍使用前述匹配环境。原始会话和正式负载的区别及单独获取方法见 [数据集说明](../datasets/README.md)。

~~~bash
python3 scripts/download_datasets.py \
  --dataset frozen --output-dir /path/to/afd-data

python3 scripts/import_dataset.py \
  --source /path/to/afd-data/frozen-256/requests.jsonl \
  --workspace /path/to/afd-work
~~~

下载器校验压缩包及解压文件的大小和 SHA256。导入器校验每轮 prompt SHA、长度、优先级、完整会话和最终文件字节；结果必须匹配 d41cca12…751c48a。失败会清理本次临时导入，保留源文件。若自行持有精确 609 会话冻结父集，导入时加 --parent；正式复现无需下载原始 conversation JSON 或重新分词。

## 配置与预览

复制 environment/local.env.example 到仓库外，填写现有路径。加载该机器正确的 CANN 环境，再加载本地 env 文件。机器地址、路径与网卡变更是部署适配，必须记录；性能参数保持冻结。

~~~bash
source /path/to/cann/set_env.sh
source /path/to/afd-local.env

"$BENEFIT_PYTHON" scripts/benchmark.py plan \
  --group non_ep4 --workspace /path/to/afd-work --run-name non-ep4-repro-001
~~~

五组的 group 值为 non_ep4、non_ep8、non_ep16、afd_eager、afd_fgraph。EP16 使用单实例 DP4/TP4/EP16，四个 DP rank 的映射和记录配置见 [EP16 定义](../experiments/2026-10-12-ep16/README.md)。每次使用新 run-name；已有目录会拒绝覆盖。plan 不启动模型、不访问 API。

## 执行一个组

以下命令使用同一 group、workspace、run-name。Non 三组在同一机器顺序运行；AFD 两组在另一机器顺序运行。不要同时在一台机器启动两组。

~~~bash
"$BENEFIT_PYTHON" scripts/benchmark.py start \
  --group afd_eager --workspace /path/to/afd-work --run-name afd-eager-repro-001

# 等待 services/*/stdout.log 中正常启动/profile 完成后：
"$BENEFIT_PYTHON" scripts/benchmark.py record \
  --group afd_eager --workspace /path/to/afd-work --run-name afd-eager-repro-001

"$BENEFIT_PYTHON" scripts/benchmark.py replay \
  --group afd_eager --workspace /path/to/afd-work --run-name afd-eager-repro-001

"$BENEFIT_PYTHON" scripts/benchmark.py audit \
  --group afd_eager --workspace /path/to/afd-work --run-name afd-eager-repro-001

"$BENEFIT_PYTHON" scripts/benchmark.py stop \
  --group afd_eager --workspace /path/to/afd-work --run-name afd-eager-repro-001
~~~

start 检查空闲设备、数据导入、模型文件和源码记录，保存服务配置并启动进程。record 采集全部 worker 的实际环境、native 映射、容量与客户端配置；读取其它自有进程的环境/内存需要相应 Linux 权限。AFD 的只读 graph 记录器还需要 Python 3.12 头文件和 gcc。

replay 内部执行全部唯一端点冷 reset、逐域基线记录，再调用原 AgentInfer 链；成功后原生审计自动执行。两组 AFD 均在压力前后记录 F 状态。任何失败保留 run 目录，不能重复调用 replay 拼接结果；检查服务时不要自动启动另一轮。stop 只处理当前 run 的已记录身份及其后代，保留工作目录和资源。

## 完成与归档

至少检查：formal-http/summary.json complete、formal-audit.json complete 且 execution_audit passed、9,078 请求/256 会话、零未解释失败；输入 SHA、域路由、就绪优先级、C16 全部一致。AFD 还要有压力前后 graph 状态，FULL 的 4 个 F worker replay 计数递增。

保留 manifest、configuration、device 快照、all-endpoint-metrics、逐域日志、formal-start、formal-http、formal-audit、stop-owned。机器环境和完整日志留在私有证据存储；公开结果采用字段白名单，不能直接上传整个 run。

整理后的工具已做离线验证，尚未重新跑硬件全量；这是迁移后的执行入口，不是新实验结果。driver/CANN 安装、匹配的模型及原生二进制取得仍是显式外部前提，不能把克隆仓库称作零依赖一键运行。
