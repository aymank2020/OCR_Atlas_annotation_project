import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# Add project root to path to allow absolute imports from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    from src.sync import sync_utils as atlas_sync_utils
except ImportError:
    atlas_sync_utils = None

try:
    from src.policy import context_manager as policy_context
except ImportError:
    policy_context = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Load config from root .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)


def _require_genai():
    if genai is None or types is None:
        raise RuntimeError("google-genai module not found! Run: pip install google-genai")


def _build_genai_client(api_key: str):
    _require_genai()
    return genai.Client(api_key=api_key)


def _response_text(response) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    if not text:
        return ""
    return str(text).strip()


def load_system_prompt(prompt_path: str) -> str:
    """Load the purifier system instruction from a text file."""
    path = Path(prompt_path)
    if not path.exists():
        logger.error("Purifier prompt not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def extract_native_rules(raw_text: str) -> str:
    """
    Extracts high-confidence rules locally using Regex.
    Cost: $0
    """
    patterns = [
        r"Golden Rule:\s*(.*?)(?:\n\[|$)",
        r"New Rule:\s*(.*?)(?:\n\[|$)",
        r"(?i)update:\s*(.*?)(?:\n\[|$)",
        r"(?i)forbidden:\s*(.*?)(?:\n\[|$)",
    ]
    extracted = []
    for pattern in patterns:
        matches = re.finditer(pattern, raw_text)
        for match in matches:
            value = match.group(1).strip()
            if value and len(value) > 15:
                extracted.append(f"- {value}")

    if extracted:
        return "NATIVE_EXTRACTION:\n" + "\n".join(extracted)
    return ""


def purify_messages_from_text(raw_text: str, model_id: str, system_prompt: str) -> str:
    """
    Send raw chat log text to Gemini for knowledge extraction.
    Uses an API key fallback loop (Primary -> Fallback -> Secondary).
    """
    _require_genai()
    if not raw_text.strip():
        return ""

    logger.info("Purifying text content using %s...", model_id)

    keys_list = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_FALLBACK"),
        os.environ.get("GEMINI_API_KEY_SECONDARY"),
    ]
    api_keys = [key.strip() for key in keys_list if key and key.strip()]

    if not api_keys:
        logger.error("No GEMINI_API_KEY values found in .env.")
        return ""

    current_date = datetime.now().strftime("%Y-%m-%d")
    sys_instructions = system_prompt.replace("[CURRENT_DATE]", current_date)

    import time

    max_retries = 3
    retry_wait = 60

    for attempt in range(max_retries):
        for index, api_key in enumerate(api_keys, start=1):
            try:
                logger.info("Trying API key #%s (attempt %s/%s)...", index, attempt + 1, max_retries)
                client = _build_genai_client(api_key)
                response = client.models.generate_content(
                    model=model_id,
                    contents=f"Extract Golden Rules from the following chat log:\n\n{raw_text}",
                    config=types.GenerateContentConfig(
                        system_instruction=sys_instructions,
                        temperature=0.1,
                    ),
                )

                result = _response_text(response)
                if not result:
                    logger.warning("Empty Gemini response on API key #%s.", index)
                    continue

                if result.upper() == "NONE" or "NONE" in result.split("\n")[0]:
                    return ""

                return result
            except Exception as exc:
                error_msg = str(exc)
                if "429" in error_msg or "Quota" in error_msg or "exhausted" in error_msg.lower():
                    logger.warning("API key #%s exceeded its quota (429).", index)
                    continue
                logger.error("AI purification failed on key #%s: %s", index, exc)
                continue

        if attempt < max_retries - 1:
            logger.warning(
                "All available API keys are exhausted. Waiting %ss before retry...",
                retry_wait,
            )
            time.sleep(retry_wait)
        else:
            logger.error("All available API keys failed or exceeded their quotas after multiple retries.")
            return ""

    return ""


def audit_rules_with_pro(combined_rules: str, system_prompt: str) -> str:
    """
    Final stage: Pass all concatenated raw rules to Gemini 3.1 Pro for de-duplication,
    quality assessment, and professional formatting.
    """
    _require_genai()
    logger.info("Initiating Stage 2: Quality Audit by gemini-3.1-pro-preview...")

    _ = system_prompt
    keys_list = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_FALLBACK"),
        os.environ.get("GEMINI_API_KEY_SECONDARY"),
    ]
    api_keys = [key.strip() for key in keys_list if key and key.strip()]
    if not api_keys:
        return combined_rules

    audit_prompt = f"""
    You are the Senior Quality Architect for the Atlas Annotation Project.
    Below is a compiled list of "Golden Rules" and updates extracted from a massive Discord chat history by an initial AI pass.

    Your task:
    1. DE-DUPLICATE the rules. Remove redundancies.
    2. REWRITE them into a clean, highly professional, bulleted Markdown manifesto.
    3. Categorize them logically (e.g., General, Tools, Forbidden Actions).
    4. Provide your "Architect's Opinion" at the very top on the quality of these updates.

    Raw Extracted Rules:
    {combined_rules}
    """

    import time

    for _attempt in range(2):
        for index, api_key in enumerate(api_keys, start=1):
            try:
                client = _build_genai_client(api_key)
                response = client.models.generate_content(
                    model="gemini-3.1-pro-preview",
                    contents=audit_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction="You are Atlas Senior Architect.",
                        temperature=0.2,
                    ),
                )
                result = _response_text(response)
                if result:
                    return result
                logger.warning("Audit returned empty text on auth key #%s.", index)
            except Exception as exc:
                logger.warning("Audit failed on auth key #%s: %s", index, exc)
        time.sleep(15)

    logger.error("High-level audit failed. Reverting to raw rules.")
    return combined_rules


