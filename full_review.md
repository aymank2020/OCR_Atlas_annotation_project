Starting CodeRabbit review in plain text mode...

Connecting to review service
Setting up
Analyzing
Reviewing

============================================================================
File: sample_web_auto_solver_production.yaml
Line: 28
Type: potential_issue

Comment:
Duplicate YAML key segment_chunking_enabled will cause unexpected behavior.

The key segment_chunking_enabled is defined twice:
- Line 28: segment_chunking_enabled: true
- Line 67: segment_chunking_enabled: false

YAML parsers will silently use only the last value (false), which contradicts the earlier setting. Based on the comments, it appears line 67's section is meant to configure "full-video-first" behavior, but this creates ambiguity about the intended production setting.


🐛 Proposed fix: Remove the duplicate and clarify intent

If chunking should be disabled for full-video-first mode:
 run:
   dry_run: false
   max_segments: 0
   max_episodes_per_run: 0
   reserve_cooldown_sec: 120
   reuse_cached_labels: true
   skip_unchanged_labels: true
   resume_from_artifacts: true
   # PRODUCTION SAFETY: never skip video steps
   resume_skip_video_steps_when_cached: false
   resume_skip_apply_steps_when_done: true
   auto_continuity_merge_enabled: true
-  segment_chunking_enabled: true
+  # FULL-VIDEO-FIRST: chunking disabled, with fallback on failure
+  segment_chunking_enabled: false
   segment_chunking_temporal_anchor_enabled: true


Then remove lines 66-68:
-  # FULL-VIDEO-FIRST: try full video inline, fall back to chunking if fails
-  segment_chunking_enabled: false
   segment_chunking_fallback_on_full_fail: true




Also applies to: 67-67

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @sample_web_auto_solver_production.yaml at line 28, The YAML contains a duplicate key segment_chunking_enabled (true at the top and false later) which causes parsers to keep only the last value; remove the redundant segment_chunking_enabled: false in the full-video-first section (or rename it to a mode-specific key like full_video_first.segment_chunking_enabled) and add a clear comment indicating that chunking is enabled for production but disabled only for the full-video-first mode so the intended behavior is unambiguous.



============================================================================
File: .agent/skills/speckit-plan/SKILL.md
Line: 71
Type: potential_issue

Comment:
Clarify Phase 2 reference.

Line 71 states "Command ends after Phase 2 planning" but the documented phases are only Phase 0 (Outline & Research) and Phase 1 (Design & Contracts). Either Phase 2 documentation is missing, or this should reference Phase 1.


🔧 Proposed fix if Phase 1 is the final phase

-4. Stop and report: Command ends after Phase 2 planning. Report branch, IMPL_PLAN path, and generated artifacts.
+4. Stop and report: Command ends after Phase 1 planning. Report branch, IMPL_PLAN path, and generated artifacts.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.agent/skills/speckit-plan/SKILL.md at line 71, The sentence "Stop and report: Command ends after Phase 2 planning" is inconsistent with the documented phases (Phase 0 and Phase 1); either add missing Phase 2 documentation or change the reference to Phase 1. Update the SKILL.md content so the step "Stop and report" correctly references the final phase by renaming "Phase 2" to "Phase 1" in that line, or if a true Phase 2 exists, add a new section for "Phase 2" (detailing its scope and outputs) and adjust other references accordingly; ensure the headings "Phase 0 (Outline & Research)" and "Phase 1 (Design & Contracts)" remain accurate after the change.



============================================================================
File: atlas_auto_sync_and_rebuild.py
Line: 200 to 206
Type: potential_issue

Comment:
Silent exception swallowing and insecure /tmp usage.

Two issues here:

1. The bare except Exception: pass silently swallows all errors. At minimum, log the failure so operators know why the symlink wasn't created.
2. Using a hardcoded /tmp path can be problematic on systems with different temp directories or where /tmp is world-writable with sticky bit concerns.



🛡️ Proposed fix: log exception and use tempfile module

+import tempfile
+import logging
+
+_logger = logging.getLogger(__name__)
+
 # Viewer may contain absolute /tmp paths from drive snapshot indexes.
 # Expose /tmp under outputs/tmp so python -m http.server --directory outputs
 # can serve those paths as /tmp/...
 if os.name != "nt":
     tmp_link = outputs_dir / "tmp"
     try:
         if not tmp_link.exists():
-            tmp_link.symlink_to(Path("/tmp"), target_is_directory=True)
-    except Exception:
-        pass
+            # Use the system's actual temp directory
+            tmp_link.symlink_to(Path(tempfile.gettempdir()), target_is_directory=True)
+    except OSError as e:
+        _log(f"Could not create tmp symlink: {e}")

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_auto_sync_and_rebuild.py around lines 200 - 206, The code silently swallows errors when creating the tmp symlink and uses a hardcoded /tmp; update the block that references tmp_link and outputs_dir so it uses tempfile.gettempdir() (convert to a Path) as the symlink target, check the target exists (or create a safe directory if appropriate), and replace the bare except in the tmp_link.symlink_to(...) attempt with an except Exception as e that logs the failure (e.g., using the module logger or a provided logger) including the exception details and context about tmp_link and the target path; keep the os.name != "nt" guard and preserve target_is_directory=True when calling symlink_to.



============================================================================
File: atlas_triplet_batch.py
Line: 745 to 746
Type: potential_issue

Comment:
Results file is truncated unconditionally, potentially losing prior run data.

The JSONL file is cleared at the start regardless of skip_existing_results. If a user expects incremental runs to accumulate results, this will cause data loss. The skip_existing_results flag skips reprocessing but still overwrites the output file.

Consider whether this is intentional behavior or if you should append when skip_existing_results=True.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_triplet_batch.py around lines 745 - 746, The current code unconditionally truncates the output JSONL via results_jsonl.write_text("") which will erase prior runs even when skip_existing_results is True; update the logic around results_jsonl and skip_existing_results so that you only create parent dirs and create an empty file if the file does not exist, or open/append to the file when skip_existing_results is True (i.e., do not call results_jsonl.write_text("") in that case); locate the results_jsonl usage and the skip_existing_results flag in atlas_triplet_batch.py and change the file initialization to conditional file creation or append behavior to preserve existing results.



