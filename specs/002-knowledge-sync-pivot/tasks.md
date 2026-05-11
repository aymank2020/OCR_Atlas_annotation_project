# Tasks: Knowledge Sync Pivot

**Input**: Design documents from `/specs/002-knowledge-sync-pivot/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create `tests/` directory if missing in `e:/OCR_annotation_Atlas/tests/`
- [x] T002 [P] Verify `google-cloud-aiplatform` and `discord.py` are installed in `.venv`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure for synchronization triggers

- [x] T003 [P] Extract sync logic (Vertex Cache, Git Push) from `atlas_discord_bot.py` into a reusable function in a new or existing utility file.
- [x] T004 Setup environment configuration for `COMMAND_CHANNEL_ID` in `.env`

---

## Phase 3: User Story 1 - Private Command Center (Priority: P1) 🎯 MVP

**Goal**: Refactor the bot to listen to a private channel and respond to authorized commands.

**Independent Test**: Use the DanaTimmer bot in a private server, paste a rule, and verify it triggers a sync.

### Implementation for User Story 1

- [x] T005 [P] [US1] Update `atlas_discord_bot.py` constructor to load `COMMAND_CHANNEL_ID` from environment.
- [x] T006 [US1] Refactor `on_message` in `atlas_discord_bot.py` to only process messages from the `COMMAND_CHANNEL_ID`.
- [x] T007 [US1] Implement command parsing for `rule:`, `correction:`, and `sync!` in `atlas_discord_bot.py`.
- [x] T008 [US1] Integrate the sync trigger into the command handlers.
- [x] T009 [US1] Add logging for successful knowledge ingestion from the command channel.

**Checkpoint**: User Story 1 (Dana Commander) should be functional in the private server.

---

## Phase 4: User Story 2 - Manual History Ingestion (Priority: P2)

**Goal**: Create a utility to ingest historical JSON exports from DiscordChatExporter.

**Independent Test**: Run `python atlas_knowledge_ingest.py --file sample.json` and verify `atlas_vertex_context_pack.txt` contains the new data without duplicates.

### Implementation for User Story 2

- [x] T010 [P] [US2] Create standalone CLI script `atlas_knowledge_ingest.py` at `e:/OCR_annotation_Atlas/atlas_knowledge_ingest.py`.
- [x] T011 [US2] Implement JSON parser for DiscordChatExporter format in `atlas_knowledge_ingest.py`.
- [x] T012 [US2] Implement ID-based deduplication against existing `prompts/atlas_vertex_context_pack.txt`.
- [x] T013 [US2] Add message formatting (Timestamp, Author, Content) for context pack consistency.
- [x] T014 [P] [US2] Create unit test `tests/test_ingest.py` for deduplication and parsing logic.

**Checkpoint**: Ingestion script is ready for batch processing.

---

## Phase 5: User Story 3 - The Perfect Automation Loop (Priority: P2)

**Goal**: Automate the export and ingestion on an 8-hour cycle.

- [ ] T015 [P] [US3] Create `atlas_auto_harvest.sh` orchestrator script.
- [ ] T016 [US3] Implement loop/sleep logic (28800 seconds) in the orchestrator.
- [ ] T017 [US3] Integrate `atlas-export` and `atlas_knowledge_ingest.py` into the shell script.
- [ ] T018 [US3] Add configuration for specific Channel IDs in the harvester.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T019 [P] Update `quickstart.md` in `specs/002-knowledge-sync-pivot/` with any final CLI flags.
- [x] T020 Final verification of `atlas_vertex_context_pack.txt` integrity after multiple ingestions.
- [x] T021 [P] Self-cleanup: Remove any old hardcoded channel IDs from `atlas_discord_bot.py`.

---

## Dependencies & Execution Order

- **Foundational (Phase 2)**: T003 is a prerequisite for US1 (T008).
- **US1 & US2**: Can be implemented in parallel after Phase 2.
- **Polish**: Final phase.
