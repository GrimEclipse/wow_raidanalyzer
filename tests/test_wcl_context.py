import unittest

from analyzer_core.wcl_context import WclCredentials, resolve_wcl_credentials, use_wcl_credentials


class WclContextTests(unittest.TestCase):
    def test_context_credentials_override_and_restore_fallback(self):
        fallback = resolve_wcl_credentials("global-id", "global-secret")
        self.assertEqual(fallback.client_id, "global-id")
        scoped = WclCredentials("account-id", "account-secret")
        with use_wcl_credentials(scoped):
            self.assertEqual(resolve_wcl_credentials("global-id", "global-secret"), scoped)
        self.assertEqual(resolve_wcl_credentials("global-id", "global-secret"), fallback)


if __name__ == "__main__":
    unittest.main()