============================================================================
File: atlas_triplet_batch.py
Line: 195 to 198
Type: potential_issue

Comment:
Missing timeout for subprocess call can cause batch to hang indefinitely.

The ffmpeg subprocess lacks a timeout parameter. If the video transcoding hangs (e.g., corrupted file, I/O issues), the entire batch process will block indefinitely.



Add timeout to subprocess call

     try:
-        subprocess.run(cmd, check=True)
+        subprocess.run(cmd, check=True, timeout=600)  # 10 minute timeout
     except Exception:
         return None

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_triplet_batch.py around lines 195 - 198, The subprocess.run call currently has no timeout and can hang; update the call subprocess.run(cmd, check=True) to include a sensible timeout (e.g., a constant like FFMPEG_TIMEOUT or a passed-in parameter) and catch subprocess.TimeoutExpired separately from the generic Exception so the batch can fail fast; in the except block for TimeoutExpired, terminate/cleanup as needed and return None (and optionally log the timeout) while keeping other exception handling unchanged.



============================================================================
File: specs/001-4way-episode-solver/spec.md
Line: 33 to 34
Type: potential_issue

Comment:
Fix formatting typo in acceptance scenario.

Line 33 has a formatting issue: 3.gIVEN should be 3. Given (missing space, incorrect capitalization).



📝 Proposed fix

-3.gIVEN نجمع الحلول الاربعة ونقارنهم ببعض ونختار الافضل او ننشئ حل جديد فيه مجموع ما تم حله من كل طريقة  WHEN يتم تشغيل 4-way pipeline, Then طريقة واحدة على الأقل تنتج حل بجودة ≥95%.
+3. Given نجمع الحلول الاربعة ونقارنهم ببعض ونختار الافضل أو ننشئ حل جديد فيه مجموع ما تم حله من كل طريقة, When يتم تشغيل 4-way pipeline, Then طريقة واحدة على الأقل تنتج حل بجودة ≥95%.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @specs/001-4way-episode-solver/spec.md around lines 33 - 34, Fix the formatting typo in the acceptance scenario header: locate the entry that currently reads "3.gIVEN" and change it to "3. Given (capitalize 'Given' and add a space after the period) so the scenario headings follow the same capitalization and spacing as the other items; ensure the rest of the line's Arabic/English text remains unchanged.



============================================================================
File: .specify/scripts/powershell/check-prerequisites.ps1
Line: 139 to 147
Type: potential_issue

Comment:
Remove | Out-Null piping to display status messages from prerequisite checks.

The Test-FileExists and Test-DirHasFiles functions use Write-Output to emit status messages (✓ or ✗ symbols), but piping their output to Out-Null suppresses these messages. The status information is discarded and never displayed to the user.

Remove the | Out-Null pipes from lines 140-146 to allow the status output to be shown.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.specify/scripts/powershell/check-prerequisites.ps1 around lines 139 - 147, The status output from the prerequisite checks is being suppressed by piping the results of Test-FileExists and Test-DirHasFiles to Out-Null; remove the trailing "| Out-Null" from the calls that invoke Test-FileExists ($paths.RESEARCH, $paths.DATA_MODEL, $paths.QUICKSTART, and $paths.TASKS when $IncludeTasks is true) and from the Test-DirHasFiles call ($paths.CONTRACTS_DIR) so their Write-Output messages (✓/✗) are displayed to the user.



============================================================================
File: atlas_correction_chat.py
Line: 117 to 135
Type: potential_issue

Comment:
Edge case: "skip" or "accept" as part of multi-line JSON is consumed as a command.

If a user pastes JSON containing a field value like "skip" on its own line, it will be interpreted as a command and exit the input loop prematurely.



💡 Proposed fix - check command only on first non-empty line

     lines = []
     print("  > Paste your JSON (or command) below:")
+    first_input = True
     while True:
         try:
             line = input()
         except (EOFError, KeyboardInterrupt):
             break
-        if line.lower() in ("skip", "accept"):
+        if first_input and line.lower() in ("skip", "accept"):
             if line.lower() == "skip":
                 print("[correction] Episode skipped.")
                 return None
             if line.lower() == "accept":
                 print("[correction] Accepted Gemini's labels as-is.")
                 return labels_data  # Return original labels
+        first_input = False
         lines.append(line)

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_correction_chat.py around lines 117 - 135, The input loop currently treats any line equal to "skip" or "accept" as a command even if it's part of pasted JSON; change the check so those keywords are only recognized when entered as the first non-empty line. In the loop in atlas_correction_chat.py (the block that reads lines and returns labels_data on "accept" or None on "skip"), use line_stripped = line.strip() and only handle the command if line_stripped in ("skip","accept") AND all previously collected lines are empty/whitespace (e.g., track a flag like seen_non_empty or check if any(l.strip() for l in lines) is False). Preserve the existing behavior for returning labels_data on "accept" and printing/skipping on "skip", and keep the two-empty-line JSON termination logic unchanged.



============================================================================
File: pipeline_runner.py
Line: 694 to 696
Type: potential_issue

Comment:
Use the public API set_console_output_enabled(False) instead of accessing the private attribute.

Line 696 accesses the private attribute _disable_console_output, which is fragile and not the recommended approach. AgentScope provides a public API for this:

-        agent._disable_console_output = True  # type: ignore[attr-defined]
+        agent.set_console_output_enabled(False)

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @pipeline_runner.py around lines 694 - 696, Replace the fragile private-attribute access agent._disable_console_output = True with the public API call agent.set_console_output_enabled(False); find the location where agent is used inside the pipeline stage (the block that currently sets _disable_console_output) and call set_console_output_enabled(False) on that AgentScope/agent instance instead, removing the type: ignore and relying on the public method for controlling console output.



============================================================================
File: pipeline_runner.py
Line: 622 to 702
Type: potential_issue

Comment:
Consider replacing the private _disable_console_output attribute with a public alternative or add a fallback.

