"""Unit tests for the pilot safety rails (refuse-list + cost cap)."""
from __future__ import annotations

import pytest

from app.pilot.safety import cost_cap_exceeded, is_repo_refused

# ---------------------------------------------------------------------------
# is_repo_refused
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_empty_refuse_list_allows_everything():
    assert is_repo_refused("acme/widget", refuse_list="") is False
    assert is_repo_refused("acme/widget", refuse_list="   ") is False


@pytest.mark.unit
def test_owner_entry_blocks_all_their_repos():
    rl = "blocked-org"
    assert is_repo_refused("blocked-org/repo-a", refuse_list=rl) is True
    assert is_repo_refused("blocked-org/repo-b", refuse_list=rl) is True
    assert is_repo_refused("other-org/repo-a", refuse_list=rl) is False


@pytest.mark.unit
def test_full_slug_entry_blocks_only_that_repo():
    rl = "acme/secret-repo"
    assert is_repo_refused("acme/secret-repo", refuse_list=rl) is True
    assert is_repo_refused("acme/public-repo", refuse_list=rl) is False


@pytest.mark.unit
def test_matching_is_case_insensitive():
    assert is_repo_refused("ACME/Widget", refuse_list="acme/widget") is True
    assert is_repo_refused("acme/widget", refuse_list="ACME/WIDGET") is True
    assert is_repo_refused("Blocked-Org/x", refuse_list="blocked-org") is True


@pytest.mark.unit
def test_multiple_entries():
    rl = "org-a, org-b/repo, org-c"
    assert is_repo_refused("org-a/anything", refuse_list=rl) is True
    assert is_repo_refused("org-b/repo", refuse_list=rl) is True
    assert is_repo_refused("org-b/other", refuse_list=rl) is False
    assert is_repo_refused("org-c/x", refuse_list=rl) is True
    assert is_repo_refused("org-d/x", refuse_list=rl) is False


@pytest.mark.unit
def test_whitespace_around_entries_is_trimmed():
    rl = "  org-a ,  org-b/repo  "
    assert is_repo_refused("org-a/x", refuse_list=rl) is True
    assert is_repo_refused("org-b/repo", refuse_list=rl) is True


# ---------------------------------------------------------------------------
# cost_cap_exceeded
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cost_cap_zero_means_unlimited(session, make_logged_in_user, monkeypatch):
    from app.pilot import safety as safety_mod
    user = make_logged_in_user()
    monkeypatch.setattr(safety_mod.settings, "max_user_cost_usd", 0.0)
    exceeded, spent, cap = cost_cap_exceeded(session, user.id)
    assert exceeded is False
    assert cap == 0.0


@pytest.mark.unit
def test_cost_cap_not_exceeded_when_under(session, make_logged_in_user, monkeypatch):
    from app.db.models import AgentRun
    from app.pilot import safety as safety_mod
    user = make_logged_in_user()
    session.add(AgentRun(
        user_id=user.id, agent_name="x", provider="gemini",
        model="m", cost_usd=0.5,
    ))
    session.commit()
    monkeypatch.setattr(safety_mod.settings, "max_user_cost_usd", 5.0)
    exceeded, spent, cap = cost_cap_exceeded(session, user.id)
    assert exceeded is False
    assert spent == pytest.approx(0.5)
    assert cap == 5.0


@pytest.mark.unit
def test_cost_cap_exceeded_when_over(session, make_logged_in_user, monkeypatch):
    from app.db.models import AgentRun
    from app.pilot import safety as safety_mod
    user = make_logged_in_user()
    for _ in range(3):
        session.add(AgentRun(
            user_id=user.id, agent_name="x", provider="gemini",
            model="m", cost_usd=2.0,
        ))
    session.commit()
    monkeypatch.setattr(safety_mod.settings, "max_user_cost_usd", 5.0)
    exceeded, spent, cap = cost_cap_exceeded(session, user.id)
    assert exceeded is True
    assert spent == pytest.approx(6.0)


@pytest.mark.unit
def test_cost_cap_isolated_per_user(session, make_logged_in_user, monkeypatch):
    """One user's spend doesn't count against another's cap."""
    from app.db.models import AgentRun, User
    from app.pilot import safety as safety_mod
    user = make_logged_in_user(github_login="spender", github_id=1)
    other = User(github_login="thrifty", github_id=2, name=None)
    session.add(other)
    session.flush()
    session.add(AgentRun(
        user_id=user.id, agent_name="x", provider="gemini",
        model="m", cost_usd=10.0,
    ))
    session.commit()
    monkeypatch.setattr(safety_mod.settings, "max_user_cost_usd", 5.0)

    assert cost_cap_exceeded(session, user.id)[0] is True
    # The thrifty user has spent nothing.
    assert cost_cap_exceeded(session, other.id)[0] is False
