"""
Collect multilingual WhatsApp group messages/media previews for Atlas training.

This script uses WhatsApp Web automation (Playwright) and stores reusable
datasets under outputs/training_feedback/whatsapp.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


DEFAULTS: Dict[str, Any] = {
    "browser": {
        "headless": False,
        "slow_mo_ms": 40,
        "chrome_channel": "chrome",
    },
    "gemini": {
        "model": "gemini-2.5-flash",
        "connect_timeout_sec": 30,
        "request_timeout_sec": 300,
    },
    "whatsapp_training": {
        "enabled": True,
        "headless": False,
        "continuous": False,
        "interval_sec": 3600,
        "max_cycles": 0,
        "ready_timeout_sec": 180,
        "messages_per_group": 120,
        "media_screenshot_limit_per_group": 20,
        "media_extract_max_messages_per_group": 24,
        "media_extract_max_items_per_message": 2,
        "media_extract_max_item_mb": 6.0,
        "attach_media_to_gemini": True,
        "gemini_max_image_attachments": 18,
        "gemini_max_audio_attachments": 12,
        "gemini_max_total_attachment_mb": 18.0,
        "gemini_min_attachment_bytes": 300,
        "root_dir": "outputs/training_feedback/whatsapp",
        "runs_subdir": "runs",
        "use_chrome_profile": False,
        "require_profile_launch_success": False,
        "profile_launch_timeout_ms": 35000,
        "chrome_user_data_dir": "",
        "chrome_profile_directory": "Default",
        "web_url": "https://web.whatsapp.com",
        "groups": [
            "Atlas Capture annotation Room",
            "Atlas Capture",
            "Atlas Capture.io",
        ],
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def cfg_get(cfg: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_config(path: Path) -> Dict[str, Any]:
    raw = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    return deep_merge(DEFAULTS, raw)


def resolve_gemini_key(cfg: Dict[str, Any]) -> str:
    explicit = str(cfg_get(cfg, "gemini.api_key", "")).strip()
    if explicit:
        return explicit
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    return ""


def slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    out = out.strip("_")
    return out or "group"


def unique_run_dir(runs_root: Path, prefix: str = "whatsapp_training") -> Path:
    base = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out = runs_root / base
    if not out.exists():
        out.mkdir(parents=True, exist_ok=False)
        return out
    idx = 1
    while True:
        candidate = runs_root / f"{base}_{idx}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        idx += 1


def launch_context(
    pw,
    cfg: Dict[str, Any],
    headless: bool,
    force_no_profile: bool,
) -> Tuple[BrowserContext, Optional[Browser]]:
    channel = str(cfg_get(cfg, "browser.chrome_channel", "chrome"))
    slow_mo = int(cfg_get(cfg, "browser.slow_mo_ms", 40))
    use_profile = bool(cfg_get(cfg, "whatsapp_training.use_chrome_profile", False))
    require_profile_ok = bool(cfg_get(cfg, "whatsapp_training.require_profile_launch_success", False))
    launch_timeout_ms = int(cfg_get(cfg, "whatsapp_training.profile_launch_timeout_ms", 35000))
    if force_no_profile:
        use_profile = False

    if use_profile:
        user_data_dir = str(cfg_get(cfg, "whatsapp_training.chrome_user_data_dir", "")).strip()
        profile_dir = str(cfg_get(cfg, "whatsapp_training.chrome_profile_directory", "Default")).strip()
        launch_args = [f"--profile-directory={profile_dir}"] if profile_dir else []
        if user_data_dir:
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel=channel,
                    headless=headless,
                    slow_mo=slow_mo,
                    args=launch_args,
                    timeout=launch_timeout_ms,
                )
                print(
                    f"[whatsapp] using Chrome profile user_data_dir={user_data_dir} profile={profile_dir or 'default'}"
                )
                return ctx, None
            except Exception as exc:
                msg = f"[whatsapp] profile launch failed ({exc}); falling back to isolated context."
                if require_profile_ok:
                    raise RuntimeError(msg) from exc
                print(msg)
        elif require_profile_ok:
            raise RuntimeError("[whatsapp] require_profile_launch_success=true but chrome_user_data_dir is empty.")

    browser = pw.chromium.launch(channel=channel, headless=headless, slow_mo=slow_mo)
    ctx = browser.new_context()
    print("[whatsapp] using isolated browser context (no persistent profile).")
    return ctx, browser


def _any_visible(page: Page, selectors: List[str], timeout_ms: int = 500) -> bool:
    for sel in selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=timeout_ms):
                return True
        except Exception:
            continue
    return False


def detect_whatsapp_state(page: Page) -> str:
    ready_selectors = [
        "#pane-side",
        "div[data-testid='chat-list']",
        "div[data-testid='chat-list-search']",
        'div[role="textbox"][title*="Search" i]',
        'div[contenteditable="true"][data-tab="3"]',
        'div[contenteditable="true"][data-tab="10"]',
        "header div[contenteditable='true']",
    ]
    qr_selectors = [
        "canvas[aria-label*='Scan' i]",
        "canvas[aria-label*='QR' i]",
        "div[data-testid='qrcode']",
        "div[data-ref] canvas",
    ]
    if _any_visible(page, ready_selectors):
        return "ready"
    if _any_visible(page, qr_selectors):
        return "qr_required"
    return "loading"


def wait_for_whatsapp_ready(page: Page, timeout_sec: int = 120) -> str:
    deadline = time.time() + timeout_sec
    last_state = "loading"
    while time.time() < deadline:
        state = detect_whatsapp_state(page)
        last_state = state
        if state == "ready":
            return "ready"
        page.wait_for_timeout(700)
    return last_state


def open_group(page: Page, group_name: str) -> bool:
    search_selectors = [
        "div[data-testid='chat-list-search'] div[contenteditable='true']",
        "div[data-testid='chat-list-search'] [role='textbox']",
        'div[contenteditable="true"][data-tab="10"]',
        'div[role="textbox"][title*="Search" i]',
        'div[contenteditable="true"][data-tab="3"]',
        'div[contenteditable="true"][aria-label*="Search" i]',
        "header div[contenteditable='true']",
    ]
    search_box = None
    for sel in search_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=900):
                search_box = loc
                break
        except Exception:
            continue
    if search_box is None:
        return False

    try:
        search_box.click(timeout=1000, force=True)
        try:
            search_box.press("Control+A")
            search_box.press("Backspace")
        except Exception:
            pass
        search_box.type(group_name, delay=20)
        page.wait_for_timeout(700)
    except Exception:
        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(group_name, delay=20)
            page.wait_for_timeout(700)
        except Exception:
            return False

    escaped = group_name.replace('"', '\\"')
    group_selectors = [
        f'div[data-testid="cell-frame-container"] span[title="{escaped}"]',
        f'span[title="{escaped}"]',
        f'div[title="{escaped}"]',
        f'//span[@title="{group_name}"]',
        f'text=/{re.escape(group_name)}/i',
    ]
    for sel in group_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=900):
                loc.click(timeout=1200, force=True)
                page.wait_for_timeout(900)
                return True
        except Exception:
            continue

    try:
        search_box.press("Enter")
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False


def extract_messages(page: Page, keep_last: int) -> List[Dict[str, Any]]:
    js = r"""
