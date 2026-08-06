# 旧格式 .xls / .doc 自动转换设计

## 背景

`src/review/attachments.py:_extract_attachment_text` 当前不支持 `.xls` 和 `.doc`，落到 `return "", "unsupported"`，导致这些附件完全不进 LLM 上下文，受限 Agent 也只能记 `unresolved`。

虽然 IT 审计场景下新格式占绝大多数，但部分客户的历史年度底稿和老旧 OA 系统仍会输出 `.xls`/`.doc`，尤其是财务/合规审计。

## 目标

- 自动将 `.xls` → `.xlsx`、`.doc` → `.docx`，转换后走现有提取管道
- 不引入新的 Python 依赖；依赖系统已安装的 LibreOffice `soffice`
- 转换失败时优雅降级到 `unsupported`，不阻塞审阅

## 非目标

- 不安装 LibreOffice（由用户/部署环境负责）
- 不支持 `.ppt`（旧 PowerPoint，出现的概率极低）
- 不改变 `soffice` 的输出格式选择策略（统一转为新格式，不尝试多格式）
- 不优化转换性能（启动开销 ~3-5 秒/文件是可接受的）

## 方案

### 配置

```bash
# .env（可选，不设置或 =0 表示禁用）
LIBREOFFICE_CONVERT_TIMEOUT=30        # 单文件转换超时（秒）
```

默认 30 秒。设为 `0` 或空字符串表示禁用转换。

### 后端

**新增** `src/review/legacy_convert.py`：

```python
"""Convert legacy .xls/.doc to modern .xlsx/.docx via LibreOffice headless."""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

_logger = logging.getLogger("review.legacy_convert")

_LEGACY_FORMATS = {
    ".xls": "xlsx",
    ".doc": "docx",
}


def _resolve_soffice() -> Optional[str]:
    """Locate soffice executable; None if unavailable."""
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_timeout() -> int:
    raw = os.getenv("LIBREOFFICE_CONVERT_TIMEOUT", "30").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def convert_legacy_to_modern(
    src_path: Path,
    dest_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Convert .xls/.doc to .xlsx/.docx. Returns converted path or None.

    None if soffice unavailable, timeout exceeded, conversion failed, or
    format is not legacy.
    """
    src_path = Path(src_path)
    ext = src_path.suffix.lower()
    if ext not in _LEGACY_FORMATS:
        return None
    if _convert_timeout() <= 0:
        return None
    soffice = _resolve_soffice()
    if not soffice:
        _logger.warning("soffice not on PATH; legacy %s conversion skipped", ext)
        return None

    dest_dir = dest_dir or Path(tempfile.mkdtemp(prefix="audit_legacy_convert_"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_ext = _LEGACY_FORMATS[ext]

    try:
        proc = subprocess.run(
            [
                soffice, "--headless", "--convert-to", target_ext,
                "--outdir", str(dest_dir), str(src_path),
            ],
            capture_output=True, text=True,
            timeout=_convert_timeout(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        _logger.warning("soffice convert %s timed out", src_path)
        return None
    except OSError as exc:
        _logger.warning("soffice invocation failed: %s", exc)
        return None

    if proc.returncode != 0:
        _logger.warning("soffice convert failed (rc=%s): %s",
                        proc.returncode, proc.stderr.strip())
        return None

    converted = dest_dir / (src_path.stem + "." + target_ext)
    if not converted.is_file():
        _logger.warning("soffice did not produce expected output: %s", converted)
        return None
    return converted
```

**修改** `src/review/attachments.py:_extract_attachment_text`：

在 `.docx` 分支之前增加：

```python
if suffix in {".xls", ".doc"}":
    from review.legacy_convert import convert_legacy_to_modern
    converted = convert_legacy_to_modern(path)
    if converted is None:
        return "", "unsupported"
    # Recurse into the modernized file
    if converted.suffix.lower() == ".xlsx":
        return _read_xlsx_file(converted)
    if converted.suffix.lower() == ".docx":
        return _read_docx_file(converted)
    return "", "unsupported"
```

### 临时目录清理

`convert_legacy_to_modern` 在 `dest_dir` 为 None 时创建临时目录。不主动清理——`tempfile.mkdtemp` 默认在系统临时目录，系统重启或 `tempfile` 周期清理即可。审阅期间不清理也无影响（每个文件 ~10-100 KB）。

如果对磁盘敏感，后续可加 `shutil.rmtree` 在调用方控制。当前不清理以保持代码聚焦。

### 错误处理

| 情况 | 行为 |
|---|---|
| soffice 不在 PATH | 警告 + 返回 `("","unsupported")` |
| 转换超时（默认 30 秒） | 警告 + 返回 `("","unsupported")` |
| soffice 退出码非 0 | 警告 + 返回 `("","unsupported")` |
| 输出文件不存在 | 警告 + 返回 `("","unsupported")` |
| 文件后缀非 `.xls`/`.doc` | 不调用，直接返回 `None` |
| 配置 `LIBREOFFICE_CONVERT_TIMEOUT=0` | 不调用 |

任一失败都不会阻塞真实附件扫描或后续嵌入图提取。

### 测试

`tests/review/test_legacy_convert.py`：

- `convert_legacy_to_modern` 对非 legacy 后缀返回 None
- `convert_legacy_to_modern` 在 `LIBREOFFICE_CONVERT_TIMEOUT=0` 时返回 None
- `convert_legacy_to_modern` 在 soffice 不可用时返回 None（用 `monkeypatch.setattr(shutil, "which", lambda _: None)`）
- `convert_legacy_to_modern` 在超时/失败时返回 None（mock subprocess.run）
- `_extract_attachment_text` 集成测试：传入 `.xls`/`.doc` 时通过 monkeypatch 的 fake converter 走通整条路径

并增加一个集成冒烟测试（用真实 `.xls`，如果仓库里有；否则创建最小有效的 `.xls` fixture）。

## 接口变更

- 新增 `src/review/legacy_convert.py` 模块
- 修改 `src/review/attachments.py:_extract_attachment_text`
- 无对外 API 变更
- 可选新增环境变量 `LIBREOFFICE_CONVERT_TIMEOUT`