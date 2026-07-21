# PDF 工卡差异比较工具

比较两份工卡 PDF 的文字差异：提取结构化内容（layout.json），
按句子/步骤分割为比较单元，归一化消除 PDF 提取伪影后对齐，生成左右对照的 HTML 差异报告。

提取支持两种引擎，产出同构的 layout.json，后续流程完全一致：

| 引擎 | `--engine` | 依赖 | 适用场景 |
|------|-----------|------|----------|
| MinerU 在线 API | `mineru`（默认） | API 密钥、网络、每日额度 | 扫描件/复杂表格/公式，需要 OCR 与表格结构 |
| Mozilla [pdf.js](https://github.com/mozilla/pdf.js) 本地 | `pdfjs` | Node.js ≥ 22 | 有文字图层的电子版 PDF，秒级完成、零成本、可离线 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt

# 仅使用 pdf.js 引擎时需要
npm install
```

### 2. 配置 API 密钥（仅 MinerU 引擎需要）

在项目根目录创建 `.env` 文件（已被 .gitignore 忽略，**切勿提交到 git**）：

```
MINERU_API_KEY=your_api_key_here
```

获取密钥：https://mineru.net/apiManage/apiKey

### 3. 一键比较（推荐）

```bash
# 全流程：提取两个 PDF + 比较 + 生成报告
python pdf_compare.py run old.pdf new.pdf -o diff.html

# 用本地 pdf.js 提取（无需 API 密钥与额度）
python pdf_compare.py run old.pdf new.pdf --engine pdfjs

# 只比较第 2-17 页
python pdf_compare.py run old.pdf new.pdf --pages 2-17

# 保留中间 layout.json（可复用，避免重复调 API）
python pdf_compare.py run old.pdf new.pdf --keep-json output/json
```

### 其他子命令

```bash
# 仅提取：PDF -> layout.json
python pdf_compare.py extract file.pdf -o output/file
python pdf_compare.py extract file.pdf --engine pdfjs -o output/file

# 仅比较：两个 layout.json -> HTML（不消耗 API 额度，两种引擎的 JSON 均可）
python pdf_compare.py compare old.json new.json --pdf1 old.pdf --pdf2 new.pdf
```

## 参数说明

| 参数 | 适用命令 | 说明 |
|------|----------|------|
| `-o, --output` | 全部 | 输出路径（run/compare 为 HTML，extract 为目录） |
| `-t, --theme` | run/compare | 颜色主题：`light` / `dark`（默认 dark） |
| `--pages` | run/extract | 仅处理页码范围（1-based，如 `2-17`） |
| `-e, --engine` | run/extract | 提取引擎：`mineru`（默认）/ `pdfjs`（本地 Node） |
| `--model` | run/extract | MinerU 模型：`vlm`（默认，hybrid 后端，本项目工卡效果最好）/ `pipeline`；`pdfjs` 引擎忽略 |
| `--keep-json` | run | 保留中间 layout.json 到指定目录 |
| `--no-content-filter` | run/compare | 禁用内容体过滤 |

## 工作原理

```
        ┌ MinerU API ┐
PDF ────┤            ├──> layout.json ──提取──> 全文文本
        └ pdf.js本地 ┘
                                            │ 按句号/分号/WARNING/步骤编号分割
                                            ▼
                                        比较单元
                                            │ 归一化（消除提取伪影）
                                            ▼
                        SequenceMatcher 对齐 + 块内相似度 DP 配对
                                            │ 字符级高亮
                                            ▼
                                    HTML 左右对照报告
```

### 归一化（`pdfdiff/compare.py`）

比较前消除以下 PDF/MinerU 提取伪影（不影响真实差异的检出）：

- 中文换行连字符、中文字符间空格、英文字母/数字间断词空格
- 全角/半角标点差异（`，` vs `,`、`～` vs `~` 等）
- LaTeX 公式伪影（`^{\circ}\mathrm{C}` → `℃`、`\sim` → `~` 等）
- MinerU 交叉引用链接文字的重复提取（"Table Table 1"、"Refer to Figure Refer to Fig."）
- `WARNING:` / `警告：` 等标记前缀（两份文档提取不一致）

### 内容体过滤

比较正文时排除页眉/页脚：以"工卡标题"下方横线为顶界、"飞机适用范围"右侧竖线上端为底界。
锚点检测不到的页面（如已裁剪过的 PDF）自动跳过过滤，不会误裁内容。

### 提取覆盖率自检（`pdfdiff/coverage.py`）

提取引擎可能整段丢内容且不报错，在报告里只表现为一处"删除"，与真实差异无法区分。
比较前会用 PyMuPDF 的文字图层做基准，按 token 多重集（顺序无关）核对覆盖率：

```
  提取覆盖率: old.pdf 98.7%（缺失 118/8916 token）
  提取覆盖率: new.pdf 92.4%（缺失 667/8776 token）  ⚠ 可能有内容丢失
```

低于 95% 时给出告警。启用内容体过滤时基准同步只取内容体范围，不会把页眉页脚误判为丢失；
扫描件（无文字图层）无法建立基准，自动跳过。

### 差异类型

| 类型 | 说明 | 样式 |
|------|------|------|
| 未变 | 归一化后内容相同 | 无背景 |
| 新增 | 新文有，原文无 | 绿色 |
| 删除 | 原文有，新文无 | 红色 |
| 修改 | 配对成功但内容有差异 | 黄色 + 字符级高亮 |

报告支持：上一处/下一处差异导航（Alt+↑/↓）、文本搜索（Ctrl+F）、两侧行高严格对齐。

## 目录结构

```
.
├── pdf_compare.py        # 命令行入口（run / extract / compare）
├── pdfdiff/              # 核心包
│   ├── config.py         # .env 加载、API 密钥
│   ├── mineru.py         # MinerU v4 API 客户端（提取引擎之一）
│   ├── pdfjs.py          # pdf.js 本地提取客户端（提取引擎之一）
│   ├── content.py        # 内容体范围检测、页码截取（PyMuPDF）
│   ├── coverage.py       # 提取覆盖率自检（对照 PDF 文字图层）
│   ├── extract.py        # layout.json -> 文本
│   ├── compare.py        # 分割、归一化、差异对齐
│   └── report.py         # HTML 报告生成
├── tools/
│   └── pdfjs_extract.mjs # pdf.js 提取脚本（Node），输出 MinerU 同构 JSON
├── qa/
│   ├── test_compare.py   # 回归测试（pytest）
│   └── testdata/         # 金标测试数据
├── sampleData/           # 样本 PDF/XML
├── archive/              # 旧版脚本（已归档，勿用）
├── requirements.txt      # Python 依赖
├── package.json          # Node 依赖（pdfjs-dist）
└── .env                  # API 密钥（本地文件，不入库）
```

## 测试

```bash
python -m pytest qa/test_compare.py -v
```

回归测试保证：真实变更（扭矩值、件号、单字增删）必被检出；
提取伪影（空格、全角半角、LaTeX 符号）不产生误报；
金标数据（qa/testdata）的差异统计不劣化。

## MinerU API 限制

- 单文件 ≤ 200MB、≤ 600 页
- 每日 2000 页高优先级额度
- TLS 校验默认开启；证书异常环境（如 WSL）可在 `.env` 中设 `MINERU_SSL_VERIFY=0`

### 服务端版本会变，且无法指定

`model_version` 只接受 `pipeline` / `vlm` / `MinerU-HTML`，**不能锁定具体版本号**。
MinerU 在同一版本内是确定性的（同输入必得同输出），跨版本则不然。
实测同样两份 PDF、同为 hybrid 后端：

| MinerU 版本 | 差异统计 | LaTeX 伪影 | 覆盖率 |
|-------------|----------|-----------|--------|
| 2.7.5 | +35/-29/~17 | 52 / 92 处 | 98.8% / 98.7% |
| 3.4.0 | +49/-47/~14 | 0 | 98.7% / 98.1% |

3.4.0 消除了把数值打碎成 LaTeX 的问题（`80-260℃` 曾被提取为
`8 0 { - } 2 6 0 ^ { \circ } \mathrm { C }`，而温度/力矩值正是本工具要比的东西），
代价是偶发整句丢失。**因此跨时间的差异统计不可直接比较**——
报告标题下已记录本次的提取来源（如 `提取来源: MinerU 3.4.0 (hybrid)`），比较统计量前请先核对它。

## 常见问题

**Q: 该用哪个提取引擎？**
A: 电子版工卡（PDF 自带文字图层）优先 `--engine pdfjs`：本地秒级完成、不消耗额度、
版本锁定在 `package.json` 因而结果长期可复现。扫描件、需要 OCR/表格结构/公式识别的
场景用 `--engine mineru`。

实测样本 C19M7324501-1-1 第 2-17 页（同一时间、同一份 PDF）：

| 引擎 | 差异统计 | 提取覆盖率 |
|------|----------|-----------|
| pdf.js 6.1.200 | +41/-36/~25 | 100% / 99.8% |
| MinerU 3.4.0 (hybrid) | +49/-47/~14 | 98.7% / 98.1% |

**差异数量不能用来判断引擎优劣**——数量少可能只是两份文档被同样地提取错了。
应看覆盖率：MinerU 3.4.0 会静默丢掉整句（如"发动机部件会在关车后保持高温…"），
在报告里只表现为一处"删除"。反之 pdf.js 缺少表格结构，其差异有约 86% 集中在表格内
（跨列合并造成的噪声），正文部分几乎无误报。
注意覆盖率基准取自 PDF 文字图层，对同属文字层提取的 pdf.js 天然有利，
不能用于评价扫描件上的 OCR 提取。

**Q: pdf.js 引擎报"未安装 pdfjs-dist"？**
A: 在项目根目录执行 `npm install`（需 Node.js ≥ 22）。

**Q: 该用哪个模型？**
A: 默认 `vlm`（对应 MinerU hybrid 后端），实测对工卡的提取内容最完整；`pipeline` 对此类文档提取内容明显偏少
（同一份 xinyuan：hybrid 27339 字符 vs pipeline 21506 字符，差异统计因此劣化到 +52/-147/~20）。
已提取过的 PDF 请用 `--keep-json` 保留 JSON，之后用 `compare` 子命令直接比较，不再消耗额度。

**Q: 为什么有时显示"删除+新增"而不是"修改"？**
A: 两个单元相似度低于 0.85 时不配对（阈值见 `pdfdiff/compare.py` 的 `PAIR_THRESHOLD`）。
差异仍然完整显示，只是不做字符级高亮。

**Q: 旧版脚本在哪里？**
A: 在 `archive/` 目录（`auto_crop_correct_logic.py`、`compare_integration.py`、
`mineru_extract_v4.py`、`pdf_compare_auto.py`）。新版 `pdf_compare.py` 已覆盖其全部功能；
裁剪工具由 `--pages` 页码截取 + 自动内容体过滤替代。

## 参考

- [MinerU API 文档](https://mineru.net/doc/docs/)
- [MinerU vs PyMuPDF 对比](mineru_vs_pymupdf_comparison.md)
- [PDF 提取 API 选型建议](pdf_extraction_api_recommendations.md) - 各提取方案对比与实测结论
