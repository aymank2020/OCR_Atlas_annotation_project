# Feature Specification: The AI Purifier (US4)

Extract "Golden Rules" and actionable instructions from raw Discord harvesting data using Gemini 3.1 Pro.

## Context
The "Perfect Automation Loop" currently dumps raw Discord JSON into the context pack. This builds up noise. The "AI Purifier" acts as a filter that reads incoming messages and only appends refined, high-value instructions to the project's knowledge base.

## User Stories
- **US4**: As a Project Lead, I want my automation to "purify" Discord chats using AI so that my Bot and Solver only learn clear, valid rules instead of raw chatter.

## Functional Requirements
- **FR-007 (AI Extraction)**: The ingestor must send new messages to Gemini 3.1 Pro for processing.
- **FR-008 (Prompting)**: Use a specialized "Purifier System Prompt" that identifies:
  - New labeling rules/conventions.
  - Corrections from trainers.
  - Best practices noted by senior annotators.
- **FR-009 (Format)**: The result must be clean bullet points in the `atlas_vertex_context_pack.txt` format.
- **FR-010 (Deduplication)**: AI-generated points should still be checked for semantic duplication.

## Acceptance Criteria
1. Running `atlas_knowledge_ingest.py` with `--ai-clean` triggers an AI processing step.
2. Raw chatter (e.g., "Hello", "How are you?") is ignored by the AI.
3. Precise rules (e.g., "Always label the left side first") are extracted and appended.
4. The output matches the existing context pack structure.
