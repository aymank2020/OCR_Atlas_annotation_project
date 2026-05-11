from pathlib import Path

from package_for_colab import build_colab_file_list, should_include_path


def test_should_include_path_filters_secrets_and_runtime_artifacts(tmp_path: Path):
    keep_file = tmp_path / "src" / "module.py"
    keep_file.parent.mkdir(parents=True, exist_ok=True)
    keep_file.write_text("print('ok')\n", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1\n", encoding="utf-8")

    service_account = tmp_path / "project-123.json"
    service_account.write_text('{"type":"service_account"}\n', encoding="utf-8")

    node_module = tmp_path / "node_modules" / "leftpad" / "index.js"
    node_module.parent.mkdir(parents=True, exist_ok=True)
    node_module.write_text("module.exports = 1;\n", encoding="utf-8")

    assert should_include_path(tmp_path, keep_file) is True
    assert should_include_path(tmp_path, env_file) is False
    assert should_include_path(tmp_path, service_account) is False
    assert should_include_path(tmp_path, node_module) is False


def test_build_colab_file_list_keeps_code_and_skips_heavy_outputs(tmp_path: Path):
    files = {
        "atlas_web_auto_solver.py": "print('solver')\n",
        "requirements.txt": "pytest\n",
        "outputs/demo.json": "{}\n",
        "logs/runtime.log": "hello\n",
        "data/sample.txt": "ok\n",
        "Atlas_Project_Colab.zip": "oldzip\n",
    }
    for rel_path, content in files.items():
        file_path = tmp_path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    packaged = [path.relative_to(tmp_path).as_posix() for path in build_colab_file_list(tmp_path)]

    assert "atlas_web_auto_solver.py" in packaged
    assert "requirements.txt" in packaged
    assert "data/sample.txt" in packaged
    assert "outputs/demo.json" not in packaged
    assert "logs/runtime.log" not in packaged
    assert "Atlas_Project_Colab.zip" not in packaged


def test_real_project_colab_package_keeps_new_scheduler_and_configs():
    root = Path(__file__).resolve().parents[1]
    packaged = {path.relative_to(root).as_posix() for path in build_colab_file_list(root)}

    assert "atlas_multi_account_runner.py" in packaged
    assert "configs/production_hetzner.yaml" in packaged
    assert "configs/accounts/index.yaml" in packaged
    assert "configs/accounts/danatimer.yaml" in packaged
    assert "configs/accounts/wafaabayoumi.yaml" in packaged
