from __future__ import annotations

import os
import fnmatch
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_OUTPUT_FILENAME = "Atlas_Project_Colab.zip"
DEFAULT_MANIFEST_FILENAME = "Atlas_Project_Colab_manifest.txt"

# Keep Colab uploads lean and avoid bundling local runtime state or secrets.
IGNORE_GLOBS: Sequence[str] = (
    ".git",
    ".git/*",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    "__pycache__",
    "__pycache__/*",
    ".pytest_cache",
    ".pytest_cache/*",
    ".mypy_cache",
    ".mypy_cache/*",
    ".idea",
    ".idea/*",
    ".vscode",
    ".vscode/*",
    ".archive",
    ".archive/*",
    "_archive",
    "_archive/*",
    ".agent",
    ".agent/*",
    ".claude",
    ".claude/*",
    ".junie",
    ".junie/*",
    ".specify",
    ".specify/*",
    ".state",
    ".state/*",
    "outputs",
    "outputs/*",
    "outputs_test",
    "outputs_test/*",
    "discord",
    "discord/*",
    "logs",
    "logs/*",
    "tmp",
    "tmp/*",
    "tmp_*",
    "tmp_*/*",
    "node_modules",
    "node_modules/*",
    "offline_packages",
    "offline_packages/*",
    "scribe_sessions",
    "scribe_sessions/*",
    "*.pyc",
    "*.pyo",
    "*.zip",
    "*.mp4",
    "*.webm",
    "*.mkv",
    "*.avi",
    "*.mov",
    "*.pdf",
    "*.docx",
    DEFAULT_MANIFEST_FILENAME,
    ".env",
    ".env.*",
    "project-*.json",
    "*service-account*.json",
    "secrets/*.json",
    "*.pem",
    "*.key",
)


def _matches_any_glob(rel_posix_path: str, name: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix_path, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def should_include_path(project_root: Path, path: Path, *, ignore_globs: Sequence[str] = IGNORE_GLOBS) -> bool:
    rel_path = path.relative_to(project_root)
    rel_posix = rel_path.as_posix()

    # Ignore any path once a sensitive or bulky parent directory appears.
    for part in rel_path.parts:
        if _matches_any_glob(part, part, ignore_globs):
            return False

    return not _matches_any_glob(rel_posix, path.name, ignore_globs)


def build_colab_file_list(project_root: Path, *, ignore_globs: Sequence[str] = IGNORE_GLOBS) -> List[Path]:
    files: List[Path] = []

    def _on_walk_error(exc: OSError) -> None:
        print(f"[package] warning: skipping inaccessible path: {exc}")

    for root, dirs, filenames in os.walk(project_root, topdown=True, onerror=_on_walk_error, followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            dirname
            for dirname in dirs
            if should_include_path(project_root, root_path / dirname, ignore_globs=ignore_globs)
        ]
        for filename in filenames:
            path = root_path / filename
            if should_include_path(project_root, path, ignore_globs=ignore_globs):
                files.append(path)
    return sorted(files)


def write_manifest(project_root: Path, packaged_files: Iterable[Path], manifest_path: Path) -> None:
    lines = ["Atlas Project Colab package manifest", ""]
    for file_path in packaged_files:
        lines.append(file_path.relative_to(project_root).as_posix())
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_colab_package(
    output_filename: str = DEFAULT_OUTPUT_FILENAME,
    *,
    manifest_filename: str = DEFAULT_MANIFEST_FILENAME,
    ignore_globs: Sequence[str] = IGNORE_GLOBS,
) -> Path:
    project_root = Path(__file__).parent.resolve()
    output_path = project_root / output_filename
    manifest_path = project_root / manifest_filename

    files_to_package = build_colab_file_list(project_root, ignore_globs=ignore_globs)
    write_manifest(project_root, files_to_package, manifest_path)

    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files_to_package:
            archive.write(file_path, file_path.relative_to(project_root))

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[package] wrote {output_path.name} with {len(files_to_package)} files ({file_size_mb:.2f} MB)")
    print(f"[package] manifest: {manifest_path.name}")
    return output_path


if __name__ == "__main__":
    create_colab_package()
