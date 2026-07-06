"""Side store for structured review findings (JSON file under assets/results)."""
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


def _results_dir() -> str:
    workspace = os.getenv("COZE_WORKSPACE_PATH", os.getcwd())
    d = os.path.join(workspace, "assets", "results")
    os.makedirs(d, exist_ok=True)
    return d


def _path_for(review_id: str) -> str:
    return os.path.join(_results_dir(), f"{review_id}_findings.json")


def save_findings(review_id: str, findings: list, stats: dict, source: str = "") -> str:
    """Persist findings + stats to a JSON file. Returns the file path."""
    payload = {
        "review_id": review_id,
        "created_at": datetime.now().isoformat(),
        "source": source,
        "stats": stats,
        "findings": findings,
    }
    path = _path_for(review_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_findings(review_id: str) -> Optional[Dict[str, Any]]:
    """Load a saved findings payload, or None if not found."""
    path = _path_for(review_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
