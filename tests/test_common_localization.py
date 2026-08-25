import unittest

from boss_plugins.common import spec_localization


class CommonLocalizationTests(unittest.TestCase):
    def test_protection_warrior_keeps_bilingual_labels(self):
        labels = spec_localization(73)
        self.assertEqual(labels["spec"], {"enUS": "Protection", "zhCN": "防护"})
        self.assertEqual(labels["class"], {"enUS": "Warrior", "zhCN": "战士"})
        self.assertEqual(labels["role"], {"enUS": "Tank", "zhCN": "坦克"})

    def test_unknown_spec_is_safe(self):
        labels = spec_localization(None)
        self.assertEqual(labels["spec"], {})
        self.assertEqual(labels["class"], {})
        self.assertEqual(labels["role"]["zhCN"], "未知")

    def test_devourer_demon_hunter_uses_current_chinese_name(self):
        labels = spec_localization(1480)
        self.assertEqual(labels["spec"], {"enUS": "Devourer", "zhCN": "噬灭"})


if __name__ == "__main__":
    unittest.main()
