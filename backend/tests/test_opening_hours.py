from datetime import datetime

import pytest

from app.services.opening_hours import check_hours


@pytest.mark.parametrize('hours,arrival,dwell,expected', [
    ('24/7', '2026-09-07T03:00:00+08:00', 15, 'open'),
    ('Mo-Fr 09:00-22:00', '2026-09-07T21:50:00+08:00', 15, 'closing_soon'),
    ('Mo-Fr 09:00-22:00', '2026-09-07T22:00:00+08:00', 15, 'closed'),
    ('Mo-Fr 09:00-22:00', '2026-09-06T12:00:00+08:00', 15, 'closed'),
    ('Mo 22:00-02:00', '2026-09-08T01:00:00+08:00', 15, 'open'),
    ('09:00-22:00', '2026-09-07T01:00:00+00:00', 15, 'open'),
    ('09:00-22:00', '2026-09-07T09:00:00', 15, 'open'),
    ('09:00-22:00; Su off', '2026-09-06T12:00:00+08:00', 15, 'unknown'),
    ('PH off', '2026-09-07T12:00:00+08:00', 15, 'unknown'),
    ('25:00-26:00', '2026-09-07T12:00:00+08:00', 15, 'unknown'),
    ('00:00-00:00', '2026-09-07T12:00:00+08:00', 15, 'unknown'),
    (None, '2026-09-07T12:00:00+08:00', 15, 'unknown'),
    ('24/7', None, 15, 'unknown'),
])
def test_conservative_hours(hours, arrival, dwell, expected):
    assert check_hours(hours, datetime.fromisoformat(arrival) if arrival else None, dwell) == expected
