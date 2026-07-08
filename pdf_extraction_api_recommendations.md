# PDF Extraction API Recommendations

**Date:** 2026-07-08
**Context:** This project compares Chinese aviation job-card PDFs (C919 maintenance, MRO vs Xinyuan editions). It currently uses the **MinerU online API** (v4, `mineru.net`) to extract structured `layout.json`, which the `pdfdiff` package then diffs. This document evaluates whether a better extraction API exists and records the findings from live testing.

---

## TL;DR

1. **Short term (done):** Stay on the MinerU API, but use `model_version=vlm` — it maps to MinerU's **hybrid** backend, which extracts these job cards significantly better than `pipeline` (27–28k chars vs 21.5k on the qa testdata). This is now the project default.
2. **Recommended next step:** Switch to **self-hosted MinerU** (`pip install mineru`, open-source project behind the same API). Identical `layout.json` schema → **zero code change** in `pdfdiff`. Removes the 2000-page/day quota, polling latency, and stops uploading airline maintenance documents to a third-party cloud.
3. **Only if table fidelity becomes a problem:** trial **Docling** (IBM, MIT license) on the qa testdata. It has the strongest open-source table-structure extraction, but would require an adapter for its `DoclingDocument` format.
4. **If a hosted API is mandatory:** LlamaParse or Azure Document Intelligence are the strongest for tables — but weigh sending these documents to a US/EU cloud against the actual quality gap.

---

## Candidate Comparison (as of mid-2026)

| Option | Type | Table quality | CJK support | Output format | Fit for this project |
|---|---|---|---|---|---|
| **MinerU online API** (current) | Hosted API | Good (HTML tables) | **Excellent** | `layout.json` | Baseline — works today; quota 2000 pages/day |
| **MinerU self-hosted** | Local, open-source (AGPL) | Good | **Excellent** | Same `layout.json` | **Best next step — zero code change** |
| **Docling** (IBM) | Local, open-source (MIT) | **Excellent** (TableFormer) | Good | `DoclingDocument` JSON | Adapter needed; slower; can hallucinate on very dense tables |
| **Marker / Datalab API** | Local (GPL) or hosted | Very good | Good | Markdown / JSON / chunks | Benchmark leader among OSS converters; adapter needed |
| **LlamaParse** | Hosted API | **Best on nested tables** | Good | Markdown / JSON | Inconsistent on borderless / merged-cell tables |
| **Azure Document Intelligence** | Hosted API | Excellent | Good | Proprietary JSON | Enterprise SLA; per-page cost; data residency question |
| **PyMuPDF (raw)** | Local library | Weak (fragmented) | OK | Text blocks | Already rejected for diffing (see [mineru_vs_pymupdf_comparison.md](mineru_vs_pymupdf_comparison.md)); still used for line detection, cropping, page slicing |

Benchmark context (opendataloader-bench, 200 PDFs, 2026): Docling 0.877 > Marker 0.861 > MinerU 0.831 among free tools — but MinerU remains one of the strongest specifically for **CJK / mixed Chinese-English layouts**, which is exactly this corpus.

---

## Live Findings on This Corpus (2026-07-07)

Tested against `qa/testdata` (15–16 page job-card extracts, golden JSONs produced by MinerU **hybrid** backend v2.7.5):

| Extraction | Backend reported | Extracted chars (xinyuan doc) |
|---|---|---|
| Golden testdata (reference) | `hybrid` v2.7.5 | 29,291 |
| API `model_version=pipeline` | `pipeline` v3.4.0 | **21,506** (content dropped) |
| API `model_version=vlm` | `hybrid` v3.4.0 | **27,339** (close to golden) |

**Conclusion:** on MinerU 3.4.0, `pipeline` regressed for this document type; `vlm` (hybrid backend) is the right setting and is the project default (`pdfdiff/mineru.py`, CLI `--model`).

Also note: MinerU extraction of the *same* page can differ between two documents (e.g., one table OCR'd as LaTeX formulas, the other as clean text). The diff engine's normalization (`pdfdiff/compare.py`) folds the known artifact classes; residual added/deleted blocks in reports are usually this phenomenon, not real content changes.

---

## Why Self-Hosted MinerU Is the Recommended Move

- **Zero migration cost:** same `layout.json` schema; `pdfdiff/extract.py` needs no changes. Only `pdfdiff/mineru.py` would gain a "local" mode (run `mineru` CLI instead of HTTP calls).
- **Data privacy:** airline maintenance job cards stop leaving the machine. This is likely the strongest argument for this project.
- **No quota / no polling:** the online API's 2000-page daily limit and multi-minute polling loop disappear.
- **Version pinning:** the online service silently upgraded 2.7.5 → 3.4.0 and changed extraction behavior (see table above). Self-hosting pins the model version, so golden testdata stays comparable.
- **Cost:** requires a machine with a GPU for reasonable speed (CPU works but is slow). If no GPU is available, staying on the API is reasonable.

## When to Consider Docling Instead

Only if you observe **actual table-structure errors** (merged cells misread, rows dropped) that survive MinerU hybrid. Then:

1. Run Docling on `qa/testdata` PDFs and compare its table output against the PDFs manually.
2. If clearly better, write an adapter mapping `DoclingDocument` → the text-unit stream `pdfdiff/compare.py` consumes.
3. Keep PyMuPDF for content-body line detection regardless — that part is extractor-independent.

---

## Sources

- [Best Open-Source PDF-to-Markdown Tools in 2026: Marker vs Docling vs MinerU](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [pdfmux vs LlamaParse vs Docling vs Unstructured (2026)](https://pdfmux.com/blog/pdfmux-vs-llamaparse-vs-docling-vs-unstructured-2026/)
- [PDF Table Extraction: Docling vs Marker vs LlamaParse](https://codecut.ai/docling-vs-marker-vs-llamaparse/)
- [Best PDF Parsers for AI and RAG Workflows in 2026](https://www.firecrawl.dev/blog/best-pdf-parsers)
- [PDF Data Extraction Benchmark: Docling, Unstructured, LlamaParse](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/)
- [MinerU (open-source)](https://github.com/opendatalab/MinerU) · [MinerU API docs](https://mineru.net/doc/docs/)
