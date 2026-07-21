#!/usr/bin/env node
/**
 * 用 Mozilla pdf.js 提取 PDF 文本，输出与 MinerU layout.json 同构的 JSON。
 *
 * 用法: node tools/pdfjs_extract.mjs <input.pdf> <output.json>
 *
 * 输出结构（下游 pdfdiff/extract.py 直接复用，无需分支）:
 *   { pdf_info: [ { page_idx, page_size, para_blocks: [
 *       { type: "text", bbox, index, lines: [ { bbox, spans: [{type:"text", content}] } ] }
 *     ], discarded_blocks: [] } ] }
 *
 * 坐标系: 左上原点、PDF 点（pt），与 PyMuPDF 一致 —— 内容体过滤（content.py）
 * 依赖此坐标系，故不可改为 pdf.js 原生的左下原点。
 */

import { readFile, writeFile } from "node:fs/promises";
import { getDocument, Util, version } from "pdfjs-dist/legacy/build/pdf.mjs";

// 同一行的基线 y 容差（pt）；超过则视为新行
const LINE_TOLERANCE = 2.5;
// 相邻 text item 之间插入空格的最小水平间隙（pt）
const SPACE_GAP = 1.0;

/** 把 text item 转成带左上原点 bbox 的字形片段 */
function toFragment(item, viewport) {
  const m = Util.transform(viewport.transform, item.transform);
  const height = Math.hypot(m[2], m[3]) || item.height || 0;
  const x = m[4];
  const baseline = m[5];
  return {
    text: item.str,
    x,
    right: x + (item.width || 0),
    baseline,
    bbox: [x, baseline - height, x + (item.width || 0), baseline],
  };
}

/** 按基线 y 聚类为行，行内按 x 排序并拼接文本 */
function groupLines(fragments) {
  const sorted = [...fragments].sort(
    (a, b) => a.baseline - b.baseline || a.x - b.x,
  );
  const lines = [];
  let current = null;

  for (const frag of sorted) {
    if (!current || Math.abs(frag.baseline - current.baseline) > LINE_TOLERANCE) {
      current = { baseline: frag.baseline, frags: [frag] };
      lines.push(current);
    } else {
      current.frags.push(frag);
    }
  }

  return lines.map((line) => {
    const frags = line.frags.sort((a, b) => a.x - b.x);
    let text = "";
    let prevRight = null;
    for (const frag of frags) {
      const needsSpace =
        prevRight !== null &&
        frag.x - prevRight > SPACE_GAP &&
        !text.endsWith(" ") &&
        !frag.text.startsWith(" ");
      text += (needsSpace ? " " : "") + frag.text;
      prevRight = frag.right;
    }
    return { text: text.trim(), bbox: mergeBbox(frags.map((f) => f.bbox)) };
  }).filter((line) => line.text.length > 0);
}

function mergeBbox(boxes) {
  return [
    Math.min(...boxes.map((b) => b[0])),
    Math.min(...boxes.map((b) => b[1])),
    Math.max(...boxes.map((b) => b[2])),
    Math.max(...boxes.map((b) => b[3])),
  ];
}

async function extractPage(page, pageIdx) {
  const viewport = page.getViewport({ scale: 1 });
  const content = await page.getTextContent();
  const fragments = content.items
    .filter((item) => typeof item.str === "string" && item.str.trim())
    .map((item) => toFragment(item, viewport));

  // 一行一块：pdf.js 不提供段落/表格结构，块粒度取最保守的行级
  const paraBlocks = groupLines(fragments).map((line, index) => ({
    type: "text",
    bbox: line.bbox,
    index,
    lines: [{ bbox: line.bbox, spans: [{ type: "text", content: line.text }] }],
  }));

  return {
    page_idx: pageIdx,
    page_size: [viewport.width, viewport.height],
    para_blocks: paraBlocks,
    discarded_blocks: [],
  };
}

async function main() {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) {
    console.error("用法: node tools/pdfjs_extract.mjs <input.pdf> <output.json>");
    process.exit(2);
  }

  const data = new Uint8Array(await readFile(input));
  const loadingTask = getDocument({
    data,
    useSystemFonts: true,
    // Node 环境无 canvas/字体服务，关闭无关能力以提速
    disableFontFace: true,
    isEvalSupported: false,
  });
  const doc = await loadingTask.promise;

  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    pages.push(await extractPage(await doc.getPage(i), i - 1));
  }
  const numPages = doc.numPages;
  await loadingTask.destroy();

  // 与 MinerU 一致地记录提取来源，供报告溯源（pdfdiff/extract.py: source_info）
  await writeFile(
    output,
    JSON.stringify({ _backend: "pdfjs", _version_name: version, pdf_info: pages }),
    "utf-8",
  );
  console.error(`  pdf.js: ${numPages} 页, ${pages.reduce((n, p) => n + p.para_blocks.length, 0)} 行`);
}

main().catch((err) => {
  console.error(`pdf.js 提取失败: ${err?.message || err}`);
  process.exit(1);
});
