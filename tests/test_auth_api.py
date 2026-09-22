import unittest
import json
import time
import os
from pathlib import Path
from urllib.request import Request, urlopen
from src import db

class TestAuthAPI(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def tearDown(self):
        db.clear_all_users()

    def test_signup_login_flow(self):
        # We can test the underlying db methods and json serialization
        email = f"api_test_{int(time.time() * 1000)}@test.com"
        user = db.create_user(email, "SecretPassword123", "API Tester")
        token = db.create_session(user["id"])
        
        fetched = db.get_user_by_session(token)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["email"], email)
        self.assertEqual(fetched["name"], "API Tester")

    def test_remember_me_session(self):
        email = f"remember_{int(time.time() * 1000)}@test.com"
        user = db.create_user(email, "Pass123456", "Remember Tester")

        # Session without remember_me
        token_standard = db.create_session(user["id"], remember_me=False)
        fetched_standard = db.get_user_by_session(token_standard)
        self.assertIsNotNone(fetched_standard)
        self.assertFalse(fetched_standard["session_remember_me"])

        # Session with remember_me
        token_remembered = db.create_session(user["id"], remember_me=True)
        fetched_remembered = db.get_user_by_session(token_remembered)
        self.assertIsNotNone(fetched_remembered)
        self.assertTrue(fetched_remembered["session_remember_me"])

    def test_google_upsert_flow(self):
        sub = f"g_sub_{int(time.time() * 1000)}"
        email = f"googler_{sub}@gmail.com"
        user = db.upsert_google_user(sub, email, "Google Bettor", "https://img.com/avatar.jpg")
        self.assertEqual(user["google_sub"], sub)
        self.assertEqual(user["auth_provider"], "google")

    def test_profile_update_and_locked_email(self):
        email = f"locked_email_{int(time.time() * 1000)}@edgepulse.com"
        user = db.create_user(email, "InitialPass123!", "Original Name")
        uid = user["id"]

        # Update name and avatar
        updated = db.update_user_profile(
            user_id=uid,
            name="Updated Name",
            avatar_url="https://api.dicebear.com/7.x/bottts/svg?seed=Test",
        )
        self.assertEqual(updated["name"], "Updated Name")
        self.assertEqual(updated["avatar_url"], "https://api.dicebear.com/7.x/bottts/svg?seed=Test")
        self.assertEqual(updated["email"], email)  # Email strictly unchanged

        # Verify password update fails with incorrect old password
        with self.assertRaises(ValueError):
            db.update_user_profile(
                user_id=uid,
                current_password="WrongOldPassword!",
                new_password="NewSecretPass999!",
            )

        # Verify password update succeeds with correct old password
        db.update_user_profile(
            user_id=uid,
            current_password="InitialPass123!",
            new_password="NewSecretPass999!",
        )
        self.assertIsNotNone(db.authenticate_user(email, "NewSecretPass999!"))
        self.assertIsNone(db.authenticate_user(email, "InitialPass123!"))

        # Verify preferences update together
        settings_update = db.update_user_settings(uid, {
            "bankroll": 5000.0,
            "kelly_multiplier": 0.50,
            "preferred_region": "in",
            "discord_webhook": "https://discord.com/api/webhooks/test",
            "discord_enabled": True,
        })
        self.assertEqual(settings_update["bankroll"], 5000.0)
        self.assertEqual(settings_update["kelly_multiplier"], 0.50)
        self.assertEqual(settings_update["preferred_region"], "in")
        self.assertEqual(settings_update["discord_webhook"], "https://discord.com/api/webhooks/test")
        self.assertEqual(settings_update["discord_enabled"], 1)


class TestProfileHTTPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from web_app import DashboardHandler
        cls.config_path = Path(__file__).resolve().parent.parent / "discord_config.json"
        if cls.config_path.exists():
            cls.orig_config = cls.config_path.read_text(encoding="utf-8")
        else:
            cls.orig_config = None
        cls.port = 8899
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), DashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if cls.orig_config is not None:
            cls.config_path.write_text(cls.orig_config, encoding="utf-8")

    def test_side_drawer_in_html(self):
        req = Request(f"http://127.0.0.1:{self.port}/")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("profile-drawer", html)
            self.assertIn("openProfileDrawer()", html)
            self.assertIn("drawer-input-email", html)
            self.assertIn("drawer-hero-avatar", html)
            self.assertIn("drawer-select-region", html)
            self.assertIn("drawer-btn-save", html)

    def test_full_profile_http_cycle(self):
        # 1. Signup a user
        ts = int(time.time() * 1000)
        email = f"drawer_user_{ts}@test.com"
        signup_data = json.dumps({
            "email": email,
            "password": "Password123!",
            "name": "Initial Name"
        }).encode("utf-8")

        req = Request(
            f"http://127.0.0.1:{self.port}/api/auth/signup",
            data=signup_data,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            token = data["token"]
            self.assertEqual(data["user"]["email"], email)

        # 2. Get profile
        req_profile = Request(
            f"http://127.0.0.1:{self.port}/api/user/profile",
            headers={"Authorization": f"Bearer {token}"}
        )
        with urlopen(req_profile) as resp:
            p_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(p_data["status"], "success")
            self.assertEqual(p_data["user"]["name"], "Initial Name")

        # 3. Update profile details: Name, Avatar, Preferences
        avatar_url = "https://api.dicebear.com/7.x/bottts/svg?seed=AlphaEdge"
        update_data = json.dumps({
            "name": "Sharpshooter Pro",
            "avatar_url": avatar_url,
            "preferred_region": "in",
            "bankroll": 5000.0,
            "kelly_multiplier": 0.50,
            "min_ev": 0.08,
            "discord_enabled": True,
            "discord_webhook": "https://discord.com/api/webhooks/123/abc"
        }).encode("utf-8")

        req_update = Request(
            f"http://127.0.0.1:{self.port}/api/user/profile",
            data=update_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
        )
        with urlopen(req_update) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res_json["status"], "success")
            updated = res_json["user"]
            self.assertEqual(updated["name"], "Sharpshooter Pro")
            self.assertEqual(updated["avatar_url"], avatar_url)
            self.assertEqual(updated["preferred_region"], "in")
            self.assertEqual(updated["bankroll"], 5000.0)
            self.assertEqual(updated["kelly_multiplier"], 0.50)
            self.assertEqual(updated["email"], email)  # Email is locked and immutable

        # 4. Successful password update
        good_pw_data = json.dumps({
            "current_password": "Password123!",
            "new_password": "BrandNewPassword123!"
        }).encode("utf-8")

        req_good_pw = Request(
            f"http://127.0.0.1:{self.port}/api/user/profile",
            data=good_pw_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
        )
        with urlopen(req_good_pw) as resp:
            pw_res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(pw_res["status"], "success")

        # 5. Verify new password successfully logs in
        new_login_data = json.dumps({
            "email": email,
            "password": "BrandNewPassword123!"
        }).encode("utf-8")
        req_new_login = Request(
            f"http://127.0.0.1:{self.port}/api/auth/login",
            data=new_login_data,
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req_new_login) as resp:
            login_res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(login_res["status"], "success")
            self.assertEqual(login_res["user"]["name"], "Sharpshooter Pro")

    def test_admin_clear_users_endpoint(self):
        # 1. Calling clear_users when ALLOW_USER_WIPE is not set must fail (403)
        if "ALLOW_USER_WIPE" in os.environ:
            del os.environ["ALLOW_USER_WIPE"]
        req_blocked = Request(
            f"http://127.0.0.1:{self.port}/api/admin/clear_users?secret=edgepulse_wipe_2026",
            method="POST"
        )
        try:
            with urlopen(req_blocked) as resp:
                self.assertNotEqual(resp.status, 200)
        except Exception as e:
            self.assertIn("403", str(e))

        # 2. When ALLOW_USER_WIPE="1", calling without secret must fail (403)
        try:
            os.environ["ALLOW_USER_WIPE"] = "1"
            req_unauth = Request(f"http://127.0.0.1:{self.port}/api/admin/clear_users", method="POST")
            try:
                with urlopen(req_unauth) as resp:
                    self.assertNotEqual(resp.status, 200)
            except Exception as e:
                self.assertIn("403", str(e))

            # 3. Calling with secret key and ALLOW_USER_WIPE="1" succeeds
            req_auth = Request(
                f"http://127.0.0.1:{self.port}/api/admin/clear_users?secret=edgepulse_wipe_2026",
                method="POST",
                headers={"Content-Type": "application/json"}
            )
            with urlopen(req_auth) as resp:
                self.assertEqual(resp.status, 200)
                res = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(res["status"], "success")
                self.assertIn("All user data successfully wiped", res["message"])
        finally:
            if "ALLOW_USER_WIPE" in os.environ:
                del os.environ["ALLOW_USER_WIPE"]


if __name__ == '__main__':
    unittest.main()


