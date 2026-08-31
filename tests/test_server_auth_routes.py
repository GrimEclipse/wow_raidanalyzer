import unittest

from server import (
    AnalyzerHandler,
    local_wowhead_data,
    normalize_static_request_path,
    safe_redirect_target,
    wowhead_static_asset_url,
)


class ServerAuthRouteTests(unittest.TestCase):
    def test_static_app_routes_accept_trailing_slashes(self):
        self.assertEqual(normalize_static_request_path("/raid-guide/"), "/raid-guide")
        self.assertEqual(
            normalize_static_request_path("/frontend/tools/raid-guide/"),
            "/frontend/tools/raid-guide",
        )
        self.assertEqual(normalize_static_request_path("/"), "/")

    def test_raid_guide_trailing_slash_resolves_to_html(self):
        handler = AnalyzerHandler.__new__(AnalyzerHandler)
        handler.send_response_body = lambda status, content_type, body: (status, content_type, body)
        handler.send_error = lambda status: (status, "", b"")
        status, content_type, body = handler.handle_static("/raid-guide/")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html")
        self.assertIn("assets/vendor/zone54-raid-guide-data.js", body.decode("utf-8"))

    def test_safe_redirect_accepts_local_paths(self):
        self.assertEqual(safe_redirect_target("/cooldowns?boss=crown"), "/cooldowns?boss=crown")

    def test_safe_redirect_rejects_external_and_backslash_targets(self):
        for value in ("https://example.com", "//example.com", "/\\example.com", "login"):
            with self.subTest(value=value):
                self.assertEqual(safe_redirect_target(value), "/online")

    def test_local_wowhead_spell_scaling_accepts_bundled_client_path(self):
        payload = local_wowhead_data(
            "/wowhead-tooltip/data/spell-scaling&dataEnv=1&json"
        )
        self.assertEqual(payload["scalingValue"], {})
        self.assertEqual(payload["spellInformation"], {})
        self.assertEqual(payload["randPropPoints"], {})

    def test_local_wowhead_data_supports_standard_query_path_and_rejects_unknown_data(self):
        payload = local_wowhead_data("/wowhead-tooltip/data/spell-scaling")
        self.assertEqual(payload["scalingValue"], {})
        self.assertIsNone(local_wowhead_data("/wowhead-tooltip/data/unknown&json"))

    def test_bundled_wowhead_static_assets_redirect_to_trusted_cdn(self):
        self.assertEqual(
            wowhead_static_asset_url(
                "/zamimg/images/wow/icons/large/inv_misc_questionmark.jpg",
                "v=4",
            ),
            "https://wow.zamimg.com/images/wow/icons/large/inv_misc_questionmark.jpg?v=4",
        )
        self.assertIsNone(wowhead_static_asset_url("/zamimg/../server.py"))
        self.assertIsNone(wowhead_static_asset_url("/assets/app.css"))


if __name__ == "__main__":
    unittest.main()
