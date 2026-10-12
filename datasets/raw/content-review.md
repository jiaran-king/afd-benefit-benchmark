# 原始数据中私钥格式内容的核对

日期：2026-10-12。范围：原始文件 SHA256 670f1ae8325fd70aac6ae6bdf4b03bbbd740d6ac8f2b49d8a02daaee3193fbc3 中检测到的 7 处私钥格式内容。位置均为零基数组下标，不在本记录中复制密钥正文。

| 源会话 ID | conversations 消息下标 | 数量 | 已核对上下文 |
|---:|---:|---:|---|
| 166 | 26 | 1 | 命令先在临时 flipt-testcert 目录用 openssl 生成 RSA 2048、自签名、CN=localhost 测试证书，再读取该目录中的 ssl_key.pem |
| 293 | 48 | 2 | 读取 fixtures/certs/identities/key-cert-ca.pem 与 fixtures/certs/identities/tls.pem 的测试样例 |
| 311 | 4 | 4 | Teleport 测试辅助代码中的 testPairs；源码注释明确说明为 unit tests 预生成的四组公私钥 |

这 7 处都有明确测试用途上下文，不能把格式扫描命中当作生产凭据泄露证据。没有使用这些内容进行鉴权尝试。本记录仅说明这 7 处的来源和用途，不是对数据中每个字符串的认证有效性判断。

正式 256 会话子集包含源 ID 166，不包含 293 和 311；因此不能通过删掉命中内容来声称仍是同一正式负载。此次按用户授权发布原始文件及精确冻结 token 文件，保持两者原有 SHA256。
