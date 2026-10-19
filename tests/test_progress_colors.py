import json
import subprocess
from pathlib import Path


def test_progress_colors_use_wcl_completion_and_ignore_phase():
    functions = 'const window={};\n' + (Path(__file__).resolve().parents[1] / 'frontend/core/pull-progress.js').read_text(encoding='utf-8')
    cases = [
        ({'bossPercentage': 51.94, 'fightPercentage': 37, 'wipePhase': 'P3'}, '#0070ff'),
        ({'bossPercentage': 67.2, 'fightPercentage': 76.45, 'wipePhase': 'P2', 'phaseColor': '#a98bff'}, '#999999'),
        ({'bossPercentage': 65.54, 'fightPercentage': 68.44, 'wipePhase': 'P2'}, '#1eff00'),
        ({'fightPercentage': 25}, '#a335ee'),
        ({'fightPercentage': 5}, '#ff8000'),
        ({'fightPercentage': 1}, '#e268a8'),
        ({'fightPercentage': 75}, '#1eff00'),
        ({'fightPercentage': 50}, '#0070ff'),
        ({'bossPercentage': 90}, '#999999'),
    ]
    script = functions + '\nconst cases=' + json.dumps(cases) + ';for(const [pull,color] of cases){if(window.MythicPullProgress.color(pull)!==color)throw Error(JSON.stringify(pull));}'
    script += '''
    const p=window.MythicPullProgress;
    if(p.phaseCode({wipePhase:'P2.5 full name'})!=='P2.5')throw Error('short phase');
    if(p.completion({wipePhase:'P3',bossPercentage:5})!==null)throw Error('stage HP cannot be whole progress');
    if(p.completion({isKill:true})!==100)throw Error('kill');
    '''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
