#!/usr/bin/env python3
"""
MinerU PDF extraction using online API (v4) - Batch upload flow

Correct API flow:
1. POST /api/v4/file-urls/batch to get presigned URLs
2. PUT files to presigned URLs (OSS)
3. System auto-submits parsing tasks after upload
4. GET /api/v4/extract-results/batch/{batch_id} for results
"""
import os
import sys
import time
import json
import requests
import zipfile
from pathlib import Path
import urllib3

# Suppress SSL warnings for WSL compatibility
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Read API key from environment or use default
MINERU_API_KEY = os.environ.get("MINERU_API_KEY", "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiI0OTYwMzA0NyIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3Mjk0NTMyOCwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiIiwib3BlbklkIjpudWxsLCJ1dWlkIjoiMGQ2NjFjYmItYjQ2Zi00YWU0LTlhMGYtYmVjYzdkYTIwYjg2IiwiZW1haWwiOiIiLCJleHAiOjE3ODA3MjEzMjh9.ZM0LghV2wfgA9YuiTq8TBETzqDK1FXPx4PznRGPXbgF_f4AE1Be6AEwqE32WT1YjNSSua9f3P0iUY2xTbYU21w")

# MinerU API v4 endpoints
MINERU_BATCH_URL = "https://mineru.net/api/v4/file-urls/batch"
MINERU_RESULTS_URL = "https://mineru.net/api/v4/extract-results/batch"


def get_headers() -> dict:
    """Get API headers with Bearer token"""
    return {
        "Authorization": f"Bearer {MINERU_API_KEY}",
        "Content-Type": "application/json"
    }


def get_presigned_urls(pdf_name: str, data_id: str = None, model_version: str = "pipeline") -> tuple:
    """
    Get presigned URL for file upload

    Returns: (batch_id, presigned_url)
    """
    headers = get_headers()
    data = {
        "files": [{"name": pdf_name}],
        "model_version": model_version
    }
    if data_id:
        data["files"][0]["data_id"] = data_id

    response = requests.post(MINERU_BATCH_URL, headers=headers, json=data, timeout=60, verify=False)

    if response.status_code != 200:
        raise Exception(f"Failed to get presigned URL: {response.status_code} - {response.text}")

    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"API error: {result.get('msg')}")

    batch_id = result.get("data", {}).get("batch_id")
    file_urls = result.get("data", {}).get("file_urls", [])
    file_url = file_urls[0] if file_urls else None

    if not file_url:
        raise Exception(f"No file URL in response: {result}")

    return batch_id, file_url


def upload_pdf(file_path: str, presigned_url: str) -> None:
    """Upload PDF to presigned URL (OSS)"""
    print(f"Uploading {Path(file_path).name}...")

    with open(file_path, "rb") as f:
        # Note: Do NOT set Content-Type header - it will break the signature
        upload_resp = requests.put(presigned_url, data=f, timeout=300, verify=False)

    if upload_resp.status_code not in [200, 201]:
        raise Exception(f"File upload failed: {upload_resp.status_code} - {upload_resp.text}")

    print("Upload complete!")


def wait_for_completion(batch_id: str, max_wait: int = 600) -> dict:
    """Wait for parsing to complete and return result"""
    print(f"Waiting for parsing to complete... (max {max_wait}s)")
    headers = get_headers()
    start_time = time.time()

    last_state = None

    while time.time() - start_time < max_wait:
        url = f"{MINERU_RESULTS_URL}/{batch_id}"
        response = requests.get(url, headers=headers, timeout=30, verify=False)

        if response.status_code != 200:
            raise Exception(f"Status check failed: {response.status_code} - {response.text}")

        result = response.json()

        if result.get("code") == 0:
            data = result.get("data", {})
            extract_result = data.get("extract_result", [])

            if extract_result:
                result_item = extract_result[0]
                state = result_item.get('state', 'unknown')
                elapsed = int(time.time() - start_time)

                if state != last_state:
                    print(f"  [{elapsed}s] state={state}", flush=True)
                    last_state = state

                if state == 'done':
                    print("\nParsing completed successfully!")
                    return result_item
                elif state == 'failed':
                    err_msg = result_item.get('err_msg', 'Unknown error')
                    raise Exception(f"Parsing failed: {err_msg}")
                elif state == 'running':
                    progress = result_item.get('extract_progress', {})
                    current = progress.get('extracted_pages', 0)
                    total = progress.get('total_pages', '?')
                    print(f"  [{elapsed}s] Parsing: {current}/{total} pages", flush=True, end='\r')

        time.sleep(5)

    raise Exception("Timeout waiting for parsing to complete")


def download_result(result_item: dict, output_path: str = None) -> str:
    """
    Download and extract the result ZIP file

    Returns path to the extracted layout.json file
    """
    zip_url = result_item.get('full_zip_url')
    if not zip_url:
        raise Exception("No ZIP URL in result")

    print(f"Downloading result ZIP...")

    zip_resp = requests.get(zip_url, timeout=120, verify=False)
    if zip_resp.status_code != 200:
        raise Exception(f"Download failed: {zip_resp.status_code}")

    # Determine output path
    if output_path is None:
        output_path = "mineru_output"

    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save and extract ZIP
    zip_path = output_dir / "result.zip"
    zip_path.write_bytes(zip_resp.content)
    print(f"Downloaded: {len(zip_resp.content)/1024:.1f} KB")

    print("Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(output_dir)

    zip_path.unlink()  # Remove ZIP after extraction

    # Find layout.json
    layout_json = None
    for f in output_dir.rglob("layout.json"):
        layout_json = f
        break

    if layout_json:
        print(f"Result saved to: {output_dir}/")
        print(f"Layout JSON: {layout_json}")
        return str(layout_json)
    else:
        raise Exception("layout.json not found in extracted files")


def extract_pdf(pdf_path: str, output_path: str = None, model_version: str = "pipeline") -> str:
    """
    Extract PDF using MinerU API

    Returns path to the extracted layout.json file
    """
    pdf_path = Path(pdf_path).resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Generate data_id from filename
    data_id = pdf_path.stem.replace('-', '_').replace(' ', '_')

    # Step 1: Get presigned URL
    batch_id, presigned_url = get_presigned_urls(pdf_path.name, data_id, model_version)
    print(f"Batch ID: {batch_id}")

    # Step 2: Upload PDF
    upload_pdf(pdf_path, presigned_url)

    # Step 3: Wait for completion
    result_item = wait_for_completion(batch_id)

    # Step 4: Download and extract result
    return download_result(result_item, output_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mineru_extract_v4.py <pdf_path> [output_path] [model_version]")
        print("  model_version: pipeline (default) or vlm")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    model_version = sys.argv[3] if len(sys.argv) > 3 else "pipeline"

    try:
        json_path = extract_pdf(pdf_path, output_path, model_version)
        print(f"\nExtraction complete: {json_path}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
