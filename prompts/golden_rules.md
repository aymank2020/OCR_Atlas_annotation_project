# Atlas Annotation Golden Rules (Complete Spec-Kit)
# Source: Official Learning Hub (9 pages) + Discord Policy + QA Lead Corrections
# Last updated: 2026-04-24
# Discord harvest: 102,608 messages (March 27 - April 24, 2026)
# This file is the SINGLE SOURCE OF TRUTH for all annotation rules.

---

## 1. PROJECT OVERVIEW (Hub Page 1)
- This is a **human egocentric video annotation workflow**.
- Videos show humans completing physical tasks from **first-person (ego) perspective**.
- Tasks include: sewing, cleaning, gym equipment, etc.
- **Your Role**: Review text annotations (labels) segment-by-segment and correct when necessary.
- **Goal**: Ensure ego's main **actions**, **objects**, and **timestamps** are accurate.
- **Do NOT label** the ego's movement through a location (walking, navigating, etc.).

### Key Focus Areas
| ✅ Focus On | ❌ Don't Focus On |
|------------|------------------|
| Main Actions (primary task) | Movement Through Space (walking/navigation) |
| Hand Dexterity (meaningful hand-object interactions) | Idle Hand Gestures (unrelated to work) |

---

## 2. CORE MENTAL MODEL (Hub Page 3)
- **Episode**: A full video task.
- **Segment**: A continuous time span paired with one label.
- **A segment represents one continuous interaction with a primary object toward a single goal.**
- A segment begins when hands engage the primary object and ends when interaction is complete, hands disengage, or interaction focus/goal changes.
- **No hand contact → No Action** (default).

### What Requires a Label
- Goal-oriented hand-object actions that matter to the task.

### Do NOT Label (as actions)
- Walking / navigating through space
- Idle gestures
- Looking / visually examining (no "inspect", "check")
- Unrelated actions (e.g., adjusting camera, checking phone when not important to task)
- "Reach" (see Action Verb Rules)
- **Do not use numerical characters** (e.g., 1, 2, 5th, 10th). Use words ("three") or omit quantities.

---

## 3. LABEL FORMAT RULES (Hub Page 4)

### 3.1 Imperative Voice
- Write labels as commands: `pick up spoon`, `place box on table`

### 3.2 Consistency Within an Episode
- Use consistent verbs and nouns. If you choose "wash," don't alternate with "clean" without reason.

### 3.3 Action Separators
- When multiple actions are in one label, separate with **comma** or **and**:
  - ✅ `pick up cup, place cup on table`
  - ✅ `pick up cup and place cup on table`
  - ❌ `pick up cup place cup on table` (no separator = fail)

### 3.4 No Numerals
- ❌ `pick up 3 knives`
- ✅ `pick up three knives`
- ✅ `pick up knives`

### 3.5 No Intent-Only Language
- Don't add mental-state intent that isn't a physical action.
- Prefer the physical verb that occurred.
- ❌ "prepare to cut tape" → ✅ "pick up scissors", "cut tape"

---

## 4. DENSE VS. COARSE LABELS (Hub Page 5)

### 4.1 Segment Rule
- **A segment is either Dense OR Coarse — do not mix within a single segment.**

### 4.2 Video Rule
- A video may contain both dense and coarse segments.

### 4.3 When to Use
**Use coarse when:**
- A clear goal exists, AND
- Listing atomic steps risks errors/hallucination, OR
- The atomic steps are too many to list safely

**Use dense when:**
- Multiple distinct hand actions are required to be accurate (no single goal verb fits).

### 4.4 Important Notes
- **Latest segmenting update**: shorter segments are now the standard.
- Preferred density sweet spot is **2-5 seconds** and no segment should exceed **10 seconds**.
- **Dense-first is preferred** when the visible actions support it; use coarse only when it still preserves the visible interaction faithfully.
- Correct and refine existing auto-labels before rewriting from scratch.
- Label should contain no more than **~20 words** or **2 atomic actions**.
- Long labels increase hallucination risk.
- **Accuracy and completeness always take priority over label length.**

### 4.5 Pause Handling Update
- Within each kept segment, capture task-relevant actions and pauses.
- Do not ignore a meaningful pause/disengagement just to keep an older coarse segment.

---

## 5. ACTION VERB RULES (Hub Page 6)

### 5.1 Forbidden Verbs
- ❌ **inspect / check** — NEVER use these
- ❌ **reach** — Only if action is truncated at episode end AND no better verb exists
  - If "reach" feels necessary, timestamps are usually wrong. Fix timestamps instead.

