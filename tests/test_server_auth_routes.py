import unittest

from server import safe_redirect_target


class ServerAuthRouteTests(unittest.TestCase):
    def test_safe_redirect_accepts_local_paths(self):
        self.assertEqual(safe_redirect_target("/cooldowns?boss=crown"), "/cooldowns?boss=crown")

    def test_safe_redirect_rejects_external_and_backslash_targets(self):
        for value in ("https://example.com", "//example.com", "/\\example.com", "login"):
            with self.subTest(value=value):
                self.assertEqual(safe_redirect_target(value), "/online")


if __name__ == "__main__":
    unittest.main()
