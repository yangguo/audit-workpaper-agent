"""Convert legacy .xls/.doc to modern .xlsx/.docx via LibreOffice headless."""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

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

    None if soffice unavailable, timeout exceeded, conversion failed,
    or format is not legacy.
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