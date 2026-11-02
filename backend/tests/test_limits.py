import pytest

from app.services.limits import RateLimitExceeded, check_rate_limit


def test_calls_up_to_the_limit_pass_and_the_next_one_is_refused(redis_client):
    for _ in range(3):
        check_rate_limit(redis_client, "user:1", limit=3, window_sec=60)

    with pytest.raises(RateLimitExceeded) as exc:
        check_rate_limit(redis_client, "user:1", limit=3, window_sec=60)

    assert 1 <= exc.value.retry_after <= 60


def test_keys_are_independent(redis_client):
    for _ in range(3):
        check_rate_limit(redis_client, "user:1", limit=3)

    check_rate_limit(redis_client, "user:2", limit=3)  # another user is not affected


def test_counters_always_expire(redis_client):
    check_rate_limit(redis_client, "user:1", limit=3, window_sec=60)

    key = next(iter(redis_client.scan_iter("ratelimit:user:1:*")))
    assert 0 < redis_client.ttl(key) <= 61


def test_a_refused_call_still_counts(redis_client):
    for _ in range(5):
        with pytest.raises(RateLimitExceeded) if _ >= 2 else _nullcontext():
            check_rate_limit(redis_client, "user:1", limit=2)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
