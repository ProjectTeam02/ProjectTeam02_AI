from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_required_directories_exist() -> None:
    for name in ("app", "migrations", "scripts", "notebook", "data", "integration", "docs"):
        assert (PROJECT_ROOT / name).is_dir()
