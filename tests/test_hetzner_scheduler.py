from pathlib import Path
import json
import os
import signal

import pytest
import yaml

from src.infra import solver_config, utils
from src.solver import account_scheduler, browser, gemini, legacy_impl, segments


def test_shared_utils_are_single_source_for_legacy_helpers():
    assert legacy_impl._safe_float is utils._safe_float
    assert legacy_impl._normalize_label_for_compare is utils._normalize_label_for_compare
    assert solver_config.DEFAULT_CONFIG is legacy_impl.DEFAULT_CONFIG
    assert legacy_impl._load_selectors_yaml is solver_config._load_selectors_yaml
    assert legacy_impl._deep_merge is solver_config._deep_merge
    assert legacy_impl._cfg_get is solver_config._cfg_get
    assert utils._safe_float("3.25") == 3.25
    assert utils._safe_float("bad", 7.0) == 7.0
    assert utils._normalize_label_for_compare("  Place   Cup On Table  ") == "place cup on table"


def test_gemini_key_pool_uses_config_then_pool_then_legacy_envs(monkeypatch):
    for env_name in [
        "GEMINI_API_KEYS_PAID_POOL",
        "GEMINI_API_KEYS_POOL",
        "GEMINI_API_KEY_PAID_EPISODE_EVAL",
        "GEMINI_API_KEY_PAID_SECONDARY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY2",
        "GEMINI_API_KEY_FALLBACK",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEY_FALLBACK",
        "GEMINI_API_KEY_SECONDARY",
        "GOOGLE_API_KEY_SECONDARY",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS_PAID_POOL", "paid-a,paid-b")
    monkeypatch.setenv("GEMINI_API_KEY", "env-primary")
    monkeypatch.setenv("GEMINI_API_KEY_FALLBACK", "env-fallback")
    monkeypatch.setenv("GEMINI_API_KEY_PAID_EPISODE_EVAL", "paid-primary")
    monkeypatch.setenv("GEMINI_API_KEY_PAID_SECONDARY", "paid-secondary")

    pool = solver_config.GeminiKeyPool(
        explicit_key="explicit-primary",
        fallback_key="explicit-fallback",
        dotenv={"GEMINI_API_KEYS_POOL": "legacy-pool-a,legacy-pool-b"},
        cfg_api_keys=["cfg-a", "cfg-b", "paid-a"],
        rotation_policy="round_robin",
    )

    assert pool.keys == [
        "cfg-a",
        "cfg-b",
        "paid-a",
        "paid-b",
        "legacy-pool-a",
        "legacy-pool-b",
        "explicit-primary",
        "explicit-fallback",
        "paid-primary",
        "paid-secondary",
        "env-primary",
        "env-fallback",
    ]
    assert pool.begin_request() == "cfg-a"
    assert pool.begin_request() == "cfg-b"
    assert pool.switch_to_next() is True
    assert pool.get_current_key() == "paid-a"


def test_gemini_key_pool_prioritized_key_is_used_first_in_round_robin():
    pool = solver_config.GeminiKeyPool(
        explicit_key="primary-key",
        fallback_key="paid-key",
        dotenv={},
        cfg_api_keys=["free-key-1", "free-key-2"],
        rotation_policy="round_robin",
    )

    pool.prioritize_key("paid-key")

    assert pool.begin_request() == "paid-key"
    assert pool.begin_request() == "free-key-1"


def test_gemini_key_pool_skips_temporarily_unavailable_keys_in_round_robin():
    pool = solver_config.GeminiKeyPool(
        explicit_key="primary-key",
        fallback_key="fallback-key",
        dotenv={},
        cfg_api_keys=["cfg-a", "cfg-b"],
        rotation_policy="round_robin",
    )

    assert pool.begin_request() == "cfg-a"
    pool.mark_key_temporarily_unavailable("cfg-b", 60.0)

    assert pool.begin_request() != "cfg-b"
    assert pool.is_key_temporarily_unavailable("cfg-b") is True


def test_build_runner_env_can_override_paid_episode_eval_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ops-key")
    monkeypatch.setenv("GEMINI_API_KEY_FALLBACK", "ops-fallback")
    monkeypatch.setenv("GEMINI_API_KEYS_POOL", "ops-a,ops-b")
    monkeypatch.setenv("GEMINI_API_KEYS_PAID_POOL", "paid-a,paid-b")
    monkeypatch.setenv("GEMINI_API_KEY_PAID_EPISODE_EVAL", "paid-primary")
    monkeypatch.setenv("GEMINI_API_KEY_PAID_SECONDARY", "paid-secondary")

    env = account_scheduler.build_runner_env(
        {
            "runner": {
                "env_map": {
                    "GEMINI_API_KEY": "GEMINI_API_KEY_PAID_EPISODE_EVAL",
                    "GOOGLE_API_KEY": "GEMINI_API_KEY_PAID_EPISODE_EVAL",
                    "GEMINI_API_KEY_FALLBACK": "GEMINI_API_KEY_PAID_SECONDARY",
                    "GOOGLE_API_KEY_FALLBACK": "GEMINI_API_KEY_PAID_SECONDARY",
                    "GEMINI_API_KEYS_POOL": "GEMINI_API_KEYS_PAID_POOL",
                }
            }
        }
    )

    assert env["GEMINI_API_KEY"] == "paid-primary"
    assert env["GOOGLE_API_KEY"] == "paid-primary"
    assert env["GEMINI_API_KEY_FALLBACK"] == "paid-secondary"
    assert env["GOOGLE_API_KEY_FALLBACK"] == "paid-secondary"
    assert env["GEMINI_API_KEYS_POOL"] == "paid-a,paid-b"


def test_danatimer_account_pins_free_pool_to_fallback2(monkeypatch):
    for key, value in {
        "GEMINI_API_KEYS_FREE_POOL": "bad-a,bad-b,bad-c,bad-d",
        "GEMINI_API_KEY_FREE_OPS": "bad-a",
        "GEMINI_API_KEY2_FREE_OPS2": "bad-b",
        "GEMINI_API_KEY_FREE_FALLBACK": "bad-c",
        "GEMINI_API_KEY_FREE_FALLBACK2": "good-key",
        "GEMINI_API_KEY_OPS": "bad-ops",
    }.items():
        monkeypatch.setenv(key, value)

    repo_root = Path(__file__).resolve().parents[1]
    account_cfg = account_scheduler.load_config(repo_root / "configs" / "accounts" / "danatimer.yaml")
    env = account_scheduler.build_runner_env(account_cfg)

    assert env["GEMINI_API_KEY"] == "good-key"
    assert env["GOOGLE_API_KEY"] == "good-key"
    assert env["GEMINI_API_KEY_FALLBACK"] == "good-key"
    assert env["GOOGLE_API_KEY_FALLBACK"] == "good-key"
    assert env["GEMINI_API_KEY_SECONDARY"] == "good-key"
    assert env["GEMINI_API_KEYS_POOL"] == "good-key"
    assert env["GEMINI_API_KEYS_FREE_POOL"] == "good-key"
    assert env["GEMINI_API_KEY_FREE_OPS"] == "good-key"
    assert env["GEMINI_API_KEY2_FREE_OPS2"] == "good-key"
    assert env["GEMINI_API_KEY_FREE_FALLBACK"] == "good-key"
    assert env["GEMINI_API_KEY_OPS"] == "good-key"


def test_build_runner_env_can_clear_ops_keys_before_episode_eval_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ops-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "ops-key")
    monkeypatch.delenv("GEMINI_API_KEY_EPISODE_EVAL", raising=False)

    env = account_scheduler.build_runner_env(
        {
            "runner": {
                "env_clear": [
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                    "GEMINI_API_KEY_FALLBACK",
                    "GOOGLE_API_KEY_FALLBACK",
                    "GEMINI_API_KEYS_POOL",
                ],
                "env_map": {
                    "GEMINI_API_KEY": "GEMINI_API_KEY_EPISODE_EVAL",
                    "GOOGLE_API_KEY": "GEMINI_API_KEY_EPISODE_EVAL",
                },
            }
        }
    )

    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env


def test_load_project_env_reads_dotenv_without_overwriting_existing(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "ATLAS_LOGIN_EMAIL1=dotenv-user@example.com",
                "KEEP_ME=from-dotenv",
                'QUOTED_VALUE="quoted-secret"',
            ]
        ),
        encoding="utf-8",
    )

    env = account_scheduler._load_project_env(
        tmp_path,
        base_env={"KEEP_ME": "from-env", "ALREADY_SET": "yes"},
    )

    assert env["ATLAS_LOGIN_EMAIL1"] == "dotenv-user@example.com"
    assert env["QUOTED_VALUE"] == "quoted-secret"
    assert env["KEEP_ME"] == "from-env"
    assert env["ALREADY_SET"] == "yes"


def test_run_account_process_returns_124_on_timeout(monkeypatch, tmp_path: Path):
    class _FakeProc:
        def __init__(self, *args, **kwargs):
            self.pid = 4321
            self.wait_calls = 0
            self.sent_signals = []

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise account_scheduler.subprocess.TimeoutExpired(cmd=["py"], timeout=42)
            return 0

        def poll(self):
            return None if self.wait_calls < 2 else 0

        def send_signal(self, sig):
            self.sent_signals.append(sig)

    sent = []
    monkeypatch.setattr(account_scheduler.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(account_scheduler.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(account_scheduler.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)), raising=False)

    exit_code = account_scheduler.run_account_process(
        repo_root=tmp_path,
        account_name="danatimer",
        generated_cfg_path=tmp_path / "generated.yaml",
        env={},
        execute=False,
        timeout_sec=42,
    )

    assert exit_code == 124
    assert sent == [(4321, signal.SIGINT)]


def test_run_account_process_interrupt_cleans_child_process_group(monkeypatch, tmp_path: Path):
    class _FakeProc:
        def __init__(self, *args, **kwargs):
            self.pid = 9876
            self.wait_calls = 0
            self.sent_signals = []

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise KeyboardInterrupt()
            return 130

        def poll(self):
            return None if self.wait_calls < 2 else 130

        def send_signal(self, sig):
            self.sent_signals.append(sig)

    sent = []
    monkeypatch.setattr(account_scheduler.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(account_scheduler.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(account_scheduler.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)), raising=False)

    with pytest.raises(KeyboardInterrupt):
        account_scheduler.run_account_process(
            repo_root=tmp_path,
            account_name="danatimer",
            generated_cfg_path=tmp_path / "generated.yaml",
            env={},
            execute=True,
            timeout_sec=0,
        )

    assert sent == [(9876, signal.SIGINT)]


