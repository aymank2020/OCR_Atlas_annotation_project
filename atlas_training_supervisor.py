"""
Run Atlas solver and training collectors together.

This lets feedback/disputes training refresh continue while solver is active.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def spawn(cmd: List[str], cwd: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        shell=False,
    )


def terminate(proc: Optional[subprocess.Popen], name: str) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    print(f"[supervisor] stopped {name}")


def is_running(proc: Optional[subprocess.Popen]) -> bool:
    return proc is not None and proc.poll() is None


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False))
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="sample_web_auto_solver.yaml")
    parser.add_argument("--execute", action="store_true", help="Run atlas_web_auto_solver with --execute.")
    parser.add_argument("--no-solver", action="store_true")
    parser.add_argument("--no-feedback", action="store_true")
    parser.add_argument("--with-whatsapp", action="store_true")
    parser.add_argument("--with-discord", action="store_true")
    parser.add_argument("--headless-collectors", action="store_true")
    parser.add_argument("--feedback-interval-sec", type=int, default=3600)
    parser.add_argument("--whatsapp-interval-sec", type=int, default=3600)
    parser.add_argument("--discord-interval-sec", type=int, default=900)
    parser.add_argument(
        "--keep-collectors",
        action="store_true",
        help="Deprecated (collectors are kept by default).",
    )
    parser.add_argument(
        "--stop-collectors-with-solver",
        action="store_true",
        help="Stop feedback/whatsapp/discord collectors when solver exits.",
    )
    parser.add_argument("--collector-restart-delay-sec", type=int, default=8)
    parser.add_argument("--auto-restart-solver", action="store_true")
    parser.add_argument("--solver-restart-delay-sec", type=int, default=10)
    parser.add_argument("--solver-max-restarts", type=int, default=20)
    parser.add_argument("--incident-log", default=None)
    parser.add_argument("--action-log", default=None)
    args = parser.parse_args()

    root = Path.cwd()
    outputs = root / "outputs"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    incident_log = Path(args.incident_log) if args.incident_log else outputs / f"ops_incidents_{ts}.jsonl"
    action_log = Path(args.action_log) if args.action_log else outputs / f"ops_actions_{ts}.jsonl"
    keep_collectors = (not bool(args.stop_collectors_with_solver)) or bool(args.keep_collectors)
    auto_restart_solver = bool(args.auto_restart_solver)

    solver_proc: Optional[subprocess.Popen] = None
    feedback_proc: Optional[subprocess.Popen] = None
    whatsapp_proc: Optional[subprocess.Popen] = None
    discord_proc: Optional[subprocess.Popen] = None
    feedback_cmd: Optional[List[str]] = None
    whatsapp_cmd: Optional[List[str]] = None
    discord_cmd: Optional[List[str]] = None
    feedback_log: Optional[Path] = None
    whatsapp_log: Optional[Path] = None
    discord_log: Optional[Path] = None
    solver_log: Optional[Path] = None
    solver_cmd: Optional[List[str]] = None
    solver_restarts = 0

    try:
        append_jsonl(
            incident_log,
            {
                "ts": datetime.now().isoformat(),
                "event": "supervisor_start",
                "config": args.config,
                "execute": bool(args.execute),
                "with_whatsapp": bool(args.with_whatsapp),
                "with_discord": bool(args.with_discord),
                "keep_collectors": keep_collectors,
                "auto_restart_solver": auto_restart_solver,
            },
        )
        if not args.no_feedback:
            feedback_cmd = [
                "python",
                "-u",
                "atlas_feedback_training_export.py",
                "--config",
                args.config,
                "--continuous",
                "--interval-sec",
                str(max(60, int(args.feedback_interval_sec))),
                "--no-profile",
            ]
            if args.headless_collectors:
                feedback_cmd.append("--headless")
            feedback_log = outputs / f"training_feedback_live_{ts}.log"
            feedback_proc = spawn(feedback_cmd, root, feedback_log)
            print(f"[supervisor] started feedback collector: pid={feedback_proc.pid} log={feedback_log}")
            append_jsonl(
                action_log,
                {
                    "ts": datetime.now().isoformat(),
                    "action": "start_feedback_collector",
                    "pid": feedback_proc.pid,
                    "log": str(feedback_log),
                    "cmd": feedback_cmd,
                },
            )

        if args.with_whatsapp:
            whatsapp_cmd = [
                "python",
                "-u",
                "whatsapp_training_collector.py",
                "--config",
                args.config,
                "--continuous",
                "--interval-sec",
                str(max(120, int(args.whatsapp_interval_sec))),
            ]
            if args.headless_collectors:
                whatsapp_cmd.append("--headless")
            whatsapp_log = outputs / f"training_whatsapp_live_{ts}.log"
            whatsapp_proc = spawn(whatsapp_cmd, root, whatsapp_log)
            print(f"[supervisor] started whatsapp collector: pid={whatsapp_proc.pid} log={whatsapp_log}")
            append_jsonl(
                action_log,
                {
                    "ts": datetime.now().isoformat(),
                    "action": "start_whatsapp_collector",
                    "pid": whatsapp_proc.pid,
                    "log": str(whatsapp_log),
                    "cmd": whatsapp_cmd,
                },
            )

        if args.with_discord:
            discord_cmd = [
                "python",
                "-u",
                "discord_updates_collector.py",
                "--config",
                args.config,
                "--continuous",
                "--interval-sec",
                str(max(60, int(args.discord_interval_sec))),
            ]
            discord_log = outputs / f"training_discord_live_{ts}.log"
            discord_proc = spawn(discord_cmd, root, discord_log)
            print(f"[supervisor] started discord collector: pid={discord_proc.pid} log={discord_log}")
            append_jsonl(
                action_log,
                {
                    "ts": datetime.now().isoformat(),
                    "action": "start_discord_collector",
                    "pid": discord_proc.pid,
                    "log": str(discord_log),
                    "cmd": discord_cmd,
                },
            )

        if not args.no_solver:
            solver_cmd = ["python", "-u", "atlas_web_auto_solver.py", "--config", args.config]
            if args.execute:
                solver_cmd.append("--execute")
            solver_log = outputs / f"solver_live_{ts}.log"
            solver_proc = spawn(solver_cmd, root, solver_log)
            print(f"[supervisor] started solver: pid={solver_proc.pid} log={solver_log}")
            append_jsonl(
                action_log,
                {
                    "ts": datetime.now().isoformat(),
                    "action": "start_solver",
                    "pid": solver_proc.pid,
                    "log": str(solver_log),
                    "cmd": solver_cmd,
                },
            )

        while True:
            time.sleep(5)
            if solver_proc is not None and solver_proc.poll() is not None:
                print(f"[supervisor] solver exited with code={solver_proc.returncode}")
                append_jsonl(
                    incident_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "solver_exit",
                        "code": solver_proc.returncode,
                        "pid": solver_proc.pid,
                    },
                )
                if auto_restart_solver and solver_cmd and solver_log and solver_restarts < max(0, int(args.solver_max_restarts)):
                    wait_s = max(1, int(args.solver_restart_delay_sec))
                    print(f"[supervisor] restarting solver in {wait_s}s...")
                    time.sleep(wait_s)
                    solver_proc = spawn(solver_cmd, root, solver_log)
                    solver_restarts += 1
                    print(f"[supervisor] restarted solver: pid={solver_proc.pid} restart={solver_restarts}")
                    append_jsonl(
                        action_log,
                        {
                            "ts": datetime.now().isoformat(),
                            "action": "restart_solver",
                            "pid": solver_proc.pid,
                            "restart_index": solver_restarts,
                            "log": str(solver_log),
                        },
                    )
                    continue
                if not keep_collectors:
                    break
                solver_proc = None

            if keep_collectors and feedback_proc is not None and feedback_proc.poll() is not None and feedback_cmd and feedback_log:
                print(f"[supervisor] feedback collector exited with code={feedback_proc.returncode}; restarting...")
                append_jsonl(
                    incident_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "feedback_collector_exit",
                        "code": feedback_proc.returncode,
                        "pid": feedback_proc.pid,
                    },
                )
                time.sleep(max(1, int(args.collector_restart_delay_sec)))
                feedback_proc = spawn(feedback_cmd, root, feedback_log)
                print(f"[supervisor] restarted feedback collector: pid={feedback_proc.pid}")
                append_jsonl(
                    action_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "action": "restart_feedback_collector",
                        "pid": feedback_proc.pid,
                        "log": str(feedback_log),
                    },
                )

            if keep_collectors and whatsapp_proc is not None and whatsapp_proc.poll() is not None and whatsapp_cmd and whatsapp_log:
                print(f"[supervisor] whatsapp collector exited with code={whatsapp_proc.returncode}; restarting...")
                append_jsonl(
                    incident_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "whatsapp_collector_exit",
                        "code": whatsapp_proc.returncode,
                        "pid": whatsapp_proc.pid,
                    },
                )
                time.sleep(max(1, int(args.collector_restart_delay_sec)))
                whatsapp_proc = spawn(whatsapp_cmd, root, whatsapp_log)
                print(f"[supervisor] restarted whatsapp collector: pid={whatsapp_proc.pid}")
                append_jsonl(
                    action_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "action": "restart_whatsapp_collector",
                        "pid": whatsapp_proc.pid,
                        "log": str(whatsapp_log),
                    },
                )

            if keep_collectors and discord_proc is not None and discord_proc.poll() is not None and discord_cmd and discord_log:
                print(f"[supervisor] discord collector exited with code={discord_proc.returncode}; restarting...")
                append_jsonl(
                    incident_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "discord_collector_exit",
                        "code": discord_proc.returncode,
                        "pid": discord_proc.pid,
                    },
                )
                time.sleep(max(1, int(args.collector_restart_delay_sec)))
                discord_proc = spawn(discord_cmd, root, discord_log)
                print(f"[supervisor] restarted discord collector: pid={discord_proc.pid}")
                append_jsonl(
                    action_log,
                    {
                        "ts": datetime.now().isoformat(),
                        "action": "restart_discord_collector",
                        "pid": discord_proc.pid,
                        "log": str(discord_log),
                    },
                )

            if solver_proc is None and not keep_collectors:
                break
            if keep_collectors and solver_proc is None:
                if not is_running(feedback_proc) and not is_running(whatsapp_proc) and not is_running(discord_proc):
                    print("[supervisor] no running collectors remain; exiting.")
                    break
                continue
    except KeyboardInterrupt:
        print("[supervisor] interrupted by user")
        append_jsonl(
            incident_log,
            {"ts": datetime.now().isoformat(), "event": "supervisor_interrupted"},
        )
    finally:
        terminate(solver_proc, "solver")
        if not keep_collectors:
            terminate(feedback_proc, "feedback collector")
            terminate(whatsapp_proc, "whatsapp collector")
            terminate(discord_proc, "discord collector")
        append_jsonl(
            incident_log,
            {"ts": datetime.now().isoformat(), "event": "supervisor_stop"},
        )


if __name__ == "__main__":
    main()
