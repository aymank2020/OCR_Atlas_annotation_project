# Implementation Plan: The AI Purifier (US4)

## Technical Architecture
We will enhance `atlas_knowledge_ingest.py` to include a new processing stage between *parsing* and *appending*.

### Component: AI Cleaning Stage
- **Input**: List of new `Message` objects.
- **Interface**: `gemini-3.1-pro-preview` via Vertex AI (using the `VERTEX_MODEL` env var).
- **Prompt**: A new system prompt stored in `prompts/purifier_system_prompt.txt`.

## Proposed Changes

### [NEW] prompts/purifier_system_prompt.txt
A detailed instruction set for Gemini to identify "Golden Rules" in chat logs. 
It will skip social talk and focus on annotation guidelines.

### [MODIFY] atlas_knowledge_ingest.py
- Add `--ai-clean` CLI flag.
- Implement `ai_purifier_step(messages: list)` function.
- Tokenize and batch large message sets to fit Gemini's context window (though 3.1 handles 1M+ tokens).
- Parse the AI response and append to context pack.

### [MODIFY] atlas_auto_harvest.sh
- Update the ingestion call to include the `--ai-clean` flag by default.

## Verification Plan

### Automated Tests
- Test valid extraction from mock Discord JSON containing both "chatter" and "rules".
- Verify error handling if the API returns 404 or 429.

### Manual Verification
- Run a harvest on the `LEVEL3QUESTION_CHANNEL` and verify the context pack receives distilled bullet points instead of a dump of IDs and names.
