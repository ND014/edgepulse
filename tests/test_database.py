import unittest
import time
from src import db

class TestDatabaseAuth(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_user_creation_and_auth(self):
        email = f"user_{int(time.time() * 1000)}@test.com"
        u = db.create_user(email, "MyStrongPassword123!", "Alice Tester")
        self.assertEqual(u["email"], email)
        self.assertEqual(u["name"], "Alice Tester")
        self.assertEqual(u["bankroll"], 1000.0)

        # Authenticate with correct password
        auth_ok = db.authenticate_user(email, "MyStrongPassword123!")
        self.assertIsNotNone(auth_ok)
        self.assertEqual(auth_ok["id"], u["id"])

        # Authenticate with wrong password
        auth_bad = db.authenticate_user(email, "WrongPassword!")
        self.assertIsNone(auth_bad)

    def test_session_lifecycle(self):
        email = f"sess_{int(time.time() * 1000)}@test.com"
        u = db.create_user(email, "Password123!")
        token = db.create_session(u["id"], duration_days=7)
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 64)

        # Retrieve user by session
        sess_user = db.get_user_by_session(token)
        self.assertIsNotNone(sess_user)
        self.assertEqual(sess_user["id"], u["id"])

        # Delete session
        del_ok = db.delete_session(token)
        self.assertTrue(del_ok)
        self.assertIsNone(db.get_user_by_session(token))

    def test_google_upsert(self):
        sub = f"sub_{int(time.time() * 1000)}"
        email = f"google_{sub}@gmail.com"
        g_user = db.upsert_google_user(sub, email, "Google Champ", "https://pic.url")
        self.assertEqual(g_user["google_sub"], sub)
        self.assertEqual(g_user["email"], email)
        self.assertEqual(g_user["auth_provider"], "google")

        # Upserting again should update instead of duplicating
        g_updated = db.upsert_google_user(sub, email, "Google Champ Updated", "https://pic2.url")
        self.assertEqual(g_updated["id"], g_user["id"])
        self.assertEqual(g_updated["name"], "Google Champ Updated")

    def test_guest_user(self):
        guest = db.create_guest_user()
        self.assertEqual(guest["auth_provider"], "guest")
        self.assertTrue(guest["email"].startswith("guest_"))

    def test_settings_update(self):
        email = f"settings_{int(time.time() * 1000)}@test.com"
        u = db.create_user(email, "Password123!")
        updated = db.update_user_settings(u["id"], {
            "bankroll": 2500.0,
            "kelly_multiplier": 0.5,
            "discord_webhook": "https://discord.com/api/webhooks/test",
            "discord_enabled": True,
            "min_ev": 0.02,
            "preferred_region": "in"
        })
        self.assertEqual(updated["bankroll"], 2500.0)
        self.assertEqual(updated["kelly_multiplier"], 0.5)
        self.assertEqual(updated["discord_webhook"], "https://discord.com/api/webhooks/test")
        self.assertEqual(updated["discord_enabled"], 1)
        self.assertEqual(updated["min_ev"], 0.02)
        self.assertEqual(updated["preferred_region"], "in")

    def test_email_cross_provider_collision_prevention(self):
        email = f"collision_{int(time.time() * 1000)}@test.com"
        # 1. Create with local password
        u = db.create_user(email, "StrongPass123!")
        self.assertEqual(u["email"], email)

        # Attempt to create duplicate local account
        with self.assertRaises(ValueError):
            db.create_user(email, "AnotherPass123!")

        # Attempt to sign in via Google with same email
        with self.assertRaises(ValueError):
            db.upsert_google_user("fake_google_sub_123", email, "Google Imposter")

        # 2. Test reverse: Google account cannot be hijacked via password signup
        g_sub = f"google_sub_{int(time.time() * 1000)}"
        g_email = f"g_only_{int(time.time() * 1000)}@gmail.com"
        g_user = db.upsert_google_user(g_sub, g_email, "Real Google User")
        self.assertEqual(g_user["email"], g_email)

        # Attempt to create password account with Google email
        with self.assertRaises(ValueError):
            db.create_user(g_email, "HackedPass123!")

        # Attempt to authenticate password against Google account
        with self.assertRaises(ValueError):
            db.authenticate_user(g_email, "AnyPassword123!")

    def test_update_user_profile(self):
        email = f"profile_test_{int(time.time() * 1000)}@edgepulse.com"
        user = db.create_user(email, "InitialPass123!", name="Old Name")
        user_id = user["id"]

        # 1. Update display name and avatar
        updated = db.update_user_profile(
            user_id=user_id,
            name="New Display Name",
            avatar_url="https://example.com/avatar.png",
        )
        self.assertEqual(updated["name"], "New Display Name")
        self.assertEqual(updated["avatar_url"], "https://example.com/avatar.png")
        self.assertEqual(updated["email"], email)  # Email unchanged

        # 2. Test password change with incorrect current password
        with self.assertRaises(ValueError) as ctx:
            db.update_user_profile(
                user_id=user_id,
                current_password="WrongPassword!",
                new_password="BrandNewPass456!",
            )
        self.assertIn("Current password is incorrect", str(ctx.exception))

        # 3. Test password change with too short new password
        with self.assertRaises(ValueError) as ctx:
            db.update_user_profile(
                user_id=user_id,
                current_password="InitialPass123!",
                new_password="123",
            )
        self.assertIn("at least 6 characters", str(ctx.exception))

        # 4. Successful password change
        db.update_user_profile(
            user_id=user_id,
            current_password="InitialPass123!",
            new_password="BrandNewPass456!",
        )

        # 5. Old password no longer works
        self.assertIsNone(db.authenticate_user(email, "InitialPass123!"))

        # 6. New password successfully authenticates
        auth_user = db.authenticate_user(email, "BrandNewPass456!")
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["id"], user_id)

    def test_bet_tracker_crud_and_stats(self):
        email = f"bettor_{int(time.time() * 1000)}@test.com"
        user = db.create_user(email, "Pass123456!", "Bet Analyst")
        uid = user["id"]

        # 1. Log two bets
        b1 = db.log_bet(
            user_id=uid,
            event_id="evt_101",
            sport="mma",
            event_name="Fighter A vs Fighter B",
            selection="Fighter A",
            sportsbook="pinnacle",
            odds=2.00,
            stake=100.0,
            fair_odds=1.80,
            edge_pct=0.111,
            notes="Strong sharp divergence",
        )
        self.assertEqual(b1["status"], "pending")
        self.assertEqual(b1["profit"], 0.0)

        b2 = db.log_bet(
            user_id=uid,
            event_id="evt_102",
            sport="mma",
            event_name="Fighter C vs Fighter D",
            selection="Fighter C",
            sportsbook="draftkings",
            odds=2.50,
            stake=100.0,
            fair_odds=2.10,
            edge_pct=0.19,
        )

        # Initial stats: 2 pending bets
        stats0 = db.get_bet_performance_stats(uid)
        self.assertEqual(stats0["total_bets"], 2)
        self.assertEqual(stats0["pending_count"], 2)
        self.assertEqual(stats0["total_staked"], 200.0)
        self.assertEqual(stats0["total_profit"], 0.0)

        # 2. Settle b1 as Won: 100 * 2.00 = 200 payout, +100 profit
        settled_b1 = db.settle_bet(b1["id"], uid, "won")
        self.assertEqual(settled_b1["status"], "won")
        self.assertEqual(settled_b1["payout"], 200.0)
        self.assertEqual(settled_b1["profit"], 100.0)

        # 3. Settle b2 as Lost: payout = 0, profit = -100
        settled_b2 = db.settle_bet(b2["id"], uid, "lost")
        self.assertEqual(settled_b2["status"], "lost")
        self.assertEqual(settled_b2["payout"], 0.0)
        self.assertEqual(settled_b2["profit"], -100.0)

        # 4. Check stats: 1 win, 1 loss, 50% win rate, net profit 0
        stats1 = db.get_bet_performance_stats(uid)
        self.assertEqual(stats1["won_count"], 1)
        self.assertEqual(stats1["lost_count"], 1)
        self.assertEqual(stats1["pending_count"], 0)
        self.assertEqual(stats1["win_rate"], 50.0)
        self.assertEqual(stats1["total_profit"], 0.0)
        self.assertEqual(len(stats1["equity_curve"]), 2)

        # 5. Delete b2
        self.assertTrue(db.delete_bet(b2["id"], uid))
        stats2 = db.get_bet_performance_stats(uid)
        self.assertEqual(stats2["total_bets"], 1)
        self.assertEqual(stats2["won_count"], 1)
        self.assertEqual(stats2["total_profit"], 100.0)
        self.assertEqual(stats2["win_rate"], 100.0)

    def test_activity_logs(self):
        uid = 999
        log_id = db.log_activity("soccer_epl", "Soccer (EPL)", "view_sport", user_id=uid, user_email="fan@epl.com", user_name="Soccer Fan")
        self.assertGreater(log_id, 0)
        logs = db.get_activity_logs(limit=10, user_id=uid)
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]["sport_key"], "soccer_epl")
        self.assertEqual(logs[0]["sport_name"], "Soccer (EPL)")
        self.assertEqual(logs[0]["user_email"], "fan@epl.com")
        self.assertIn("UTC", logs[0]["formatted_time"])


if __name__ == '__main__':
    unittest.main()


