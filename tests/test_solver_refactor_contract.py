import json
from pathlib import Path
from types import SimpleNamespace

import atlas_web_auto_solver as solver
from package_for_colab import build_colab_file_list
from src.solver import cli


def test_solver_shim_exports_compatibility_symbols():
    required = [
        "_SCRIPT_BUILD",
        "DEFAULT_CONFIG",
        "_load_selectors_yaml",
        "_selector_variants",
        "_allowed_label_start_verb_token_patterns_from_cfg",
        "_apply_consistency_aliases_to_label",
        "_autofix_label_candidate",
        "_build_auto_continuity_merge_operations",
        "_count_atomic_actions_in_label",
        "_find_equivalent_canonical_term",
        "_label_starts_with_allowed_action_verb",
        "_normalize_operations",
        "_normalize_upload_chunk_size",
        "_rewrite_label_tier3",
        "_update_chunk_consistency_memory",
        "_validate_segment_plan_against_policy",
        "build_prompt",
        "call_gemini_labels",
        "extract_segments",
        "apply_labels",
        "load_config",
        "run",
        "parse_args",
        "main",
    ]
    for name in required:
        assert hasattr(solver, name), f"Missing shim export: {name}"


def test_solver_cli_uses_production_colab_config(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: SimpleNamespace(
            config="configs/production_colab.yaml",
            execute=False,
            max_episodes=0,
            dry_run=False,
            gemini_model="",
            use_fallback_key=False,
        ),
    )
    monkeypatch.setattr(cli, "_apply_cli_overrides", lambda cfg, args: captured.setdefault("cfg", cfg))
    monkeypatch.setattr(cli, "run", lambda cfg, execute: captured.update({"cfg": cfg, "execute": execute}))

    cli.main()

    assert captured["execute"] is False
    assert captured["cfg"]["browser"]["headless"] is True


def test_apply_cli_overrides_disables_recycle_for_one_shot_runs():
    cfg = {"run": {"recycle_after_max_episodes": True}, "gemini": {}}
    args = SimpleNamespace(
        max_episodes=1,
        gemini_model="",
        use_fallback_key=False,
    )

    cli._apply_cli_overrides(cfg, args)

    assert cfg["run"]["max_episodes_per_run"] == 1
    assert cfg["run"]["recycle_after_max_episodes"] is False


def test_colab_notebook_targets_main_and_production_config():
    notebook = json.loads(Path("Atlas_Colab_Runner.ipynb").read_text(encoding="utf-8"))
    notebook_text = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
    )
    assert "origin/main" in notebook_text
    assert "configs/production_colab.yaml" in notebook_text
    assert "Atlas_Project_Colab.zip" in notebook_text


def test_colab_package_includes_refactor_targets():
    root = Path(__file__).resolve().parents[1]
    packaged = {path.relative_to(root).as_posix() for path in build_colab_file_list(root)}

    assert "Atlas_Colab_Runner.ipynb" in packaged
    assert "configs/production_colab.yaml" in packaged
    assert "src/infra/runtime.py" in packaged
    assert "src/solver/cli.py" in packaged
    assert "src/solver/legacy_impl.py" in packaged
    assert "src/rules/labels.py" in packaged
