from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "fallen_king_salhadaar",
        "name": "陨落之王萨哈达尔",
        "keywords": ["fallen-king salhadaar", "fallen king salhadaar", "陨落之王萨哈达尔"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

