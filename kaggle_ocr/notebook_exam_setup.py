"""One-import bootstrap for the DOCX exam preview UI on Kaggle.

Upload this file to a notebook (or import it from the cloned repository), then::

    from notebook_exam_setup import launch
    ui = launch()

The first call clones the project when needed, installs missing lightweight
dependencies, makes the source directories importable, and displays the upload
UI.  Later calls reuse the same checkout and installed packages.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any, Callable


REPOSITORY = "https://github.com/qavahoai19-cmd/docx-extract.git"
DEFAULT_ROOT = Path("/kaggle/working/docx-extract")

_DEPENDENCIES = {
    "lxml": "lxml",
    "PIL": "Pillow",
    "olefile": "olefile",
    "requests": "requests",
    "ipywidgets": "ipywidgets",
}

_PROJECT_MODULES = {
    "exam_print",
    "notebook_upload",
    "ocr_logic",
    "preserve_upload",
    "question_extract",
}


def ensure_repository(
    root: str | Path = DEFAULT_ROOT,
    *,
    repository: str = REPOSITORY,
    update: bool = False,
) -> Path:
    """Clone the project once and optionally fast-forward an existing clone."""
    root = Path(root)

    if not root.exists():
        print(f"Dang tai project vao {root} ...", flush=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", repository, str(root)],
            check=True,
        )
    elif update:
        if not (root / ".git").is_dir():
            raise RuntimeError(f"{root} ton tai nhung khong phai Git repository")
        print("Dang cap nhat project ...", flush=True)
        subprocess.run(
            ["git", "-C", str(root), "pull", "--ff-only"],
            check=True,
        )

    required = (
        root / "src" / "docx_extract",
        root / "kaggle_ocr" / "preserve_upload.py",
        root / "colab_ocr_server" / "ocr_logic.py",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Project bi thieu file: " + ", ".join(missing))

    return root


def install_missing_dependencies() -> list[str]:
    """Install only packages that are absent from the current kernel."""
    missing = [
        package
        for module, package in _DEPENDENCIES.items()
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        return []

    print("Dang cai dependency: " + ", ".join(missing), flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            *missing,
        ],
        check=True,
    )
    importlib.invalidate_caches()
    return missing


def add_project_paths(root: str | Path = DEFAULT_ROOT) -> list[Path]:
    """Put all three source roots on ``sys.path`` in a stable order."""
    root = Path(root)
    paths = [
        root / "kaggle_ocr",
        root / "src",
        root / "colab_ocr_server",
    ]

    for path in reversed(paths):
        value = str(path)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)

    importlib.invalidate_caches()
    return paths


def clear_project_modules() -> None:
    """Remove earlier or partially imported project modules from the kernel."""
    for name in list(sys.modules):
        if name in _PROJECT_MODULES or name.startswith("docx_extract"):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()


def load(
    root: str | Path = DEFAULT_ROOT,
    *,
    repository: str = REPOSITORY,
    update: bool = False,
    install: bool = True,
    reload_modules: bool = True,
) -> ModuleType:
    """Prepare the notebook and return the imported ``preserve_upload`` module."""
    root = ensure_repository(root, repository=repository, update=update)
    if install:
        install_missing_dependencies()
    add_project_paths(root)
    if reload_modules:
        clear_project_modules()

    module = importlib.import_module("preserve_upload")
    print(f"Da nap preserve_upload tu {module.__file__}", flush=True)
    return module


def launch(
    root: str | Path = DEFAULT_ROOT,
    *,
    repository: str = REPOSITORY,
    update: bool = False,
    install: bool = True,
    reload_modules: bool = True,
    print_page: Callable[..., str] | None = None,
    select_markup: Callable[..., str] | None = None,
    sample: str | Path | None = None,
    samples: list[Any] | None = None,
) -> dict[str, Any]:
    """Display the DOCX/ZIP upload UI and return its state dictionary."""
    root = Path(root)
    module = load(
        root,
        repository=repository,
        update=update,
        install=install,
        reload_modules=reload_modules,
    )

    if print_page is not None:
        module.print_page = print_page
    if select_markup is not None:
        module.select_markup = select_markup

    return module.show_preserve_ui(root, sample=sample, samples=samples)


__all__ = [
    "DEFAULT_ROOT",
    "REPOSITORY",
    "add_project_paths",
    "clear_project_modules",
    "ensure_repository",
    "install_missing_dependencies",
    "launch",
    "load",
]
