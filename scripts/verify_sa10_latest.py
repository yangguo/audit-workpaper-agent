"""Temporary one-shot SA-10 review to verify embedded-media extraction + OCR."""
import asyncio
import json
import os
import urllib3
import uuid
import warnings
from datetime import datetime
from pathlib import Path

import httpx
import openpyxl
from langchain_openai import ChatOpenAI

import sys
sys.path.insert(0, "src")

from review.attachments import build_attachment_index
from review.checkpoints import load_checkpoints_xlsx
from review.pipeline import run_review

WORKBOOK = "assets/uploads/67c00ae1a5e24c55a3510e4bc78c3e63_C22 IT一般控制测试2025v5.xlsx"
CHECKPOINTS = "assets/uploads/037bad2afebd43c0852a727cbeac8b98_检查要点.xlsx"
ATTACHMENTS_DIR = "assets/uploads/attachments/9f4e173e30a94bba8148e64b01b335f2"
OUTPUT_DIR = "assets/results"
SHEETS = "SA-10"

# TEMPORARY: Kaspersky HTTPS interception breaks certifi validation, so this
# verification script uses an httpx client with verify=False. DO NOT use this
# in production or commit this pattern into src/.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _make_review_llm():
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("REVIEW_LLM_MODEL", "doubao-seed-1-6-251015")
    temperature = float(os.getenv("REVIEW_LLM_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("REVIEW_LLM_MAX_TOKENS", "4096"))
    timeout = int(os.getenv("REVIEW_LLM_TIMEOUT", "600"))
    http_client = httpx.Client(verify=False, timeout=timeout)
    http_async_client = httpx.AsyncClient(verify=False, timeout=timeout)
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        http_client=http_client,
        http_async_client=http_async_client,
    )


async def main():
    _load_env()
    review_id = uuid.uuid4().hex
    print(f"[{datetime.now()}] Starting SA-10 review: {review_id}")

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    checkpoints = load_checkpoints_xlsx(CHECKPOINTS)
    print(f"Loaded workbook: {wb.sheetnames}")
    print(f"Loaded checkpoints sheets: {list(checkpoints.keys())}")

    print("Building attachment index...")
    attachments = build_attachment_index(ATTACHMENTS_DIR)
    embedded = [it for it in attachments["items"] if it.rel_path.startswith(".embedded_media/")]
    print(f"Indexed {len(attachments['items'])} items, {len(embedded)} embedded media")
    print(f"Disk files in .embedded_media/: {len(list((Path(ATTACHMENTS_DIR) / '.embedded_media').glob('*'))) if (Path(ATTACHMENTS_DIR) / '.embedded_media').exists() else 0}")

    llm = _make_review_llm()

    def on_progress(p):
        print(f"[{datetime.now()}] {p['stage']} | {p['current_sheet']} | {p['msg']}")

    findings, stats = await run_review(
        wb=wb,
        checkpoints=checkpoints,
        attachments=attachments,
        sheets=SHEETS,
        llm=llm,
        on_progress=on_progress,
    )

    output_path = Path(OUTPUT_DIR) / f"{review_id}_findings.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "review_id": review_id,
            "created_at": datetime.now().isoformat(),
            "source": Path(WORKBOOK).name,
            "stats": stats,
            "findings": findings,
        }, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now()}] Review complete. Findings: {len(findings)}")
    print(f"Saved to: {output_path}")

    # Summarize evidence_refs.attachment and OCR status
    for fnd in findings:
        atts = [r.get("attachment") for r in fnd.get("evidence_refs", [])]
        print(f"  [{fnd.get('risk_type') or fnd.get('issue_type', '')[:20]}] attachments={atts}")

    agent_stats = stats.get("evidence_agent", {})
    print(f"\nEvidence agent: runs={agent_stats.get('runs')}, tool_calls={agent_stats.get('tool_calls')}, "
          f"accepted={agent_stats.get('accepted_evidence')}, unresolved={agent_stats.get('unresolved')}, "
          f"errors={agent_stats.get('errors')}")
    ocr_stats = agent_stats.get("ocr", {})
    print(f"OCR: calls={ocr_stats.get('calls')}, success={ocr_stats.get('success')}, errors={ocr_stats.get('errors')}, timeouts={ocr_stats.get('timeouts')}")


if __name__ == "__main__":
    asyncio.run(main())
