from datetime import datetime, timedelta, timezone

import pytest

from services.worker.app.search_worker import elapsed_seconds


@pytest.mark.parametrize("offset", [0, 8, -5])
def test_elapsed_is_independent_of_database_timezone(offset):
    start = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
    database_start = start.astimezone(timezone(timedelta(hours=offset)))
    assert elapsed_seconds(database_start, start + timedelta(seconds=21)) == 21


def test_elapsed_accepts_naive_utc_from_sqlite():
    start = datetime(2026, 10, 29, 6, 0)
    finish = datetime(2026, 10, 29, 6, 0, 21, tzinfo=timezone.utc)
    assert elapsed_seconds(start, finish) == 21
