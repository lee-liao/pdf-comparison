# PDF 工卡差异比较工具

比较两份工卡 PDF 的文字差异：使用 MinerU 在线 API 提取结构化内容（layout.json），
按句子/步骤分割为比较单元，归一化消除 PDF 提取伪影后对齐，生成左右对照的 HTML 差异报告。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥

在项目根目录创建 `.env` 文件（已被 .gitignore 忽略，**切勿提交到 git**）：

```
MINERU_API_KEY=your_api_key_here
```

获取密钥：https://mineru.net/apiManage/apiKey

### 3. 一键比较（推荐）

```bash
# 全流程：提取两个 PDF + 比较 + 生成报告
python pdf_compare.py run old.pdf new.pdf -o diff.html

# 只比较第 2-17 页
python pdf_compare.py run old.pdf new.pdf --pages 2-17

# 保留中间 layout.json（可复用，避免重复调 API）
python pdf_compare.py run old.pdf new.pdf --keep-json output/json
```

### 其他子命令

```bash
# 仅提取：PDF -> layout.json
python pdf_compare.py extract file.pdf -o output/file

# 仅比较：两个 layout.json -> HTML（不消耗 API 额度）
python pdf_compare.py compare old.json new.json --pdf1 old.pdf --pdf2 new.pdf
```

## 参数说明

| 参数 | 适用命令 | 说明 |
|------|----------|------|
| `-o, --output` | 全部 | 输出路径（run/compare 为 HTML，extract 为目录） |
| `-t, --theme` | run/compare | 颜色主题：`light` / `dark`（默认 dark） |
| `--pages` | run/extract | 仅处理页码范围（1-based，如 `2-17`） |
| `--model` | run/extract | MinerU 模型：`vlm`（默认，hybrid 后端，本项目工卡效果最好）/ `pipeline` |
| `--keep-json` | run | 保留中间 layout.json 到指定目录 |
| `--no-content-filter` | run/compare | 禁用内容体过滤 |

## 工作原理

```
PDF ──MinerU API──> layout.json ──提取──> 全文文本
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
│   ├── mineru.py         # MinerU v4 API 客户端
│   ├── content.py        # 内容体范围检测、页码截取（PyMuPDF）
│   ├── extract.py        # layout.json -> 文本
│   ├── compare.py        # 分割、归一化、差异对齐
│   └── report.py         # HTML 报告生成
├── qa/
│   ├── test_compare.py   # 回归测试（pytest）
│   └── testdata/         # 金标测试数据
├── sampleData/           # 样本 PDF/XML
├── archive/              # 旧版脚本（已归档，勿用）
├── requirements.txt
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

## 常见问题

**Q: 该用哪个模型？**
A: 默认 `vlm`（对应 MinerU hybrid 后端），实测对工卡的提取内容最完整；`pipeline` 对此类文档提取内容偏少。已提取过的 PDF 请用 `--keep-json` 保留 JSON，之后用 `compare` 子命令直接比较，不再消耗额度。

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
