from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENOMOUS = ROOT / "boss_plugins" / "venomous_abyss"


def test_boss_logic_is_not_collected_in_cross_boss_modules():
    assert not (VENOMOUS / "progression.py").exists()
    assert not (VENOMOUS / "court_profiles.py").exists()


def test_each_supported_venomous_boss_has_its_own_backend_module():
    for module in (
        "nakzali", "sentinels", "lostexplorers", "vashnik",
        "sszorak", "twinfangs", "coiledaltar", "ulatek",
    ):
        assert (VENOMOUS / f"{module}.py").is_file()


def test_retired_offline_and_verdict_application_paths_stay_removed():
    retired = (
        "offline_server.py", "build_offline_package.py", "build_offline_package.ps1",
        "build_offline_package.bat", "start_offline.bat", "frontend/offline", "host/OfflineHost.cs",
        "verdicts",
    )
    for relative in retired:
        assert not (ROOT / relative).exists(), relative


def test_calendar_store_uses_descriptive_name_and_new_data_path():
    source = (ROOT / "analyzer_core" / "raid_calendar_store.py").read_text(encoding="utf-8")
    assert 'DB_PATH = ROOT / "data" / "raid_calendar.db"' in source
    assert "raid_calendar_store" in (ROOT / "server.py").read_text(encoding="utf-8")
    assert (ROOT / "frontend" / "tools" / "raid-calendar" / "index.html").is_file()
