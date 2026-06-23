from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "imperator_averzian",
        "name": "元首阿福扎恩",
        "keywords": ["imperator averzian", "元首阿福扎恩"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