() => {
  let rowSelector = 'div.copyable-text[data-pre-plain-text]';
  let rows = Array.from(document.querySelectorAll(rowSelector));
  if (!rows.length) {
    rowSelector = 'div[data-testid="msg-container"]';
    rows = Array.from(document.querySelectorAll(rowSelector));
  }
  if (!rows.length) {
    rowSelector = 'div.message-in, div.message-out';
    rows = Array.from(document.querySelectorAll(rowSelector));
  }
  const out = rows.map((row, idx) => {
    const root = row.closest('div.copyable-text[data-pre-plain-text]') || row;
    const plain = root.getAttribute?.('data-pre-plain-text') || row.querySelector('[data-pre-plain-text]')?.getAttribute('data-pre-plain-text') || '';
    const txtParts = Array.from(row.querySelectorAll('span.selectable-text span, span.selectable-text'))
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
    const text = txtParts.join(' ').replace(/\s+/g, ' ').trim();
    const hasImage = !!row.querySelector('img');
    const hasVideo = !!row.querySelector('video');
    const hasAudio = !!row.querySelector('[data-testid="audio-play"], [data-icon="audio-play"]');
    const hasDocument = !!row.querySelector('[data-testid="document-thumb"], [data-icon="document"]');
    return {
      dom_index: idx,
      plain_meta: plain,
      text: text,
      row_selector: rowSelector,
      has_media: !!(hasImage || hasVideo || hasAudio || hasDocument),
      has_image: hasImage,
      has_video: hasVideo,
      has_audio: hasAudio,
      has_document: hasDocument
    };
  });
  return out;
}
"""
    try:
        rows = page.evaluate(js) or []
    except Exception:
        rows = []
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "dom_index": int(row.get("dom_index", -1)),
                "plain_meta": str(row.get("plain_meta", "")).strip(),
                "text": str(row.get("text", "")).strip(),
                "row_selector": str(row.get("row_selector", "")).strip(),
                "has_media": bool(row.get("has_media", False)),
                "has_image": bool(row.get("has_image", False)),
                "has_video": bool(row.get("has_video", False)),
                "has_audio": bool(row.get("has_audio", False)),
                "has_document": bool(row.get("has_document", False)),
            }
        )
    if keep_last > 0 and len(cleaned) > keep_last:
        cleaned = cleaned[-keep_last:]
    return cleaned


def capture_media_previews(
    page: Page,
    messages: List[Dict[str, Any]],
    out_dir: Path,
    max_shots: int,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: List[Dict[str, Any]] = []
    if max_shots <= 0:
        return shots
    row_selector = "div.copyable-text[data-pre-plain-text]"
    if messages:
        inferred = str(messages[0].get("row_selector", "")).strip()
        if inferred:
            row_selector = inferred
    msg_loc = page.locator(row_selector)
    used = 0
    for msg in messages:
        if not msg.get("has_media", False):
            continue
        dom_index = int(msg.get("dom_index", -1))
        if dom_index < 0:
            continue
        if used >= max_shots:
            break
        img_name = f"media_preview_{dom_index}_{used+1}.png"
        img_path = out_dir / img_name
        try:
            node = msg_loc.nth(dom_index)
            node.scroll_into_view_if_needed(timeout=1200)
            node.screenshot(path=str(img_path))
            shots.append({"dom_index": dom_index, "path": str(img_path)})
            used += 1
        except Exception:
            continue
    return shots


def _ext_from_mime(mime: str, fallback: str = ".bin") -> str:
    mime = (mime or "").strip().lower()
    if not mime:
        return fallback
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    if "gif" in mime:
        return ".gif"
    if "ogg" in mime:
        return ".ogg"
    if "webm" in mime:
        return ".webm"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "wav" in mime:
        return ".wav"
    guess = mimetypes.guess_extension(mime)
    return guess or fallback


def export_message_media_files(
    page: Page,
    row_selector: str,
    dom_index: int,
    out_dir: Path,
    basename: str,
    max_items: int,
    max_item_bytes: int,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = r"""
