"""Keep catalog, playback, density, and calculators on one chart reconstruction."""
import json
from pathlib import Path
import subprocess
import tempfile

def project_formal_charts(build):
    if not build.artifacts.music_chart_data:
        return
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder)/'input.json', Path(folder)/'output.json'
        source.write_text(json.dumps(build.artifacts.music_chart_data))
        subprocess.run(['node', str(Path(__file__).with_name('project_formal_charts.mjs')), str(source), str(target)], check=True)
        projected = json.loads(target.read_text())
    build.artifacts.music_chart_data.clear()
    build.artifacts.music_chart_data.update(projected)
    by_id = {}
    for chart in build.catalog['musicCharts']:
        data = projected[chart['id']]
        stats = data['statistics']
        for key in ('judgementCount','judgementCountSource','sourceJudgementCount','explicitJudgementCount',
                    'slideComboCandidateCount','skippedSlideComboCount','mergedEndpointReduction','averageDensity','peakDensity'):
            chart[key] = stats[key]
        delta = stats['runtimeFullCombo'] - chart['masterFullComboCount']
        chart.update(fullComboCount=stats['runtimeFullCombo'], fullComboDelta=delta,
                     fullComboClassification='MATCH' if delta == 0 else 'RUNTIME_HIGHER' if delta > 0 else 'RUNTIME_LOWER',
                     fullComboStatus='match' if delta == 0 else 'conflict', duration=data['duration'],
                     runtimeAlgorithmVersion=data['meta']['runtimeAlgorithmVersion'])
        by_id[chart['id']] = chart
    for track in build.catalog['musicTracks']:
        expert = next((c for c in by_id.values() if c['trackId'] == track['id'] and c['difficulty'] == 'expert'), None)
        if expert: track['expertNoteCount'] = expert['fullComboCount']
    for row in build.quality_report['musicScoreRuntimeReport']:
        chart = by_id[row['chartId']]
        for key in ('runtimeAlgorithmVersion','explicitJudgementCount','slideComboCandidateCount','skippedSlideComboCount','mergedEndpointReduction'):
            row[key] = chart[key]
        row.update(runtimeFullCombo=chart['fullComboCount'],delta=chart['fullComboDelta'],classification=chart['fullComboClassification'])
    build.quality_report['musicScoreRuntimeClassificationCounts'] = {
        status:sum(c['fullComboClassification'] == status for c in by_id.values())
        for status in ('MATCH','RUNTIME_HIGHER','RUNTIME_LOWER')}
