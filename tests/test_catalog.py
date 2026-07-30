import unittest
from pathlib import Path

from analyzer_core.catalog import CATALOG_PATH, build_catalog, find_boss, to_frontend_catalog


class BossCatalogTests(unittest.TestCase):
    def test_existing_supported_boss_comes_from_json_catalog(self):
        crown = find_boss("12.0", "void_spire", "crown_of_the_cosmos")
        self.assertTrue(crown.supported)
        self.assertEqual(crown.plugin, "boss_plugins.void_spire.crown_of_the_cosmos")
        self.assertEqual(crown.capabilities["avoidable"]["renderer"], "mistake-tracker")
        self.assertTrue(crown.capabilities["replay"]["enabled"])

    def test_venomous_abyss_order_and_external_keys(self):
        frontend = to_frontend_catalog()
        version = next(item for item in frontend["versions"] if item["version"] == "12.1")
        raid = next(item for item in version["raids"] if item["key"] == "venomous_abyss")
        self.assertEqual(raid["externalKey"], "wow.venomabyss")
        self.assertEqual([boss["order"] for boss in raid["bosses"]], list(range(1, 9)))
        self.assertEqual(raid["bosses"][0]["externalKey"], "wow.venomabyss,01.nakzali")
        self.assertEqual(raid["bosses"][-1]["externalKey"], "wow.venomabyss,08.ulatek")

    def test_venomous_abyss_arena_assets_exist(self):
        root = CATALOG_PATH.parent
        version = next(item for item in to_frontend_catalog()["versions"] if item["version"] == "12.1")
        raid = next(item for item in version["raids"] if item["key"] == "venomous_abyss")
        assets = [asset for boss in raid["bosses"] for asset in boss.get("arenaAssets", [])]
        self.assertEqual(len(assets), 9)
        for asset in assets:
            self.assertTrue((root / asset["path"]).is_file(), asset["path"])
            self.assertEqual((asset["width"], asset["height"]), (914, 514))

    def test_tidebound_grotto_reference_is_kept_separate(self):
        boss = find_boss("12.1", "tidebound_grotto", "nymrissa_wavecaller")
        self.assertEqual(boss.english_name, "Nymrissa Wavecaller")
        self.assertEqual(boss.external_key, "")
        self.assertEqual(boss.arena_assets, [])

    def test_duplicate_boss_identity_is_rejected(self):
        duplicate = {
            "versions": [{
                "version": "12.1",
                "raids": [{
                    "key": "raid",
                    "name": "Raid",
                    "bosses": [
                        {"key": "boss", "name": "Boss", "supported": False},
                        {"key": "boss", "name": "Boss Copy", "supported": False},
                    ],
                }],
            }],
        }
        with self.assertRaisesRegex(RuntimeError, "重复项"):
            build_catalog(duplicate)


if __name__ == "__main__":
    unittest.main()