### 5.2 Verb Definitions
| Verb | Meaning | Audit Notes |
|------|---------|-------------|
| **pick up** | Object leaves surface/container resting position | Required when using dense and a pickup occurred |
| **place** | Object contacts a surface and is released/positioned | Required when using dense and a placement occurred |
| **move** | Coarse relocation (pick up + place as one goal), OR repositioning without detailing steps | ✅ Allowed coarse substitute for "pick up and place" when relocation is the goal |
| **adjust** | Small corrective change in position/orientation | Use instead of inspect/check |
| **hold** | Maintain grip without relocating | Only if task-relevant |
| **grab** | Grip itself is meaningful | Rare; use sparingly |
| **loosen** | Turning/unfastening screws, bolts, connectors | Use instead of "remove" when using a tool to unfasten |
| **remove** | Physically detaching and taking away an object | Only for actual detachment, not turning |

### 5.3 "Move" Clarification
- `move mat to table` (coarse) ✅
- `move box onto shelf` (coarse) ✅
- If dense: `pick up mat, place mat on table` ✅

### 5.4 Attach Verbs to Objects
- Every verb MUST apply to an object.
- ❌ `pick up, place on table` → ✅ `pick up cup, place cup on table`

---

## 6. HOLD RULE (Hub Page 6 + Discord Shang + Clemmie)
- **Hold MUST be labeled in EVERY segment where ego is holding an object.**
- When the person is ONLY holding without another action: use `hold [object]` ONLY.
- **NEVER add intent/purpose** (e.g., "to check", "to inspect", "to verify").
- If the held object is already mentioned in another action → do NOT add separate hold.
- ✅ `hold cup, pick up cloth` (cup not in "pick up cloth")
- ✅ `wipe cup with cloth` (cup already in action)
- ❌ `hold cup, wipe cup with cloth` (cup redundant)
- ❌ `hold phone to check charging status` (intent added)
- ✅ `hold phone`

---

## 6.5 EDGE CASE HANDLING (Company Policy — 2026-03-27)
- **NEVER invent or guess** a specific object name if you cannot clearly see it.
- **NEVER use placeholder tags** like [UNCERTAIN], [UNKNOWN], or [OCCLUDED].
- **MUST fallback to broad categorical nouns (Hypernyms)**:
  | Unsure about... | Use | Examples |
  |-----------------|-----|---------|
  | Tool type | "tool" | "pick up tool" |
  | Part type | "part" or "component" | "remove part" |
  | Cable type | "cable" or "wire" | "disconnect cable" |
  | Container type | "container" | "place item in container" |
  | Completely unknown | "item" or "object" | "pick up item" |
- If object is 100% clearly visible -> use precise name ("Phillips screwdriver", "battery")
- If unclear (blur, occlusion, speed) -> use hypernym ("tool", "part", "device")

### 6.5.1 Examples
- Hand reaches for small metal object, unclear: "pick up part" (NOT "pick up M4 screw")
- Person grips cylindrical thing, blurry: "pick up tool" (NOT "pick up Phillips screwdriver")
- Ego holds something, camera angle bad: "hold item" (NOT "hold [UNCERTAIN] object")

---

## 7. NO ACTION & OBJECT RULES (Hub Page 7)

### 7.1 When to Use "No Action"
- Use **only** when: hands touch nothing, OR ego is idle/doing irrelevant behavior

### 7.2 No Action Rules
- **Do not split** solely to isolate "No Action" pauses.
- **Do not combine** "No Action" with real actions in a single label.
- **Do not use** "No Action" if ego is holding an object and that hold is task-relevant.

### 7.3 Object Naming
- **Identify only what you can defend**: if unsure, use general nouns ("tool", "container", "cloth").
- Incorrect object naming must be fixed (spoon vs fork, blue vs orange).
- **Consistency**: stay consistent in object naming through the episode.
- **Adjectives**: use only to disambiguate two similar items (e.g., "blue cloth" vs "white cloth").
  - If only one cloth exists: just `pick up cloth`
- **"Place" requires a location** (can be general): `place cup on table`, `place cup in bin`.
- **Left/Right**: allowed if accurate from ego view, but not required.
- **Body parts**: avoid referencing unless unavoidable. ✅ `wash spoon` not `wash spoon with hand`.

---

## 8. SEGMENT EDITING RULES (Hub Page 8)

### 8.1 Timestamps
- **Start**: when the action begins (hands begin engaging toward contact to cover the full interaction)
- **End**: when hands disengage and the interaction ends
- Minor idle time inside the segment is acceptable **if the segment still represents one continuous interaction**.

