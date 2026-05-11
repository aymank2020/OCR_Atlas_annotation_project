"""
Interactive Gemini Chat login helper for Linux servers.

Why this exists:
- Google sign-in is often rejected when Chrome is launched under Playwright
  control ("This browser or app may not be secure").
- For server-side Gemini Chat compare, we want a real Chrome profile that the
  user signs into manually over noVNC, then let automation attach later via CDP.

Flow:
1) Start Xvfb + noVNC on the server.
2) Run this script with DISPLAY set to that virtual screen.
3) The script launches a real Chrome process with a persistent profile and a
   remote debugging port.
4) Complete Google login manually in noVNC.
5) Press Enter in terminal. The Chrome process stays open by default so
   Playwright can connect over CDP later.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path


def _pick_chrome_binary(explicit: str) -> str:
    candidates = []
    if str(explicit or "").strip():
        candidates.append(str(explicit).strip())
    env_val = str(os.environ.get("GEMINI_CHAT_CHROME_BINARY", "") or "").strip()
    if env_val:
        candidates.append(env_val)
    candidates.extend(
        [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
        ]
    )
    for item in candidates:
        resolved = shutil.which(item) if not os.path.isabs(item) else item
        if resolved and Path(resolved).exists():
            return str(Path(resolved).resolve())
    raise SystemExit(
        "Could not find Chrome/Chromium binary. Install google-chrome-stable or set "
        "GEMINI_CHAT_CHROME_BINARY / --chrome-binary."
    )


def _is_port_open(port: int) -> bool:
    try:
        import socket

        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.0):
            return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch a real Chrome session for manual Gemini login on a server.")
    parser.add_argument(
        "--profile-dir",
        default="/root/OCR_annotation_Atlas/.state/gemini_chat_login_profile",
        help="Persistent Chrome user data dir",
    )
    parser.add_argument(
        "--url",
        default="https://gemini.google.com/app/b3006ba9f325b55c",
        help="Gemini chat URL",
    )
    parser.add_argument(
        "--chrome-binary",
        default="",
        help="Optional Chrome binary path. Defaults to google-chrome/google-chrome-stable.",
    )
    parser.add_argument(
        "--remote-debugging-port",
        type=int,
        default=9222,
        help="CDP port that later automation will attach to.",
    )
    parser.add_argument(
        "--close-when-done",
        action="store_true",
        help="Close Chrome after you press Enter. Default keeps it running for CDP reuse.",
    )
    args = parser.parse_args()

    display = str(os.environ.get("DISPLAY", "") or "").strip()
    if not display:
        raise SystemExit(
            "DISPLAY is empty. Start Xvfb/noVNC first, then run with DISPLAY set "
            "(example: DISPLAY=:99 python atlas_gemini_chat_login_server.py)."
        )

    profile_dir = Path(args.profile_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    runtime_json = profile_dir / "runtime.json"
    chrome_binary = _pick_chrome_binary(args.chrome_binary)
    cdp_port = max(1024, int(args.remote_debugging_port))

    if _is_port_open(cdp_port):
        print(f"[gemini-login] CDP port {cdp_port} is already active. Reusing current Chrome.")
        proc = None
    else:
        cmd = [
            chrome_binary,
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={cdp_port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            args.url,
        ]
        try:
            if hasattr(os, "geteuid") and int(os.geteuid()) == 0:
                cmd.extend(["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception:
            pass
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        for _ in range(60):
            if _is_port_open(cdp_port):
                break
            time.sleep(0.5)
        else:
            raise SystemExit(f"Chrome launched but CDP port {cdp_port} did not open.")

    runtime = {
        "display": display,
        "profile_dir": str(profile_dir),
        "chrome_binary": chrome_binary,
        "cdp_url": f"http://127.0.0.1:{cdp_port}",
        "pid": int(proc.pid) if proc is not None else None,
        "url": args.url,
    }
    runtime_json.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[gemini-login] DISPLAY={display}")
    print(f"[gemini-login] profile_dir={profile_dir}")
    print(f"[gemini-login] cdp_url=http://127.0.0.1:{cdp_port}")
    print(f"[gemini-login] opening: {args.url}")
    print(
        "\n[gemini-login] Complete Google sign-in + 2FA in the opened browser window.\n"
        "[gemini-login] When Gemini chat is ready, return here and press Enter.\n"
        "[gemini-login] Chrome stays open by default so Atlas can reuse this session over CDP."
    )
    input()

    if args.close_when_done and proc is not None:
        try:
            proc.send_signal(signal.SIGTERM)
        except Exception:
            pass
        print("[gemini-login] chrome terminated")
    else:
        print("[gemini-login] chrome kept alive for later CDP reuse")
    print(f"[gemini-login] runtime metadata: {runtime_json}")


if __name__ == "__main__":
    main()
