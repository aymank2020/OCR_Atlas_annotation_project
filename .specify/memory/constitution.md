# Atlas OCR Annotation — Project Constitution

> This document defines the non-negotiable rules for this project.
> SpecKit will treat any violation as CRITICAL.

## Core Principles

### P1: Label Quality Above All
- Every label MUST start with an imperative action verb from the approved list.
- "No Action" is ONLY valid when there is zero hand/object interaction.
- Never use intent language: "prepare to", "try to", "about to".
- Never use numerals — write "two" not "2".

### P2: Forbidden Verbs
- NEVER use: inspect, check, look, examine, reach, rotate, grab, relocate.
- Replace "grab" → "pick up", "twist" → "turn".

### P3: Timestamp Integrity
- Segments MUST be gapless and monotonically increasing.
- No overlaps allowed between consecutive segments.
- segment_index is 1-based (matches validator.py).

### P4: Video Context is Mandatory
- Production mode MUST require video for all Gemini calls.
- Text-only fallback is NOT allowed in production.

### P5: Security
- All user inputs (episode_id, file paths) MUST be validated.
- Path traversal attack vectors MUST be prevented.
- No PII in logs or debug output.

### P6: Error Visibility
- Silent `except: pass` is FORBIDDEN.
- All exceptions MUST be logged at minimum WARNING level.
- Bare `except:` is FORBIDDEN — use `except Exception:`.

### P7: Timezone Safety
- `datetime.utcnow()` is FORBIDDEN — use `datetime.now(timezone.utc)`.

## Technology Stack
- **Language**: Python 3.10+
- **Browser Automation**: Playwright (Chromium)
- **AI Model**: Gemini (API Key or Vertex AI)
- **Deployment**: Ubuntu VPS (2GB RAM), systemd services
- **Config**: YAML files, `.env` for secrets

## Quality Gates
- All labels pass `validator.py` before submission.
- `submit_gate.py` MUST approve before final submit.
- Pre-submit live recheck is ALWAYS enabled in production.