### 8.2 Extend / Shorten
- Don't extend into a new action.
- Don't cut off completion of the action.

### 8.3 Merge (when allowed)
- Merge adjacent segments ONLY if:
  - Same action/goal, AND
  - **Hands never disengage** between them.
- **Combined duration ≤ 10 seconds** (updated from 60s per March 27, 2026 rules).
- Tolerance: gaps ≤ 0.5s between segments count as continuous.
- Note: Even if same action continues without disengagement, split at 10 seconds.

### 8.4 Do NOT Merge
- Repeated pick up → place cycles with clear disengagement.
- Different objects or different goals.

### 8.5 Split (when required)
- Hands disengage and a new interaction begins, OR
- A new goal/action begins that must be labeled separately.
- **If segment exceeds 10 seconds**, split even if same action continues (March 27, 2026 rule).
- For split continuations of same action, use same label on both segments.
- Legacy: If a continuous action exceeds 60s, split and use `continue [verb] [object]`.

---

## 9. REPEATED ACTIONS & FINAL RULES (Hub Page 9)

### 9.1 Repeated Actions
- If ego **disengages and repeats**: they are **separate segments** (unless "move"/coarse goal covers a continuous relocation).
- If ego **never disengages**: it is **one segment** (often coarse).

### 9.2 Simultaneous Actions
- If multiple task-relevant actions happen in the same segment, include them either:
  - As a coarse goal label, OR
  - As dense enumerated actions
- ⚠️ **Do not invent steps.**

---

## 10. AUDIT FAIL CONDITIONS (Hub Page 9)
A segment FAILS audit if ANY of these are true:
1. Missed major task-relevant hand action
2. Hallucinated (non-occurring) action/object
3. Timestamps cut off the action or include a different action
4. Forbidden verbs used ("inspect/check", "reach" except truncated-end)
5. Dense/coarse mixed in one label
6. "No Action" combined with action

---

## 11. IDEAL SEGMENT CHECKLIST (Hub Page 9)
✅ One goal
✅ Full action coverage
✅ Accurate verbs
✅ No hallucinated steps
✅ Dense OR coarse (not mixed)
> **Remember**: Quality over quantity. A well-labeled segment accurately captures the main hand-object interaction from start to finish, using clear and consistent language.

---

## 12. MERGE RULE (Extended from Hub + QA, updated March 2026)
- Consecutive segments with IDENTICAL labels and combined duration ≤ 10s SHOULD be merged.
- Gaps ≤ 0.5s count as continuous.
- **New (March 27, 2026)**: Max merged duration is now 10 seconds (was 60s).
- If combined > 10s, split and give same labels to both segments.
- Legacy fallback: `continue [verb] [object]` for splits of very long continuous actions.

---

## 13. NO INTENT RULE (QA Lead + Discord 2026-03-29)
- Label ONLY observable physical actions — what the hands/body DO, not WHY.
- NEVER infer purpose, intent, mental state, or goals.
- ❌ "examine battery for damage" → ✅ "hold battery"
- ❌ "test connection by wiggling wire" → ✅ "wiggle wire"
- **NEVER use "to" to show ego's next intended action** (m.xssx, 2026-03-29):
  - ❌ "pick up shirt to fold" → ✅ "pick up shirt" then split → "fold shirt"
  - ❌ "dip knife in water to rinse" → ✅ "dip knife in water" then split → "rinse knife"
- Label every micro action separately instead of chaining intent.

---

## 13.5 LABEL FORMAT RULES (Discord 2026-03-27)
- **No articles**: Do not use "a", "the" in labels (austin._._0, 2026-03-27)
  - ❌ "Pull the pink mat" → ✅ "Pull pink mat"
- **No pronouns**: Never use "it" — always name the object explicitly (m.xssx, 2026-03-27)
- **Comma separator**: Separate actions with comma, NOT "and" (m.xssx, 2026-03-27)
  - ❌ "pick up book and place on table" → ✅ "pick up book, place book on table"
- **Label every action**: Do not summarize multiple actions into one (m.xssx, 2026-03-28)
- **Segment independence**: Each segment stands alone — next segment has no context of previous (2026-03-29)
- **Adjective/noun consistency**: Maintain consistent naming throughout the episode (austin._._0, 2026-03-29)

---

## 14. DISCORD-EXTRACTED LABELING RULES (2026-03-26)

### Hold Label Update (by Shang, 2026-03-26)
- Effective immediately: annotate "hold" on every segment where ego holds an object.
- Always label what you see — if holding something, it must be annotated.

