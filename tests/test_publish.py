"""Unit tests for the publish-step push retry.

The push is the last thing in a long build, so these cover the failure that
costs the most: a finished tile pyramid thrown away by a resolver blip.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import publish as pub  # noqa: E402

RESOLVER_FAILURE = (
    "git push --force origin gh-pages failed (exit 128):\n"
    "fatal: unable to access 'https://github.com/skfd/toronto-parks-layer.git/': "
    "Could not resolve host: github.com"
)
REJECTED = (
    "git push --force origin gh-pages failed (exit 1):\n"
    " ! [rejected] gh-pages -> gh-pages (non-fast-forward)"
)


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(pub, "PUSH_WAIT", 0)


@pytest.fixture(autouse=True)
def usable_link(monkeypatch):
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)


def failing_git(calls, message, fail_times=99):
    def git(args, env):
        calls.append(args)
        if len(calls) <= fail_times:
            raise RuntimeError(message)
        return ""
    return git


def test_a_resolver_failure_is_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(pub, "_git", failing_git(calls, RESOLVER_FAILURE, fail_times=2))

    pub._push({})

    assert len(calls) == 3  # two blips, then through


def test_a_rejected_push_is_not_retried(monkeypatch):
    # A rejected push fails the same way every time. Surface it now rather than
    # ten minutes from now.
    calls = []
    monkeypatch.setattr(pub, "_git", failing_git(calls, REJECTED))

    with pytest.raises(RuntimeError):
        pub._push({})
    assert len(calls) == 1


def test_offline_at_the_push_surfaces_as_link_unavailable(monkeypatch):
    # The build is finished and on disk. Naming this a dead link exits 75, and
    # 'run.py publish' can finish the job later without rebuilding the pyramid.
    calls = []
    monkeypatch.setattr(pub, "_git", failing_git(calls, RESOLVER_FAILURE))
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )

    with pytest.raises(net.Offline):
        pub._push({})
    assert len(calls) == pub.PUSH_RETRIES + 1
