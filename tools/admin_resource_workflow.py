"""Manual resource stages; called only under the production workflow lock."""
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from tools.global_remote_sync import read_json, write_json, file_hash


def pointer_digest(config):
    pointer = Path(config['contentPublication']['root']) / 'current.json'
    return file_hash(pointer) if pointer.is_file() else None


def checked_plan(record):
    from tools.release_preflight import inspect_plan
    plan = Path(record['inputPlan'])
    if file_hash(plan) != record['inputPlanSha256'] or inspect_plan(plan, require_production=True)['status'] != 'passed':
        raise ValueError('inputs changed; fetch resources again')
    return plan


def execute(config, journal, action, candidate_id=None):
    from tools import global_update as workflow
    from tools.content_publication import publish_content, verify_tree
    from tools.update_retention import history
    if not config.get('contentPublication') or config.get('publication'):
        raise ValueError('manual stages require the content-only publication profile')
    workspace = config['workspace']
    fetched_path, staged_path = workspace/'manual-inputs.json', workspace/'manual-candidate.json'
    state_path = workspace/'state.json'
    if action == 'fetch':
        if workflow.shutil.disk_usage(workspace).free < config.get('minimumFreeBytes', 0):
            raise ValueError('insufficient free disk space')
        journal.step('dependencies', lambda: workflow.doctor(config, build=True))
        client = workflow.GlobalPublicClient(config['clientVersion'])
        package = journal.step('official-package', lambda: workflow.package_check(config, client))
        decoder = None
        if config.get('intakePackages'):
            from tools.current_client import intake
            decoder = journal.step('verify-client', lambda: intake(package['package'], workspace/'clients', workflow.ROOT/config['apksigJar']))
            client = workflow.GlobalPublicClient(decoder['clientVersion'])
        synced = journal.step('sync-inputs', lambda: workflow.update(client, workspace/('sync-complete' if config.get('completeContent') else 'sync'),
            config['baseline'], config['inputPlan'], False, complete_content=config.get('completeContent', False), decoder=decoder))
        plan = Path(synced.get('inputPlan') or synced['candidate'])
        record = {'schemaVersion': 1, 'status': 'inputs_fetched', 'observation': synced['observation'],
                  'inputPlan': str(plan), 'inputPlanSha256': file_hash(plan), **package}
        journal.step('input-preflight', lambda: checked_plan(record))
        write_json(fetched_path, record)
        # A new explicit fetch invalidates a previous manual selection.
        staged_path.unlink(missing_ok=True)
        return {'status': 'inputs_fetched', 'inputPlanSha256': record['inputPlanSha256']}
    if action == 'build':
        if workflow.shutil.disk_usage(workspace).free < config.get('minimumFreeBytes', 0):
            raise ValueError('insufficient free disk space')
        record = read_json(fetched_path)
        plan = journal.step('input-preflight', lambda: checked_plan(record))
        projection_fingerprint = workflow.chart_projection_fingerprint()
        previous = read_json(state_path) if state_path.exists() else {}
        if (previous.get('inputPlanSha256') == record['inputPlanSha256']
                and previous.get('chartProjectionFingerprint') == projection_fingerprint):
            build = Path(previous['buildDirectory']).resolve()
        else:
            build = workspace/'builds'/(record['inputPlanSha256'][:20]+'-'+uuid4().hex[:8])
        if (workspace/'builds').resolve() not in build.resolve().parents:
            raise ValueError('candidate is outside the registered workspace')
        candidate = build/'candidate'
        if not candidate.exists():
            journal.command('compile-data', [sys.executable, 'tools/release_candidates.py', '--plan', str(plan), '--output', str(candidate), '--keep-failed'])
        metadata = read_json(candidate/'candidate.json')
        if metadata.get('inputPlanSha256') != record['inputPlanSha256'] or metadata.get('status') != 'candidate_generated' or metadata.get('historicalReplay'):
            raise ValueError('candidate input binding is invalid')
        journal.step('verify-candidate', lambda: verify_tree(candidate, metadata['files'], exclude=('candidate.json',)))
        from tools.scoring_content import bind_scoring_rules
        sources = read_json(plan)['environments']
        if len(sources) != 1:
            raise ValueError('candidate requires one bound source')
        source = sources[0]
        rules = journal.step('scoring-rules', lambda: bind_scoring_rules(workflow.ROOT/source['masterRoot'], source['contentReleaseId']))
        checked_plan(record)
        if workflow.chart_projection_fingerprint() != projection_fingerprint:
            raise ValueError('chart projection changed during candidate generation')
        rules_path = build/'manual-scoring-rules.json'
        write_json(rules_path, rules)
        write_json(build/'workflow-input.json', {'inputPlan': str(plan), 'chartProjectionFingerprint': projection_fingerprint})
        record.update(candidate=str(candidate), buildDirectory=str(build), candidateSha256=file_hash(candidate/'candidate.json'),
                      rulesPath=str(rules_path), rulesSha256=file_hash(rules_path), publicationBaseline=pointer_digest(config),
                      contentReleaseId=source['contentReleaseId'], status='candidate_built',
                      chartProjectionFingerprint=projection_fingerprint)
        record['id'] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        write_json(staged_path, record)
        return {'status': 'candidate_built', 'candidateId': record['id'], 'contentReleaseId': record['contentReleaseId']}
    if action != 'publish':
        raise ValueError('unsupported manual action')
    record = read_json(staged_path)
    if not candidate_id or candidate_id != record.get('id'):
        raise ValueError('candidate changed; refresh and confirm the candidate again')
    if record.get('chartProjectionFingerprint') != workflow.chart_projection_fingerprint():
        raise ValueError('chart projection changed; rebuild the candidate before publishing')
    if pointer_digest(config) != record['publicationBaseline']:
        raise ValueError('published content changed; rebuild the candidate before publishing')
    journal.step('input-preflight', lambda: checked_plan(record))
    candidate = Path(record['candidate']).resolve()
    if (workspace/'builds').resolve() not in candidate.parents:
        raise ValueError('candidate is outside the registered workspace')
    if file_hash(candidate/'candidate.json') != record['candidateSha256'] or file_hash(Path(record['rulesPath'])) != record['rulesSha256']:
        raise ValueError('candidate changed after verification')
    published = journal.step('publish-content', lambda: publish_content(candidate, config['contentPublication']['root'], scoring_rules=record['rulesPath'], expected_current=record['publicationBaseline'] or ''))
    previous = read_json(state_path) if state_path.exists() else None
    result = {k: record[k] for k in ('schemaVersion', 'observation', 'inputPlan', 'inputPlanSha256', 'buildDirectory', 'candidate', 'package', 'packageChanged', 'chartProjectionFingerprint') if k in record}
    result.update(status=published['status'], publication=published, publicationReady=False, limitations=['formal_gameplay_not_verified'])
    result['retainedBuilds'] = history(previous, result)
    result['retention'] = {'status': 'deferred_to_operations'}
    write_json(Path(record['buildDirectory'])/'content-publication.json', published)
    journal.step('save-success', lambda: write_json(state_path, result))
    staged_path.unlink(missing_ok=True)
    # Manual publication has the same boundary as automatic content publication:
    # independent audited maintenance owns historical inputs/content lifecycle.
    return {'status': published['status'], 'candidateId': candidate_id, 'publication': published,
            'retention': result['retention']}