The main AgentScope APIs (ReActAgent, Msg, get_text_content(), model classes, and formatters) are correctly implemented per AgentScope documentation. However, line 693 directly assigns to agent._disable_console_output, a private internal attribute. Since private attributes are not part of the public API contract, this could break if AgentScope changes its internal implementation. Either use a public mechanism for controlling console output (if available in AgentScope), or add a fallback that gracefully handles the case where this attribute no longer exists.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @pipeline_runner.py around lines 622 - 702, The code in _call_agentscope_json sets the private attribute agent._disable_console_output directly; replace this with a robust public-or-fallback approach: after creating the ReActAgent instance (variable agent), first check for and call any public method like disable_console_output() or set_disable_console_output(...) if provided by ReActAgent, and if no such method exists use a safe fallback that only sets the private attribute when present (e.g., check hasattr(agent, "_disable_console_output") before assigning) or otherwise ignore without raising; update the assignment site (referencing ReActAgent and agent._disable_console_output in _call_agentscope_json) to implement this try-public-then-fallback pattern so console suppression works without relying on a private API.



============================================================================
File: atlas_repair_loop.py
Line: 486 to 513
Type: potential_issue

Comment:
Segment count mismatch allows repair to continue, may cause issues.

When the repair produces a different number of segments (line 488), the code logs a warning but then continues using the repaired segments (line 493). This could cause downstream issues if the pipeline expects consistent segment counts. Consider whether this should be a blocking condition instead.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_repair_loop.py around lines 486 - 513, The repair branch currently accepts a repaired_segments list with a different length and overwrites current_segments, which can break downstream assumptions; change the logic in the new_ok handling (the block that checks len(repaired_segments) != len(current_segments)) to treat a segment-count mismatch as a rejected repair: log the mismatch (keep the existing print), do NOT assign current_segments = repaired_segments, and mark this attempt as a failure so the loop will continue with the original current_segments (or return a failed RepairLoopResult if you want to abort immediately); update the behavior around new_ok, repaired_segments, current_segments and the return path (RepairLoopResult) so mismatched-length repairs never replace current_segments.



============================================================================
File: vertex_create_cache.py
Line: 138
Type: potential_issue

Comment:
Use a valid Vertex AI Gemini model identifier for the default.

The model name gemini-3.1-pro-preview does not exist in Vertex AI. Based on 2025 Gemini models, valid options include gemini-2.5-pro, gemini-2.0-flash-001, or other documented models in the Vertex AI catalog. Update the default to a valid model identifier.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @vertex_create_cache.py at line 138, The default model name passed to the argument parser is invalid; update the ap.add_argument("--model", default="gemini-3.1-pro-preview") call to use a valid Vertex AI Gemini model identifier (for example "gemini-2.5-pro" or "gemini-2.0-flash-001") so the script runs against an existing model; locate the ap.add_argument("--model", ...) invocation and replace the default value with a supported model string and, if applicable, update any help text or README references to reflect the supported defaults.



============================================================================
File: atlas_triplet_compare.py
Line: 279 to 281
Type: potential_issue

Comment:
Subprocess call appears safe but lacks timeout.

The _run function executes subprocess commands without a timeout. For external tools like rclone and ffmpeg, this could hang indefinitely on network issues or corrupted files.



💡 Add timeout parameter

-def _run(cmd: list[str]) -> None:
-    subprocess.run(cmd, check=True)
+def _run(cmd: list[str], timeout: int = 300) -> None:
+    subprocess.run(cmd, check=True, timeout=timeout)

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_triplet_compare.py around lines 279 - 281, The helper function _run currently calls subprocess.run(cmd, check=True) with no timeout which can hang for external tools like rclone or ffmpeg; modify _run to accept a timeout parameter (e.g., timeout: int | float = 300), pass that timeout into subprocess.run(..., timeout=timeout, check=True), and handle subprocess.TimeoutExpired (and re-raise or convert to a clear exception/log message) so callers get a deterministic failure instead of hanging; update any callers of _run if they need custom timeouts.



============================================================================
File: run_production.sh
Line: 163 to 166
Type: potential_issue

Comment:
Queue count may be inaccurate due to JSONL duplicates.

The manual queue file is append-only with potential duplicate episode entries (as noted in the dashboard code). Using wc -l counts all entries, not unique episodes. This could mislead operators about the actual queue size.



💡 More accurate count using jq

 if [[ -f "$MANUAL_QUEUE" ]]; then
