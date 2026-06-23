from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "rotmire",
        "name": "腐沼",
        "keywords": ["rotmire", "腐沼"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

