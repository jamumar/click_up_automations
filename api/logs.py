from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
import os
from typing import List, Dict
from pathlib import Path
import time

router = APIRouter()

LOG_DIR = Path("webhook_logs")
LOG_DIR.mkdir(exist_ok=True)

def _safe_path(name: str) -> Path:
    # Only allow files directly under LOG_DIR
    p = (LOG_DIR / name).resolve()
    if p.parent != LOG_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid log file path")
    return p

@router.get("/logs")
def list_logs() -> List[Dict]:
    files = []
    for entry in LOG_DIR.iterdir():
        if entry.is_file() and (entry.suffix in (".log", ".json")):
            stat = entry.stat()
            files.append({
                "name": entry.name,
                "size": stat.st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "type": entry.suffix.lstrip(".")
            })
    # Sort by modified desc
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files

@router.get("/logs/{name}")
def get_log(
    name: str,
    tail: int = Query(200, ge=1, le=5000),  # default last 200 lines
) -> PlainTextResponse:
    p = _safe_path(name)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")
    # Read last N lines efficiently
    lines = _tail_lines(p, tail)
    return PlainTextResponse("".join(lines))

def _tail_lines(path: Path, n: int) -> List[str]:
    # Efficiently read last n lines without loading entire file
    avg_line_length = 150
    to_read = n * avg_line_length
    size = path.stat().st_size
    with path.open("rb") as f:
        if to_read < size:
            f.seek(size - to_read)
        data = f.read().decode(errors="replace")
    lines = data.splitlines(keepends=True)
    return lines[-n:]