-  QUEUE_COUNT=$(wc -l /dev/null 2>&1; then
+    QUEUE_COUNT=$(jq -r '.episode_id' "$MANUAL_QUEUE" 2>/dev/null | sort -u | wc -l | tr -d ' ')
+  else
+    QUEUE_COUNT=$(wc -l

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @run_production.sh around lines 163 - 166, The current queue count uses wc -l on MANUAL_QUEUE, which counts all JSONL entries including duplicates; change the QUEUE_COUNT calculation to parse MANUAL_QUEUE with jq to extract the episode identifier field (the same key used by the dashboard, e.g., "episode" or "episode_id"), then deduplicate (sort -u) and count unique IDs so QUEUE_COUNT reflects unique episodes; update the code that sets QUEUE_COUNT (the variable and block referencing MANUAL_QUEUE and QUEUE_COUNT) to use this jq+dedupe approach and ensure it still behaves correctly when jq is missing or the file is empty.



============================================================================
File: run_production.sh
Line: 193 to 195
Type: potential_issue

Comment:
grep -oP requires PCRE support which isn't universal.

The -P flag (Perl-compatible regex) isn't available on all systems (e.g., macOS default grep). Consider using a more portable approach.



💡 Portable alternative

-  FOLDER_ID=$(echo "$DRIVE_LINK" | grep -oP '(?

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @run_production.sh around lines 193 - 195, The current FOLDER_ID extraction uses grep -oP which requires PCRE; replace it with a POSIX-portable extraction (e.g., use sed or awk) when setting FOLDER_ID in run_production.sh so it reliably captures the segment after "/folders/" from $DRIVE_LINK; update the FOLDER_ID assignment (the line using grep -oP) to use a sed or awk substitution that extracts the [a-zA-Z0-9_-]+ token and preserve the existing fallback (|| true) and variable name semantics.



============================================================================
File: atlas_repair_loop.py
Line: 629 to 641
Type: potential_issue

Comment:
Silent failure when queueing for manual review.

If append_to_manual_queue fails (e.g., disk full, permissions), the error is silently swallowed. This could result in episodes being neither repaired nor queued, leaving them in an undefined state.



🛡️ Log the failure

     try:
         from submit_gate import append_to_manual_queue  # type: ignore
         append_to_manual_queue(
             outputs_dir,
             gate_result,
             extra_meta={
                 "repair_attempted": True,
                 "repair_attempts": len(result.attempts),
                 "repair_failure_reason": result.failure_reason,
             },
         )
-    except Exception:
-        pass
+    except Exception as exc:
+        print(f"[repair-loop] CRITICAL: failed to queue episode={episode_id} for manual review: {exc}")

     return None

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_repair_loop.py around lines 629 - 641, The try/except around append_to_manual_queue currently swallows all errors; change the except to capture the exception (except Exception as e) and log it instead of passing silently—use the module logger (e.g., processLogger or the existing logger) or logger.exception to record the error message and stack trace, and include contextual fields like outputs_dir, gate_result identifiers, result.failure_reason and len(result.attempts) so failures to queue for manual review are visible for debugging while preserving the existing control flow.



============================================================================
File: atlas_dashboard_v2.py
Line: 232 to 265
Type: potential_issue

Comment:
Potential XSS vulnerability in HTML table generation.

User-controlled data from JSON files (fail reasons, model names, episode IDs, etc.) is interpolated directly into HTML without escaping. If any of this data contains  or other HTML, it could lead to XSS when viewing the dashboard.



🛡️ Proposed fix using html.escape

+import html
+
+def _escape(value: Any) -> str:
+    return html.escape(str(value or ""))
+
 # Then in the table row generation:
     fail_rows = "".join(
-        f"{r}{c}"
+        f"{_escape(r)}{c}"
         for r, c in m.get("top_fail_reasons", [])
     )


Apply similar escaping to all user-controlled content: val_fail_rows, winner_rows, queue_rows, know_rows, cost_rows, status_rows.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_dashboard_v2.py around lines 232 - 265, Escape all user-controlled values before embedding them into HTML by using html.escape: import html and replace direct interpolations in the comprehension generators (fail_rows, val_fail_rows, winner_rows, queue_rows, know_rows, cost_rows, status_rows) so that string fields like fail reason (r), validator fail type, winner (w), episode_id, winner field, reason, category (cat), model name, and status are passed through html.escape(...) before formatting; leave numeric formatting (counts, cost, dates) as-is but ensure any value coming from m.get(...) that is rendered as text is escaped to prevent XSS.



============================================================================
File: atlas_knowledge_collector.py
Line: 241 to 249
Type: potential_issue

Comment:
Security: URL scheme not validated before opening.

urllib.request.urlopen accepts file:// and custom schemes by default. Discord attachment URLs should always be HTTPS, so validating the scheme prevents potential SSRF or local file access if malicious URLs are injected into the Discord export.



🛡️ Proposed fix to validate URL scheme

+from urllib.parse import urlparse
+
 def download_discord_videos(
     video_urls: List[str],
     out_dir: Path,
     max_videos: int = 20,
 ) -> List[Path]:
     """Download Discord video attachments as reference material."""
     out_dir.mkdir(parents=True, exist_ok=True)
     downloaded: List[Path] = []

     for i, url in enumerate(video_urls[:max_videos]):
+        # Validate URL scheme to prevent SSRF
+        parsed = urlparse(url)
+        if parsed.scheme not in ("http", "https"):
+            print(f"[knowledge] warn: skipping non-HTTP URL: {url[:60]}")
+            continue
+
         filename = re.sub(r"[^\w\-.]", "_", url.split("/")[-1].split("?")[0])

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_knowledge_collector.py around lines 241 - 249, The download loop currently calls urllib.request.urlopen(req, ...) on unvalidated URLs (variables url and req), which allows file:// or other schemes; before creating the Request or opening the URL in the block that appends to downloaded and writes out_path, parse the URL (e.g., via urllib.parse.urlparse) and validate that parsed.scheme == "https" (optionally also reject "http" if strict), otherwise log a warning and skip the URL; ensure the check is applied right where url is used (the try/except around urllib.request.urlopen) so the code never calls urllib.request.urlopen for non-HTTPS schemes.



============================================================================
File: atlas_triplet_compare.py
Line: 243 to 249
Type: potential_issue

Comment:
Remove or update outdated model aliases.

The alias gemini-3.1-pro-preview → gemini-3-pro-preview maps to a non-existent model. As of March 2026, Gemini API has gemini-3.1-pro-preview but no gemini-3-pro-preview. The gemini-3.1-flash-preview → gemini-3-flash-preview alias maps to an existing model, but both aliases appear to assume deprecated naming conventions. Verify if these normalizations are still necessary or if the source models should be used directly.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_triplet_compare.py around lines 243 - 249, The _normalize_vertex_model_id function contains outdated alias mappings; remove the mapping that rewrites "gemini-3.1-pro-preview" to "gemini-3-pro-preview" (since "gemini-3-pro-preview" no longer exists) and either delete the aliases dict entirely or reduce it to only valid/current mappings (e.g., keep or update "gemini-3.1-flash-preview" only if you confirm it must map to another name); update the function so it returns the input model string unchanged for current valid names and add a brief comment in _normalize_vertex_model_id explaining why any remaining alias exists and that mappings must mirror the live Gemini API model names.



============================================================================
File: .agent/skills/speckit-implement/SKILL.md
Line: 32 to 53
Type: potential_issue

Comment:
Add languages to these fenced examples.

markdownlint will keep flagging these blocks until the fences declare a language. md or text would both work here.



Also applies to: 187-206

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.agent/skills/speckit-implement/SKILL.md around lines 32 - 53, The fenced code blocks in the SKILL.md examples for "Optional Pre-Hook" and "Automatic Pre-Hook" (the blocks showing the command, prompt, and EXECUTE_COMMAND examples) are missing a language and trigger markdownlint warnings; update each triple-backtick fence to include a language (e.g., md or text) for both the example under "Optional Pre-Hook" and the example under "Automatic Pre-Hook", and make the same change for the similar fenced examples referenced at lines 187-206 so all code fences declare a language.



============================================================================
File: .specify/scripts/powershell/update-agent-context.ps1
Line: 421 to 444
Type: potential_issue

Comment:
Deduplicate file targets before iterating.

AGENTS.md is referenced here via AGENTS_FILE, KIRO_FILE, and BOB_FILE, so one Update-AllExistingAgents run can rewrite the same file multiple times and compound the duplicate-entry problem above.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.specify/scripts/powershell/update-agent-context.ps1 around lines 421 - 444, The Update-AllExistingAgents function currently calls Update-AgentFile multiple times for the same path (e.g., AGENTS_FILE referenced also by KIRO_FILE and BOB_FILE), causing duplicate rewrites; fix it by collecting all file variables referenced in Update-AllExistingAgents (AGENTS_FILE, KIRO_FILE, BOB_FILE, CLAUDE_FILE, GEMINI_FILE, etc.) into a single array, filter that array to unique existing paths (e.g., with PowerShell's Select-Object -Unique or a Hashtable), then iterate that deduplicated list calling Update-AgentFile once per target while preserving the $found and $ok update logic; keep the same Update-AgentFile calls and agent-name semantics but ensure each physical file path is processed only once.



============================================================================
File: atlas_build_vertex_fewshot.py
Line: 88 to 97
Type: potential_issue

Comment:
Restrict candidate refs to trusted roots before reading them.

_try_resolve_file() accepts any absolute path found in triplet detail JSON, and _build_candidates() then copies that file's contents into the few-shot/context bundle. A poisoned artifact can therefore pull arbitrary local files into the prompt pack.



Also applies to: 148-181

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_build_vertex_fewshot.py around lines 88 - 97, The resolver currently allows any absolute path from triplet JSON; change _try_resolve_file to only accept paths that resolve inside trusted roots (e.g., the provided base_dir or an explicit trusted_roots list) before returning a Path: resolve the candidate with Path.resolve(), then verify it is a file and that str(resolved_path).startswith(str(base_dir.resolve())) or use Path.is_relative_to(trusted_root) for each trusted root; reject any path that is absolute but not under those trusted roots so _build_candidates cannot include arbitrary local files (also apply the same restrictions to the logic referenced in _build_candidates).



============================================================================
File: atlas_build_vertex_fewshot.py
Line: 320 to 321
Type: potential_issue

Comment:
Recompute pass/fail totals after --max-examples truncation.

examples is sliced here, but pass_count and fail_count still reflect the pre-slice set. The metadata and logs can then disagree with the files you actually wrote.


Suggested fix

     if args.max_examples and int(args.max_examples) > 0:
         examples = examples[: int(args.max_examples)]
+        pass_count = sum(1 for rec in examples if rec.get("label") == "PASS")
+        fail_count = sum(1 for rec in examples if rec.get("label") == "FAIL")




Also applies to: 381-395

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_build_vertex_fewshot.py around lines 320 - 321, After slicing examples by args.max_examples, recompute the aggregate counters (e.g., pass_count and fail_count) from the truncated examples list (examples) before emitting metadata/logs or writing files; for example set pass_count = sum(1 for ex in examples if ex.get("status") == "pass") and fail_count = len(examples) - pass_count (and recompute any derived totals or pass_rate). Apply the same recompute step to the other similar block (the counts computed around the code handling lines ~381-395) so metadata and logs reflect the actual written examples.



============================================================================
File: .specify/scripts/powershell/update-agent-context.ps1
Line: 306 to 355
Type: potential_issue

Comment:
Make existing-file updates idempotent and create missing sections.

This logic only injects content when ## Active Technologies or ## Recent Changes already exist, and it prepends the current branch entry on every run without checking for an existing match. Existing agent files can stay stale, while reruns accumulate duplicate Recent Changes lines.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.specify/scripts/powershell/update-agent-context.ps1 around lines 306 - 355, The loop currently only injects under existing "## Active Technologies" and "## Recent Changes" headers and blindly prepends $newChangeEntry and $newTechEntries causing duplicates; make updates idempotent by: before adding any $newTechEntries or $newChangeEntry, scan $lines (or $output) for matching entries and skip additions if present; if the headers "## Active Technologies" or "## Recent Changes" are missing, create them (and insert the entries) in the post-loop check using $output.InsertRange, and when adding recent changes respect $existingChanges and check for an existing line that equals $newChangeEntry to avoid repeated prepends; ensure the frontmatter insertion for .mdc remains but runs after dedup/insertion logic so it won’t create duplicates.



============================================================================
File: .agent/commands/speckit.implement.md
Line: 23 to 44
Type: potential_issue

Comment:
Add languages to these fenced examples.

The unlabeled fences here will keep tripping MD040. Using md or text is enough.



Also applies to: 178-197

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.agent/commands/speckit.implement.md around lines 23 - 44, Update the fenced code blocks in .agent/commands/speckit.implement.md so each triple-backtick fence is language-labeled (e.g., md or text) to satisfy MD040; specifically modify the example blocks under "Optional Pre-Hook" and "Automatic Pre-Hook" (the blocks showing Command/Description/Prompt/To execute and the block showing Executing/EXECUTE_COMMAND/Wait for the result) and the similar examples at lines ~178-197 to include a language tag after the opening ``` for each fence.



============================================================================
File: run_single_episode_4way.sh
Line: 39 to 44
Type: potential_issue

Comment:
Validate EPISODE_ID before interpolating it into paths.

This value is reused in rm targets, temp config names, and generated JSON paths. Without a strict episode-id check, a crafted value containing / or .. can escape the intended per-episode directories.


Suggested fix

 EPISODE_ID="${EPISODE_ID:-${1:-}}"
 if [[ -z "$EPISODE_ID" ]]; then
   echo "[single4] error: missing EPISODE_ID"
   echo "[single4] usage: EPISODE_ID= bash ./run_single_episode_4way.sh"
   exit 1
 fi
+if [[ ! "$EPISODE_ID" =~ ^[0-9A-Fa-f]{24}$ ]]; then
+  echo "[single4] error: EPISODE_ID must be a 24-character hex Atlas episode id"
+  exit 1
+fi
+EPISODE_ID="${EPISODE_ID,,}"




============================================================================
File: atlas_review_viewer_gen.py
Line: 688 to 725
Type: potential_issue

Comment:
Don't classify ordinary compare FAILs as error.

The detail-only fallback hardcodes ok: true, and the later mapping turns every non-skipped non-ok row into error. Episodes that simply failed the gate will show the wrong comparison status in the new panel.


Suggested fix

-        rec = {
+        const derivedOk =
+          !!winnerTmp &&
+          winnerTmp !== "none" &&
+          (!judgeTmp.submit_safe_solution ||
+            String(judgeTmp.submit_safe_solution).trim().toLowerCase() === winnerTmp);
+        rec = {
           episode_id: safeEid,
-          ok: true,
+          ok: derivedOk,
           skipped: false,
@@
-      const statusTxt = rec.ok ? "ok" : (rec.skipped ? "skipped" : "error");
+      const statusTxt = rec.ok ? "ok" : (rec.skipped ? "skipped" : "failed");

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_review_viewer_gen.py around lines 688 - 725, The fallback that builds rec from detail currently hardcodes ok: true which masks real failure status and causes failed comparisons to be misclassified as "error" later; update the block that creates rec (using variables judgeTmp, winnerTmp, scoreTmp) to derive rec.ok and rec.skipped from judgeTmp (e.g., rec.ok = Boolean(judgeTmp.ok) or based on judgeTmp.status/pass field, and rec.skipped = Boolean(judgeTmp.skipped) or when status indicates skipped) and preserve the original reason/status fields from judgeTmp if present so ordinary compare FAILs are not turned into generic errors.



============================================================================
File: atlas_dynamic_rag.py
Line: 36 to 50
Type: potential_issue

Comment:
Parse JSONL per line and keep only object records.

The current try wraps the whole read loop, so one bad line stops processing the rest of the file. It also appends non-dict JSON values, but the retrieval code later calls .get() on every record. That makes the loader brittle instead of fault-tolerant.


Suggested fix

 def _load_jsonl(path: str) -> List[Dict[str, Any]]:
     """Load all lines from a JSONL file."""
     p = Path(path)
     if not p.exists():
         return []
-    records = []
-    try:
-        with open(p, "r", encoding="utf-8") as f:
-            for line in f:
-                line = line.strip()
-                if line:
-                    records.append(json.loads(line))
-    except Exception as e:
-        print(f"[RAG] Warning: Failed to parse {path}: {e}")
+    records: List[Dict[str, Any]] = []
+    with open(p, "r", encoding="utf-8") as f:
+        for lineno, line in enumerate(f, start=1):
+            line = line.strip()
+            if not line:
+                continue
+            try:
+                obj = json.loads(line)
+            except json.JSONDecodeError as e:
+                print(f"[RAG] Warning: Failed to parse {path} line {lineno}: {e}")
+                continue
+            if isinstance(obj, dict):
+                records.append(obj)
     return records

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_dynamic_rag.py around lines 36 - 50, The _load_jsonl function should parse each line independently and only keep dict/object records: move the try/except inside the line loop (around json.loads) so a malformed line is skipped with a warning and does not stop processing the rest of the file, and after parsing check that the parsed value is a dict before appending to records (skip and warn for non-dict JSON values); keep the file-open and existence logic as-is and use the same path/name in warnings to aid debugging.



============================================================================
File: atlas_dashboard_gen.py
Line: 163 to 169
Type: potential_issue

Comment:
Include labels_.json in the chat-usage fallback.

This only scans labels_*_chat.json, but atlas_build_vertex_fewshot.py, Lines 168-170, and run_single_episode_4way.sh, Lines 97-99, both use chat_reviews//labels_.json. When gemini_usage.jsonl is missing, timed-chat requests disappear from the cost totals.


Suggested fix

-    for f in sorted((outputs_dir / "chat_reviews").rglob("labels_*_chat.json")):
+    chat_payloads = {
+        p
+        for pattern in ("labels__chat.json", "labels_.json")
+        for p in (outputs_dir / "chat_reviews").rglob(pattern)
+    }
+    for f in sorted(chat_payloads):
         payload = _load_json(f, default={})
         default_ts = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
         row = _usage_row_from_payload(payload, default_mode="timed_labels:chat", default_ts=default_ts)
         if row:
             rows.append(row)

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_dashboard_gen.py around lines 163 - 169, The loop that builds timed-chat usage only rglobs "labels__chat.json" and misses files named "labels_.json"; update the iteration over outputs_dir / "chat_reviews" to rglob for "labels_.json" (so it picks up both labels_.json and labels_*_chat.json), then continue to call _load_json(...) and _usage_row_from_payload(...) as before (ensure you deduplicate rows if you make multiple pattern searches). Change the pattern used in the for f in ... loop that references outputs_dir / "chat_reviews" and keep using _load_json and _usage_row_from_payload unchanged.



============================================================================
File: atlas_dashboard_gen.py
Line: 1087 to 1093
Type: potential_issue

Comment:
Don't double-count errored rows in top_reasons.

A non-ok row with error increments "error" and then increments its normalized reason again, so % of Non-OK can exceed 100% and the ranking stops being a true breakdown of failed/skipped episodes.


Suggested fix

         if err:
             errors += 1
-            reason_counts["error"] += 1
 
         if not is_ok:
-            norm_reason = _normalize_failure_reason(reason)
+            norm_reason = "error" if err and not reason else _normalize_failure_reason(reason)
             reason_counts[norm_reason] += 1
             recent.append(

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_dashboard_gen.py around lines 1087 - 1093, The code double-counts rows that have err=True because it always increments reason_counts["error"] and then, since such rows are also not is_ok, it also increments reason_counts[norm_reason]; change the logic so the normalized reason is incremented only for non-ok rows that are not errored — e.g., replace the second if with elif not is_ok: and keep the call to _normalize_failure_reason(reason) and reason_counts[norm_reason] += 1 so errored rows only contribute to "error" and non-error failures are bucketed by their normalized reason (variables involved: err, is_ok, reason_counts, _normalize_failure_reason, reason).



============================================================================
File: atlas_dashboard_gen.py
Line: 2127 to 2131
Type: potential_issue

Comment:
Escape HTML special characters in r.reason before inserting via innerHTML.

r.reason is inserted raw into the table HTML on line 14. If it contains HTML markup (e.g., , ), it will be executed in the dashboard instead of displayed as text. Replace the template literal ${(r.reason || "").toString()} with an escaped version using a helper function like:
function escapeHtml(str) {
  const map = { '&': '&amp;', '': '&gt;', '"': '&quot;', "'": '&#39;' };
  return (str || '').replace(/[&"']/g, c => map[c]);
}

Then use ${escapeHtml(r.reason)} in the template.

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_dashboard_gen.py around lines 2127 - 2131, Sanitize r.reason before injecting into the HTML template to prevent XSS: add an escapeHtml helper (mapping &  " ') and use it inside the template expression used by reasons.map instead of ${(r.reason || "").toString()} so the table row uses ${escapeHtml(r.reason)} (or escapeHtml(r.reason || '')) and leave other fields unchanged; ensure the helper is used wherever r.reason is rendered into innerHTML.



============================================================================
File: atlas_build_vertex_fewshot.py
Line: 196 to 212
Type: potential_issue

Comment:
Treat missing or unknown winners as FAIL.

If judge_result exists but winner is empty or not present in scores, this falls through to PASS. That will seed malformed compare outputs into the few-shot set as positive examples.


Suggested fix

 def _judge_label(judge: Dict[str, Any], pass_score_threshold: int) -> str:
     winner = str(judge.get("winner") or "").strip().lower()
     submit_safe = str(judge.get("submit_safe_solution") or "").strip().lower()
     scores = judge.get("scores", {})
@@
-    if winner == "none":
+    if not winner or winner == "none":
         return "FAIL"
+    if winner_score is None:
+        return "FAIL"
     if submit_safe and submit_safe != winner:
         return "FAIL"

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_build_vertex_fewshot.py around lines 196 - 212, In _judge_label, missing/unknown or non-scored winners can fall through to PASS; change logic so that if winner is empty/falsy or scores is not a dict or winner is not a key in scores (or yields no numeric score) the function returns "FAIL" instead of continuing, and only allow "PASS" when a valid numeric winner_score exists and meets pass_score_threshold; update checks around winner, scores, and winner_score accordingly while preserving the existing "none" and submit_safe comparisons.



============================================================================
File: .specify/scripts/powershell/update-agent-context.ps1
Line: 416 to 417
Type: potential_issue

Comment:
Return success for the generic no-op path.

The generic case only calls Write-Info, which outputs to the information stream without producing a pipeline return value. This causes Update-SpecificAgent to return $null, which Main interprets as failure (line 469: if (-not (Update-SpecificAgent -Type $AgentType))), causing the script to exit with code 1 even though the operation succeeded.


Suggested fix

-        'generic'  { Write-Info 'Generic agent: no predefined context file. Use the agent-specific update script for your agent.' }
+        'generic'  {
+            Write-Info 'Generic agent: no predefined context file. Use the agent-specific update script for your agent.'
+            return $true
+        }

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @.specify/scripts/powershell/update-agent-context.ps1 around lines 416 - 417, The 'generic' branch in Update-SpecificAgent only calls Write-Info and doesn't emit a pipeline boolean, causing callers (Main's if (-not (Update-SpecificAgent -Type $AgentType))) to treat it as failure; modify the 'generic' case in Update-SpecificAgent to explicitly return $true (after the Write-Info) so the no-op path signals success to Main and other callers.



============================================================================
File: atlas_web_auto_solver.py
Line: 8095 to 8101
Type: potential_issue

Comment:
This full-video-first fallback is currently dead code.

should_chunk can only be true when chunking_enabled is true, but full_video_first is computed from not chunking_enabled. That makes the branch impossible to enter, so run.segment_chunking_fallback_on_full_fail never does anything.



🔧 Proposed fix

-    full_video_first = not chunking_enabled and bool(
+    full_video_first = chunking_enabled and bool(
         _cfg_get(cfg, "run.segment_chunking_fallback_on_full_fail", True)
     )

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 8095 - 8101, The branch that sets full-video-first is unreachable because full_video_first is computed as not chunking_enabled while should_chunk is only true if chunking_enabled; change full_video_first to be based on chunking_enabled and the config flag instead (e.g., full_video_first = chunking_enabled and bool(_cfg_get(cfg, "run.segment_chunking_fallback_on_full_fail", True))) so the if full_video_first and should_chunk: block can be entered and the fallback behavior for run.segment_chunking_fallback_on_full_fail takes effect; update the expression around the symbols full_video_first, should_chunk, chunking_enabled, and _cfg_get accordingly.



============================================================================
File: atlas_web_auto_solver.py
Line: 11771 to 11782
Type: potential_issue

Comment:
This overlap clamp will crash on the first 2+ segment task.

segment_plan is a dict keyed by segment_index, so the first iteration looks up segment_plan[0]. That raises immediately for the normal 1-based plans returned by _normalize_segment_plan().



🔧 Proposed fix

                 segment_plan = _normalize_segment_plan(labels_payload, simulated_segments, cfg=cfg)
                 # Auto-clamp overlapping timestamps to prevent validation errors
                 if segment_plan:
-                    for _ci in range(1, len(segment_plan)):
-                        _prev = segment_plan[_ci - 1]
-                        _curr = segment_plan[_ci]
+                    ordered_indices = sorted(segment_plan)
+                    for prev_idx, curr_idx in zip(ordered_indices, ordered_indices[1:]):
+                        _prev = segment_plan[prev_idx]
+                        _curr = segment_plan[curr_idx]
                         _prev_end = float(_prev.get("end_sec", 0))
                         _curr_start = float(_curr.get("start_sec", 0))
                         if _curr_start

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 11771 - 11782, segment_plan returned by _normalize_segment_plan can be a dict keyed by segment_index (1-based), so the current numeric-index loop that accesses segment_plan[0] will KeyError; update the overlap-clamp to handle both list and dict shapes: detect if segment_plan is a dict and, if so, iterate over its sorted integer keys (e.g., sorted(map(int, segment_plan.keys()))) comparing each key to the previous key to read "end_sec" and "start_sec" and write the clamped "start_sec" back into segment_plan[key]; if segment_plan is a list, keep the existing index-based loop. Ensure you reference segment_plan and _normalize_segment_plan when locating the change.



============================================================================
File: atlas_web_auto_solver.py
Line: 10818 to 10822
Type: potential_issue

Comment:
Store the effective execution mode here, not just the CLI flag.

dry_run already reflects YAML + --execute, but run.execute only mirrors the flag. With run.dry_run: false and no --execute, the run performs real edits while helpers like _release_all_reserved_episodes() still think they're in dry-run and skip release/recovery actions.



🔧 Proposed fix

     dry_run = bool(_cfg_get(cfg, "run.dry_run", True))
     if execute:
         dry_run = False
-    cfg.setdefault("run", {})["execute"] = execute
+    cfg.setdefault("run", {})["execute"] = not dry_run
+    cfg["run"]["dry_run"] = dry_run

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 10818 - 10822, The code currently writes the CLI flag into cfg as cfg.setdefault("run", {})["execute"] = execute, but you must store the effective execution mode that combines YAML + flag (the dry_run variable). Change the assignment to write the computed mode (e.g., cfg.setdefault("run", {})["execute"] = not dry_run) or alternatively set cfg.setdefault("run", {})["dry_run"] = dry_run so helpers read the actual effective state; update references to use the same key if needed. Ensure you reference the dry_run local variable and keep the execute CLI variable unchanged.



============================================================================
File: atlas_web_auto_solver.py
Line: 9243 to 9249
Type: potential_issue

Comment:
Dry-run merge simulation is using the wrong side of the merge.

The rest of the file builds merge ops as “merge row N into N-1” (see the descending indices from _build_auto_continuity_merge_operations()), but this simulator merges N with N+1 whenever it can. That makes dry-run validation and exported artifacts disagree with execute mode.



🔧 Proposed fix

         if action == "delete":
             segs.pop(list_idx)
         elif action == "merge":
-            if list_idx + 1 = 0:
-                prev_seg = segs.pop(list_idx)
-                segs[list_idx - 1]["end_sec"] = prev_seg.get("end_sec", segs[list_idx - 1].get("end_sec"))
+            if list_idx - 1 >= 0:
+                current_seg = segs.pop(list_idx)
+                segs[list_idx - 1]["end_sec"] = current_seg.get(
+                    "end_sec",
+                    segs[list_idx - 1].get("end_sec"),
+                )

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 9243 - 9249, The dry-run merge branch currently merges a segment with its next neighbor (popping segs[list_idx + 1] and updating segs[list_idx]) which is the opposite of how real merges are built (they merge row N into N-1); update the "merge" case in the simulator so it merges the current row into the previous row: when action == "merge" pop the current segment (segs.pop(list_idx)) and set segs[list_idx - 1]["end_sec"] from the popped segment (using get(...) as in the existing code), ensuring you only do this when list_idx - 1 >= 0; this aligns the simulator with the behavior produced by _build_auto_continuity_merge_operations() and variables segs, list_idx, action.



============================================================================
File: atlas_web_auto_solver.py
Line: 788 to 799
Type: potential_issue

Comment:
Add file_uri → fileUri translation for Vertex requests.

_build_gcs_video_parts() and _build_files_api_video_parts() both emit file_data.file_uri, but _translate_payload_for_vertex() does not translate this key. In vertex_ai mode, the payload will be sent to Vertex API with snake_case file_uri, while the Vertex REST API expects camelCase fileUri. Video attachments via GCS or Files API will fail in vertex_ai mode.


🔧 Proposed fix

 def _translate_payload_for_vertex(value: Any) -> Any:
     if isinstance(value, dict):
         out: Dict[str, Any] = {}
         for key, item in value.items():
             mapped = key
             if key == "inline_data":
                 mapped = "inlineData"
             elif key == "file_data":
                 mapped = "fileData"
             elif key == "mime_type":
                 mapped = "mimeType"
+            elif key == "file_uri":
+                mapped = "fileUri"
             out[mapped] = _translate_payload_for_vertex(item)
         return out

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 788 - 799, The function _translate_payload_for_vertex currently maps inline_data→inlineData, file_data→fileData and mime_type→mimeType but misses translating file_uri; update _translate_payload_for_vertex to also map the key "file_uri" to "fileUri" (treat it alongside the other key mappings) so payloads emitted by _build_gcs_video_parts and _build_files_api_video_parts that use file_data.file_uri are converted to camelCase before sending to Vertex.



============================================================================
File: atlas_web_auto_solver.py
Line: 7202 to 7217
Type: potential_issue

Comment:
Pass explicit Vertex credentials to the GCS client.

When gemini.vertex_credentials_path is configured, storage.Client() still falls back to ADC (Application Default Credentials) and will fail silently if the environment has no ADC set up. This causes the GCS upload to fail and degrade to inline video attachment without warning.


🔧 Proposed fix

     try:
         from google.cloud import storage
+        from google.oauth2 import service_account
     except ImportError:
         raise RuntimeError("google-cloud-storage is not installed. Run: pip install google-cloud-storage")
             
     file_size_mb = vfile.stat().st_size / (1024 * 1024)
     import time
@@
-        client = storage.Client()
+        creds = service_account.Credentials.from_service_account_file(
+            _resolve_vertex_credentials_path(config)
+        )
+        client = storage.Client(
+            project=_resolve_vertex_project(config),
+            credentials=creds,
+        )
         bucket = client.bucket(bucket_name)
         blob = bucket.blob(blob_name)

Prompt for AI Agent:
Verify each finding against the current code and only fix it if needed.

In @atlas_web_auto_solver.py around lines 7202 - 7217, The GCS upload uses storage.Client() which falls back to ADC; when gemini.vertex_credentials_path is set you must load and pass explicit service account credentials to the client to avoid silent failures. Modify the upload block in atlas_web_auto_solver.py to: check gemini.vertex_credentials_path, load credentials via google.oauth2.service_account.Credentials.from_service_account_file (or appropriate loader) and call storage.Client(credentials=creds, project=...) instead of storage.Client(); keep the rest (bucket = client.bucket(bucket_name), blob = bucket.blob(blob_name), blob.upload_from_filename(str(vfile), content_type="video/mp4")) the same and ensure any ImportError handling for google.cloud and google.oauth2 imports is present.



Review completed: 39 findings ✔
