import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import ocr

# Error real de cuota que motivó esto (429 RESOURCE_EXHAUSTED + retryDelay).
QUOTA_ERR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', "
    "'details': [{'quotaValue': '20'}, {'@type': '...RetryInfo', 'retryDelay': '26s'}]}}"
)


def test_is_retryable_429_quota():
    assert ocr._is_retryable(Exception(QUOTA_ERR))


def test_is_retryable_503():
    assert ocr._is_retryable(Exception("503 UNAVAILABLE: model overloaded"))


# La cuota DIARIA del free tier no se resetea en horas: reintentar hoy no sirve.
DAILY_QUOTA_ERR = (
    "429 RESOURCE_EXHAUSTED. quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "quotaValue: '20', retryDelay: '25s'"
)
PER_MINUTE_QUOTA_ERR = (
    "429 RESOURCE_EXHAUSTED. quotaId: 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "retryDelay: '20s'"
)


def test_daily_quota_not_retryable():
    assert not ocr._is_retryable(Exception(DAILY_QUOTA_ERR))


def test_per_minute_quota_is_retryable():
    assert ocr._is_retryable(Exception(PER_MINUTE_QUOTA_ERR))


def test_not_retryable_400():
    assert not ocr._is_retryable(Exception("400 INVALID_ARGUMENT: bad image"))


def test_retry_delay_honors_api_hint():
    assert ocr._retry_delay(Exception(QUOTA_ERR), attempt=0) == 26.0


def test_retry_delay_exponential_without_hint():
    err = Exception("503 overloaded")
    assert ocr._retry_delay(err, attempt=1) > ocr._retry_delay(err, attempt=0)


def test_retry_delay_capped():
    assert ocr._retry_delay(Exception("retryDelay: '9999s'"), attempt=0) <= ocr.RETRY_DELAY_CAP


def test_generate_with_retry_retries_then_succeeds():
    calls = {"n": 0}
    slept = []

    def call():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("429 RESOURCE_EXHAUSTED retryDelay: '1s'")
        return "OK"

    out = ocr._generate_with_retry(call, sleep=slept.append)
    assert out == "OK"
    assert calls["n"] == 3 and len(slept) == 2


def test_generate_with_retry_gives_up_on_non_retryable():
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise Exception("400 INVALID_ARGUMENT")

    with pytest.raises(Exception):
        ocr._generate_with_retry(call, sleep=lambda s: None)
    assert calls["n"] == 1   # no reintenta errores no transitorios


def test_generate_with_retry_exhausts_attempts():
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise Exception("503 overloaded")

    with pytest.raises(Exception):
        ocr._generate_with_retry(call, max_attempts=3, sleep=lambda s: None)
    assert calls["n"] == 3
