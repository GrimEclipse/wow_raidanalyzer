from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "lightblinded_vanguard",
        "name": "光盲先锋军",
        "keywords": ["lightblinded vanguard", "光盲先锋军"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

