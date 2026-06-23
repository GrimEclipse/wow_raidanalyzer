from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "beloren",
        "name": "贝洛朗，奥的子嗣",
        "keywords": ["belo'ren, child of al'ar", "beloren", "贝洛朗", "奥的子嗣"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