def test_choose_rotating_gemini_key_advances_cursor(tmp_path: Path):
    keys = ["free-1", "free-2", "free-3"]

    picked_1 = solver_config.choose_rotating_gemini_key(
        keys,
        cursor_name="free_ops_test",
        state_dir=tmp_path,
    )
    picked_2 = solver_config.choose_rotating_gemini_key(
        keys,
        cursor_name="free_ops_test",
        state_dir=tmp_path,
    )
    picked_3 = solver_config.choose_rotating_gemini_key(
        keys,
        cursor_name="free_ops_test",
        state_dir=tmp_path,
    )

    assert [picked_1, picked_2, picked_3] == ["free-1", "free-2", "free-3"]


def test_rewrite_label_tier3_adds_motion_verb_for_object_to_destination_clause():
    rewritten = legacy_impl._rewrite_label_tier3(
        "hold candy box, candy box to freezer"
    )
    assert rewritten == "hold candy box, move candy box to freezer"


def test_build_effective_config_forces_linux_safe_defaults():
    merged = account_scheduler.build_effective_config(
        {
            "browser": {
                "headless": False,
                "use_chrome_profile": True,
                "restore_state_in_profile_mode": True,
                "chrome_user_data_dir": r"E:\\OCR_annotation_Atlas\\.state\\chrome_user_data_danatimer",
            },
            "run": {"output_dir": "outputs/base"},
            "gemini": {"rotation_policy": "sticky"},
        },
        {
            "browser": {"storage_state_path": ".state/custom_auth.json"},
            "run": {"output_dir": "outputs/custom"},
        },
        "danatimer",
    )

    assert merged["browser"]["headless"] is False
    assert merged["browser"]["use_chrome_profile"] is False
    assert merged["browser"]["restore_state_in_profile_mode"] is False
    assert merged["browser"]["storage_state_path"] == ".state/custom_auth.json"
    assert merged["run"]["output_dir"] == "outputs/custom"
    assert merged["gemini"]["rotation_policy"] == "sticky"
    assert merged["gemini"]["api_keys"] == []


def test_build_effective_config_rewrites_generic_default_storage_state_per_account():
    merged = account_scheduler.build_effective_config(
        {
            "browser": {
                "headless": True,
                "storage_state_path": ".state/atlas_auth.json",
            }
        },
        {},
        "wafaabayoumi",
    )

    assert merged["browser"]["storage_state_path"] == ".state/accounts/wafaabayoumi/atlas_auth.json"


def test_load_config_normalizes_legacy_room_and_gemini_execution_defaults(tmp_path: Path):
    cfg_path = tmp_path / "legacy.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "atlas": {"room_url": "https://audit.atlascapture.io/tasks/room/normal"},
                "gemini": {
                    "model": "gemini-2.5-pro",
                    "policy_retry_model": "gemini-2.5-pro",
                    "retry_with_stronger_model_on_policy_fail": True,
                    "retry_with_quota_fallback_model": True,
                    "quota_fallback_model": "gemini-3-pro-preview",
                    "video_transport": "files_api",
                    "files_api_fallback_to_inline": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = solver_config.load_config(cfg_path)

    assert cfg["atlas"]["room_url"] == "https://audit.atlascapture.io/tasks"
    assert cfg["gemini"]["model"] == "gemini-3.1-pro-preview"
    assert cfg["gemini"]["policy_retry_model"] == "gemini-3.1-pro-preview"
    assert cfg["gemini"]["retry_with_stronger_model_on_policy_fail"] is False
    assert cfg["gemini"]["quota_fallback_model"] == "gemini-3.1-pro-preview"
    assert cfg["gemini"]["retry_with_quota_fallback_model"] is False
    assert cfg["gemini"]["files_api_fallback_to_inline"] is True


def test_call_gemini_labels_optimizes_video_before_split(tmp_path: Path, monkeypatch):
    source_video = tmp_path / "source.mp4"
    optimized_video = tmp_path / "source_upload_opt.mp4"
    source_video.write_bytes(b"source-video")
    optimized_video.write_bytes(b"optimized-video")

    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {"GEMINI_API_KEY": "test-key-1234567890"},
    )
    for env_name in [
        "GEMINI_API_KEYS_FREE_POOL",
        "GEMINI_API_KEY_FREE_OPS",
        "GEMINI_API_KEY2_FREE_OPS2",
        "GEMINI_API_KEY_FREE_FALLBACK",
        "GEMINI_API_KEY_FREE_FALLBACK2",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL_SIGNATURE", None)
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})

    def _fake_optimize(video_file: Path, cfg):
        seen["optimized_from"] = video_file
        return optimized_video

    class _StopAfterSplit(Exception):
        pass

    def _fake_split(video_file: Path, cfg):
        seen["split_from"] = video_file
        raise _StopAfterSplit()

    monkeypatch.setattr(legacy_impl, "_maybe_optimize_video_for_upload", _fake_optimize)
    monkeypatch.setattr(legacy_impl, "_split_video_for_upload", _fake_split)

    with pytest.raises(_StopAfterSplit):
        legacy_impl.call_gemini_labels(
            {
                "gemini": {
                    "model": "gemini-3.1-pro-preview",
                    "attach_video": True,
                    "video_transport": "files_api",
                    "files_api_fallback_to_inline": False,
                }
            },
            "prompt",
            video_file=source_video,
            segment_count=3,
        )

    assert seen["optimized_from"] == source_video
    assert seen["split_from"] == optimized_video


def test_normalize_target_task_urls_accepts_urls_ids_and_deduplicates():
    urls = legacy_impl._normalize_target_task_urls(
        [
            "https://audit.atlascapture.io/tasks/room/normal/label/690ab7a86f5394d420ff041f",
            "/tasks/room/normal/label/690ab2f48ca9eb4f6206ceda",
            "690ab345552c14c3b6efcb50",
            "https://audit.atlascapture.io/tasks/room/normal/label/690ab345552c14c3b6efcb50",
            "not-a-task",
        ]
    )

    assert urls == [
        "https://audit.atlascapture.io/tasks/room/normal/label/690ab7a86f5394d420ff041f",
        "https://audit.atlascapture.io/tasks/room/normal/label/690ab2f48ca9eb4f6206ceda",
        "https://audit.atlascapture.io/tasks/room/normal/label/690ab345552c14c3b6efcb50",
    ]


def test_build_runner_env_maps_account_specific_secrets():
    env = account_scheduler.build_runner_env(
        {
            "runner": {
                "env_map": {
                    "ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_DANATIMER",
                    "GMAIL_APP_PASSWORD": "GMAIL_APP_PASSWORD_DANATIMER",
                }
            }
        },
        base_env={
            "ATLAS_LOGIN_EMAIL_DANATIMER": "dana@example.com",
            "GMAIL_APP_PASSWORD_DANATIMER": "secret-app-password",
        },
    )

    assert env["ATLAS_LOGIN_EMAIL"] == "dana@example.com"
    assert env["GMAIL_APP_PASSWORD"] == "secret-app-password"


def test_build_runner_env_clears_target_when_numbered_source_missing():
    env = account_scheduler.build_runner_env(
        {
            "runner": {
                "env_map": {
                    "ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL3",
                    "GMAIL_APP_PASSWORD": "GMAIL_APP_PASSWORD3",
                }
            }
        },
        base_env={
            "ATLAS_LOGIN_EMAIL": "legacy@example.com",
            "GMAIL_APP_PASSWORD": "legacy-password",
        },
    )

    assert "ATLAS_LOGIN_EMAIL" not in env
    assert "GMAIL_APP_PASSWORD" not in env


def test_repo_account_index_defaults_to_four_accounts_and_five_tasks():
    repo_root = Path(__file__).resolve().parents[1]
    index_cfg = account_scheduler.load_account_index(repo_root / "configs" / "accounts" / "index.yaml")

    assert index_cfg["scheduler"]["episodes_per_account_per_turn"] == 5
    assert [row["name"] for row in index_cfg["accounts"]] == [
        "danatimer",
        "wafaabayoumi",
        "amirakamelkorany",
        "badrbayoumi865",
    ]


def test_repo_production_config_uses_chat_web_backend_for_hetzner():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = account_scheduler.load_config(repo_root / "configs" / "production_hetzner.yaml")

    run_cfg = cfg["run"]
    gemini_cfg = cfg["gemini"]

    assert run_cfg["use_episode_runtime_v2"] is True
    assert run_cfg["strict_single_chat_session"] is True
    assert run_cfg["force_episode_browser_isolation"] is True
    assert run_cfg["single_window_two_tabs"] is False
    assert run_cfg["single_window_single_tab"] is True
    assert run_cfg["max_atomic_actions_per_label"] == 2
    assert run_cfg["primary_solve_backend"] == "chat_web"
    assert run_cfg["chat_only_mode"] is True
    assert run_cfg["segment_chunking_disable_operations"] is False
    assert run_cfg["submit_deep_verify_dashboard"] is True
    assert float(run_cfg["submit_deep_verify_dashboard_timeout_sec"]) >= 30.0
    assert float(run_cfg["quality_review_submit_settle_sec"]) >= 30.0
    assert gemini_cfg["auth_mode"] == "chat_web"
    assert gemini_cfg["model"] == "gemini-3.1-pro-preview"
    assert gemini_cfg["policy_retry_model"] == "gemini-3.1-pro-preview"
    assert gemini_cfg["retry_on_quota_429"] is True
    assert float(gemini_cfg["quota_retry_default_wait_sec"]) >= 30.0
    assert gemini_cfg["video_transport"] == "inline"
    assert gemini_cfg["split_upload_enabled"] is False
    assert float(gemini_cfg["optimize_video_target_mb"]) >= 15.0
    assert float(gemini_cfg["inline_read_bytes_max_mb"]) >= 8.0
    assert gemini_cfg["chat_ops_model"] == "gemini-3.1-pro-preview"
    assert gemini_cfg["chat_labels_model"] == "gemini-3.1-pro-preview"
    assert gemini_cfg["chat_web_preserve_existing_thread"] is False
    assert gemini_cfg["chat_web_preserve_existing_thread_across_episodes"] is False
    assert gemini_cfg["chat_web_clean_thread_per_episode"] is True
    assert gemini_cfg["chat_web_clean_thread_per_request"] is False


def test_cleanup_browser_connections_preserves_shared_cdp_browser():
    class _FakeHandle:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    context = _FakeHandle()
    browser_handle = _FakeHandle()
    gemini_browser = _FakeHandle()

    legacy_impl._cleanup_browser_connections(
        context=context,
        browser=browser_handle,
        atlas_browser_mode="cdp",
        gemini_browser=gemini_browser,
        owns_gemini_browser=False,
    )

    assert context.close_calls == 0
    assert browser_handle.close_calls == 0
    assert gemini_browser.close_calls == 0


