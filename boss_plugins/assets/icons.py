from pathlib import Path


ASSET_DIR = Path(__file__).resolve().parent

BOSS_ICON_PATHS = {
    "alleria_windrunner": ASSET_DIR / "alleria_windrunner.png",
    "silver_phantom": ASSET_DIR / "silver_phantom.png",
    "zuljan": ASSET_DIR / "Zul'jan.png",
    "hex_lord_malacrass": ASSET_DIR / "HexLord_Malacrass.png",
    "poison_orb": ASSET_DIR / "poison_orb.png",
    "manifestation_dread": ASSET_DIR / "Manifestation_Dread.png",
}


def get_boss_icon_path(key):
    return BOSS_ICON_PATHS[key]
