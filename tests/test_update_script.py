from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_generated_backups_are_ignored_by_git():
    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "/backups/" in patterns or "backups/" in patterns


def test_update_script_is_valid_and_reports_dirty_files():
    script_path = ROOT / "scripts" / "update.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(script_path)], check=True)

    assert "git status --short --untracked-files=normal" in script
    assert "Файлы не будут сброшены или удалены автоматически" in script
    assert "git reset --hard" in script  # warning only
    assert "git clean" in script  # warning only
    assert script.index("./scripts/backup.sh") < script.index("git fetch")
    assert "git merge --ff-only origin/main" in script
