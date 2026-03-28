#!/usr/bin/env python3
"""Upload a document, monitor pipeline status, and sample CPU/GPU signals.

Usage:
  ./.venv/bin/python tools/e2e_upload_extract_monitor.py \
      --pdf "Documents/COMMON Module 3 Characteristics of LNG.pdf" \
      --base-url "http://localhost:8001" \
      --poll-seconds 5 \
      --timeout-seconds 3600
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


INGESTION_TERMINAL_STATUSES = {
    "validation-complete",
    "in-review",
    "review-complete",
    "approved-for-optimization",
    "optimizing",
    "optimization-complete",
    "qa-review",
    "qa-passed",
    "final-approved",
    "approved",
    "rejected",
    "failed",
}


@dataclass
class Sample:
    timestamp: str
    status: str
    stage: str
    progress: int
    gpu_apps: str
    top_cpu: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0 and err:
            return f"ERR({proc.returncode}): {err}"
        return out or (f"ERR({proc.returncode})" if proc.returncode != 0 else "")
    except Exception as exc:  # pragma: no cover
        return f"EXC: {exc}"


def sample_gpu_apps() -> str:
    query = run_cmd(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    if not query:
        return "no-gpu-processes"
    return query.replace("\n", " | ")[:400]


def sample_top_cpu(container: str) -> str:
    ps_out = run_cmd(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-lc",
            "ps -eo pid,pcpu,pmem,comm,args --sort=-pcpu | sed -n '1,6p'",
        ]
    )
    if not ps_out or ps_out.startswith("ERR(") or ps_out.startswith("EXC:"):
        stats_out = run_cmd(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}",
                container,
            ]
        )
        if stats_out:
            return f"container_stats={stats_out}"
        return "no-ps-output"
    lines = [ln.strip() for ln in ps_out.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return lines[1][:500]
    return lines[0][:500]


def upload_document(base_url: str, pdf_path: Path, title: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/documents/upload"
    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        data = {
            "title": title,
            "version": "gpu-check",
            "system": "Validation",
            "document_type": "PDF",
            "notes": "E2E GPU extraction verification run",
        }
        resp = requests.post(url, files=files, data=data, timeout=180)

    if resp.status_code >= 400:
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")

    payload = resp.json()
    if "document_id" not in payload:
        raise RuntimeError(f"Upload response missing document_id: {payload}")
    return payload


def get_status(base_url: str, document_id: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/documents/{document_id}/status"
    resp = requests.get(url, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"Status failed ({resp.status_code}): {resp.text}")
    return resp.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload and monitor extraction pipeline.")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--base-url", default=os.getenv("BACKEND_URL", "http://localhost:8001"))
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--container", default="plantiq-backend", help="Backend container name")
    parser.add_argument("--out", default="logs/e2e_upload_extract_monitor.json", help="Output JSON log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return 2

    title = f"GPU Monitor {pdf_path.stem} {int(time.time())}"
    print(f"[{now_iso()}] Uploading: {pdf_path.name}")
    upload = upload_document(args.base_url, pdf_path, title)
    document_id = str(upload["document_id"])
    print(f"[{now_iso()}] document_id={document_id}")
    print(f"[{now_iso()}] initial={upload.get('status')} message={upload.get('message')}")

    started = time.time()
    deadline = started + args.timeout_seconds
    last_status = None
    last_stage = None
    samples: list[Sample] = []

    while True:
        if time.time() > deadline:
            print(f"[{now_iso()}] TIMEOUT waiting for terminal status")
            break

        status_payload = get_status(args.base_url, document_id)
        status = str(status_payload.get("status") or "")
        stage = str(status_payload.get("current_stage") or "")
        progress = int(status_payload.get("progress") or 0)

        gpu_apps = sample_gpu_apps()
        top_cpu = sample_top_cpu(args.container)

        sample = Sample(
            timestamp=now_iso(),
            status=status,
            stage=stage,
            progress=progress,
            gpu_apps=gpu_apps,
            top_cpu=top_cpu,
        )
        samples.append(sample)

        changed = (status != last_status) or (stage != last_stage)
        if changed:
            print(
                f"[{sample.timestamp}] status={status:>24} stage={stage or '-':>20} progress={progress:3d}%"
            )
            print(f"  gpu_apps: {gpu_apps}")
            print(f"  top_cpu : {top_cpu}")

        if status in INGESTION_TERMINAL_STATUSES:
            print(f"[{now_iso()}] Reached terminal ingestion status: {status}")
            if status == "failed":
                print(f"[{now_iso()}] Failure details: {status_payload.get('error') or status_payload.get('message')}")
            break

        last_status = status
        last_stage = stage
        time.sleep(max(1, args.poll_seconds))

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_payload = {
        "base_url": args.base_url,
        "pdf": str(pdf_path),
        "document_id": document_id,
        "uploaded": upload,
        "samples": [sample.__dict__ for sample in samples],
        "last_sample": samples[-1].__dict__ if samples else None,
        "duration_seconds": int(time.time() - started),
    }
    out_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
    print(f"[{now_iso()}] Wrote monitor log: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
