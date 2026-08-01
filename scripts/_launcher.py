"""Detached experiment launcher — survives agent-turn boundaries on Windows."""
import subprocess, sys, os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent

def launch(argv: list[str], log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(str(log_path), "w", encoding="utf-8", buffering=1)
    popen_kw = dict(
        args=[sys.executable, "-u"] + argv,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=str(CODE_ROOT),
    )
    if sys.platform == "win32":
        popen_kw["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen(**popen_kw)
    print(f"Launched PID {proc.pid}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    launch(ns.script_args, ns.log)
