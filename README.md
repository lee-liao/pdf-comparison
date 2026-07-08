# PDF 工差异比较工具集

基于 Myers Diff 算法（Git/GitHub 同款）的 PDF 差异比较工具套件，支持自动裁剪、在线提取和精确对比。

## 工具概览

| 工具 | 功能 | 适用场景 |
|------|------|----------|
| `pdf_compare_auto.py` | 全流程自动化 | 一键完成提取+对比，推荐使用 |
| `mineru_extract_v4.py` | 在线 API 提取 | 使用 MinerU 在线服务提取 PDF |
| `auto_crop_correct_logic.py` | PDF 自动裁剪 | 剪除 header/footer，保留内容体 |
| `compare_integration.py` | 核心比较引擎 | 高级用法，支持 JSON 直接比较 |

---

## 快速开始

### 一键比较 PDF（推荐）

```bash
# 自动提取 + 比较 + 生成报告（自动过滤 header/footer）
python pdf_compare_auto.py file1.pdf file2.pdf

# 指定输出文件
python pdf_compare_auto.py file1.pdf file2.pdf -o result.html

# 禁用内容体过滤（提取所有内容）
python pdf_compare_auto.py file1.pdf file2.pdf --no-content-filter
```

### 使用 MinerU 在线 API 提取

```bash
# 提取 PDF，获得 layout.json
python mineru_extract_v4.py input.pdf output_dir

# 使用 pipeline 模型（默认，更准确）
python mineru_extract_v4.py input.pdf output_dir pipeline

# 使用 vlm 模型（更快）
python mineru_extract_v4.py input.pdf output_dir vlm
```

### PDF 自动裁剪

```bash
# 自动检测并剪除 header/footer
python auto_crop_correct_logic.py input.pdf -o output.pdf

# 显示调试信息
python auto_crop_correct_logic.py input.pdf -o output.pdf --debug
```

**裁剪行为**：
- 自动识别并删除附图（大图片页），如插图、图解页
- 删除附图之后的**所有页面**（通常附图在文档末尾）
- 基于"工卡标题"和"飞机适用范围"智能检测内容体范围

### 高级用法：直接比较 JSON

```bash
# 比较已提取的 JSON 文件
python compare_integration.py --json file1.json file2.json --pdf1 file1.pdf --pdf2 file2.pdf

# 使用自定义主题
python compare_integration.py --json file1.json file2.json -t light
```

---

## 功能特点

### 1. 全流程自动化 (`pdf_compare_auto.py`)
- 自动调用 MinerU API 提取 PDF 内容
- 自动计算内容体范围，过滤 header/footer
- 生成 HTML 差异报告，支持搜索和同步滚动
- 支持亮色/暗色主题

### 2. MinerU 在线 API (`mineru_extract_v4.py`)
- 使用 MinerU 官方 API，无需本地安装
- 支持批量上传和自动任务提交
- 自动下载结果并解压
- 输出包含 layout.json、markdown、images 等

**API 限制**：
- 单个文件 ≤ 200MB，≤ 600 页
- 每日 2000 页高优先级额度

### 3. PDF 自动裁剪 (`auto_crop_correct_logic.py`)
- 基于"工卡标题"和"飞机适用范围"智能检测裁剪线
- 自动识别并删除附图（大图片页）及其之后的所有页面
- 所有页面使用统一的微调系数
- 使用屏幕坐标系统（y=0 在顶部）

### 4. 核心比较引擎 (`compare_integration.py`)
- **Myers Diff 算法** - 业界标准差异算法
- **字符级高亮** - 精确显示单词/字符的增删改
- **左右对照视图** - 并排显示，带行号
- **内容体过滤** - 自动过滤 header/footer 内容
- **空格归一化** - 避免 PDF 提取伪影导致误判

---

## 参数说明

### pdf_compare_auto.py

| 参数 | 说明 |
|------|------|
| `FILE1 FILE2` | 要比较的两个 PDF 文件（必需） |
| `-o, --output` | 输出 HTML 文件路径（默认: diff_result.html） |
| `-t, --theme` | 颜色主题：light / dark（默认: dark） |
| `--no-content-filter` | 禁用内容体过滤（不过滤 header/footer） |
| `--keep-intermediate` | 保留中间 JSON 文件 |
| `--debug` | 显示调试信息 |

### mineru_extract_v4.py

| 参数 | 说明 |
|------|------|
| `pdf_path` | 输入 PDF 文件（必需） |
| `output_path` | 输出目录（可选） |
| `model_version` | 模型版本：pipeline（默认）或 vlm |

### auto_crop_correct_logic.py

