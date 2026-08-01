"""Publish build/site/ to the orphan gh-pages branch (single commit, force-push).

The tile pyramid is tens of thousands of files. To avoid copying them all
into a worktree, this stages them in place with a temporary index and
GIT_WORK_TREE, builds an orphan commit with git plumbing, and force-pushes it.
Each publish replaces the branch tip, so repository history never grows.
"""

import os
import re
import subprocess
import time
from datetime import date

from addressvault import net

from src import config

GH_PAGES_INDEX = os.path.join(config.BUILD_DIR, ".gh-pages-index")

# Publishing is the last step of a long build, so a blip here is the most
# expensive failure in the project: the streets sibling lost a finished 150k-tile
# pyramid on 2026-07-27 to a push that could not resolve github.com. Retry the
# push rather than the build.
PUSH_RETRIES = 2
PUSH_WAIT = 300
# Only network failures are worth retrying. A rejected push or a bad credential
# fails the same way every time, and should surface now instead of ten minutes
# from now.
_NETWORK_ERR = re.compile(
    r"could not resolve host|unable to access|failed to connect"
    r"|connection timed out|operation timed out|connection reset",
    re.I,
)


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
    _push(env)

    os.remove(GH_PAGES_INDEX)
    print("Published to the gh-pages branch.")


def _push(env):
    """Force-push gh-pages, retrying a network failure.

    The commit is already written to refs/heads/gh-pages locally by the time we
    get here, so a retry costs one round-trip -- and giving up leaves the build
    on disk for a later ``run.py publish`` rather than requiring a rebuild.
    Raises ``net.LinkUnavailable`` if the link is what died, so the caller can
    exit 75: an unreachable github.com is not a failed build.
    """
    for attempt in range(PUSH_RETRIES + 1):
        try:
            _git(["push", "--force", "origin", "gh-pages"], env)
            return
        except RuntimeError as e:
            if not _NETWORK_ERR.search(str(e)):
                raise
            if attempt == PUSH_RETRIES:
                net.wait_for_link(wait=False)
                raise
            print(f"  push failed ({e.args[0].splitlines()[-1]});"
                  f" retrying in {PUSH_WAIT}s")
            time.sleep(PUSH_WAIT)


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
