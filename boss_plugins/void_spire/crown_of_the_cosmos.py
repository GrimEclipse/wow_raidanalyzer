from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "crown_of_the_cosmos",
        "name": "宇宙之冕",
        "keywords": ["crown of the cosmos", "宇宙之冕"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

