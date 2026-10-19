import unittest
from unittest.mock import Mock, patch

from server import (
    AnalyzerHandler,
    FAVICON_PATH,
    local_wowhead_data,
    normalize_static_request_path,
    safe_redirect_target,
    wowhead_spell_tooltip,
    wowhead_static_asset_url,
)


class ServerAuthRouteTests(unittest.TestCase):
    def test_coiledaltar_icon_timeline_static_assets_are_public(self):
        handler = AnalyzerHandler.__new__(AnalyzerHandler)
        handler.send_response_body = lambda status, content_type, body: (status, content_type, body)
        handler.send_error = lambda status: (status, '', b'')
        for filename in ('guild-timeline.js', 'timeline-assets.js', 'icon-timeline.js', 'icon-timeline.css'):
            path = '/frontend/report/plugins/venomous_abyss/coiledaltar/'+filename
            self.assertTrue(AnalyzerHandler.is_public_page(path))
            status, _, body = handler.handle_static(path, public=True)
            self.assertEqual(status, 200)
            self.assertFalse(body.startswith(b'<!doctype'))

    def test_report_login_preserves_json_fight_and_tab_query(self):
        from urllib.parse import urlparse, parse_qs
        handler = AnalyzerHandler.__new__(AnalyzerHandler)
        handler.path = '/frontend/report/overview.html?json=/data/report.json&fight=5&tab=guildTimeline'
        handler.current_user = lambda: None
        handler.redirect = Mock()
        handler.require_user('/frontend/report/overview.html')
        destination = handler.redirect.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(destination).query)['next'][0], handler.path)

    def test_vashnik_demo_scripts_are_public_javascript(self):
        handler = AnalyzerHandler.__new__(AnalyzerHandler)
        handler.send_response_body = lambda status, content_type, body: (status, content_type, body)
        handler.send_error = lambda status: (status, "", b"")
        for name in ("wave-replay.js", "field-view.js"):
            path = f"/frontend/report/plugins/venomous_abyss/vashnik/{name}"
            self.assertTrue(AnalyzerHandler.is_public_page(path))
            status, content_type, body = handler.handle_static(path, public=True)
            self.assertEqual(status, 200)
            self.assertIn("javascript", content_type)
            self.assertFalse(body.startswith(b"<!doctype"))

    def test_animated_favicon_is_a_bundled_gif(self):
        self.assertTrue(FAVICON_PATH.is_file())
        self.assertTrue(FAVICON_PATH.read_bytes().startswith(b"GIF8"))

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

    def test_public_raid_guide_can_load_boss_hero_images(self):
        path = "/assets/raids/unbinding_of_kithix/01-kithix-hero.png"
        self.assertTrue(AnalyzerHandler.is_public_page(path))
        handler = AnalyzerHandler.__new__(AnalyzerHandler)
        handler.send_response_body = lambda status, content_type, body: (status, content_type, body)
        handler.send_error = lambda status: (status, "", b"")
        status, content_type, body = handler.handle_static(path, public=True)
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

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
