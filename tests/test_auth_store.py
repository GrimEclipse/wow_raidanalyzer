import tempfile
import unittest
from pathlib import Path

from analyzer_core.auth_store import AuthError, AuthStore


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = AuthStore(root / "auth.db", root / "master.key", session_hours=1)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_roles_authentication_and_sessions(self):
        viewer = self.store.create_user("reader", "ReaderPassword123", role="viewer")
        editor = self.store.create_user("editor", "EditorPassword123", role="editor")
        admin = self.store.create_user("admin", "AdminPassword123", role="admin")

        self.assertFalse(viewer["canModify"])
        self.assertTrue(editor["canModify"])
        self.assertFalse(editor["isAdmin"])
        self.assertTrue(admin["isAdmin"])
        self.assertIsNone(self.store.authenticate("reader", "wrong"))
        self.assertEqual(self.store.authenticate("READER", "ReaderPassword123")["id"], viewer["id"])

        token = self.store.create_session(viewer["id"])
        self.assertEqual(self.store.session_user(token)["id"], viewer["id"])
        self.store.set_disabled(viewer["id"], True)
        self.assertIsNone(self.store.session_user(token))

    def test_password_change_invalidates_old_sessions(self):
        user = self.store.create_user("member", "OriginalPass123", role="viewer")
        token = self.store.create_session(user["id"])
        self.store.change_password(user["id"], "OriginalPass123", "ReplacementPass456")
        self.assertIsNone(self.store.session_user(token))
        self.assertIsNone(self.store.authenticate("member", "OriginalPass123"))
        self.assertIsNotNone(self.store.authenticate("member", "ReplacementPass456"))

    def test_wcl_credentials_are_encrypted_at_rest(self):
        user = self.store.create_user("member", "MemberPassword123", role="viewer")
        self.store.set_wcl_credentials(user["id"], "client-visible-id", "secret-never-plain")
        credentials = self.store.get_wcl_credentials(user["id"])
        self.assertEqual(credentials.client_id, "client-visible-id")
        self.assertEqual(credentials.client_secret, "secret-never-plain")
        raw_database = self.store.db_path.read_bytes()
        self.assertNotIn(b"client-visible-id", raw_database)
        self.assertNotIn(b"secret-never-plain", raw_database)

    def test_self_demotion_is_rejected(self):
        admin = self.store.create_user("admin", "AdminPassword123", role="admin")
        with self.assertRaises(AuthError):
            self.store.set_role(admin["id"], "viewer", actor_user_id=admin["id"])

    def test_user_guilds_have_one_default_and_follow_the_user(self):
        user = self.store.create_user("raider", "password", role="editor")
        first = self.store.upsert_guild(user["id"], 1001, "First Guild")
        self.assertTrue(first["isDefault"])
        self.store.upsert_guild(user["id"], 1002, "Second Guild")
        self.store.set_default_guild(user["id"], 1002)
        guilds = self.store.list_guilds(user["id"])
        self.assertEqual(guilds[0]["id"], 1002)
        self.assertEqual(sum(1 for guild in guilds if guild["isDefault"]), 1)
        self.store.delete_guild(user["id"], 1002)
        self.assertTrue(self.store.list_guilds(user["id"])[0]["isDefault"])


if __name__ == "__main__":
    unittest.main()