def load_processed_files(state_path: Path) -> set:
    """Load the set of already processed file paths to avoid duplicate work."""
    if state_path.exists():
        try:
            return set(json.loads(state_path.read_text()))
        except Exception:
            pass
    return set()


def save_processed_files(state_path: Path, processed: set):
    """Save the set of processed file paths to the state tracker."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(list(processed), indent=2))


def main():
    """
    Main entry point for AI Purification.
    Discovers JSON exports, extracts knowledge using Gemini, and syncs results.
    """
    parser = argparse.ArgumentParser(description="Atlas Knowledge Builder (AI Purifier)")
    parser.add_argument("--file", help="Path to single Discord JSON export")
    parser.add_argument("--dir", default="discord", help="Directory to search for new Discord JSON exports")
    parser.add_argument("--sync", action="store_true", help="Trigger Git/Vertex sync after ingestion")
    args = parser.parse_args()

    try:
        _require_genai()
    except RuntimeError as exc:
        logger.error("Missing Gemini SDK: %s", exc)
        return

    model_id = os.getenv("PURIFIER_MODEL", "gemini-1.5-flash")
    logger.info("Selected bulk purifier model: %s", model_id)

    context_pack_path = Path("prompts/atlas_vertex_context_pack.txt")
    system_prompt_path = "prompts/purifier_system_prompt.txt"
    state_path = Path("data/processed_files.json")

    system_prompt = load_system_prompt(system_prompt_path)
    if not system_prompt:
        return

    processed_files = load_processed_files(state_path)

    files_to_process = []
    if args.file:
        files_to_process.append(Path(args.file))
    elif Path(args.dir).exists():
        files_to_process = list(Path(args.dir).rglob("*.json"))

    new_files = [path for path in files_to_process if str(path.resolve()) not in processed_files]

    if not new_files:
        logger.info("No new files to process.")
        return

    total_purified_rules = []

    for export_path in new_files:
        logger.info("Processing %s...", export_path)
        try:
            with open(export_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            if isinstance(data, list):
                messages = data
            else:
                messages = data.get("messages", [])

            if policy_context and messages:
                policy_report = policy_context.ingest_message_entries(messages)
                promoted = len(policy_report.get("changed_fields", []))
                if promoted:
                    logger.info("[policy] Promoted %s canonical rule updates from %s.", promoted, export_path.name)

            batch_size = 2000
            total_messages = len(messages)

            logger.info("Dividing %s messages into batches of %s...", total_messages, batch_size)

            for offset in range(0, total_messages, batch_size):
                batch = messages[offset:offset + batch_size]
                batch_num = (offset // batch_size) + 1
                total_batches = (total_messages + batch_size - 1) // batch_size
                progress_pct = (batch_num / total_batches) * 100

                logger.info(
                    "[Batch %s/%s] Processing %s messages (%.1f%% complete)...",
                    batch_num,
                    total_batches,
                    len(batch),
                    progress_pct,
                )

                def get_author_name(message):
                    author = message.get("author", {})
                    return author.get("username") or author.get("name") or "User"

                raw_text = "\n".join(
                    [
                        f"[{message.get('id', '')}] {get_author_name(message)}: {message.get('content', '')}"
                        for message in batch
                        if message.get("content")
                    ]
                )

                if not raw_text.strip():
                    continue

                long_messages = sum(
                    1
                    for message in batch
                    if isinstance(message.get("content"), str) and len(message.get("content", "")) > 40
                )
                if long_messages < 5:
                    logger.info(
                        "Skipping batch %s (casual chat detected: only %s long messages).",
                        batch_num,
                        long_messages,
                    )
                    continue

                native_rules = extract_native_rules(raw_text)
                if native_rules:
                    logger.info("Zero-budget regex caught rules in batch %s. Skipping Gemini.", batch_num)
                    total_purified_rules.append(native_rules)
                    continue

                rules = purify_messages_from_text(raw_text, model_id, system_prompt)
                if rules:
                    logger.info(
                        "AI rules found in batch %s. Total rule sets collected: %s",
                        batch_num,
                        len(total_purified_rules) + 1,
                    )
                    total_purified_rules.append(rules)
                else:
                    logger.info("No new rules in batch %s. Continuing...", batch_num)

                if batch_num < total_batches:
                    import time

                    time.sleep(3)

            processed_files.add(str(export_path.resolve()))
        except Exception as exc:
            logger.error("Failed to process %s: %s", export_path, exc)

    if total_purified_rules:
        logger.info("Extracted raw knowledge from %s batches.", len(total_purified_rules))
        combined_rules = "\n\n".join(total_purified_rules)
        audited_rules = audit_rules_with_pro(combined_rules, system_prompt)

        with open(context_pack_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n\n# --- AI Ingested Rules (Audited) ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ---\n")
            handle.write(audited_rules + "\n")

        save_processed_files(state_path, processed_files)
        logger.info("Successfully appended to %s", context_pack_path)
    else:
        logger.info("No new rules extracted. Marked files as processed.")
        save_processed_files(state_path, processed_files)

    if args.sync and total_purified_rules:
        logger.info("Triggering project-wide synchronization...")
        if atlas_sync_utils is not None:
            import asyncio

            project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
            asyncio.run(
                atlas_sync_utils.trigger_full_sync(
                    config_path="sample_web_auto_solver_production.yaml",
                    vertex_prompt_id="7380211766946430976",
                    vertex_project=project,
                )
            )
        else:
            logger.warning("atlas_sync_utils not found, unable to trigger sync automatically.")


if __name__ == "__main__":
    main()
