from boss_plugins.venomous_abyss.progression import analyze_boss, build_aggregated_json as _build


def build_aggregated_json(report_ids, options=None):
    return _build("sszorak", report_ids, options)


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return analyze_boss("sszorak", report_ids, output_path, catalog_entry, options)
