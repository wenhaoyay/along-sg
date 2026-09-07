import pytest
from tools.benchmark_journeys import run


@pytest.mark.asyncio
async def test_fixed_catalog_benchmark_is_reproducible_and_bounded():
    first, second = await run(), await run()
    assert first['catalog_sha256'] == second['catalog_sha256']
    assert len(first['cases']) == 6
    assert not first['human_reviewed'] and not first['live_verified']
    for before, after in zip(first['cases'], second['cases']):
        assert before['human_review'] is None
        assert before['diagnostics']['routing_call_count'] <= 18
        assert before['outcome'] == 'recommendation'
        for field in ('stops', 'total_minutes', 'detour_minutes', 'walking_m', 'transfers'):
            assert before[field] == after[field]
