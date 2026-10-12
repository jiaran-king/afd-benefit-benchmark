# EP8 host loader 最小部署修复

原包不修改。修复目录将 `op_api/lib/libcust_opapi.so` 的符号链接实体化为同字节文件，使 aclnn 按该库真实路径寻找 host；将实际加载的 `op_tiling/lib/linux/aarch64/libcust_opmaster_rt2.0.so` 同步为包内历史快照修复已构建的 host 产物。旧 master 字节另存。

| 产物 | 修复前 | 修复后 |
|---|---|---|
| op API SHA256 | 8b555cd6188876b15a8243456fcd17e05a69dd678765db97135809534bfb8dc2 | 相同 |
| 实际 opmaster SHA256 | 6c791b96f6f1508c84ef105d0401bb63f0a9c16bb6b7e12ed442561baf3f5978 | 2e0fa08edea5cb0cc1bdbd076cf06f4bf2b0bbc7feb380dcc740f444e571d612 |
| Compressor device kernel SHA256 | ac96a866542d1230e1a212453048deb77231e1c0acb6e6fa3d8c8c15d9fb7927 | 相同 |

固定输入 b1/t773/ratio128/coff1/rotary2/cache2 的实际 CalcWorkSpace 日志由旧源码248行的29,360,128 bytes变为修复源码254行的29,884,416 bytes，补回524,288 bytes。独立单算子输出SHA相同。旧模型两请求回归首轮成功、第二轮失败；同一冻结输入/域/第二轮命中12,288 tokens下，修复后2/2成功。原45项数值回归及两个故障形状参考对比均通过。全量验证另记，不将上述测试等同于9,078完成。

未修改模型参数、Python算术或设备kernel，未关闭异步/CWS/checkpoint。现有证据确认部署遗漏并消除稳定模型复现。后续独立冷缓存正式run `non_ep8-workspace-fixed-256sessions-v1` 已完成256完整会话、9,078/9,078成功、零失败及748,751,397输入tokens；冻结输入和原生审计通过，原故障source185两轮亦成功。最终扫描50份原生/服务日志未发现检查的MTE/SMMU标记，无新故障dump，自有进程已停止。未证明其他已完成组出现静默数值错误，也未完整重建CANN底层物理越界的每一步。

完整验证：正式审计（原始留存证据）、冻结输入审计（原始留存证据）、最终清理（原始留存证据）。

记录：`../evidence/ep8-host-loader-fix-staging.json`、`workspace-fixed-host-trace.json`、`ep8-minimal-before-after.json`、`checkpoint-native-fixed-result-1.json`。正式run在发压前另查全部16worker的实际API/master映射及SHA，排除仅核对primary liboptiling而遗漏实际host的旧审计缺口。
