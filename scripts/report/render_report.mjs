// Optional report export: npm install marked@17.0.5 playwright@1.62.1
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const source = path.join(repo, 'results/2026-10-12-ep16/REPORT.zh-CN.md');
const output = path.resolve(process.argv[2] || path.join(repo, 'results/2026-10-12-ep16'));
// Override only locates already-installed optional packages, e.g. a shared runtime.
const packages = process.env.REPORT_NODE_MODULES;
const {marked} = await import(packages ? pathToFileURL(path.join(packages, 'marked/lib/marked.esm.js')).href : 'marked');
const {chromium} = await import(packages ? pathToFileURL(path.join(packages, 'playwright/index.mjs')).href : 'playwright');
const publicBase = 'https://github.com/jiaran-king/afd-benefit-benchmark/blob/main/results/2026-10-12-ep16/';
const tokens = marked.lexer(fs.readFileSync(source, 'utf8'));
marked.walkTokens(tokens, token => {
  if (token.type === 'image') {
    const figure = path.resolve(path.dirname(source), token.href);
    token.href = 'data:image/png;base64,' + fs.readFileSync(figure).toString('base64');
  } else if (token.type === 'link') {
    token.href = new URL(token.href, publicBase).href;
  }
});
const css = `
* { box-sizing: border-box; }
body { margin: 0; color: #20242a; background: #f3f4f5; font-family: 'Microsoft YaHei','Noto Sans CJK SC',sans-serif; }
main { max-width: 1030px; margin: 30px auto; padding: 42px 50px; background: white; }
h1 { font-size: 23px; line-height: 1.45; } h2 { font-size: 17px; margin: 30px 0 10px; }
p,li { font-size: 13.5px; line-height: 1.85; } a { color: #285b83; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; margin: 17px 0; font-size: 12px; line-height: 1.55; }
th,td { border-bottom: 1px solid #dce0e4; padding: 8px 7px; vertical-align: top; }
th { border-top: 1.5px solid #535b65; border-bottom: 1px solid #535b65; text-align: left; }
tr:last-child td { border-bottom: 1.5px solid #535b65; }
img { display: block; max-width: 100%; height: auto; margin: 22px auto 6px; }
code { font-size: .92em; }
@page { size: A4; margin: 16mm 15mm; }
@media print {
  body { background: white; } main { margin: 0; padding: 0; max-width: none; }
  h1 { font-size: 20px; } h2 { font-size: 15px; break-after: avoid; }
  p,li { font-size: 10.3pt; line-height: 1.64; } table { font-size: 8.9pt; }
  th,td { padding: 6px; } tr,img { break-inside: avoid; }
}`;
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  '<title>五组部署实验：KV 缓存与性能</title><style>' + css + '</style></head>' +
  '<body><main>' + marked.parser(tokens) + '</main></body></html>';
fs.mkdirSync(output, {recursive: true});
fs.writeFileSync(path.join(output, 'REPORT.zh-CN.html'), html);
const browser = await chromium.launch({headless: true, executablePath: process.env.REPORT_CHROMIUM || undefined});
try {
  const page = await browser.newPage({viewport: {width: 1100, height: 900}});
  await page.route('**/*', route => route.abort());
  await page.setContent(html, {waitUntil: 'load'});
  await page.evaluate(() => document.fonts.ready);
  const images = await page.locator('img').evaluateAll(nodes => nodes.every(n => n.complete && n.naturalWidth > 0));
  if (!images) throw new Error('Report image failed to load');
  await page.pdf({path: path.join(output, 'REPORT.zh-CN.pdf'), printBackground: true, preferCSSPageSize: true});
  if (process.env.REPORT_PREVIEW) await page.screenshot({path: process.env.REPORT_PREVIEW, fullPage: true});
  console.log(JSON.stringify({html: 'REPORT.zh-CN.html', pdf: 'REPORT.zh-CN.pdf', embeddedImages: await page.locator('img').count()}));
} finally {
  await browser.close();
}
