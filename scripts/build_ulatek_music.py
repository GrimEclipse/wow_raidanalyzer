"""Cut the owner-provided Ula'tek soundtrack into its four replay phases."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from boss_plugins.venomous_abyss.ulatek import ULATEK_MUSIC_TRACKS


def track_filter(track):
    """Join explicitly reviewed silent gaps; don't auto-cut quiet music."""
    cuts = track.get('silenceCutsSeconds') or []
    if not cuts:
        return None
    duration = track['sourceDurationMs']/1000
    segments, cursor = [], 0
    for begin, end in cuts:
        if not cursor < begin < end < duration:
            raise ValueError('Invalid or overlapping silence cuts')
        segments.append((cursor, begin))
        cursor = end
    segments.append((cursor, duration))
    split = ''.join(f'[s{i}]' for i in range(len(segments)))
    graph = [f'[0:a]asplit={len(segments)}{split}']
    for i,(begin,end) in enumerate(segments):
        graph.append(f'[s{i}]atrim=start={begin}:end={end},asetpts=PTS-STARTPTS[a{i}]')
    previous = 'a0'
    fade = track['joinCrossfadeMs']/1000
    for i in range(1,len(segments)):
        label = 'music' if i==len(segments)-1 else f'join{i}'
        graph.append(f'[{previous}][a{i}]acrossfade=d={fade}:c1=tri:c2=tri[{label}]')
        previous = label
    return ';'.join(graph)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--phase',action='append',choices=list(ULATEK_MUSIC_TRACKS),help='Rebuild only these phases')
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error('Source audio does not exist')
    executable = args.ffmpeg or shutil.which('ffmpeg')
    if not executable:
        parser.error('Provide --ffmpeg with a local FFmpeg executable')
    for key, track in ULATEK_MUSIC_TRACKS.items():
        if args.phase and key not in args.phase:
            continue
        target = ROOT / track['src'].removeprefix('/')
        target.parent.mkdir(parents=True,exist_ok=True)
        graph = track_filter(track)
        filters = ['-filter_complex',graph,'-map','[music]'] if graph else ['-map','0:a:0']
        subprocess.run([executable,'-hide_banner','-loglevel','error','-nostdin','-y',
            '-ss',str(track['sourceStartSeconds']),'-i',str(args.source),*filters,
            '-t',str(track['durationMs']/1000),'-map_metadata','-1','-c:a','libmp3lame',
            '-b:a','128k','-ar','44100',str(target)],check=True)
        print(key,track['durationMs']/1000,'seconds',target.stat().st_size,'bytes')


if __name__=='__main__':
    main()
