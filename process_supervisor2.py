"""
Atlas Training Supervisor.
Orchestrates the solver and collectors with restart strategies, cooldowns, and incident logging.

Usage:
  python atlas_training_supervisor.py --config supervisor_config.yaml
"""

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# --- Configuration ---

@dataclass
class ProcessConfig:
    name: str
    command: str
    cwd: str = "."
    restart_policy: str = "always"  # always | on_failure | never
    restart_delay_sec: float = 5.0
    max_restarts_per_hour: int = 10
    crash_signatures: List[str] = field(default_factory=list)

@dataclass
class ProcessState:
    process: Optional[subprocess.Popen] = None
    last_start_ts: float = 0.0
    restart_count_hour: int = 0
    hour_window_start_ts: float = 0.0
    consecutive_failures: int = 0
    status: str = "stopped"  # stopped | running | backoff | fatal

# --- Supervisor ---

class Supervisor:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.processes: Dict[str, ProcessState] = {}
        self.running = True
        self.events_file = Path(self.config.get("supervisor", {}).get("events_file", "outputs/supervisor_events.jsonl"))
        self._setup_logging()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_stop_signal)
        signal.signal(signal.SIGTERM, self._handle_stop_signal)

    def _setup_logging(self):
        log_file = self.config.get("supervisor", {}).get("log_file", "outputs/supervisor.log")
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _load_config(self, path: str) -> Dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _log_event(self, event_type: str, process_name: str, details: Dict):
        payload = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event_type,
            "process": process_name,
            **details
        }
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        logging.info(f"[{process_name}] {event_type}: {details}")

    def _handle_stop_signal(self, signum, frame):
        logging.info("Received stop signal. Shutting down...")
        self.running = False

    def _start_process(self, p_cfg: ProcessConfig, state: ProcessState):
        logging.info(f"Starting {p_cfg.name}...")
        try:
            # Prepare log files for stdout/stderr redirection
            log_dir = Path("outputs/logs") / p_cfg.name
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = log_dir / "stdout.log"
            stderr_path = log_dir / "stderr.log"
            
            # Rotate logs if too large? For now just append.
            
            state.process = subprocess.Popen(
                p_cfg.command,
                shell=True,
                cwd=p_cfg.cwd,
                stdout=open(stdout_path, "a"),
                stderr=open(stderr_path, "a"),
                text=True
            )
            state.last_start_ts = time.time()
            state.status = "running"
            
            # Reset hour window if needed
            if time.time() - state.hour_window_start_ts > 3600:
                state.hour_window_start_ts = time.time()
                state.restart_count_hour = 0
            
            state.restart_count_hour += 1
            self._log_event("started", p_cfg.name, {"pid": state.process.pid})
            
        except Exception as e:
            logging.error(f"Failed to start {p_cfg.name}: {e}")
            state.status = "fatal"
            self._log_event("start_failed", p_cfg.name, {"error": str(e)})

    def _check_crash_signature(self, p_cfg: ProcessConfig) -> str:
        """Reads the last few lines of stderr to find crash reasons."""
        log_file = Path("outputs/logs") / p_cfg.name / "stderr.log"
        if not log_file.exists():
            return "unknown"
        
        try:
            # Read last 2KB
            size = log_file.stat().st_size
            if size == 0:
                return "empty_log"
                
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                if size > 2048:
                    f.seek(size - 2048)
                content = f.read()
                
            for sig in p_cfg.crash_signatures:
                if re.search(sig, content, re.IGNORECASE):
                    return f"match:{sig}"
            
            # Generic heuristics
            if "MemoryError" in content: return "OOM"
            if "KeyboardInterrupt" in content: return "manual_stop"
            if "429 Too Many Requests" in content: return "rate_limit"
            if "Quota exceeded" in content: return "quota_limit"
            
        except Exception:
            pass
        return "unknown"

    def run(self):
        # Initialize processes
        configs = []
        raw_procs = self.config.get("processes", {})
        for name, cfg in raw_procs.items():
            configs.append(ProcessConfig(
                name=name,
                command=cfg.get("command", ""),
                cwd=cfg.get("cwd", "."),
                restart_policy=cfg.get("restart_policy", "always"),
                restart_delay_sec=float(cfg.get("restart_delay_sec", 5.0)),
                max_restarts_per_hour=int(cfg.get("max_restarts_per_hour", 10)),
                crash_signatures=cfg.get("crash_signatures", [])
            ))
            self.processes[name] = ProcessState()

        # Main Loop
        logging.info("Supervisor loop started.")
        while self.running:
            active_count = 0
            
            for p_cfg in configs:
                state = self.processes[p_cfg.name]
                
                # Check if process is running
                if state.process:
                    ret = state.process.poll()
                    if ret is None:
                        active_count += 1
                        continue  # Still running
                    
                    # Process finished
                    crash_reason = self._check_crash_signature(p_cfg)
                    self._log_event("exited", p_cfg.name, {
                        "exit_code": ret, 
                        "reason": crash_reason,
                        "uptime": round(time.time() - state.last_start_ts, 1)
                    })
                    state.process = None
                    
                    # Restart Logic
                    if p_cfg.restart_policy == "never":
                        state.status = "stopped"
                        continue
                        
                    if p_cfg.restart_policy == "on_failure" and ret == 0:
                        state.status = "stopped"
                        logging.info(f"{p_cfg.name} exited cleanly. Not restarting (policy=on_failure).")
                        continue
                        
                    # Check restart limits
                    if time.time() - state.hour_window_start_ts > 3600:
                         state.restart_count_hour = 0
                         state.hour_window_start_ts = time.time()
                    
                    if state.restart_count_hour >= p_cfg.max_restarts_per_hour:
                        logging.error(f"{p_cfg.name} hit restart limit ({p_cfg.max_restarts_per_hour}/hr). pausing.")
                        state.status = "backoff"
                        continue
                        
                    # Calculate Backoff
                    state.consecutive_failures += 1
                    delay = p_cfg.restart_delay_sec * (1.5 ** min(state.consecutive_failures, 4))
                    
                    logging.info(f"{p_cfg.name} stopped. Restarting in {delay:.1f}s...")
                    state.status = "waiting"
                    time.sleep(delay)  # Blocking sleep for simplicity in this thread
                    self._start_process(p_cfg, state)
                    state.consecutive_failures = 0 # reset on successful restart attempt
                    
                else:
                    # Not running, should we start it?
                    if state.status == "stopped":
                        if p_cfg.restart_policy == "on_failure" and state.last_start_ts > 0:
                            # Already ran once and stopped, don't restart
                            pass
                        else:
                            self._start_process(p_cfg, state)
            
            time.sleep(1.0)
            
        # Cleanup
        logging.info("Stopping all processes...")
        for name, state in self.processes.items():
            if state.process:
                state.process.terminate()
                try:
                    state.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    state.process.kill()
                    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="supervisor_config.yaml", help="Path to config")
    args = parser.parse_args()
    
    sup = Supervisor(args.config)
    sup.run()