async ({ rowSelector, rowIndex, maxItems, maxItemBytes }) => {
  const rows = Array.from(document.querySelectorAll(rowSelector || 'div.copyable-text[data-pre-plain-text]'));
  const row = rows[rowIndex];
  if (!row) return [];
  const results = [];

  async function srcToPayload(src, kindHint) {
    if (!src || results.length >= maxItems) return null;
    try {
      let dataUrl = '';
      if (src.startsWith('data:')) {
        dataUrl = src;
      } else {
        const resp = await fetch(src);
        if (!resp.ok) return null;
        const blob = await resp.blob();
        if (!blob || !blob.size) return null;
        if (blob.size > maxItemBytes) {
          return { skipped: true, reason: 'too_large', size: blob.size, mime: blob.type || '' };
        }
        dataUrl = await new Promise((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => resolve(String(fr.result || ''));
          fr.onerror = reject;
          fr.readAsDataURL(blob);
        });
      }
      const m = dataUrl.match(/^data:([^;,]+);base64,(.+)$/i);
      if (!m) return null;
      const mime = m[1] || '';
      const b64 = m[2] || '';
      return {
        kind: kindHint || 'media',
        mime,
        data_base64: b64,
      };
    } catch (e) {
      return null;
    }
  }

  const imageNodes = Array.from(row.querySelectorAll('img'));
  for (const img of imageNodes) {
    if (results.length >= maxItems) break;
    const src = img.currentSrc || img.src || '';
    const payload = await srcToPayload(src, 'image');
    if (payload && !payload.skipped) results.push(payload);
  }

  const audioNodes = Array.from(row.querySelectorAll('audio'));
  for (const audio of audioNodes) {
    if (results.length >= maxItems) break;
    const src = audio.currentSrc || audio.src || '';
    const payload = await srcToPayload(src, 'audio');
    if (payload && !payload.skipped) results.push(payload);
  }

  const videoNodes = Array.from(row.querySelectorAll('video'));
  for (const video of videoNodes) {
    if (results.length >= maxItems) break;
    const src = video.currentSrc || video.src || '';
    const payload = await srcToPayload(src, 'video');
    if (payload && !payload.skipped) results.push(payload);
  }

  return results;
}
"""
    try:
        payloads = page.evaluate(
            js,
            {
                "rowSelector": row_selector,
                "rowIndex": dom_index,
                "maxItems": max(1, int(max_items)),
                "maxItemBytes": max(64_000, int(max_item_bytes)),
            },
        )
    except Exception:
        payloads = []

    out: List[Dict[str, Any]] = []
    if not isinstance(payloads, list):
        return out
    for idx, item in enumerate(payloads, start=1):
        if not isinstance(item, dict):
            continue
        b64 = str(item.get("data_base64", "")).strip()
        mime = str(item.get("mime", "")).strip() or "application/octet-stream"
        kind = str(item.get("kind", "")).strip() or "media"
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            continue
        if not raw:
            continue
        if len(raw) > max_item_bytes:
            continue
        ext = _ext_from_mime(mime, ".bin")
        file_path = out_dir / f"{basename}_{idx}{ext}"
        try:
            file_path.write_bytes(raw)
        except Exception:
            continue
        out.append(
            {
                "kind": kind,
                "mime": mime,
                "bytes": len(raw),
                "path": str(file_path),
                "dom_index": dom_index,
            }
        )
    return out


def collect_media_files_for_group(
    page: Page,
    group_dir: Path,
    messages: List[Dict[str, Any]],
    max_messages: int,
    max_items_per_message: int,
    max_item_bytes: int,
) -> List[Dict[str, Any]]:
    def _prime_audio_blob(row_sel: str, idx: int) -> None:
        try:
            row = page.locator(row_sel).nth(idx)
            row.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            return
        play_selectors = [
            "button[data-testid='audio-play']",
            "button[aria-label*='Play' i]",
            "button[title*='Play' i]",
            "button[data-icon='audio-play']",
        ]
        pause_selectors = [
            "button[data-testid='audio-pause']",
            "button[aria-label*='Pause' i]",
            "button[title*='Pause' i]",
            "button[data-icon='audio-pause']",
        ]
        for sel in play_selectors:
            try:
                btn = row.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=800, force=True)
                    page.wait_for_timeout(900)
                    break
            except Exception:
                continue
        for sel in pause_selectors:
            try:
                btn = row.locator(sel).first
                if btn.is_visible(timeout=300):
                    btn.click(timeout=600, force=True)
                    break
            except Exception:
                continue

    out: List[Dict[str, Any]] = []
    if not messages:
        return out
    # Prefer latest messages that contain media.
    media_msgs = [m for m in messages if bool(m.get("has_media", False))]
    if max_messages > 0:
        media_msgs = media_msgs[-max_messages:]
    row_selector = "div.copyable-text[data-pre-plain-text]"
    if media_msgs:
        inferred = str(media_msgs[0].get("row_selector", "")).strip()
        if inferred:
            row_selector = inferred
    media_dir = group_dir / "media_files"
    media_dir.mkdir(parents=True, exist_ok=True)
    for i, msg in enumerate(media_msgs, start=1):
        dom_index = int(msg.get("dom_index", -1))
        if dom_index < 0:
            continue
        basename = f"msg_{dom_index}_{i}"
        files = export_message_media_files(
            page=page,
            row_selector=row_selector,
            dom_index=dom_index,
            out_dir=media_dir,
            basename=basename,
            max_items=max_items_per_message,
            max_item_bytes=max_item_bytes,
        )
        has_audio_hint = bool(msg.get("has_audio", False))
        has_audio_file = any(str(f.get("mime", "")).startswith("audio/") for f in files if isinstance(f, dict))
        if has_audio_hint and not has_audio_file:
            _prime_audio_blob(row_selector, dom_index)
            retry_files = export_message_media_files(
                page=page,
                row_selector=row_selector,
                dom_index=dom_index,
                out_dir=media_dir,
                basename=f"{basename}_audio",
                max_items=max_items_per_message,
                max_item_bytes=max_item_bytes,
            )
            for rf in retry_files:
                if isinstance(rf, dict):
                    files.append(rf)
        out.extend(files)
    return out


def build_gemini_attachments_from_groups(
    groups_payload: List[Dict[str, Any]],
    max_images: int,
    max_audio: int,
    max_total_bytes: int,
    min_attachment_bytes: int,
) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    images_used = 0
    audio_used = 0
    total_bytes = 0

    def _try_add(path: str, mime: str, kind: str) -> bool:
        nonlocal images_used, audio_used, total_bytes
        p = Path(path)
        if not p.exists() or not p.is_file():
            return False
        try:
            sz = p.stat().st_size
        except Exception:
            return False
        if sz <= 0:
            return False
        if sz < max(64, min_attachment_bytes):
            return False
        if total_bytes + sz > max_total_bytes:
            return False
        if kind == "image":
            if images_used >= max_images:
                return False
            images_used += 1
        elif kind == "audio":
            if audio_used >= max_audio:
                return False
            audio_used += 1
        attachments.append({"path": str(p), "mime": mime, "kind": kind, "bytes": sz})
        total_bytes += sz
        return True

    for group in groups_payload:
        for media in group.get("media_files", []):
            if not isinstance(media, dict):
                continue
            kind = str(media.get("kind", "")).strip().lower()
            mime = str(media.get("mime", "")).strip().lower()
            path = str(media.get("path", "")).strip()
            if not path:
                continue
            if kind in ("audio", "voice") or mime.startswith("audio/"):
                _try_add(path, mime or "audio/webm", "audio")
            elif kind in ("image",) or mime.startswith("image/"):
                _try_add(path, mime or "image/png", "image")
            elif kind in ("video",) or mime.startswith("video/"):
                # For videos, use preview PNG if available in media_previews.
                continue

        # Add preview screenshots as image evidence.
        for shot in group.get("media_previews", []):
            if not isinstance(shot, dict):
                continue
            path = str(shot.get("path", "")).strip()
            if not path:
                continue
            _try_add(path, "image/png", "image")

    return attachments


def call_gemini_whatsapp_summary(
    cfg: Dict[str, Any],
    prompt_text: str,
    attachments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    key = resolve_gemini_key(cfg)
    if not key:
        raise RuntimeError("Missing Gemini API key in env (GEMINI_API_KEY/GOOGLE_API_KEY).")
    model = str(cfg_get(cfg, "gemini.model", "gemini-2.5-flash"))
    connect_timeout = int(cfg_get(cfg, "gemini.connect_timeout_sec", 30))
    request_timeout = int(cfg_get(cfg, "gemini.request_timeout_sec", 300))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": key}
    system_instruction = (
        "You are a multilingual data curator for Atlas annotation QA. "
        "Normalize mixed-language team chat evidence into a practical training brief. "
        "Keep final guidance strict, actionable, and policy-oriented."
    )
    tiers = [1.0, 0.7, 0.4, 0.0]
    if not attachments:
        tiers = [0.0]
    last_error = ""
    attachments_meta: Dict[str, Any] = {}
    for attempt, tier in enumerate(tiers, start=1):
        parts: List[Dict[str, Any]] = [{"text": prompt_text}]
        used = 0
        total_bytes = 0
        attach_count = int(len(attachments) * tier) if tier > 0 else 0
        if attach_count > 0:
            for att in attachments[:attach_count]:
                path = Path(str(att.get("path", "")))
                mime = str(att.get("mime", "")).strip() or "application/octet-stream"
                if not path.exists():
                    continue
                try:
                    raw = path.read_bytes()
                except Exception:
                    continue
                if not raw:
                    continue
                b64 = base64.b64encode(raw).decode("ascii")
                parts.append({"inline_data": {"mime_type": mime, "data": b64}})
                used += 1
                total_bytes += len(raw)
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=(connect_timeout, request_timeout),
            )
            if resp.status_code == 200:
                data = resp.json()
                text = ""
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    text = "".join([str(p.get("text", "")) for p in parts if isinstance(p, dict)])
                except Exception:
                    text = ""
                text = text.strip()
                parsed: Dict[str, Any] = {}
                if text:
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = {"raw_text": text}
                attachments_meta = {
                    "provided_total": len(attachments),
                    "used": used,
                    "used_bytes": total_bytes,
                    "tier": tier,
                    "attempt": attempt,
                }
                return {"http_status": 200, "raw": data, "parsed": parsed, "attachments": attachments_meta}
            last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:500]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep((2 ** (attempt - 1)) * 1.0)
    raise RuntimeError(f"Gemini WhatsApp summary failed: {last_error}")


def collect_whatsapp_snapshot(
    context: BrowserContext,
    cfg: Dict[str, Any],
    run_dir: Path,
    groups: List[str],
    messages_per_group: int,
    media_limit: int,
    skip_gemini: bool,
) -> Dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    groups_root = run_dir / "groups"
    groups_root.mkdir(parents=True, exist_ok=True)
    web_url = str(cfg_get(cfg, "whatsapp_training.web_url", "https://web.whatsapp.com"))
    ready_timeout_sec = int(cfg_get(cfg, "whatsapp_training.ready_timeout_sec", 180))
    max_media_messages = int(cfg_get(cfg, "whatsapp_training.media_extract_max_messages_per_group", 24))
    max_items_per_message = int(cfg_get(cfg, "whatsapp_training.media_extract_max_items_per_message", 2))
    max_item_bytes = int(float(cfg_get(cfg, "whatsapp_training.media_extract_max_item_mb", 6.0)) * 1024 * 1024)
    attach_media_to_gemini = bool(cfg_get(cfg, "whatsapp_training.attach_media_to_gemini", True))
    gemini_max_images = int(cfg_get(cfg, "whatsapp_training.gemini_max_image_attachments", 18))
    gemini_max_audio = int(cfg_get(cfg, "whatsapp_training.gemini_max_audio_attachments", 12))
    gemini_max_total_bytes = int(float(cfg_get(cfg, "whatsapp_training.gemini_max_total_attachment_mb", 18.0)) * 1024 * 1024)
    gemini_min_attachment_bytes = int(cfg_get(cfg, "whatsapp_training.gemini_min_attachment_bytes", 300))

    page = context.new_page()
    page.set_default_timeout(14000)
    page.goto(web_url, wait_until="domcontentloaded")
    state = wait_for_whatsapp_ready(page, timeout_sec=max(30, ready_timeout_sec))
    if state != "ready":
        try:
            (run_dir / "whatsapp_not_ready.png").write_bytes(page.screenshot(full_page=True))
        except Exception:
            pass
        try:
            (run_dir / "whatsapp_not_ready.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass
        raise RuntimeError(
            f"WhatsApp Web is not ready (state={state}). "
            "Login might be missing for this profile, or QR is required."
        )

    data: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "url": web_url,
        "groups": [],
    }

    for name in groups:
        g_slug = slugify(name)
        g_dir = groups_root / g_slug
        g_dir.mkdir(parents=True, exist_ok=True)
        opened = open_group(page, name)
        messages: List[Dict[str, Any]] = []
        media_shots: List[Dict[str, Any]] = []
        if opened:
            page.wait_for_timeout(900)
            messages = extract_messages(page, keep_last=messages_per_group)
            media_files = collect_media_files_for_group(
                page=page,
                group_dir=g_dir,
                messages=messages,
                max_messages=max_media_messages,
                max_items_per_message=max_items_per_message,
                max_item_bytes=max_item_bytes,
            )
            media_shots = capture_media_previews(
                page=page,
                messages=messages,
                out_dir=g_dir / "media_previews",
                max_shots=media_limit,
            )
            try:
                (g_dir / "chat_full.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            try:
                (g_dir / "chat_full.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
        else:
            media_files = []

        group_payload = {
            "group_name": name,
            "group_slug": g_slug,
            "opened": opened,
            "messages_count": len(messages),
            "text_messages_count": sum(1 for m in messages if str(m.get("text", "")).strip()),
            "media_previews_count": len(media_shots),
            "media_files_count": len(media_files),
            "audio_files_count": sum(1 for m in media_files if str(m.get("mime", "")).startswith("audio/")),
            "image_files_count": sum(1 for m in media_files if str(m.get("mime", "")).startswith("image/")),
            "messages": messages,
            "media_previews": media_shots,
            "media_files": media_files,
        }
        (g_dir / "messages.json").write_text(
            json.dumps(group_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        data["groups"].append(group_payload)

    page.close()

    dataset_path = run_dir / "whatsapp_dataset.json"
    dataset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt_lines: List[str] = []
    prompt_lines.append("Multilingual WhatsApp Atlas training digest request.")
    prompt_lines.append("Goal: convert chat signals into QA improvements for Atlas annotation quality.")
    prompt_lines.append("Return strict JSON with keys:")
    prompt_lines.append(
        "language_mix, high_signal_rules, low_signal_noise_patterns, prompt_additions, "
        "operator_checklist, escalation_flags, media_observations, corrected_examples_catalog"
    )
    prompt_lines.append("")
    prompt_lines.append(
        "Media policy: image attachments and audio attachments may contain approved examples "
        "(e.g., green 'correct'). Use them as high-priority supervision signals."
    )
    for group in data.get("groups", []):
        prompt_lines.append("")
        prompt_lines.append(
            f"[GROUP] {group.get('group_name')} opened={group.get('opened')} "
            f"text_msgs={group.get('text_messages_count',0)} media_files={group.get('media_files_count',0)} "
            f"audio_files={group.get('audio_files_count',0)} image_files={group.get('image_files_count',0)}"
        )
        for msg in group.get("messages", [])[:120]:
            txt = str(msg.get("text", "")).strip()
            plain = str(msg.get("plain_meta", "")).strip()
            media_flags = []
            if bool(msg.get("has_image")):
                media_flags.append("image")
            if bool(msg.get("has_audio")):
                media_flags.append("audio")
            if bool(msg.get("has_video")):
                media_flags.append("video")
            media_tag = f" media={','.join(media_flags)}" if media_flags else ""
            if txt:
                prompt_lines.append(f"- {plain}{media_tag} {txt}")
            else:
                prompt_lines.append(f"- {plain}{media_tag} [no text]")
    prompt_text = "\n".join(prompt_lines)
    prompt_path = run_dir / "gemini_whatsapp_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    attachments: List[Dict[str, Any]] = []
    if attach_media_to_gemini:
        attachments = build_gemini_attachments_from_groups(
            groups_payload=data.get("groups", []),
            max_images=gemini_max_images,
            max_audio=gemini_max_audio,
            max_total_bytes=gemini_max_total_bytes,
            min_attachment_bytes=gemini_min_attachment_bytes,
        )
    (run_dir / "gemini_whatsapp_attachments.json").write_text(
        json.dumps({"count": len(attachments), "items": attachments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    gemini_status = "skipped"
    if not skip_gemini:
        try:
            resp = call_gemini_whatsapp_summary(cfg, prompt_text, attachments)
            (run_dir / "gemini_whatsapp_response.json").write_text(
                json.dumps(resp, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "gemini_whatsapp_parsed.json").write_text(
                json.dumps(resp.get("parsed", {}), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            gemini_status = "ok"
        except Exception as exc:
            (run_dir / "gemini_whatsapp_error.txt").write_text(str(exc), encoding="utf-8")
            gemini_status = "error"

    index = {
        "run_dir": str(run_dir),
        "dataset_json": str(dataset_path),
        "prompt_path": str(prompt_path),
        "groups_count": len(data.get("groups", [])),
        "messages_total": sum(int(g.get("messages_count", 0)) for g in data.get("groups", [])),
        "text_messages_total": sum(int(g.get("text_messages_count", 0)) for g in data.get("groups", [])),
        "media_files_total": sum(int(g.get("media_files_count", 0)) for g in data.get("groups", [])),
        "audio_files_total": sum(int(g.get("audio_files_count", 0)) for g in data.get("groups", [])),
        "image_files_total": sum(int(g.get("image_files_count", 0)) for g in data.get("groups", [])),
        "attachments_for_gemini": len(attachments),
        "gemini_status": gemini_status,
        "generated_at": datetime.now().isoformat(),
    }
    (run_dir / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="sample_web_auto_solver.yaml")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--interval-sec", type=int, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--messages-per-group", type=int, default=None)
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--no-profile", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    cfg = load_config(root / args.config)

    root_cfg = str(cfg_get(cfg, "whatsapp_training.root_dir", "outputs/training_feedback/whatsapp")).strip()
    output_root = Path(root_cfg)
    if not output_root.is_absolute():
        output_root = root / output_root
    runs_subdir = str(cfg_get(cfg, "whatsapp_training.runs_subdir", "runs")).strip() or "runs"
    runs_root = output_root / runs_subdir
    output_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    groups = cfg_get(cfg, "whatsapp_training.groups", []) or []
    if not isinstance(groups, list):
        groups = []
    groups = [str(g).strip() for g in groups if str(g).strip()]
    if not groups:
        raise RuntimeError("No WhatsApp groups configured in whatsapp_training.groups.")

    continuous = bool(args.continuous or cfg_get(cfg, "whatsapp_training.continuous", False))
    interval_sec = int(
        args.interval_sec if args.interval_sec is not None else cfg_get(cfg, "whatsapp_training.interval_sec", 3600)
    )
    max_cycles = int(args.max_cycles if args.max_cycles is not None else cfg_get(cfg, "whatsapp_training.max_cycles", 0))
    messages_per_group = int(
        args.messages_per_group
        if args.messages_per_group is not None
        else cfg_get(cfg, "whatsapp_training.messages_per_group", 120)
    )
    media_limit = int(cfg_get(cfg, "whatsapp_training.media_screenshot_limit_per_group", 20))
    headless = bool(
        args.headless
        or cfg_get(cfg, "whatsapp_training.headless", False)
        or cfg_get(cfg, "browser.headless", False)
    )

    with sync_playwright() as pw:
        context, browser = launch_context(
            pw=pw,
            cfg=cfg,
            headless=headless,
            force_no_profile=bool(args.no_profile),
        )
        try:
            cycle = 0
            while True:
                cycle += 1
                run_dir = unique_run_dir(runs_root)
                try:
                    index = collect_whatsapp_snapshot(
                        context=context,
                        cfg=cfg,
                        run_dir=run_dir,
                        groups=groups,
                        messages_per_group=messages_per_group,
                        media_limit=media_limit,
                        skip_gemini=bool(args.skip_gemini),
                    )
                    index["cycle"] = cycle
                    (output_root / "latest.json").write_text(
                        json.dumps(index, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    with (output_root / "runs_manifest.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(index, ensure_ascii=False))
                        f.write("\n")
                    print(f"[whatsapp] saved: {run_dir}")
                    print(f"[whatsapp] messages_total: {index['messages_total']}")
                    print(f"[whatsapp] gemini_status: {index['gemini_status']}")
                except Exception as exc:
                    err = {"cycle": cycle, "error": str(exc), "generated_at": datetime.now().isoformat()}
                    (run_dir / "RUN_ERROR.json").write_text(json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8")
                    status = {
                        "run_dir": str(run_dir),
                        "cycle": cycle,
                        "status": "error",
                        "messages_total": 0,
                        "groups_count": 0,
                        "gemini_status": "error",
                        "error": str(exc),
                        "generated_at": datetime.now().isoformat(),
                    }
                    (output_root / "latest.json").write_text(
                        json.dumps(status, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    with (output_root / "runs_manifest.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(status, ensure_ascii=False))
                        f.write("\n")
                    print(f"[whatsapp] cycle failed: {exc}")

                if not continuous:
                    break
                if max_cycles > 0 and cycle >= max_cycles:
                    print(f"[whatsapp] reached max_cycles={max_cycles}.")
                    break
                wait_s = max(5, interval_sec)
                print(f"[whatsapp] waiting {wait_s}s before next cycle...")
                time.sleep(wait_s)
        finally:
            context.close()
            if browser is not None:
                browser.close()


if __name__ == "__main__":
    main()
