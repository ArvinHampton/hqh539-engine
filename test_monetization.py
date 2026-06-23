"""Unit tests for tier enforcement, usage tracking, and billing verification."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from billing import (
    apply_pro_upgrade,
    create_checkout_session,
    is_stripe_configured,
    retrieve_checkout_session,
    verify_payment_success,
)
from usage_tracker import (
    TIER_FREE,
    TIER_PRO,
    FREE_DAILY_LIMIT,
    can_use,
    check_and_record,
    get_user_state,
    grant_pro,
    normalize_state,
    record_use,
    set_user_state,
)


class TestUsageTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store_path = Path(self.tmp) / "usage_data.json"
        self.today = "2026-06-22"

    def test_free_user_under_limit_can_use(self):
        state = {"tier": TIER_FREE, "daily_count": 5, "last_date": self.today}
        self.assertTrue(can_use(state["tier"], state["daily_count"]))

    def test_free_user_at_limit_blocked(self):
        state = {"tier": TIER_FREE, "daily_count": FREE_DAILY_LIMIT, "last_date": self.today}
        self.assertFalse(can_use(state["tier"], state["daily_count"]))

    def test_pro_user_unlimited(self):
        state = {"tier": TIER_PRO, "daily_count": 9999, "last_date": self.today}
        self.assertTrue(can_use(state["tier"], state["daily_count"]))

    def test_record_use_increments_counter(self):
        state = {"tier": TIER_FREE, "daily_count": 3, "last_date": self.today}
        updated = record_use(state, self.today)
        self.assertEqual(updated["daily_count"], 4)

    def test_normalize_resets_on_new_day(self):
        state = {"tier": TIER_FREE, "daily_count": 9, "last_date": "2026-06-21"}
        normalized = normalize_state(state, self.today)
        self.assertEqual(normalized["daily_count"], 0)
        self.assertEqual(normalized["last_date"], self.today)

    def test_grant_pro_upgrades_tier(self):
        state = {"tier": TIER_FREE, "daily_count": 10, "last_date": self.today}
        upgraded = grant_pro(state, "cs_test_abc123")
        self.assertEqual(upgraded["tier"], TIER_PRO)
        self.assertEqual(upgraded["stripe_checkout_session_id"], "cs_test_abc123")

    def test_check_and_record_persists(self):
        uid = "test-user-1"
        for _ in range(FREE_DAILY_LIMIT):
            allowed, _ = check_and_record(uid, self.store_path, self.today)
            self.assertTrue(allowed)
        allowed, state = check_and_record(uid, self.store_path, self.today)
        self.assertFalse(allowed)
        self.assertEqual(state["daily_count"], FREE_DAILY_LIMIT)

        loaded = get_user_state(uid, self.store_path, self.today)
        self.assertEqual(loaded["daily_count"], FREE_DAILY_LIMIT)

    def test_pro_user_never_blocked(self):
        uid = "test-pro-user"
        pro_state = {"tier": TIER_PRO, "daily_count": 0, "last_date": self.today}
        set_user_state(uid, pro_state, self.store_path)
        for _ in range(25):
            allowed, state = check_and_record(uid, self.store_path, self.today)
            self.assertTrue(allowed)
        self.assertEqual(state["tier"], TIER_PRO)


class TestBilling(unittest.TestCase):
    def test_verify_payment_success_paid_complete(self):
        session_data = {
            "id": "cs_test_ok",
            "payment_status": "paid",
            "status": "complete",
            "paid": True,
            "error": None,
        }
        self.assertTrue(verify_payment_success(session_data))

    def test_verify_payment_success_unpaid(self):
        session_data = {
            "id": "cs_test_pending",
            "payment_status": "unpaid",
            "status": "open",
            "paid": False,
            "error": None,
        }
        self.assertFalse(verify_payment_success(session_data))

    def test_verify_payment_success_with_error(self):
        session_data = {"error": "not found", "paid": False}
        self.assertFalse(verify_payment_success(session_data))

    def test_apply_pro_upgrade_on_success(self):
        user_state = {"tier": TIER_FREE, "daily_count": 10, "last_date": "2026-06-22"}
        session_data = {
            "id": "cs_test_upgrade",
            "payment_status": "paid",
            "status": "complete",
            "paid": True,
            "error": None,
        }
        new_state, upgraded = apply_pro_upgrade(user_state, session_data)
        self.assertTrue(upgraded)
        self.assertEqual(new_state["tier"], TIER_PRO)

    def test_apply_pro_upgrade_rejects_incomplete(self):
        user_state = {"tier": TIER_FREE, "daily_count": 5, "last_date": "2026-06-22"}
        session_data = {"paid": False, "status": "open", "error": None}
        new_state, upgraded = apply_pro_upgrade(user_state, session_data)
        self.assertFalse(upgraded)
        self.assertEqual(new_state["tier"], TIER_FREE)

    def test_create_checkout_without_key_returns_error(self):
        old = os.environ.pop("STRIPE_SECRET_KEY", None)
        try:
            result = create_checkout_session(
                success_url="http://localhost:8501/?checkout=success",
                cancel_url="http://localhost:8501/?checkout=cancel",
                client_reference_id="user-123",
            )
            self.assertIsNotNone(result.get("error"))
            self.assertIsNone(result.get("url"))
        finally:
            if old:
                os.environ["STRIPE_SECRET_KEY"] = old

    def test_retrieve_checkout_without_key_returns_error(self):
        old = os.environ.pop("STRIPE_SECRET_KEY", None)
        try:
            result = retrieve_checkout_session("cs_test_fake")
            self.assertIsNotNone(result.get("error"))
            self.assertFalse(result.get("paid"))
        finally:
            if old:
                os.environ["STRIPE_SECRET_KEY"] = old

    def test_is_stripe_configured_false_without_key(self):
        old = os.environ.pop("STRIPE_SECRET_KEY", None)
        try:
            self.assertFalse(is_stripe_configured())
        finally:
            if old:
                os.environ["STRIPE_SECRET_KEY"] = old

    def test_is_stripe_configured_true_with_test_key(self):
        old = os.environ.get("STRIPE_SECRET_KEY")
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake_key_for_unit_test"
        try:
            self.assertTrue(is_stripe_configured())
        finally:
            if old:
                os.environ["STRIPE_SECRET_KEY"] = old
            else:
                os.environ.pop("STRIPE_SECRET_KEY", None)


if __name__ == "__main__":
    unittest.main()