def test_cleanup_browser_connections_closes_owned_fallback_browsers():
    class _FakeHandle:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    context = _FakeHandle()
    browser_handle = _FakeHandle()
    gemini_browser = _FakeHandle()

    legacy_impl._cleanup_browser_connections(
        context=context,
        browser=browser_handle,
        atlas_browser_mode="playwright_fallback",
        gemini_browser=gemini_browser,
        owns_gemini_browser=True,
    )

    assert context.close_calls == 1
    assert browser_handle.close_calls == 1
    assert gemini_browser.close_calls == 1


def test_connect_atlas_browser_context_keeps_browser_alive_when_only_blank_tab_exists(tmp_path: Path):
    events: list[str] = []

    class _FakePage:
        def __init__(self, url: str, name: str):
            self.url = url
            self._name = name
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            events.append(f"close:{self._name}")

    class _FakeContext:
        def __init__(self):
            self.blank_page = _FakePage("about:blank", "blank")
            self.fresh_page = _FakePage("", "fresh")
            self.pages = [self.blank_page]

        def new_page(self):
            events.append("new_page")
            self.pages.append(self.fresh_page)
            return self.fresh_page

    class _FakeBrowser:
        def __init__(self, context):
            self.contexts = [context]

    class _FakeChromium:
        def __init__(self, browser_handle):
            self._browser_handle = browser_handle

        def connect_over_cdp(self, *_args, **_kwargs):
            return self._browser_handle

    class _FakePlaywright:
        def __init__(self, browser_handle):
            self.chromium = _FakeChromium(browser_handle)

    context = _FakeContext()
    browser_handle = _FakeBrowser(context)
    pw = _FakePlaywright(browser_handle)

    browser_obj, context_obj, page_obj, mode = legacy_impl._connect_atlas_browser_context(
        pw,
        cdp_url="http://127.0.0.1:9222",
        cdp_connect_timeout_ms=1000,
        state_path=tmp_path / "state.json",
        headless=False,
        slow_mo=0,
        chrome_channel="chrome",
    )

    assert browser_obj is browser_handle
    assert context_obj is context
    assert page_obj is context.fresh_page
    assert mode == "cdp"
    assert events == ["new_page", "close:blank"]
    assert context.blank_page.close_calls == 1


def test_connect_atlas_browser_context_preserves_existing_gemini_tab(tmp_path: Path):
    events: list[str] = []

    class _FakePage:
        def __init__(self, url: str, name: str):
            self.url = url
            self._name = name
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            events.append(f"close:{self._name}")

    class _FakeContext:
        def __init__(self):
            self.atlas_page = _FakePage("https://audit.atlascapture.io/tasks", "atlas")
            self.gemini_page = _FakePage("https://gemini.google.com/app/b3006ba9f325b55c", "gemini")
            self.pages = [self.atlas_page, self.gemini_page]

        def new_page(self):
            raise AssertionError("new_page should not be called when Atlas tab already exists")

    class _FakeBrowser:
        def __init__(self, context):
            self.contexts = [context]

    class _FakeChromium:
        def __init__(self, browser_handle):
            self._browser_handle = browser_handle

        def connect_over_cdp(self, *_args, **_kwargs):
            return self._browser_handle

    class _FakePlaywright:
        def __init__(self, browser_handle):
            self.chromium = _FakeChromium(browser_handle)

    context = _FakeContext()
    browser_handle = _FakeBrowser(context)
    pw = _FakePlaywright(browser_handle)

    browser_obj, context_obj, page_obj, mode = legacy_impl._connect_atlas_browser_context(
        pw,
        cdp_url="http://127.0.0.1:9222",
        cdp_connect_timeout_ms=1000,
        state_path=tmp_path / "state.json",
        headless=False,
        slow_mo=0,
        chrome_channel="chrome",
    )

    assert browser_obj is browser_handle
    assert context_obj is context
    assert page_obj is context.atlas_page
    assert mode == "cdp"
    assert context.gemini_page.close_calls == 0
    assert events == []


def test_acquire_gemini_probe_page_prefers_existing_gemini_tab_before_opening_new_one():
    class _FakePage:
        def __init__(self, url: str):
            self.url = url
            self.goto_calls: list[str] = []
            self.wait_calls: list[int] = []

        def goto(self, url: str, wait_until=None, timeout=None):
            self.goto_calls.append(url)
            self.url = url

        def wait_for_timeout(self, timeout_ms: int):
            self.wait_calls.append(timeout_ms)

    class _FakeContext:
        def __init__(self):
            self.atlas_page = _FakePage("https://audit.atlascapture.io/tasks")
            self.gemini_page = _FakePage("https://gemini.google.com/app")
            self.pages = [self.atlas_page, self.gemini_page]
            self.new_page_calls = 0

        def new_page(self):
            self.new_page_calls += 1
            return _FakePage("")

    context = _FakeContext()

    page, created = legacy_impl._acquire_gemini_probe_page(
        context,
        gemini_chat_url="https://gemini.google.com/app/b3006ba9f325b55c",
    )

    assert page is context.gemini_page
    assert created is False


def test_fill_input_uses_insert_text_for_contenteditable_fallback():
    class _FakeKeyboard:
        def __init__(self):
            self.events = []

        def press(self, value):
            self.events.append(("press", value))

        def insert_text(self, value):
            self.events.append(("insert_text", value))

        def type(self, *_args, **_kwargs):
            raise AssertionError("keyboard.type should not be used for contenteditable fallback")

    class _FakePage:
        def __init__(self):
            self.keyboard = _FakeKeyboard()

    class _FakeLocator:
        def scroll_into_view_if_needed(self, timeout=0):
            return None

        def click(self, timeout=0, force=False):
            return None

        def evaluate(self, _script):
            return True

        def fill(self, _label, timeout=0):
            raise RuntimeError("fill unsupported")

    page = _FakePage()
    locator = _FakeLocator()

    segments._fill_input(locator, "hold blue shirt, adjust blue shirt", page)

    assert page.keyboard.events == [
        ("press", "Control+A"),
        ("insert_text", "hold blue shirt, adjust blue shirt"),
    ]


def test_acquire_gemini_probe_page_opens_chat_page_when_context_has_only_atlas_tabs():
    class _FakePage:
        def __init__(self, url: str):
            self.url = url
            self.goto_calls: list[str] = []
            self.wait_calls: list[int] = []

        def goto(self, url: str, wait_until=None, timeout=None):
            self.goto_calls.append(url)
            self.url = url

        def wait_for_timeout(self, timeout_ms: int):
            self.wait_calls.append(timeout_ms)

    class _FakeContext:
        def __init__(self):
            self.pages = [_FakePage("https://audit.atlascapture.io/tasks")]
            self.created = _FakePage("")

        def new_page(self):
            return self.created

    context = _FakeContext()

    page, created = legacy_impl._acquire_gemini_probe_page(
        context,
        gemini_chat_url="https://gemini.google.com/app/b3006ba9f325b55c",
    )

    assert page is context.created
    assert created is True
    assert context.created.goto_calls == ["https://gemini.google.com/app/b3006ba9f325b55c"]
    assert context.created.wait_calls == [5000]


