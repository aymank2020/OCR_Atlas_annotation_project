# Tasks: The AI Purifier (US4)

- [ ] **Phase 1: Foundation & Prompting**
  - [ ] Create `prompts/purifier_system_prompt.txt` with expert annotation extraction rules.
  - [ ] Verify `VERTEX_MODEL` is correctly loaded in `vertex_create_cache.py`.

- [ ] **Phase 2: Ingestor Upgrade**
  - [ ] Add `ai_clean` logic to `atlas_knowledge_ingest.py`.
  - [ ] Implement Vertex AI SDK call within the ingestor.
  - [ ] Add logic to parse structured AI output.

- [ ] **Phase 3: Loop Integration**
  - [ ] Update `atlas_auto_harvest.sh` to use `--ai-clean`.
  - [ ] Run a full cycle test on the VPS.

- [ ] **Phase 4: Verification**
  - [ ] Verify `prompts/atlas_vertex_context_pack.txt` contains purified rules.
  - [ ] Verify Vertex Context Cache is updated with the new distilled knowledge.
