# Feature Specification: Zero Budget Optimizer

**Feature Branch**: `005-zero-budget`  
**Created**: 2026-04-01  
**Status**: Draft  
**Input**: User description: "Zero Budget Operations architecture focusing on local pre-filtering, token difference payloads, and stealth VPS processes."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cost-Optimized Discord Extraction (Priority: P1)

As the Atlas system owner, I want the Discord scraping logic to pre-filter messages locally (using regex) and deduplicate rules into a local `rules_db.json`, so that I don't waste paid API tokens having Gemini process duplicate or noise messages.

**Why this priority**: Discord can output thousands of irrelevant messages or duplicate rules. Sending these to an LLM every cycle completely ruins the "zero budget" goal. Local filtering has $0 cost.

**Independent Test**: Can be fully tested by parsing a massive raw Discord `.json` dump and verifying that only semantically unique rules matching specific regex patterns are extracted and saved to `rules_db.json`, without any network calls.

**Acceptance Scenarios**:

1. **Given** a new batch of Discord messages, **When** the scraper runs, **Then** it selectively polls only messages newer than the last fetched timestamp.
2. **Given** the fetched messages, **When** attempting extraction, **Then** Python regex pre-filters messages looking for rule signatures before storage.
3. **Given** a valid rule message, **When** saving to DB, **Then** it deduplicates against `rules_db.json` and only saves if it represents a novel instruction.

---

### User Story 2 - Token Difference Optimization (Priority: P2)

As an AI architect, I want the Gemini prompt builder to use a "Difference-Only" payload logic, so that it only sends new or relevant rules rather than the entire 9,000-line context pack for every video.

**Why this priority**: Prompts that send massive context windows for every single short video scale costs linearly. Delta/Difference-Only prompts drastically slash token usage.

**Independent Test**: Can be tested by verifying the payload size of the request sent to Gemini. Success occurs if only rules matching the current label context are sent, rather than the entire `rules_db.json`.

**Acceptance Scenarios**:

1. **Given** a generated prompt context, **When** preparing the Gemini request, **Then** only the differences/updates to the project rules are appended dynamically based on the current label content, minimizing tokens.

---

### User Story 3 - Stealth & VPS Persistence (Priority: P3)

As a DevOps engineer, I want the browser automation to run in "Visible-on-Windows" mode with an active heartbeat watchdog, so that Discord/Atlas doesn't block the automated browser and the VPS process survives inevitable memory leaks or hangs.

**Why this priority**: Ensuring extreme uptime on a low-cost VPS and avoiding bot-detection algorithms.

**Independent Test**: Can be tested by forcing an artificial memory hang/throttle and verifying the watchdog cleanly restarts the execution loop, and verifying Playwright runs without `--headless` in a virtual frame buffer.

**Acceptance Scenarios**:

1. **Given** a running browser automation instance, **When** Discord attempts bot detection, **Then** the browser responds as a visible head (Headless-to-Visible toggle enabled).
2. **Given** a script stuck on a network request, **When** the heartbeat threshold is passed, **Then** the watchdog process forcefully restarts the scraping pipeline safely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST implement incremental fetching from Discord, checking only for new messages since the last successful sync.
- **FR-002**: System MUST use local Python Regex to parse "Golden Rule" patterns before considering AI intervention.
- **FR-003**: System MUST maintain a local `rules_db.json` and deduplicate incoming rules against it.
- **FR-004**: System MUST inject only contextually relevant rules (Difference-Only) into Gemini rather than the entire static context.
- **FR-005**: System MUST configure Playwright to run in a visible state (Headless=False) while executing on the headless VPS (e.g. via XVFB or Windows equivalent).
- **FR-006**: System MUST implement a Process Watchdog that monitors activity timestamps and forcefully recovers hung components.

### Key Entities

- **`DiscordMessage`**: A raw payload from Discord containing text, user, and timestamp data.
- **`GoldenRule`**: A deduplicated, regex-validated annotation instruction stored in `rules_db.json`.
- **`DiffPayload`**: The optimized, subset token prompt sent to Gemini.
- **`WatchdogState`**: The tracking state containing the last successful heartbeat timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: API costs for rule extraction and routing are reduced to $0.00 by utilizing 100% local Discord filtering.
- **SC-002**: Prompt tokens sent per Gemini request are reduced by >50% compared to full-context injections.
- **SC-003**: The pipeline achieves 99.9% uptime on a 1-core VPS, automatically resolving 100% of induced process hangs within 10 minutes without manual intervention.
- **SC-004**: Browser automation successfully evades standard bot detection through accurate visible-mimicry emulation.
