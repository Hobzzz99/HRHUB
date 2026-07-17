"""Tests for skill normalization and matching."""

from __future__ import annotations

import pytest

from app.domain.skills import match_skills, normalize_skill


def test_full_match():
    required = ["Python", "FastAPI", "Docker", "AWS"]
    candidate = ["Python", "FastAPI", "Docker", "AWS", "Kubernetes"]
    result = match_skills(required, candidate)
    assert result.matched == ["Python", "FastAPI", "Docker", "AWS"]
    assert result.missing == []
    assert result.ratio == pytest.approx(1.0)


def test_partial_match():
    required = ["Python", "FastAPI", "Docker", "AWS"]
    candidate = ["Python", "Flask", "Docker", "Azure"]
    result = match_skills(required, candidate)
    assert set(result.matched) == {"Python", "Docker"}
    assert set(result.missing) == {"FastAPI", "AWS"}
    assert result.ratio == pytest.approx(0.5)


def test_no_required_is_full_credit():
    result = match_skills([], ["Python"])
    assert result.ratio == 1.0
    assert result.matched == []


@pytest.mark.parametrize(
    "variant,canonical",
    [
        ("JS", "javascript"),
        ("js", "javascript"),
        ("React.js", "react"),
        ("nodejs", "node.js"),
        ("Postgres", "postgresql"),
        ("K8s", "kubernetes"),
        ("Golang", "go"),
    ],
)
def test_alias_normalization(variant, canonical):
    assert normalize_skill(variant) == canonical


def test_match_uses_aliases():
    result = match_skills(["JavaScript", "Kubernetes"], ["JS", "k8s"])
    assert result.missing == []
    assert result.ratio == pytest.approx(1.0)


def test_case_and_whitespace_insensitive():
    result = match_skills(["  python "], ["PYTHON"])
    assert result.matched == ["python"]
    assert result.ratio == 1.0
