"""pdf.js 本地提取客户端（MinerUClient 的可替换实现）

调用 Node 脚本 tools/pdfjs_extract.mjs，产出与 MinerU 同构的 layout.json，
因此下游 extract/compare/report 无需感知提取引擎的差异。

与 MinerU 的取舍:
- 优点: 完全本地、无 API 额度与网络依赖、秒级完成
- 局限: 只提取文本图层（扫描件无文字则为空），无表格结构/OCR/公式识别

依赖: Node.js >= 22 与项目根目录的 `npm install`（pdfjs-dist）
"""

import subprocess
from pathlib import Path

from .config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "tools" / "pdfjs_extract.mjs"
NODE_MODULE = PROJECT_ROOT / "node_modules" / "pdfjs-dist"


class PdfJsError(RuntimeError):
    """pdf.js 提取失败"""


class PdfJsClient:
    """与 MinerUClient 接口一致：extract(pdf, out_dir, model) -> layout.json 路径"""

    def __init__(self, node: str = "node"):
        self.node = node

    def _check_env(self) -> None:
        if not NODE_MODULE.exists():
            raise PdfJsError(
                f"未安装 pdfjs-dist。请在项目根目录执行：\n  npm install\n（目录: {PROJECT_ROOT}）"
            )
        try:
            subprocess.run([self.node, "--version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PdfJsError(
                f"未找到可用的 Node.js（命令: {self.node}）。pdf.js 引擎需要 Node.js >= 22。"
            ) from exc

    def extract(self, pdf_path, output_dir, model_version: str = None) -> Path:
        """提取 PDF，返回 layout.json 路径；model_version 仅为接口兼容，未使用"""
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
        self._check_env()

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        layout_json = output_dir / "layout.json"

        print(f"提取: {pdf_path.name} (engine=pdfjs)")
        result = subprocess.run(
            [self.node, str(SCRIPT), str(pdf_path), str(layout_json)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise PdfJsError((result.stderr or result.stdout).strip())
        if result.stderr.strip():
            print(result.stderr.rstrip())
        print(f"  layout.json: {layout_json}")
        return layout_json
