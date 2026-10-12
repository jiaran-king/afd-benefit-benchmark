# 报告附件生成

数值复核只需标准库，不依赖这里的排版工具。已发布报告以 [Markdown](../../results/2026-10-12-ep16/REPORT.zh-CN.md) 为文本源，配有自包含 HTML 和 PDF；链接指向本仓库公开证据。

## 重新作图

可选依赖为 Python matplotlib、numpy 和中文字体。默认查找 Noto Sans CJK，也可通过 REPORT_FONT 指定本机字体文件。脚本读取五组 metrics.csv，生成三幅图和作图数据：

~~~bash
python3 scripts/report/plot_five_arm.py --output-dir /tmp/afd-figures
~~~

图形字体和元数据可能随环境变化；以数值 CSV 和离线复核为准，不要求重新作图后字节完全一致。

## HTML / PDF

需要 Node.js、marked 17.0.5、playwright 1.62.1 及可用 Chromium。可将可选依赖安装在仓库外，再设置 REPORT_NODE_MODULES 为该目录的 node_modules；REPORT_CHROMIUM 可指定已有浏览器可执行文件。不要改动设备回放环境。

~~~bash
node scripts/report/render_report.mjs /tmp/afd-report
~~~

脚本嵌入仓库内三幅 PNG，生成 REPORT.zh-CN.html 和 REPORT.zh-CN.pdf，不访问远程页面。中文字体需由排版机器提供。Markdown 和 CSV 为可复核源，生成附件只改变展示形式。