| 参数 | 说明 |
|------|------|
| `input` | 输入 PDF 文件（必需） |
| `-o, --output` | 输出 PDF 文件路径 |
| `--debug` | 显示调试信息 |

### compare_integration.py

| 参数 | 说明 |
|------|------|
| `--json FILE1 FILE2` | 比较两个 MinerU JSON 文件 |
| `-o, --output` | 输出 HTML 文件路径 |
| `-t, --theme` | 颜色主题：light / dark（默认） |
| `--pdf1 PDF_FILE` | 原文 PDF（用于计算内容体范围） |
| `--pdf2 PDF_FILE` | 新文 PDF（用于计算内容体范围） |

---

## 内容体过滤机制

为了只比较内容体内的文字，系统会：

1. **检测关键文本位置** - 在 PDF 中查找"工卡标题"和"飞机适用范围"
2. **计算内容体范围** - 根据关键文本位置确定 y 坐标范围
3. **过滤内容** - 只提取 bbox 在内容体范围内的内容

**坐标系统**：屏幕坐标（y=0 在顶部，y 向下增大）

---

## 差异类型说明

| 类型 | 说明 | 样式 |
|------|------|------|
| 未变 | 内容相同 | 灰色背景 |
| 新增 | 新文有，原文无 | 绿色背景 |
| 删除 | 原文有，新文无 | 红色背景 |
| 修改 | 内容有差异 | 黄色背景 + 字符级高亮 |

---

## 目录结构

```
.
├── pdf_compare_auto.py              # 全流程自动化（推荐）
├── mineru_extract_v4.py              # MinerU 在线 API 提取
├── auto_crop_correct_logic.py        # PDF 自动裁剪
├── compare_integration.py            # 核心比较引擎
├── .env                              # API 密钥配置
├── README.md                         # 本文档
├── mineru_vs_pymupdf_comparison.md   # MinerU vs PyMuPDF 技术对比
├── qa/                               # 测试验证目录
│   ├── diff_result_old.html         # 旧流程结果（用于对比测试）
│   └── testdata/                    # 测试数据
│       ├── C19M7324501-1-1_mro-noheader_Page2-17.pdf
│       ├── C19M7324501-1-1_xinyuan-noheader_Page2-17.pdf
│       ├── MinerU_C19M7324501-1-1_mro-P2-17.json
│       └── MinerU_C19M7324501-1-1_xinyuan-P2-17.json
├── output/                           # 输出目录
└── sampleData/                       # 样本数据
    └── C19M7324501-1-1/
        └── C19M7324501-1-1_mro.pdf  # 示例 PDF
```

---

## 配置 API 密钥

在 `.env` 文件中设置 MinerU API 密钥：

```bash
MINERU_API_KEY=your_api_key_here
```

获取 API 密钥：https://mineru.net/apiManage/apiKey

---

## 技术细节

### PDF 裁剪系数

```python
left_offset_pt: 0.56    # 左边距微调
top_offset_pt: 0.20     # 顶边距微调
right_offset_pt: 0.74   # 右边距微调
bottom_offset_pt: 2.00  # 底边距微调
```

### 差异算法

- **主匹配**: SequenceMatcher（基于位置）
- **子匹配**: SequenceMatcher（基于内容相似度）
- **相似度阈值**: 0.85 = 匹配，0.98 = 未变

### 文本分割规则

按以下符号分割文本为比较单元：
- 句号 `.。`
- 分号、感叹号、问号 `；;！!?？`
- 关键词 `WARNING:`, `CAUTION:`, `NOTE:`
- 步骤编号 `(1)`, `(a)` 等

### 归一化处理

比较前自动删除：
- PDF 换行产生的连字符空格
- 中文字符之间的空格
- 中文标点周围的空格
- 英文字母/数字之间的多余空格
- 破折号后的空格

---

## 常见问题

**Q: 为什么有时显示"删除/新增"而不是"修改"？**
A: 当分割不一致时（如原文2句 vs 新文1句），会导致无法匹配。这是已知限制。

**Q: MinerU API 提取很慢怎么办？**
A: 可以尝试使用 `vlm` 模型代替 `pipeline`，速度更快但精度略低。

**Q: 如何只比较特定页面？**
A: 先使用 PDF 裁剪工具提取需要的页面，再进行比较。

---

## 参考资料

- [MinerU API 文档](https://mineru.net/doc/docs/)
- [MinerU vs PyMuPDF 对比](mineru_vs_pymupdf_comparison.md) - 为什么选择 MinerU
- [Myers Diff 算法](https://en.wikipedia.org/wiki/Diff_utility)