def test_run_scheduler_processes_accounts_sequentially(tmp_path: Path, monkeypatch):
    base_config = tmp_path / "production_hetzner.yaml"
    base_config.write_text(
        yaml.safe_dump(
            {
                "browser": {"headless": True},
                "run": {"keep_alive_when_idle": False, "max_episodes_per_run": 1},
                "gemini": {"api_keys": [], "rotation_policy": "round_robin"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    (accounts_dir / "a.yaml").write_text(
        yaml.safe_dump(
            {
                "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_A"}},
                "run": {"output_dir": "outputs/a"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (accounts_dir / "b.yaml").write_text(
        yaml.safe_dump(
            {
                "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_B"}},
                "run": {"output_dir": "outputs/b"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    index_path = tmp_path / "index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "base_config": str(base_config),
                "scheduler": {
                    "mode": "sequential",
                    "episodes_per_account_per_turn": 1,
                    "cooldown_between_accounts_sec": 1,
                    "continue_on_error": True,
                    "loop_pause_sec": 10,
                },
                "accounts": [
                    {"name": "a", "config": str(accounts_dir / "a.yaml"), "enabled": True},
                    {"name": "b", "config": str(accounts_dir / "b.yaml"), "enabled": True},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    for account_name in ("a", "b"):
        state_path = tmp_path / ".state" / "accounts" / account_name / "atlas_auth.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")

    calls = []
    sleeps = []

    monkeypatch.setattr(account_scheduler, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        account_scheduler,
        "run_account_process",
        lambda repo_root, account_name, generated_cfg_path, env, *, execute, timeout_sec: calls.append(
            {
                "repo_root": repo_root,
                "account_name": account_name,
                "generated_cfg_path": Path(generated_cfg_path),
                "atlas_login_email": env.get("ATLAS_LOGIN_EMAIL", ""),
                "execute": execute,
                "timeout_sec": timeout_sec,
            }
        )
        or 0,
    )
    monkeypatch.setattr(account_scheduler.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_A", "a@example.com")
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_B", "b@example.com")

    exit_code = account_scheduler.run_scheduler(index_path, execute=True, loop_forever=False)

    assert exit_code == 0
    assert [item["account_name"] for item in calls] == ["a", "b"]
    assert calls[0]["atlas_login_email"] == "a@example.com"
    assert calls[1]["atlas_login_email"] == "b@example.com"
    assert calls[0]["execute"] is True
    assert calls[0]["generated_cfg_path"].name == "a.generated.yaml"
    assert calls[1]["generated_cfg_path"].name == "b.generated.yaml"
    generated_a = yaml.safe_load(calls[0]["generated_cfg_path"].read_text(encoding="utf-8"))
    generated_b = yaml.safe_load(calls[1]["generated_cfg_path"].read_text(encoding="utf-8"))
    assert generated_a["run"]["max_episodes_per_run"] == 1
    assert generated_b["run"]["max_episodes_per_run"] == 1
    assert generated_a["run"]["recycle_after_max_episodes"] is False
    assert generated_b["run"]["recycle_after_max_episodes"] is False
    assert sleeps == [1.0]


def test_run_scheduler_rests_after_last_turn_before_loop_restart(tmp_path: Path, monkeypatch):
    base_config = tmp_path / "production_hetzner.yaml"
    base_config.write_text(
        yaml.safe_dump(
            {
                "browser": {
                    "headless": True,
                    "storage_state_path": ".state/accounts/default/atlas_auth.json",
                },
                "run": {"keep_alive_when_idle": False, "max_episodes_per_run": 1},
                "gemini": {"api_keys": [], "rotation_policy": "round_robin"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    for name in ("a", "b"):
        (accounts_dir / f"{name}.yaml").write_text(
            yaml.safe_dump(
                {
                    "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": f"ATLAS_LOGIN_EMAIL_{name.upper()}"}},
                    "browser": {"storage_state_path": f".state/accounts/{name}/atlas_auth.json"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        state_path = tmp_path / ".state" / "accounts" / name / "atlas_auth.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")

    index_path = tmp_path / "index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "base_config": str(base_config),
                "scheduler": {
                    "mode": "sequential",
                    "episodes_per_account_per_turn": 1,
                    "rest_between_turns_sec": 2,
                    "cooldown_between_accounts_sec": 1,
                    "continue_on_error": True,
                    "loop_pause_sec": 0,
                },
                "accounts": [
                    {"name": "a", "config": str(accounts_dir / "a.yaml"), "enabled": True},
                    {"name": "b", "config": str(accounts_dir / "b.yaml"), "enabled": True},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    for account_name in ("a", "b"):
        state_path = tmp_path / ".state" / "accounts" / account_name / "atlas_auth.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")

    calls = []
    sleeps = []

    monkeypatch.setattr(account_scheduler, "_resolve_repo_root", lambda: tmp_path)

    def _fake_run(repo_root, account_name, generated_cfg_path, env, *, execute, timeout_sec):
        calls.append(account_name)
        return 0

    monkeypatch.setattr(account_scheduler, "run_account_process", _fake_run)
    def _fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise RuntimeError("stop after first full cycle")

    monkeypatch.setattr(account_scheduler.time, "sleep", _fake_sleep)
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_A", "a@example.com")
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_B", "b@example.com")

    with pytest.raises(RuntimeError, match="stop after first full cycle"):
        account_scheduler.run_scheduler(index_path, execute=True, loop_forever=True)

    assert calls == ["a", "b"]
    assert sleeps == [2.0, 2.0]


def test_run_scheduler_skips_unready_account_when_enabled(tmp_path: Path, monkeypatch):
    base_config = tmp_path / "production_hetzner.yaml"
    base_config.write_text(
        yaml.safe_dump(
            {
                "browser": {"headless": True},
                "run": {"keep_alive_when_idle": False, "max_episodes_per_run": 1},
                "gemini": {"api_keys": [], "rotation_policy": "round_robin"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    (accounts_dir / "a.yaml").write_text(
        yaml.safe_dump(
            {
                "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_A"}},
                "browser": {"storage_state_path": ".state/accounts/a/atlas_auth.json"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (accounts_dir / "b.yaml").write_text(
        yaml.safe_dump(
            {
                "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_B"}},
                "browser": {"storage_state_path": ".state/accounts/b/atlas_auth.json"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ready_state = tmp_path / ".state" / "accounts" / "a" / "atlas_auth.json"
    ready_state.parent.mkdir(parents=True, exist_ok=True)
    ready_state.write_text("{}", encoding="utf-8")

    index_path = tmp_path / "index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "base_config": str(base_config),
                "scheduler": {
                    "mode": "sequential",
                    "episodes_per_account_per_turn": 1,
                    "cooldown_between_accounts_sec": 0,
                    "skip_unready_accounts": True,
                    "continue_on_error": True,
                },
                "accounts": [
                    {"name": "a", "config": str(accounts_dir / "a.yaml"), "enabled": True},
                    {"name": "b", "config": str(accounts_dir / "b.yaml"), "enabled": True},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    seen_accounts = []
    monkeypatch.setattr(account_scheduler, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        account_scheduler,
        "run_account_process",
        lambda repo_root, account_name, generated_cfg_path, env, *, execute, timeout_sec: seen_accounts.append(account_name) or 0,
    )
    for env_name in [
        "ATLAS_LOGIN_EMAIL",
        "ATLAS_EMAIL",
        "GMAIL_EMAIL",
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "ATLAS_LOGIN_EMAIL_B",
        "ATLAS_EMAIL_B",
        "GMAIL_EMAIL_B",
        "GMAIL_USER_B",
        "GMAIL_APP_PASSWORD_B",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_A", "a@example.com")

    exit_code = account_scheduler.run_scheduler(index_path, execute=True, loop_forever=False)

    assert exit_code == 0
    assert seen_accounts == ["a"]


def test_run_scheduler_retries_failed_account_once_when_configured(tmp_path: Path, monkeypatch):
    base_config = tmp_path / "production_hetzner.yaml"
    base_config.write_text(
        yaml.safe_dump(
            {
                "browser": {"headless": True},
                "run": {"keep_alive_when_idle": False, "max_episodes_per_run": 1},
                "gemini": {"api_keys": [], "rotation_policy": "round_robin"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    (accounts_dir / "a.yaml").write_text(
        yaml.safe_dump(
            {
                "runner": {"env_map": {"ATLAS_LOGIN_EMAIL": "ATLAS_LOGIN_EMAIL_A"}},
                "browser": {"storage_state_path": ".state/accounts/a/atlas_auth.json"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / ".state" / "accounts" / "a" / "atlas_auth.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{}", encoding="utf-8")

    index_path = tmp_path / "index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "base_config": str(base_config),
                "scheduler": {
                    "mode": "sequential",
                    "episodes_per_account_per_turn": 1,
                    "cooldown_between_accounts_sec": 0,
                    "continue_on_error": True,
                    "account_retry_count": 1,
                    "account_retry_delay_sec": 7,
                    "account_retry_exit_codes": [1],
                },
                "accounts": [
                    {"name": "a", "config": str(accounts_dir / "a.yaml"), "enabled": True},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    calls = []
    sleeps = []
    monkeypatch.setattr(account_scheduler, "_resolve_repo_root", lambda: tmp_path)

    def _fake_run(repo_root, account_name, generated_cfg_path, env, *, execute, timeout_sec):
        calls.append(account_name)
        return 1 if len(calls) == 1 else 0

    monkeypatch.setattr(account_scheduler, "run_account_process", _fake_run)
    monkeypatch.setattr(account_scheduler.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setenv("ATLAS_LOGIN_EMAIL_A", "a@example.com")

    exit_code = account_scheduler.run_scheduler(index_path, execute=True, loop_forever=False)

    assert exit_code == 0
    assert calls == ["a", "a"]
    assert sleeps == [7.0]


class _FakeRoomDisabledPage:
    def __init__(self, body: str):
        self._body = body
        self.url = "https://audit.atlascapture.io/tasks/room/normal"
        self.waits: list[int] = []

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return self._body

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)


class _FakeNoEditsButton:
    def __init__(self, page: "_FakeNoEditsPage", disabled_cycles: int = 2):
        self.page = page
        self.disabled_cycles = disabled_cycles
        self.disabled_checks = 0
        self.clicks = 0

    def evaluate(self, script: str) -> bool:
        self.disabled_checks += 1
        return self.disabled_checks <= self.disabled_cycles

    def click(self, timeout: int = 0, force: bool = False, no_wait_after: bool = False) -> None:
        self.clicks += 1
        self.page.modal_visible = False


class _FakeNoEditsPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.modal_visible = True
        self.waits: list[int] = []
        self.button = _FakeNoEditsButton(self)

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        if self.modal_visible:
            return (
                "No Edits Made\n"
                "Please confirm you've reviewed all labels.\n"
                "Yes, Labels Are Correct"
            )
        return "Label Episode\nsegments"

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str):
        return False


class _FakeSubmitTransitionPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks"
        self.waits: list[int] = []

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return "Tasks Reserve 3 Episodes Dashboard"

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str):
        return False


class _FakeSubmitNoEvidencePage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.waits: list[int] = []

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return "Label Episode\nsegments"

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str):
        return False


class _FakeSubmitDelayedTransitionPage:
    def __init__(self, transition_after_ms: int = 6000):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.waits: list[int] = []
        self._elapsed_ms = 0
        self._transition_after_ms = transition_after_ms

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        if self._elapsed_ms >= self._transition_after_ms:
            return "Dashboard Welcome, Dana! Complete Training Do Labeling Tasks"
        return "Label Episode\nsegments"

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)
        self._elapsed_ms += ms

    def evaluate(self, script: str):
        return False


class _FakeSubmitJsFallbackPage(_FakeSubmitDelayedTransitionPage):
    def __init__(self):
        super().__init__(transition_after_ms=0)
        self.js_submit_clicked = False

    def evaluate(self, script: str, arg=None):
        if "submit task" in script.lower() or "const candidates" in script.lower():
            self.js_submit_clicked = True
            return True
        return False


class _FakeSubmitTrainingJourneyPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return "Welcome, Dana! Your Journey Complete Training Do Labeling Tasks Set Up Payment"

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def evaluate(self, script: str):
        return False


class _FakeSubmitMixedTransitionPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return (
            "Label Episode Welcome, Dana! Your Journey "
            "Complete Training Do Labeling Tasks Set Up Payment"
        )

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def evaluate(self, script: str):
        return False


class _FakeSubmitNoEditsVisiblePage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return (
            "Label Episode\n"
            "No Edits Made\n"
            "Please confirm you've reviewed all labels.\n"
            "Yes, Labels Are Correct"
        )

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def evaluate(self, script: str):
        return False


class _FakeSubmitRoomTransitionPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.waits: list[int] = []

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        current = (self.url or "").lower().rstrip("/")
        if current.endswith("/tasks"):
            return "Your Reserved Episodes\nReserve 3 Episodes"
        if "/tasks/room/normal" in current and "/label/" not in current:
            return "Rooms are unavailable\nRoom access is currently disabled.\nBack to Tasks"
        return "Label Episode\nsegments"

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def evaluate(self, script: str):
        return False


class _FakeQualityReviewCheckboxItem:
    def __init__(self):
        self.checked = False

    def is_visible(self) -> bool:
        return True

    def evaluate(self, script: str):
        script = (script or "").lower()
        if "tagname" in script:
            return "input"
        if "getattribute('type')" in script or 'getattribute("type")' in script:
            return "checkbox"
        return False

    def check(self, timeout: int = 0, force: bool = False):
        self.checked = True
        return None

    def click(self, timeout: int = 0, force: bool = False, no_wait_after: bool = False):
        self.checked = True
        return None


class _FakeQualityReviewSubmitItem:
    def __init__(self, page):
        self.page = page
        self.clicks = 0

    def is_visible(self) -> bool:
        return True

    def evaluate(self, script: str):
        return False

    def click(self, timeout: int = 0, force: bool = False, no_wait_after: bool = False):
        self.clicks += 1
        self.page.submitted = True
        return None


class _FakeLocatorList:
    def __init__(self, items):
        self.items = list(items)

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int):
        return self.items[index]


class _FakeBodyScopedQualityReviewPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.waits: list[int] = []
        self.submitted = False
        self.checkbox = _FakeQualityReviewCheckboxItem()
        self.submit_button = _FakeQualityReviewSubmitItem(self)

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        if self.submitted:
            return "Your Reserved Episodes\nReserve 3 Episodes"
        return (
            "Label Episode\n"
            "Quality Review\n"
            "Before submitting, please confirm you've reviewed your work.\n"
            "I verify that I have reviewed every segment in this video and that every label is correct to the best of my ability and the guidelines.\n"
            "Submit"
        )

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def locator(self, candidate: str):
        candidate = (candidate or "").lower()
        if "checkbox" in candidate:
            return _FakeLocatorList([self.checkbox])
        if "submit" in candidate or "confirm" in candidate or "ok" in candidate or "yes" in candidate:
            return _FakeLocatorList([self.submit_button])
        return _FakeLocatorList([])

    def evaluate(self, script: str, arg=None):
        script = (script or "").lower()
        if "const t = document.queryselector('#toast')" in script:
            return None
        return False


class _FakeAutoAcceptQualityReviewCheckboxItem:
    def __init__(self, page):
        self.page = page
        self.checked = False

    def is_visible(self) -> bool:
        return True

    def evaluate(self, script: str):
        script = (script or "").lower()
        if "tagname" in script:
            return "input"
        if "getattribute('type')" in script or 'getattribute("type")' in script:
            return "checkbox"
        return False

    def check(self, timeout: int = 0, force: bool = False):
        self.checked = True
        self.page.submitted = True
        return None

    def click(self, timeout: int = 0, force: bool = False, no_wait_after: bool = False):
        self.checked = True
        self.page.submitted = True
        return None


class _FakeBodyScopedQualityReviewAutoAcceptPage:
    def __init__(self):
        self.url = "https://audit.atlascapture.io/tasks/room/normal/label/690ac50ce864dc7e43cc78f8"
        self.waits: list[int] = []
        self.submitted = False
        self.checkbox = _FakeAutoAcceptQualityReviewCheckboxItem(self)

    def inner_text(self, selector: str) -> str:
        assert selector == "body"
        if self.submitted:
            return "Your Reserved Episodes\nReserve 3 Episodes"
        return (
            "Label Episode\n"
            "Quality Review\n"
            "Before submitting, please confirm you've reviewed your work.\n"
            "I verify that I have reviewed every segment in this video and that every label is correct to the best of my ability and the guidelines.\n"
        )

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def locator(self, candidate: str):
        candidate = (candidate or "").lower()
        if "checkbox" in candidate:
            return _FakeLocatorList([self.checkbox])
        return _FakeLocatorList([])

    def evaluate(self, script: str, arg=None):
        script = (script or "").lower()
        if "const t = document.queryselector('#toast')" in script:
            return None
        return False


class _FakeGeminiAuthPage:
    def __init__(self, *, url: str, title: str, body: str, input_visible: bool):
        self.url = url
        self._title = title
        self._body = body
        self._input_visible = input_visible

    def title(self):
        return self._title

    def locator(self, selector: str):
        selector = (selector or "").lower()
        if selector == "body":
            class _Body:
                def __init__(self, text):
                    self.text = text
                def inner_text(self, timeout: int = 0):
                    return self.text
            return _Body(self._body)
        class _Composer:
            def __init__(self, visible):
                self.visible = visible
            @property
            def first(self):
                return self
            def is_visible(self, timeout: int = 0):
                return self.visible
        return _Composer(self._input_visible)


def test_recover_room_access_disabled_clicks_back_to_tasks(monkeypatch):
    page = _FakeRoomDisabledPage("Rooms are unavailable\nRoom access is currently disabled.")
    clicked: list[str] = []

    monkeypatch.setattr(
        browser,
        "_safe_locator_click",
        lambda page_obj, selector, timeout_ms=0: clicked.append(selector) or True,
    )

    recovered = legacy_impl._recover_room_access_disabled(
        page,
        {"atlas": {"room_url": "https://audit.atlascapture.io/tasks"}},
    )

    assert recovered is True
    assert clicked == ['button:has-text("Back to Tasks") || a:has-text("Back to Tasks")']
    assert page.waits == [1200]


def test_handle_no_edits_modal_waits_for_countdown_and_confirms(monkeypatch):
    page = _FakeNoEditsPage()

    monkeypatch.setattr(
        browser,
        "_first_visible_locator",
        lambda page_obj, selector, timeout_ms=0: page.button if "Yes, Labels Are Correct" in selector and page.modal_visible else None,
    )

    handled = legacy_impl._handle_no_edits_modal(page, timeout_ms=2500)

    assert handled is True
    assert page.button.disabled_checks >= 3
    assert page.button.clicks == 1


def test_submit_episode_accepts_navigation_away_from_label_page(monkeypatch):
    page = _FakeSubmitTransitionPage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    assert legacy_impl._submit_episode(page, cfg) is True


def test_submit_episode_returns_details_for_verified_transition(monkeypatch):
    page = _FakeSubmitTransitionPage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["submit_verification_reason"] == "post_submit_transition_observed"
    assert result["complete_button_clicked"] is True
    assert result["saw_post_submit_transition"] is True
    assert result["page_url_before_submit"].endswith("/tasks")
    assert result["page_url_after_submit"].endswith("/tasks")


def test_submit_episode_rejects_click_without_transition_or_modal_evidence(monkeypatch):
    page = _FakeSubmitNoEvidencePage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )

    assert legacy_impl._submit_episode(page, cfg) is False


def test_submit_episode_returns_details_for_unverified_click_without_evidence(monkeypatch):
    page = _FakeSubmitNoEvidencePage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is False
    assert result["submit_verification_reason"] == "missing_verification_evidence"
    assert result["submit_attempted"] is True
    assert result["complete_button_clicked"] is True
    assert result["saw_no_edits_modal"] is False
    assert result["saw_quality_review_modal"] is False
    assert result["saw_post_submit_transition"] is False


def test_submit_episode_accepts_delayed_post_submit_transition(monkeypatch):
    page = _FakeSubmitDelayedTransitionPage(transition_after_ms=6500)
    cfg = {
        "run": {"submit_verification_grace_sec": 12.0},
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        },
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["submit_verification_reason"] == "post_submit_transition_observed"
    assert result["saw_post_submit_transition"] is True


def test_submit_episode_waits_for_manual_submit_when_auto_click_fails(monkeypatch):
    page = _FakeSubmitDelayedTransitionPage(transition_after_ms=900)
    cfg = {
        "run": {
            "submit_manual_watch_enabled": True,
            "submit_manual_watch_timeout_sec": 3.0,
            "submit_manual_watch_poll_ms": 200,
            "submit_manual_watch_log_interval_sec": 0.5,
        },
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        },
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: False)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(segments, "_force_primary_submit_click", lambda page_obj, selector: False)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["submit_verification_reason"] == "post_submit_transition_observed"
    assert result["manual_submit_watch_used"] is True
    assert result["manual_submit_detected"] is True
    assert result["manual_submit_watch_signal"] == "post_submit_transition"
    assert result["manual_submit_watch_reason"] == "complete_click_failed"
    assert result["manual_submit_watch_timed_out"] is False
    assert page.waits
    assert sum(page.waits) >= 900
    assert result["complete_button_clicked"] is True


def test_submit_episode_manual_watch_times_out_without_operator_submit(monkeypatch):
    page = _FakeSubmitNoEvidencePage()
    cfg = {
        "run": {
            "submit_manual_watch_enabled": True,
            "submit_manual_watch_timeout_sec": 0.6,
            "submit_manual_watch_poll_ms": 200,
            "submit_manual_watch_log_interval_sec": 0.2,
        },
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        },
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: False)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(segments, "_force_primary_submit_click", lambda page_obj, selector: False)

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is False
    assert result["submit_verification_reason"] == "manual_submit_watch_timeout"
    assert result["manual_submit_watch_used"] is True
    assert result["manual_submit_detected"] is False
    assert result["manual_submit_watch_reason"] == "complete_click_failed"
    assert result["manual_submit_watch_signal"] == ""
    assert result["manual_submit_watch_timed_out"] is True
    assert page.waits
    assert sum(page.waits) >= 600


def test_submit_episode_js_fallback_accepts_submit_task_text(monkeypatch):
    page = _FakeSubmitJsFallbackPage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: False)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["complete_button_clicked"] is True
    assert page.js_submit_clicked is True


def test_browser_submit_verification_delegates_to_segments_submit_status(monkeypatch):
    page = _FakeSubmitNoEvidencePage()

    monkeypatch.setattr(
        segments,
        "_submit_episode",
        lambda page_obj, cfg_obj, episode_id="", return_details=False: {
            "submit_verified": True,
            "submit_verification_reason": "quality_review_confirmed",
            "complete_button_clicked": True,
            "submit_modal_already_open": False,
            "quality_review_confirmed": True,
        },
    )

    result = browser._click_submit_with_verification(page, {}, task_id="ep-submit", verify_timeout_sec=15.0)

    assert result["submit_clicked"] is True
    assert result["quality_modal_handled"] is True
    assert result["verification"]["verified"] is True
    assert result["verification"]["method"] == "quality_review_confirmed"


def test_submit_transition_detects_training_journey_page_content():
    page = _FakeSubmitTrainingJourneyPage()

    assert segments._submit_transition_observed(page) is True


def test_submit_transition_prefers_success_markers_over_stale_label_page_text():
    page = _FakeSubmitMixedTransitionPage()

    assert segments._submit_transition_observed(page) is False


def test_submit_transition_rejects_visible_no_edits_modal():
    page = _FakeSubmitNoEditsVisiblePage()

    assert segments._submit_transition_observed(page) is False


def test_submit_episode_recovers_back_to_tasks_after_room_transition(monkeypatch):
    page = _FakeSubmitRoomTransitionPage()
    cfg = {
        "atlas": {
            "room_url": "https://audit.atlascapture.io/tasks/room/normal",
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            },
        }
    }

    def _fake_safe_click(page_obj, selector, timeout_ms=0):
        if "Complete" in selector:
            page_obj.url = "https://audit.atlascapture.io/tasks/room/normal"
            return True
        return False

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", _fake_safe_click)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        browser,
        "_recover_room_access_disabled",
        lambda page_obj, cfg_obj, timeout_ms=0: setattr(page_obj, "url", "https://audit.atlascapture.io/tasks") or True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (False, False) if kwargs.get("return_details") else False,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["submit_verification_reason"] == "post_submit_transition_observed"
    assert result["page_url_after_submit"].endswith("/tasks")


def test_handle_quality_review_modal_accepts_body_prompt_without_role_dialog(monkeypatch):
    page = _FakeBodyScopedQualityReviewPage()
    cfg = {
        "run": {
            "enable_quality_review_submit": True,
            "capture_step_screenshots": False,
            "quality_review_submit_settle_sec": 30.0,
        },
        "atlas": {
            "selectors": {
                "quality_review_modal": "div[role='dialog']",
                "quality_review_checkbox": "input[type='checkbox'] || [role='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit') || button:has-text('Confirm')",
            }
        },
    }

    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)

    result = legacy_impl._handle_quality_review_modal(page, cfg, return_details=True)

    assert result == (True, True)
    assert page.checkbox.checked is True
    assert page.submit_button.clicks >= 1
    assert sum(page.waits) >= 30000


def test_handle_quality_review_modal_waits_when_checkbox_auto_accepts_without_submit_button(monkeypatch):
    page = _FakeBodyScopedQualityReviewAutoAcceptPage()
    cfg = {
        "run": {
            "enable_quality_review_submit": True,
            "capture_step_screenshots": False,
            "quality_review_submit_settle_sec": 30.0,
        },
        "atlas": {
            "selectors": {
                "quality_review_modal": "div[role='dialog']",
                "quality_review_checkbox": "input[type='checkbox'] || [role='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit') || button:has-text('Confirm')",
            }
        },
    }

    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)

    result = legacy_impl._handle_quality_review_modal(page, cfg, return_details=True)

    assert result == (True, True)
    assert page.checkbox.checked is True
    assert sum(page.waits) >= 30000


def test_is_authenticated_gemini_page_rejects_sign_in_splash():
    page = _FakeGeminiAuthPage(
        url="https://gemini.google.com/app",
        title="Google Gemini",
        body="Sign in Gemini Get access to all Gemini models Meet Gemini, your personal AI assistant",
        input_visible=True,
    )

    assert legacy_impl._is_authenticated_gemini_page(page) is False


def test_is_authenticated_gemini_page_accepts_real_composer_without_sign_in_copy():
    page = _FakeGeminiAuthPage(
        url="https://gemini.google.com/app/b3006ba9f325b55c",
        title="Google Gemini",
        body="Conversation with Gemini Atlas video annotation Tools",
        input_visible=True,
    )

    assert legacy_impl._is_authenticated_gemini_page(page) is True


def test_submit_episode_uses_strong_retry_when_complete_click_has_no_signal(monkeypatch):
    page = _FakeSubmitNoEvidencePage()
    cfg = {
        "atlas": {
            "selectors": {
                "complete_button": "button:has-text('Complete')",
                "quality_review_modal": "[data-testid='quality-modal']",
                "quality_review_checkbox": "input[type='checkbox']",
                "quality_review_submit_button": "button:has-text('Submit')",
            }
        }
    }
    retry_calls: list[str] = []

    monkeypatch.setattr(browser, "_dismiss_blocking_modals", lambda page_obj, cfg=None: None)
    monkeypatch.setattr(browser, "_dismiss_blocking_side_panel", lambda page_obj, cfg_obj, aggressive=False: None)
    monkeypatch.setattr(browser, "_safe_locator_click", lambda page_obj, selector, timeout_ms=0: True)
    monkeypatch.setattr(browser, "_first_visible_locator", lambda page_obj, selector, timeout_ms=0: None)
    monkeypatch.setattr(
        segments,
        "_handle_no_edits_modal",
        lambda page_obj, cfg_obj=None, timeout_ms=0, **kwargs: (True, False) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_handle_quality_review_modal",
        lambda page_obj, cfg_obj, timeout_ms=0, **kwargs: (True, True) if kwargs.get("return_details") else True,
    )
    monkeypatch.setattr(
        segments,
        "_force_primary_submit_click",
        lambda page_obj, selector: retry_calls.append(selector) or True,
    )

    result = legacy_impl._submit_episode(page, cfg, return_details=True)

    assert result["submit_verified"] is True
    assert result["complete_button_retried"] is True
    assert retry_calls == ["button:has-text('Complete')"]


def test_persist_submit_outcome_records_unverified_reason_and_debug_artifacts(monkeypatch):
    persisted: list[dict] = []

    def fake_persist_task_state_fields(cfg, task_id, task_state=None, **updates):
        merged = dict(task_state or {})
        merged.update(updates)
        persisted.append(dict(merged))
        if isinstance(task_state, dict):
            task_state.clear()
            task_state.update(merged)
            return task_state
        return merged

    monkeypatch.setattr(legacy_impl, "_persist_task_state_fields", fake_persist_task_state_fields)
    monkeypatch.setattr(
        legacy_impl,
        "_capture_debug_artifacts",
        lambda page_obj, cfg_obj, prefix="debug_submit_unverified": (
            Path("outputs/debug_submit_unverified.png"),
            Path("outputs/debug_submit_unverified.html"),
        ),
    )

    task_state: dict[str, object] = {}
    result = {
        "completed": False,
        "submit_status": {
            "submit_attempted": True,
            "submit_verified": False,
            "submit_verification_reason": "missing_verification_evidence",
            "page_url_before_submit": "https://audit.atlascapture.io/tasks/room/normal/label/abc",
            "page_url_after_submit": "https://audit.atlascapture.io/tasks/room/normal/label/abc",
            "complete_button_clicked": True,
            "complete_button_retried": True,
            "submit_modal_already_open": False,
            "saw_no_edits_modal": False,
            "saw_quality_review_modal": False,
            "saw_post_submit_transition": False,
            "no_edits_confirmed": False,
            "quality_review_confirmed": False,
            "manual_submit_watch_used": True,
            "manual_submit_detected": False,
            "manual_submit_watch_reason": "missing_verification_evidence",
            "manual_submit_watch_signal": "",
            "manual_submit_watch_timed_out": True,
            "manual_submit_watch_elapsed_sec": 12.5,
        },
        "submit_guard_blocked": False,
        "submit_guard_reasons": [],
    }

    updated = legacy_impl._persist_submit_outcome(
        {},
        "task123",
        task_state,
        result,
        page=object(),
        episode_submitted=False,
        last_error="submit_unverified:missing_verification_evidence",
    )

    assert updated["episode_submitted"] is False
    assert updated["submit_verified"] is False
    assert updated["submit_verification_reason"] == "missing_verification_evidence"
    assert updated["last_error"] == "submit_unverified:missing_verification_evidence"
    assert Path(updated["submit_debug_screenshot"]).as_posix() == "outputs/debug_submit_unverified.png"
    assert Path(updated["submit_debug_html"]).as_posix() == "outputs/debug_submit_unverified.html"
    assert persisted[-1]["submit_complete_button_clicked"] is True
    assert persisted[-1]["submit_complete_button_retried"] is True
    assert updated["submit_manual_watch_used"] is True
    assert updated["submit_manual_submit_detected"] is False
    assert updated["submit_manual_watch_reason"] == "missing_verification_evidence"
    assert updated["submit_manual_watch_timed_out"] is True
    assert updated["submit_manual_watch_elapsed_sec"] == 12.5


def test_call_gemini_labels_prioritizes_configured_primary_key_over_dotenv_pool(tmp_path: Path, monkeypatch):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")

    seen: dict[str, str] = {}

    monkeypatch.setenv("GEMINI_API_KEY", "paid-primary-key")
    monkeypatch.delenv("GEMINI_API_KEYS_PAID_POOL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_PAID_EPISODE_EVAL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_PAID_SECONDARY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS_FREE_POOL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_FREE_OPS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY2_FREE_OPS2", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_FREE_FALLBACK", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_FREE_FALLBACK2", raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool_signature", None)
    monkeypatch.setattr(legacy_impl, "_global_solver_key_pool", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL_SIGNATURE", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {
            "GEMINI_API_KEYS_POOL": "old-free-key-a,old-free-key-b",
            "GEMINI_API_KEY": "dotenv-primary-key",
        },
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_maybe_optimize_video_for_upload", lambda video_file, cfg: video_file)
    monkeypatch.setattr(legacy_impl, "_extract_reference_frame_inline_parts", lambda *args, **kwargs: ([], 0))

    class _StopAfterUpload(Exception):
        pass

    def _fake_upload(api_key: str, video_file: Path, cfg, connect_timeout_sec: int, request_timeout_sec: int):
        seen["api_key"] = api_key
        raise _StopAfterUpload()

    monkeypatch.setattr(legacy_impl, "_upload_video_via_gemini_files_api", _fake_upload)

    with pytest.raises(_StopAfterUpload):
        legacy_impl.call_gemini_labels(
            {
                "gemini": {
                    "model": "gemini-3.1-pro-preview",
                    "attach_video": True,
                    "require_video": True,
                    "video_transport": "files_api",
                    "files_api_fallback_to_inline": False,
                    "quota_fallback_enabled": False,
                    "prefer_fallback_key_as_primary": False,
                    "api_keys": [],
                }
            },
            "prompt",
            video_file=source_video,
            segment_count=3,
        )

    assert seen["api_key"] == "paid-primary-key"


def test_call_gemini_labels_preserves_round_robin_rotation_with_configured_primary_key(tmp_path: Path, monkeypatch):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")

    seen_keys: list[str] = []

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_PAID_EPISODE_EVAL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_PAID_SECONDARY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS_PAID_POOL", raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool_signature", None)
    monkeypatch.setattr(legacy_impl, "_global_solver_key_pool", None)
    monkeypatch.setenv("GEMINI_API_KEY_PAID_EPISODE_EVAL", "paid-primary-key")
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {"GEMINI_API_KEYS_PAID_POOL": "paid-primary-key,paid-secondary-key"},
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_maybe_optimize_video_for_upload", lambda video_file, cfg: video_file)
    monkeypatch.setattr(legacy_impl, "_extract_reference_frame_inline_parts", lambda *args, **kwargs: ([], 0))

    class _StopAfterUpload(Exception):
        pass

    def _fake_upload(api_key: str, video_file: Path, cfg, connect_timeout_sec: int, request_timeout_sec: int):
        seen_keys.append(api_key)
        raise _StopAfterUpload()

    monkeypatch.setattr(legacy_impl, "_upload_video_via_gemini_files_api", _fake_upload)

    cfg = {
        "gemini": {
            "model": "gemini-3.1-pro-preview",
            "attach_video": True,
            "require_video": True,
            "video_transport": "files_api",
            "files_api_fallback_to_inline": False,
            "quota_fallback_enabled": False,
            "prefer_fallback_key_as_primary": False,
            "api_keys": [],
            "rotation_policy": "round_robin",
        }
    }
    for _ in range(2):
        with pytest.raises(_StopAfterUpload):
            legacy_impl.call_gemini_labels(cfg, "prompt", video_file=source_video, segment_count=3)

    assert seen_keys == ["paid-primary-key", "paid-secondary-key"]


def test_call_gemini_labels_uses_paid_pool_only_for_pro_preview(tmp_path: Path, monkeypatch):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")

    seen: dict[str, str] = {}

    for env_name in [
        "GEMINI_API_KEYS_PAID_POOL",
        "GEMINI_API_KEY_PAID_EPISODE_EVAL",
        "GEMINI_API_KEY_PAID_SECONDARY",
        "GEMINI_API_KEYS_FREE_POOL",
        "GEMINI_API_KEY_FREE_OPS",
        "GEMINI_API_KEY2_FREE_OPS2",
        "GEMINI_API_KEY_FREE_FALLBACK",
        "GEMINI_API_KEY_FREE_FALLBACK2",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY_FALLBACK",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool_signature", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool_signature", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL_SIGNATURE", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {
            "GEMINI_API_KEY_PAID_EPISODE_EVAL": "paid-only-key",
            "GEMINI_API_KEYS_FREE_POOL": "free-a,free-b",
            "GEMINI_API_KEY_FREE_OPS": "free-primary",
        },
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_maybe_optimize_video_for_upload", lambda video_file, cfg: video_file)
    monkeypatch.setattr(legacy_impl, "_extract_reference_frame_inline_parts", lambda *args, **kwargs: ([], 0))

    class _StopAfterUpload(Exception):
        pass

    def _fake_upload(api_key: str, video_file: Path, cfg, connect_timeout_sec: int, request_timeout_sec: int):
        seen["api_key"] = api_key
        raise _StopAfterUpload()

    monkeypatch.setattr(legacy_impl, "_upload_video_via_gemini_files_api", _fake_upload)

    with pytest.raises(_StopAfterUpload):
        legacy_impl.call_gemini_labels(
            {
                "gemini": {
                    "model": "gemini-3.1-pro-preview",
                    "attach_video": True,
                    "require_video": True,
                    "video_transport": "files_api",
                    "files_api_fallback_to_inline": False,
                    "quota_fallback_enabled": True,
                    "api_keys": [],
                }
            },
            "prompt",
            video_file=source_video,
            segment_count=3,
            stage_name="compare_chat",
        )

    assert seen["api_key"] == "paid-only-key"


def test_call_gemini_labels_switches_key_on_503_unavailable(monkeypatch):
    for env_name in [
        "GEMINI_API_KEYS_PAID_POOL",
        "GEMINI_API_KEYS_POOL",
        "GEMINI_API_KEY_PAID_EPISODE_EVAL",
        "GEMINI_API_KEY_PAID_SECONDARY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY2",
        "GEMINI_API_KEY_FALLBACK",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEY_FALLBACK",
        "GEMINI_API_KEY_SECONDARY",
        "GOOGLE_API_KEY_SECONDARY",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool_signature", None)
    monkeypatch.setattr(legacy_impl, "_global_solver_key_pool", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {"GEMINI_API_KEYS_PAID_POOL": "paid-a,paid-b"},
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_parse_gemini_response", lambda raw: {"segments": []})
    monkeypatch.setattr(legacy_impl, "_log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_quota_cooldown", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_rate_limit", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_compute_backoff_delay", lambda cfg, attempt: 0.0)

    seen_headers: list[str] = []

    class _FakeResponse:
        def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen_headers.append(str((headers or {}).get("X-goog-api-key", "")))
        if len(seen_headers) == 1:
            return _FakeResponse(
                503,
                '{"error":{"code":503,"message":"This model is currently experiencing high demand.","status":"UNAVAILABLE"}}',
            )
        return _FakeResponse(
            200,
            "ok",
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"segments\": []}"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
            },
        )

    monkeypatch.setattr("src.solver.gemini.requests.post", _fake_post)

    result = legacy_impl.call_gemini_labels(
        {
            "gemini": {
                "model": "gemini-3.1-flash-lite-preview",
                "attach_video": False,
                "require_video": False,
                "quota_fallback_enabled": False,
                "api_keys": [],
                "rotation_policy": "round_robin",
                "max_retries": 1,
                "retry_switch_key_on_503": True,
            }
        },
        "prompt",
        video_file=None,
        segment_count=0,
    )

    assert seen_headers == ["paid-a", "paid-b"]
    assert result["_meta"]["api_key_source"] == "key_2"
    assert legacy_impl._global_solver_key_pool.is_key_temporarily_unavailable("paid-a") is True


def test_call_gemini_labels_switches_free_key_on_invalid_api_key(monkeypatch):
    for env_name in [
        "GEMINI_API_KEYS_FREE_POOL",
        "GEMINI_API_KEY_FREE_OPS",
        "GEMINI_API_KEY2_FREE_OPS2",
        "GEMINI_API_KEY_FREE_FALLBACK",
        "GEMINI_API_KEY_FREE_FALLBACK2",
        "GEMINI_API_KEY_OPS",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool_signature", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {},
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_parse_gemini_response", lambda raw: {"segments": []})
    monkeypatch.setattr(legacy_impl, "_log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_quota_cooldown", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_rate_limit", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_compute_backoff_delay", lambda cfg, attempt: 0.0)

    seen_headers: list[str] = []

    class _FakeResponse:
        def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen_headers.append(str((headers or {}).get("X-goog-api-key", "")))
        if len(seen_headers) == 1:
            return _FakeResponse(
                400,
                '{"error":{"code":400,"message":"API Key not found. Please pass a valid API key.","status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}',
            )
        return _FakeResponse(
            200,
            "ok",
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"segments\": []}"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
            },
        )

    monkeypatch.setattr("src.solver.gemini.requests.post", _fake_post)

    result = legacy_impl.call_gemini_labels(
        {
            "gemini": {
                "model": "gemini-2.5-flash",
                "attach_video": False,
                "require_video": False,
                "api_keys": ["free-bad", "free-good"],
                "rotation_policy": "sticky",
                "max_retries": 2,
            }
        },
        "prompt",
        video_file=None,
        segment_count=0,
    )

    assert seen_headers == ["free-bad", "free-good"]
    assert result["_meta"]["api_key_source"] == "key_2"
    assert result["_meta"]["api_key_class"] == "free"
    assert legacy_impl._solver_config._global_free_solver_key_pool.is_key_temporarily_unavailable("free-bad") is True


def test_request_labels_switches_2_5_flash_from_free_to_paid_on_first_429(monkeypatch):
    for env_name in [
        "GEMINI_API_KEYS_PAID_POOL",
        "GEMINI_API_KEY_PAID_EPISODE_EVAL",
        "GEMINI_API_KEY_PAID_SECONDARY",
        "GEMINI_API_KEYS_FREE_POOL",
        "GEMINI_API_KEY_FREE_OPS",
        "GEMINI_API_KEY2_FREE_OPS2",
        "GEMINI_API_KEY_FREE_FALLBACK",
        "GEMINI_API_KEY_FREE_FALLBACK2",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY_FALLBACK",
        "GOOGLE_API_KEY_FALLBACK",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_solver_key_pool_signature", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool_signature", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL", None)
    monkeypatch.setattr(gemini, "_STRICT_PAID_GEMINI_POOL_SIGNATURE", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {
            "GEMINI_API_KEYS_PAID_POOL": "paid-a",
            "GEMINI_API_KEYS_FREE_POOL": "free-a,free-b",
            "GEMINI_API_KEY_FREE_OPS": "free-primary",
        },
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_respect_gemini_quota_cooldown", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_rate_limit", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_compute_backoff_delay", lambda cfg, attempt: 0.0)

    persisted: list[dict] = []

    def fake_persist_task_state_fields(cfg, task_id, task_state=None, **updates):
        merged = dict(task_state or {})
        merged.update(updates)
        persisted.append(dict(merged))
        if isinstance(task_state, dict):
            task_state.clear()
            task_state.update(merged)
            return task_state
        return merged

    monkeypatch.setattr(legacy_impl, "_persist_task_state_fields", fake_persist_task_state_fields)

    seen_headers: list[str] = []

    class _FakeResponse:
        def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}
            self.headers = {}

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen_headers.append(str((headers or {}).get("X-goog-api-key", "")))
        if len(seen_headers) == 1:
            return _FakeResponse(
                429,
                '{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}',
            )
        return _FakeResponse(
            200,
            "ok",
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"segments\": []}"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 3994,
                    "candidatesTokenCount": 178,
                    "totalTokenCount": 4172,
                },
            },
        )

    monkeypatch.setattr("src.solver.gemini.requests.post", _fake_post)

    cfg = {
        "run": {
            "segment_chunking_enabled": False,
        },
        "gemini": {
            "model": "gemini-2.5-flash",
            "stage_models": {"labeling": "gemini-2.5-flash"},
            "attach_video": False,
            "require_video": False,
            "quota_fallback_enabled": True,
            "quota_fallback_max_uses_per_run": 2,
            "max_retries": 1,
        },
        "economics": {
            "episode_expected_revenue_usd": 0.50,
            "target_cost_ratio": 0.15,
            "hard_cost_ratio": 0.20,
        },
    }
    task_state: dict[str, object] = {}
    result = gemini._request_labels_with_optional_segment_chunking(
        cfg,
        [{"segment_index": 1, "start_sec": 0.0, "end_sec": 2.0, "current_label": "a"}],
        "prompt",
        None,
        allow_operations=False,
        task_id="ep_flash_paid_fallback",
        task_state=task_state,
        stage_name="labeling",
    )

    assert seen_headers == ["free-a", "paid-a"]
    assert result["_meta"]["api_key_class"] == "paid"
    assert result["_meta"]["episode_key_class_pin"] == "paid"
    assert task_state["episode_key_class_pin"] == "paid"
    assert task_state["episode_key_class_used"] == "paid"
    assert float(task_state["episode_estimated_cost_usd"]) > 0
    assert any(row.get("episode_key_class_pin") == "paid" for row in persisted)


def test_call_gemini_labels_retries_same_free_key_after_quota_429_when_enabled(monkeypatch):
    for env_name in [
        "GEMINI_API_KEYS_FREE_POOL",
        "GEMINI_API_KEY_FREE_OPS",
        "GEMINI_API_KEY2_FREE_OPS2",
        "GEMINI_API_KEY_FREE_FALLBACK",
        "GEMINI_API_KEY_FREE_FALLBACK2",
        "GEMINI_API_KEY_OPS",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool", None)
    monkeypatch.setattr(legacy_impl._solver_config, "_global_free_solver_key_pool_signature", None)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {},
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_parse_gemini_response", lambda raw: {"segments": []})
    monkeypatch.setattr(legacy_impl, "_log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_quota_cooldown", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_rate_limit", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_compute_backoff_delay", lambda cfg, attempt: 0.0)

    seen_headers: list[str] = []
    sleeps: list[float] = []

    class _FakeResponse:
        def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}
            self.headers = {}

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen_headers.append(str((headers or {}).get("X-goog-api-key", "")))
        if len(seen_headers) == 1:
            return _FakeResponse(
                429,
                '{"error":{"code":429,"message":"Quota exceeded. Please retry in 18 seconds.","status":"RESOURCE_EXHAUSTED"}}',
            )
        return _FakeResponse(
            200,
            "ok",
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"segments\": []}"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
            },
        )

    monkeypatch.setattr("src.solver.gemini.requests.post", _fake_post)
    monkeypatch.setattr("src.solver.gemini.time.sleep", lambda seconds: sleeps.append(seconds))

    result = legacy_impl.call_gemini_labels(
        {
            "gemini": {
                "model": "gemini-2.5-flash",
                "attach_video": False,
                "require_video": False,
                "api_keys": ["free-good"],
                "rotation_policy": "sticky",
                "max_retries": 1,
                "retry_on_quota_429": True,
            }
        },
        "prompt",
        video_file=None,
        segment_count=0,
    )

    assert seen_headers == ["free-good", "free-good"]
    assert sleeps == [18.0]
    assert result["_meta"]["api_key_source"] == "key_1"
    assert result["_meta"]["api_key_class"] == "free"


def test_call_gemini_labels_retries_http_200_with_empty_candidate_text(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        legacy_impl._solver_config,
        "_load_dotenv",
        lambda path: {"GEMINI_API_KEY": "test-key-1234567890"},
    )
    monkeypatch.setattr(legacy_impl, "_resolve_system_instruction", lambda cfg: "")
    monkeypatch.setattr(legacy_impl, "_build_gemini_generation_config", lambda cfg: {})
    monkeypatch.setattr(legacy_impl, "_log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_quota_cooldown", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_respect_gemini_rate_limit", lambda cfg: None)
    monkeypatch.setattr(legacy_impl, "_compute_backoff_delay", lambda cfg, attempt: 0.0)

    seen_attempts: list[int] = []

    class _FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self.text = json.dumps(payload)
            self._payload = payload

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen_attempts.append(len(seen_attempts) + 1)
        if len(seen_attempts) == 1:
            return _FakeResponse(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": ""}], "role": "model"}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 10, "totalTokenCount": 10},
                }
            )
        return _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"segments\": []}"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 11, "totalTokenCount": 12},
            }
        )

    monkeypatch.setattr("src.solver.gemini.requests.post", _fake_post)

    result = legacy_impl.call_gemini_labels(
        {
            "gemini": {
                "model": "gemini-3.1-flash-lite-preview",
                "attach_video": False,
                "require_video": False,
                "api_keys": [],
                "max_retries": 1,
            }
        },
        "prompt",
        video_file=None,
        segment_count=0,
    )

    assert seen_attempts == [1, 2]
    assert result["segments"] == []


def test_latest_task_id_from_output_dir_matches_ids_inside_prefixed_filenames(tmp_path: Path):
    outputs = tmp_path / "outputs" / "danatimer"
    outputs.mkdir(parents=True)
    older = outputs / "labels_6903ceb121c36d72378d9fa5.json"
    newer = outputs / "task_state_69041688c775f7b9567581bb.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    old_ts = newer.stat().st_mtime - 30
    os.utime(older, (old_ts, old_ts))

    latest = account_scheduler._latest_task_id_from_output_dir(tmp_path, "outputs/danatimer")

    assert latest == "69041688c775f7b9567581bb"


def test_request_labels_promotes_episode_model_and_pins_chunking_after_503(tmp_path: Path, monkeypatch):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"video")
    segments_in = [
        {"segment_index": 1, "start_sec": 0.0, "end_sec": 4.0, "current_label": "a"},
        {"segment_index": 2, "start_sec": 4.0, "end_sec": 8.0, "current_label": "b"},
        {"segment_index": 3, "start_sec": 8.0, "end_sec": 12.0, "current_label": "c"},
        {"segment_index": 4, "start_sec": 12.0, "end_sec": 16.0, "current_label": "d"},
    ]
    cfg = {
        "run": {
            "segment_chunking_enabled": True,
            "segment_chunking_min_segments": 4,
            "segment_chunking_min_video_sec": 0.0,
            "segment_chunking_max_segments_per_request": 2,
            "segment_chunking_max_window_sec": 0.0,
            "segment_chunking_disable_operations": True,
            "output_dir": str(tmp_path / "outputs"),
        },
        "gemini": {
            "model": "gemini-3.1-flash-lite-preview",
            "gen3_fallback_models": ["gemini-3.1-pro-preview"],
        },
    }
    seen_models: list[str] = []
    persisted: list[dict] = []

    def fake_call_gemini_labels(cfg, prompt, video_file=None, segment_count=0, model_override="", **kwargs):
        seen_models.append(str(model_override))
        if len(seen_models) == 1:
            raise RuntimeError(
                'Gemini HTTP 503: {"error":{"code":503,"message":"This model is currently experiencing high demand.","status":"UNAVAILABLE"}}'
            )
        return {
            "operations": [],
            "segments": [],
            "_meta": {
                "model": str(model_override),
                "video_attached": True,
                "mode": "with-video",
            },
        }

    def fake_persist_task_state_fields(cfg, task_id, task_state=None, **updates):
        merged = dict(task_state or {})
        merged.update(updates)
        persisted.append(dict(merged))
        if isinstance(task_state, dict):
            task_state.clear()
            task_state.update(merged)
            return task_state
        return merged

    monkeypatch.setattr(legacy_impl, "call_gemini_labels", fake_call_gemini_labels)
    monkeypatch.setattr(legacy_impl, "_persist_task_state_fields", fake_persist_task_state_fields)
    monkeypatch.setattr(legacy_impl, "_segment_duration_exceeds_limit", lambda *args, **kwargs: False)
    monkeypatch.setattr(legacy_impl, "_probe_video_duration_seconds", lambda *_args, **_kwargs: 120.0)
    monkeypatch.setattr(legacy_impl, "_resolve_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(
        legacy_impl,
        "_segment_chunks",
        lambda segs, *_args, **_kwargs: [list(segs[:2]), list(segs[2:])],
    )
    monkeypatch.setattr(legacy_impl, "_extract_video_window", lambda *args, **kwargs: False)
    monkeypatch.setattr(legacy_impl, "build_prompt", lambda segs, extra="", allow_operations=False, **kwargs: "prompt")
    monkeypatch.setattr(legacy_impl, "_collect_chunk_structural_operations", lambda **kwargs: [])
    monkeypatch.setattr(
        legacy_impl,
        "_normalize_segment_plan",
        lambda payload, segs, cfg=None: {
            int(seg["segment_index"]): {"segment_index": int(seg["segment_index"]), "label": f"label {int(seg['segment_index'])}"}
            for seg in segs
        },
    )
    monkeypatch.setattr(legacy_impl, "_rewrite_label_tier3", lambda text: text)
    monkeypatch.setattr(legacy_impl, "_normalize_label_min_safety", lambda text: text)

    task_state: dict[str, object] = {}
    result = gemini._request_labels_with_optional_segment_chunking(
        cfg,
        segments_in,
        "prompt",
        video_file,
        allow_operations=False,
        task_id="ep_fallback_chunk",
        task_state=task_state,
    )

    assert seen_models == [
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview",
    ]
    assert result["_meta"]["model"] == "gemini-3.1-pro-preview"
    assert result["_meta"]["episode_model_escalated"] is True
    assert task_state["episode_active_model"] == "gemini-3.1-pro-preview"
    assert task_state["episode_model_escalated"] is True
    assert any(row.get("episode_active_model") == "gemini-3.1-pro-preview" for row in persisted)


def test_request_labels_records_exhausted_gen3_fallback_on_repeated_503(monkeypatch):
    cfg = {
        "run": {
            "segment_chunking_enabled": False,
        },
        "gemini": {
            "model": "gemini-3.1-flash-lite-preview",
            "gen3_fallback_models": ["gemini-3.1-pro-preview"],
        },
    }
    persisted: list[dict] = []

    def fake_call_gemini_labels(cfg, prompt, video_file=None, segment_count=0, model_override="", **kwargs):
        raise RuntimeError(
            'Gemini HTTP 503: {"error":{"code":503,"message":"This model is currently experiencing high demand.","status":"UNAVAILABLE"}}'
        )

    def fake_persist_task_state_fields(cfg, task_id, task_state=None, **updates):
        merged = dict(task_state or {})
        merged.update(updates)
        persisted.append(dict(merged))
        if isinstance(task_state, dict):
            task_state.clear()
            task_state.update(merged)
            return task_state
        return merged

    monkeypatch.setattr(legacy_impl, "call_gemini_labels", fake_call_gemini_labels)
    monkeypatch.setattr(legacy_impl, "_persist_task_state_fields", fake_persist_task_state_fields)

    task_state: dict[str, object] = {}
    with pytest.raises(RuntimeError, match="Gemini HTTP 503"):
        gemini._request_labels_with_optional_segment_chunking(
            cfg,
            [{"segment_index": 1, "start_sec": 0.0, "end_sec": 2.0, "current_label": "a"}],
            "prompt",
            None,
            allow_operations=False,
            task_id="ep_fallback_exhausted",
            task_state=task_state,
        )

    assert task_state["episode_active_model"] == "gemini-3.1-pro-preview"
    assert "episode_fallback_reason" in task_state
    assert "Gen3 model fallback exhausted" in str(task_state["episode_fallback_reason"])
    assert any("Gen3 model fallback exhausted" in str(row.get("episode_fallback_reason", "")) for row in persisted)
