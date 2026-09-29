"""Publish a static HTTPS data API; reusable by independently deployed clients."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.qqbot.content import validate_identity, inside


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def build(generated: Path, public_root: Path, output: Path, existing_site: Path | None = None):
    if output.exists():
        raise ValueError('publish a new candidate directory')
    catalog = json.loads((generated / 'catalog.json').read_text())
    systems = json.loads((generated / 'global-systems.json').read_text())
    details = json.loads((generated / 'card-detail-projections.json').read_text())
    database = json.loads((generated / 'game-database.json').read_text())
    release = catalog['release']['id']
    validate_identity(catalog, systems, release)
    if database['sourceReleaseId'] != release:
        raise ValueError('inconsistent data release')
    date = re.match(r'global-prod-(\d{4})(\d{2})(\d{2})-', release)
    if not date:
        raise ValueError('invalid release date')
    # Keep actual presentation fields; omit raw growth/material expansion.
    projected = {key: [{k: row[k] for k in ('cardId','cardKind','skillSummaries','growthSummary','projectionStatus') if k in row}
                       for row in details[key]] for key in ('memberCards','supportCards')}
    skills = {'sourceReleaseId':release,'skills':[{k:s[k] for k in ('id','kind','name','iconAssetId') if k in s} for s in database['skills']]}
    docs = {'catalog.json':catalog,'global-systems.json':systems,'card-detail-projections.json':projected,'game-database.json':skills}
    old_assets = {}
    if existing_site:
        p = existing_site / 'global/zh-CN/data/catalog.json'
        if p.is_file():
            old_assets = {a['id']:a for a in json.loads(p.read_text())['assets']}
    output.mkdir(parents=True)
    manifest = {'schemaVersion':2,'releaseId':release,'snapshotDate':'-'.join(date.groups()),'files':{},'fileUrls':{},'images':{},'remoteAssets':{}}
    reused = 0
    for a in catalog['assets']:
        if a.get('publicPolicy')!='public' or a.get('sourceReleaseId')!=release or not a.get('previewUrl'):
            continue
        source=inside(public_root,a['previewUrl'].lstrip('/'))
        raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest();suffix=source.suffix.lower()
        if suffix not in ('.png','.webp','.jpg','.jpeg'):continue
        old=old_assets.get(a['id'],{});old_url=old.get('previewUrl','')
        old_path=inside(existing_site,old_url.lstrip('/')) if existing_site and old_url else None
        if old_path and old_path.is_file() and hashlib.sha256(old_path.read_bytes()).hexdigest()==digest:
            url=old_url;reused+=1
        else:
            target=output/'assets'/(digest+suffix);target.parent.mkdir(exist_ok=True);target.write_bytes(raw)
            url='/data/qqbot/assets/'+target.name
        manifest['remoteAssets'][a['id']]={'sha256':digest,'suffix':suffix,'url':url,'bytes':len(raw)}
    references=[]
    taxonomy=catalog.get('cardTaxonomy',{})
    references += [r['iconAssetId'] for k in ('attributes','rarities') for r in taxonomy.get(k,[])]
    references += list(taxonomy.get('growthIcons',{}).values())
    references += [s['iconAssetId'] for s in skills['skills'] if s.get('iconAssetId')]
    references += [b[k] for b in catalog['bands'] for k in ('logoAssetId','whiteLogoAssetId') if b.get(k)]
    if any(x not in manifest['remoteAssets'] for x in references):raise ValueError('missing referenced icon')
    for name,value in docs.items():
        raw=encoded(value);digest=hashlib.sha256(raw).hexdigest();p=output/'blobs'/(digest+'.json');p.parent.mkdir(exist_ok=True);p.write_bytes(raw)
        manifest['files'][name]=digest;manifest['fileUrls'][name]='/data/qqbot/blobs/'+p.name
    raw=encoded(manifest);revision=hashlib.sha256(raw).hexdigest();p=output/'releases'/revision/'manifest.json';p.parent.mkdir(parents=True);p.write_bytes(raw)
    (output/'current.json').write_bytes(encoded({'revision':revision,'manifest':'/data/qqbot/releases/'+revision+'/manifest.json'}))
    return {'revision':revision,'releaseId':release,'assetCount':len(manifest['remoteAssets']),'reusedWebsiteAssets':reused,'newAssetFiles':len(list((output/'assets').glob('*'))),'dataBytes':sum(p.stat().st_size for p in (output/'blobs').glob('*'))}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--generated',type=Path,required=True);p.add_argument('--public-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--existing-site',type=Path)
    a=p.parse_args();print(json.dumps(build(a.generated,a.public_root,a.output,a.existing_site),indent=2))