### Hold Label Clarification (by Clemmie, 2026-03-26)
- Hold required in every segment where ego holds an object.
- Exception: if object already mentioned in another action in the same segment.
- Only add hold when the held object is NOT already captured in another action.

<!-- BEGIN_CANONICAL_DISCORD_SYNC -->
## Canonical Discord Rule Sync
- Synced at: 2026-04-24T16:30:00+00:00
- Discord scan window: 2026-03-27 -> 2026-04-24
- Text channels scanned: 4 (level-3-announcements, level-3-questions, atlas-announcements, faqs)
- Messages fetched: 102,608
- Admin rule messages: 490
- Canonical candidates extracted: 12
- Changed fields this run: 8

### Current Canonical Policy
- Canonical policy version: atlas-discord-cra-v2
- Maximum segment duration: 10 seconds (CONFIRMED active 2026-04-14 by sharingcaring).
- Preferred density sweet spot: 2.0-5.0 seconds.
- Maximum atomic actions per label: 2.
- Maximum label words: 20.
- Forbidden verbs: inspect, check, reach, examine.
- Forbidden narrative words: then, another, continue, next, again.
- Forbidden in labels: articles (a, the), pronoun "it", intent phrases with "to".
- Segment style preference: dense_first (strongly mandated since 2026-03-27).
- Correct existing labels before rewriting from scratch: yes.
- Label task-relevant pauses inside the kept segment: yes.
- No Action is standalone only and must not be used while a task-relevant object remains held.
- Place verb MUST include location preposition (on/in/into/onto/at/to).
- Hold required in every segment where held object is NOT referenced in another action.
- Each segment is independent: next segment has no context of previous segments.
- Split on ANY hand disengagement.
- Split when same action repeats beyond 10 seconds (even without disengagement).
- Coarse labeling only when segment is too short to split or action is continuous/repetitive.
- Do NOT mix dense and coarse within one label.

### Active Promoted Rules
- `engine_limits.max_segment_seconds`: Max segment 10 seconds | sentientcake #LEVEL3_ANNOUNCEMENT | 2026-03-27 | CONFIRMED 2026-04-14
- `annotation.preferred_density_sec`: Sweet spot 2-5 seconds | sentientcake #LEVEL3_ANNOUNCEMENT | 2026-03-27
- `annotation.max_atomic_actions`: Max 2 atomic actions per segment | sentientcake + m.xssx | 2026-03-27/28
- `annotation.dense_first_mandate`: Dense labeling is now strongly preferred | austin._._0 + m.xssx | 2026-03-27
- `annotation.hold_every_segment`: Hold required in every segment where object not in action | jujumu007 + _josephgreenwood | 2026-03-27/29
- `annotation.place_requires_location`: Place MUST include location, penalized otherwise | jujumu007 | 2026-03-31
- `annotation.no_intent_to`: Do not use "to" to show ego's next intended action | m.xssx | 2026-03-29
- `annotation.no_articles`: Do not use articles (a, the) in labels | austin._._0 | 2026-03-27
- `annotation.split_on_disengagement`: Split on any hand disengagement | austin._._0 | 2026-03-27
- `annotation.segment_independence`: Each segment is independent, no context from previous | _josephgreenwood | 2026-03-29
- `annotation.comma_separator`: Separate actions with comma, not "and" | m.xssx | 2026-03-27
- `annotation.label_all_actions`: Label every action, do not summarize | m.xssx | 2026-03-28

### Promoted Admin Clarifications (from level-3-questions)
- Hold exception: when pick up + place happen in ~1 second, can combine | _josephgreenwood | 2026-03-29
- Do not hold if object already accounted for in action | _josephgreenwood | multiple dates
- Hold not needed for non-task-relevant objects (e.g., desk ego leans on) | austin._._0 | 2026-03-27
- In coarse label, pick up and place are covered by the label | _josephgreenwood | 2026-03-28
- Hands on task-relevant object = NEVER "No Action" | _josephgreenwood | 2026-03-28
- Adding hold to coarse move = mixing dense/coarse (wrong) | m.xssx | 2026-03-27
- Even with no disengagement, split if segment > 10 seconds | m.xssx | 2026-03-28
- Repeated actions: split and give same labels | m.xssx | 2026-03-29
- Use consistent nouns/adjectives throughout episode | austin._._0 | 2026-03-29
- Never use "it" - always name the object | m.xssx | 2026-03-27
<!-- END_CANONICAL_DISCORD_SYNC -->
