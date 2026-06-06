"""Unit tests for should_use_cache — pure decision logic, no DB/API."""

import pytest

from core.semantic_cache import should_use_cache


@pytest.mark.asyncio
async def test_no_cache_entry():
    ok, reason = await should_use_cache(None, "restaurants")
    assert ok is False
    assert reason == "no_cache_entry"


@pytest.mark.asyncio
async def test_high_confidence_fresh():
    ok, reason = await should_use_cache({"similarity": 0.95, "age_days": 5}, "restaurants")
    assert ok is True
    assert "high_confidence" in reason


@pytest.mark.asyncio
async def test_good_match_recent():
    # restaurants max_age 30 → good_match needs age <= 15
    ok, reason = await should_use_cache({"similarity": 0.82, "age_days": 10}, "restaurants")
    assert ok is True
    assert "good_match" in reason


@pytest.mark.asyncio
async def test_stale_data_rejected():
    ok, reason = await should_use_cache({"similarity": 0.95, "age_days": 40}, "restaurants")
    assert ok is False
    assert "stale" in reason


@pytest.mark.asyncio
async def test_low_confidence_rejected():
    ok, reason = await should_use_cache({"similarity": 0.60, "age_days": 5}, "restaurants")
    assert ok is False
    assert "low_confidence" in reason


@pytest.mark.asyncio
async def test_hotels_have_shorter_freshness():
    # hotels max_age 14, so 20 days is stale even at high similarity
    ok, reason = await should_use_cache({"similarity": 0.95, "age_days": 20}, "hotels")
    assert ok is False
    assert "stale" in reason
