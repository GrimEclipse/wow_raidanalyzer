"""Cut the owner-provided Ula'tek soundtrack into its four replay phases."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from boss_plugins.venomous_abyss.ulatek import ULATEK_MUSIC_TRACKS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--ffmpeg')
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error('Source audio does not exist')
    executable = args.ffmpeg or shutil.which('ffmpeg')
    if not executable:
        parser.error('Provide --ffmpeg with a local FFmpeg executable')
    for key, track in ULATEK_MUSIC_TRACKS.items():
        target = ROOT / track['src'].removeprefix('/')
        target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run([executable,'-hide_banner','-loglevel','error','-nostdin','-y',
            '-ss',str(track['sourceStartSeconds']),'-i',str(args.source),
            '-t',str(track['durationMs']/1000),'-map','0:a:0','-map_metadata','-1','-c:a','libmp3lame',
            '-b:a','128k','-ar','44100',str(target)],check=True)
        print(key,track['durationMs']/1000,'seconds',target.stat().st_size,'bytes')


if __name__=='__main__':
    main()
