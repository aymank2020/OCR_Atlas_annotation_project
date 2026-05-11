import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def _pid_alive(pid: int) -> bool:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return True
    return str(pid) in output


def _append_log(log_path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _find_gemini_page(browser, app_url: str):
    for context in browser.contexts:
        for page in context.pages:
            try:
                if app_url in str(page.url or ""):
                    return page
            except Exception:
                continue
    return None


def _inspect_send_state(page) -> dict:
    return page.evaluate(
        """
() => {
  const buttonNodes = Array.from(document.querySelectorAll('button,[role="button"]'));
  const sendButtons = buttonNodes
    .filter((el) => /send/i.test((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')))
    .map((el) => ({
      aria: el.getAttribute('aria-label') || '',
      text: (el.innerText || el.textContent || '').trim(),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
    }));
  const stopButtons = buttonNodes
    .filter((el) => /stop/i.test((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')))
    .map((el) => ({
      aria: el.getAttribute('aria-label') || '',
      text: (el.innerText || el.textContent || '').trim(),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
    }));
  return {
    send_buttons: sendButtons,
    stop_buttons: stopButtons,
  };
}
"""
    )


def _click_send(page) -> bool:
    selectors = [
        'button[aria-label*="Send message" i]',
        'button[aria-label*="Send" i]',
        'button:has-text("Send")',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.count() <= 0:
                continue
            try:
                disabled = bool(button.is_disabled())
            except Exception:
                disabled = False
            if disabled:
                continue
            try:
                button.click(timeout=2000, force=True)
            except Exception:
                try:
                    button.evaluate("(el) => el.click()")
                except Exception:
                    continue
            return True
        except Exception:
            continue
    return False


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: gemini_send_watchdog.py <solver_pid> <app_url> [log_path]", file=sys.stderr)
        return 2
    solver_pid = int(sys.argv[1])
    app_url = str(sys.argv[2])
    log_path = Path(sys.argv[3]) if len(sys.argv) >= 4 else Path("outputs/live_canary_runs/gemini_send_watchdog.log")
    send_enabled_since = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9223")
        _append_log(log_path, {"event": "watchdog_started", "solver_pid": solver_pid, "app_url": app_url})
        while _pid_alive(solver_pid):
            page = _find_gemini_page(browser, app_url)
            if page is None:
                _append_log(log_path, {"event": "page_missing"})
                time.sleep(2.0)
                continue
            try:
                state = _inspect_send_state(page)
            except Exception as exc:
                _append_log(log_path, {"event": "inspect_error", "error": str(exc)})
                time.sleep(2.0)
                continue

            has_stop = any(not bool(item.get("disabled")) for item in (state.get("stop_buttons") or []))
            enabled_send = any(not bool(item.get("disabled")) for item in (state.get("send_buttons") or []))

            if has_stop:
                send_enabled_since = None
                time.sleep(2.0)
                continue

            if enabled_send:
                now = time.monotonic()
                if send_enabled_since is None:
                    send_enabled_since = now
                elif (now - send_enabled_since) >= 8.0:
                    clicked = _click_send(page)
                    _append_log(
                        log_path,
                        {
                            "event": "send_click_attempt",
                            "clicked": bool(clicked),
                            "send_buttons": state.get("send_buttons", []),
                        },
                    )
                    send_enabled_since = None
                    time.sleep(2.0)
                    continue
            else:
                send_enabled_since = None

            time.sleep(2.0)

        _append_log(log_path, {"event": "watchdog_stopped", "solver_pid": solver_pid})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
