"""Publish build/site/ to the orphan gh-pages branch (single commit, force-push).

The staging, the orphan commit and the push retry are layerkit.publish; this
module binds them to this layer's paths. ``_git``, ``_push`` and ``PUSH_WAIT``
stay here because the tests stand in for them.
"""

from layerkit import publish as _kit

from src import config

PUSH_RETRIES = _kit.PUSH_RETRIES
PUSH_WAIT = _kit.PUSH_WAIT


def publish():
    """Commit build/site/ as a single orphan commit on gh-pages and force-push."""
    _kit.publish(config.PROJECT_DIR, config.SITE_DIR, config.BUILD_DIR,
                 git=_git, push_fn=_push)


def _push(env):
    """Force-push gh-pages, retrying a network failure."""
    _kit.push(env, git=_git, retries=PUSH_RETRIES, wait=PUSH_WAIT)


def _git(args, env):
    return _kit.run_git(config.PROJECT_DIR, args, env)
