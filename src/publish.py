"""Publish build/site/ to the orphan gh-pages branch (single commit, force-push).

The tile pyramid is tens of thousands of files. To avoid copying them all
into a worktree, this stages them in place with a temporary index and
GIT_WORK_TREE, builds an orphan commit with git plumbing, and force-pushes it.
Each publish replaces the branch tip, so repository history never grows.
"""

import os
import subprocess
from datetime import date

from src import config

GH_PAGES_INDEX = os.path.join(config.BUILD_DIR, ".gh-pages-index")


def publish():
    """Commit build/site/ as a single orphan commit on gh-pages and force-push."""
    if not os.path.isdir(config.SITE_DIR):
        raise RuntimeError(f"No site to publish: {config.SITE_DIR}. Run 'site' first.")

    env = {
        **os.environ,
        "GIT_DIR": os.path.join(config.PROJECT_DIR, ".git"),
        "GIT_WORK_TREE": config.SITE_DIR,
        "GIT_INDEX_FILE": GH_PAGES_INDEX,
    }
    if os.path.exists(GH_PAGES_INDEX):
        os.remove(GH_PAGES_INDEX)

    print("Staging site files ...")
    _git(["add", "-A"], env)
    tree = _git(["write-tree"], env).strip()
    commit = _git(
        ["commit-tree", tree, "-m", f"site {date.today().isoformat()}"], env
    ).strip()
    _git(["update-ref", "refs/heads/gh-pages", commit], env)

    print("Force-pushing gh-pages ...")
    _git(["push", "--force", "origin", "gh-pages"], env)

    os.remove(GH_PAGES_INDEX)
    print("Published to the gh-pages branch.")


def _git(args, env):
    result = subprocess.run(
        ["git", *args],
        cwd=config.PROJECT_DIR,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout
