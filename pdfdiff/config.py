"""配置加载：从项目根目录的 .env 读取 MinerU API 密钥等设置"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """加载项目根目录的 .env（不覆盖已存在的环境变量）"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def mineru_api_key() -> str:
    """获取 MinerU API 密钥，未配置时报错"""
    key = os.environ.get("MINERU_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "未配置 MINERU_API_KEY。请在项目根目录的 .env 文件中设置：\n"
            "  MINERU_API_KEY=your_api_key\n"
            "获取密钥: https://mineru.net/apiManage/apiKey"
        )
    return key


def ssl_verify() -> bool:
    """TLS 证书校验开关（默认开启；MINERU_SSL_VERIFY=0 可关闭，用于 WSL 等证书问题环境）"""
    return os.environ.get("MINERU_SSL_VERIFY", "1").lower() not in ("0", "false", "no")
