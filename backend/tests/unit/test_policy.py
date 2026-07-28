from datetime import date, datetime

from auth import policy
from auth.otp import OTP_MAX_ATTEMPTS, generate_otp, hash_otp, otp_matches


def test_policy_defaults_preserve_current_behaviour():
    assert policy.DEFAULT_POLICY == {
        policy.CLIENT_EMAIL_VERIFICATION: True,
        policy.EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION: True,
        policy.RETROACTIVE_SIGNING_DATES: True,
    }


def test_action_date_uses_requested_date_when_manual_dates_enabled(monkeypatch):
    monkeypatch.setattr(policy, "policy_enabled", lambda db, key: True)

    resolved = policy.resolve_realtime_action_datetime(
        object(),
        date(2026, 7, 20),
    )

    assert resolved == datetime(2026, 7, 20)


def test_action_date_uses_server_time_when_manual_dates_disabled(monkeypatch):
    monkeypatch.setattr(policy, "policy_enabled", lambda db, key: False)
    before = datetime.utcnow()

    resolved = policy.resolve_realtime_action_datetime(
        object(),
        date(2020, 1, 1),
    )

    after = datetime.utcnow()
    assert before <= resolved <= after


def test_action_datetime_override_is_preserved_when_enabled(monkeypatch):
    monkeypatch.setattr(policy, "policy_enabled", lambda db, key: True)
    requested = datetime(2025, 3, 4, 11, 22, 33)

    assert policy.resolve_realtime_action_datetime(object(), requested) == requested


def test_otp_is_six_digits_hashed_and_matches():
    code, digest, expires_at = generate_otp()

    assert len(code) == 6
    assert code.isdigit()
    assert digest == hash_otp(code)
    assert otp_matches(code, digest)
    assert not otp_matches("000000" if code != "000000" else "999999", digest)
    assert expires_at > datetime.utcnow()
    assert OTP_MAX_ATTEMPTS == 5
