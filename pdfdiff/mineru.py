"""MinerU 在线 API v4 客户端

流程:
1. POST /api/v4/file-urls/batch 获取预签名上传地址
2. PUT 上传 PDF 到预签名地址 (OSS)
3. 上传完成后系统自动提交解析任务
4. 轮询 GET /api/v4/extract-results/batch/{batch_id}
5. 下载结果 ZIP 并解压，返回 layout.json 路径

API 限制: 单文件 ≤200MB、≤600 页；每日 2000 页高优先级额度
"""

import time
import zipfile
from pathlib import Path

import requests

from . import config

BATCH_URL = "https://mineru.net/api/v4/file-urls/batch"
RESULTS_URL = "https://mineru.net/api/v4/extract-results/batch"

POLL_INTERVAL_S = 5
DEFAULT_MAX_WAIT_S = 900


class MinerUError(RuntimeError):
    """MinerU API 调用失败"""


class MinerUClient:
    def __init__(self, api_key: str = None, verify: bool = None):
        self.api_key = api_key or config.mineru_api_key()
        self.verify = config.ssl_verify() if verify is None else verify
        if not self.verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_upload_url(self, pdf_name: str, model_version: str) -> tuple:
        """申请预签名上传地址，返回 (batch_id, upload_url)"""
        payload = {
            "files": [{"name": pdf_name, "data_id": Path(pdf_name).stem}],
            "model_version": model_version,
        }
        resp = requests.post(BATCH_URL, headers=self._headers(), json=payload,
                             timeout=60, verify=self.verify)
        if resp.status_code != 200:
            raise MinerUError(f"申请上传地址失败: HTTP {resp.status_code} - {resp.text}")
        result = resp.json()
        if result.get("code") != 0:
            raise MinerUError(f"API 错误: {result.get('msg')} (code={result.get('code')})")
        data = result.get("data", {})
        file_urls = data.get("file_urls") or []
        if not file_urls:
            raise MinerUError(f"响应中缺少上传地址: {result}")
        return data.get("batch_id"), file_urls[0]

    def _upload(self, pdf_path: Path, upload_url: str) -> None:
        """上传 PDF 到预签名地址（不能设置 Content-Type，否则签名失效）"""
        with open(pdf_path, "rb") as f:
            resp = requests.put(upload_url, data=f, timeout=300, verify=self.verify)
        if resp.status_code not in (200, 201):
            raise MinerUError(f"文件上传失败: HTTP {resp.status_code} - {resp.text}")

    def _wait(self, batch_id: str, max_wait_s: int) -> dict:
        """轮询直到解析完成，返回结果条目"""
        deadline = time.time() + max_wait_s
        last_msg = ""
        while time.time() < deadline:
            resp = requests.get(f"{RESULTS_URL}/{batch_id}", headers=self._headers(),
                                timeout=30, verify=self.verify)
            if resp.status_code != 200:
                raise MinerUError(f"查询状态失败: HTTP {resp.status_code} - {resp.text}")
            result = resp.json()
            if result.get("code") == 0:
                items = result.get("data", {}).get("extract_result") or []
                if items:
                    item = items[0]
                    state = item.get("state", "unknown")
                    if state == "done":
                        print("  解析完成")
                        return item
                    if state == "failed":
                        raise MinerUError(f"解析失败: {item.get('err_msg', '未知错误')}")
                    progress = item.get("extract_progress") or {}
                    msg = f"  状态: {state}"
                    if progress.get("total_pages"):
                        msg += f" ({progress.get('extracted_pages', 0)}/{progress['total_pages']} 页)"
                    if msg != last_msg:
                        print(msg, flush=True)
                        last_msg = msg
            time.sleep(POLL_INTERVAL_S)
        raise MinerUError(f"等待解析超时 ({max_wait_s}s)")

    def _download(self, item: dict, output_dir: Path) -> Path:
        """下载结果 ZIP 并解压，返回 layout.json 路径"""
        zip_url = item.get("full_zip_url")
        if not zip_url:
            raise MinerUError(f"结果中缺少下载地址: {item}")
        resp = requests.get(zip_url, timeout=300, verify=self.verify)
        if resp.status_code != 200:
            raise MinerUError(f"结果下载失败: HTTP {resp.status_code}")

        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / "result.zip"
        zip_path.write_bytes(resp.content)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(output_dir)
        zip_path.unlink()

        layout_json = next(output_dir.rglob("layout.json"), None)
        if layout_json is None:
            raise MinerUError(f"解压结果中未找到 layout.json: {output_dir}")
        return layout_json

    def extract(self, pdf_path, output_dir, model_version: str = "vlm",
                max_wait_s: int = DEFAULT_MAX_WAIT_S) -> Path:
        """提取 PDF，返回 layout.json 路径

        model_version: vlm（默认，对应 hybrid 后端，对本项目工卡效果更好）
                       或 pipeline（传统管线，对本工卡corpus提取内容偏少）
        """
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        print(f"提取: {pdf_path.name} (model={model_version})")
        batch_id, upload_url = self._request_upload_url(pdf_path.name, model_version)
        print(f"  batch_id: {batch_id}")
        self._upload(pdf_path, upload_url)
        print("  上传完成，等待解析...")
        item = self._wait(batch_id, max_wait_s)
        layout_json = self._download(item, Path(output_dir))
        print(f"  layout.json: {layout_json}")
        return layout_json
