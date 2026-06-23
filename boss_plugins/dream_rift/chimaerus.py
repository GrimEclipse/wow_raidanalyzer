from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "chimaerus",
        "name": "奇美鲁斯，未梦之神",
        "keywords": ["chimaerus the undreamt god", "奇美鲁斯", "未梦之神"],
    },
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)

