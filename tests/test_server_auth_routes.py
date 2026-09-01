import unittest
from unittest.mock import Mock, patch

from server import (
    AnalyzerHandler,
    local_wowhead_data,
    normalize_static_request_path,
    safe_redirect_target,
    wowhead_spell_tooltip,
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

    @patch("server.requests_module")
    def test_wowhead_spell_tooltip_uses_real_nether_payload(self, requests_module):
        response = Mock()
        response.json.return_value = {
            "name": "腐蚀浪潮",
            "icon": "inv_ability_poison_wave",
            "tooltip": "<table><tr><td>真实说明</td></tr></table>",
        }
        response.raise_for_status.return_value = None
        requests_module.return_value.get.return_value = response

        payload = wowhead_spell_tooltip(1292403, "dd=15&dataEnv=1&locale=4")

        self.assertEqual(payload["name"], "腐蚀浪潮")
        self.assertNotIn("本地法术存根", payload["tooltip"])
        url = requests_module.return_value.get.call_args.args[0]
        self.assertTrue(url.startswith("https://nether.wowhead.com/tooltip/spell/1292403?"))


if __name__ == "__main__":
    unittest.main()
