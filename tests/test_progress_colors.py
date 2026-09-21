import json
import subprocess
from pathlib import Path


def test_progress_colors_use_wcl_completion_and_ignore_phase():
    source = (Path(__file__).resolve().parents[1] / 'frontend/report/overview.js').read_text(encoding='utf-8')
    functions = source[source.index('function completionProgress'):source.index('function totalTime')]
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
    script = functions + '\nconst cases=' + json.dumps(cases) + ';for(const [pull,color] of cases){if(phaseColor(pull)!==color)throw Error(JSON.stringify(pull));}'
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
