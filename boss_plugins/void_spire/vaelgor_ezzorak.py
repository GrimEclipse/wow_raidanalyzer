from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "vaelgor_ezzorak",
        "name": "威厄高尔和艾佐拉克",
        "keywords": ["vaelgor & ezzorak", "vaelgor", "ezzorak", "威厄高尔", "艾佐拉克"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

