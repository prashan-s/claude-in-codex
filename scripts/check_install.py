"""Check installer idempotency and removal without touching the user's setup."""

import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="cic-install-") as tmp:
        root = Path(tmp)
        codex_home = root / "codex"
        bin_dir = root / "bin"
        cic_home = root / "cic"
        env = dict(os.environ, CODEX_HOME=str(codex_home), CIC_BIN_DIR=str(bin_dir),
                   CIC_HOME=str(cic_home), CIC_CLAUDE_BIN="/nonexistent/claude",
                   CIC_CODEX_BIN="/nonexistent/codex", CIC_GEMINI_BIN="/nonexistent/gemini")
        # Existing user-owned skills must survive both installation and removal.
        owned = codex_home / "skills" / "claude-review"
        owned.mkdir(parents=True)
        marker = owned / "keep.txt"
        marker.write_text("user-owned\n")
        for _ in range(2):
            subprocess.run(["bash", str(ROOT / "install.sh"), "--no-rules"], env=env, check=True)
        assert (bin_dir / "cic").resolve() == ROOT / "bin" / "cic"
        for skill in (ROOT / "skills").iterdir():
            if skill.is_dir() and skill.name != owned.name:
                assert (codex_home / "skills" / skill.name).resolve() == skill
        assert not (codex_home / "rules" / "claude-in-codex.rules").exists()
        subprocess.run([str(bin_dir / "cic"), "--help"], env=env, check=True, stdout=subprocess.DEVNULL)
        cic_home.mkdir(exist_ok=True)
        history = cic_home / "keep.txt"
        history.write_text("history\n")
        subprocess.run(["bash", str(ROOT / "uninstall.sh")], env=env, check=True)
        assert not (bin_dir / "cic").is_symlink()
        assert not any(path.is_symlink() for path in (codex_home / "skills").iterdir())
        assert marker.read_text() == "user-owned\n"
        assert history.read_text() == "history\n"
    print("Installer checks passed")


if __name__ == "__main__":
    main()
