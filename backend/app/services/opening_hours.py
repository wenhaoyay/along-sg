"""Conservative weekly-hours evaluation; unsupported rules stay unknown."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAYS = ('Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su')


def check_hours(hours: str | None, arrival: datetime | None, dwell: float) -> str:
    if not hours or arrival is None:
        return 'unknown'
    if hours.strip() == '24/7':
        return 'open'
    rules = []
    for rule in hours.split(';'):
        match = re.fullmatch(r'\s*(?:(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?\s+)?(off|\d{2}:\d{2}-\d{2}:\d{2})\s*', rule)
        if not match:
            return 'unknown'
        first, last, interval = match.groups()
        days = set(range(7)) if not first else {DAYS.index(first)}
        if last:
            days = set()
            day = DAYS.index(first)
            while True:
                days.add(day)
                if day == DAYS.index(last):
                    break
                day = (day + 1) % 7
        if interval == 'off':
            rules.append((days, None, None))
            continue
        start, end = interval.split('-')
        values = []
        for value in (start, end):
            hour, minute = map(int, value.split(':'))
            if hour > 24 or minute > 59 or (hour == 24 and minute):
                return 'unknown'
            values.append(hour * 60 + minute)
        rules.append((days, *values))
    # Overlapping rules and zero-length windows have ambiguous override semantics.
    for index, (days, start, end) in enumerate(rules):
        if start is not None and start == end:
            return 'unknown'
        if any(days & other_days for other_days, _, _ in rules[:index]):
            return 'unknown'
    local = arrival.replace(tzinfo=ZoneInfo('Asia/Singapore')) if arrival.tzinfo is None else arrival.astimezone(ZoneInfo('Asia/Singapore'))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []
    for offset in (-1, 0, 1):
        date = midnight + timedelta(days=offset)
        for days, start, end in rules:
            if date.weekday() not in days or start is None:
                continue
            end = end + 1440 if end <= start else end
            windows.append((date + timedelta(minutes=start), date + timedelta(minutes=end)))
    for start, end in windows:
        if start <= local < end:
            return 'closing_soon' if local + timedelta(minutes=dwell) > end else 'open'
    return 'closed'
