"""Decode representative current resources on a new runtime before enabling updates."""
from pathlib import Path
import argparse
import gc
import gzip
import json
import tempfile
from tools.global_remote_sync import read_json,write_json,file_hash
from tools.current_resources import CurrentResources
from tools.current_content_inputs import core_image_targets


def verify(snapshot, profile, cache, output):
    if output.exists(): raise ValueError('extractor verification output must be new')
    output.mkdir(parents=True)
    decoder=read_json(profile)
    resources=CurrentResources(snapshot,cache,decoder['metadata'],decoder['apk'],decoder=decoder)
    results={}
    def image():
        container,loc=next(iter(core_image_targets(resources).items()))
        _,data=resources.texture(loc,container);data.image.save(output/'image.png')
        return {'source':container,'sha256':file_hash(output/'image.png')}
    def score():
        from analysis.crypto.decrypt_global_formal_scores import text_payload
        row=resources.rows('MasterLiveMusicScore')[0];name=row['_musicScoreTextFileName']
        loc=resources.prefix('live_assets_live_musicscore_'+name.lower().replace('/','_')+'_')
        env=resources.environment(loc.primary_key)
        values=[json.loads(gzip.decompress(text_payload(o.read().m_Script))) for o in env.objects if o.type.name=='TextAsset']
        if len(values)!=1 or not isinstance(values[0].get('score'),dict):raise ValueError('score decode failed')
        return {'source':loc.primary_key,'status':'passed'}
    def audio():
        from tools.import_global_music_audio import song_bundles,find_executable,discover_split_acb,process_split_acb,process_acb,CURRENT_USM_KEY
        _,cue,loc=song_bundles(resources.master,resources.catalog.locations)[0]
        payload=resources.get(loc)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/loc.primary_key).symlink_to(payload)
            candidates=discover_split_acb(Path(folder))
        if len(candidates)!=1:raise ValueError('missing unique audio object')
        candidate=candidates[0];candidate.source=payload
        record=process_split_acb(candidate,output/'audio',output/'audio-work',CURRENT_USM_KEY,
            find_executable(None,('vgmstream-cli','/opt/homebrew/bin/vgmstream-cli')),
            find_executable(None,('ffmpeg','/opt/homebrew/bin/ffmpeg')),process_acb)
        record.pop('hca_key',None)
        if not record.get('ok') or not record.get('streams'):raise ValueError('audio decode failed: '+str(record.get('error')))
        write_json(output/'audio-report.json',record)
        return {'cue':cue,'streams':len(record['streams']),'status':'passed'}
    def model():
        from tools.live2d_discovery import discover_models
        from tools.prepare_live2d import export_model
        item=discover_models(resources.catalog.locations,resources.rows('MasterCharacterCostume'))[0]
        asset=resources.locate('Character/Live2D/'+item['modelPath'])
        names=[n for n in asset.dependencies if n.startswith('character-live2d_')]
        if len(names)!=1:raise ValueError('ambiguous model bundle')
        loc=resources.locate(names[0])
        report=export_model(resources.environment(loc.primary_key),output/'model',item['modelPath'].rsplit('/',1)[-1])
        return {'model':item['id'],'files':len(report['resources']),'status':'passed'}
    def scene():
        from tools.export_immersive_scenes import export_scene
        spot=resources.rows('MasterHomeSpot')[0]
        names={n for key in ('_backgroundAssetPath','_situationAssetPath') for n in resources.locate(spot[key]).dependencies if n.startswith('spot_')}
        sources={n:{'bundle':n,'sha256':file_hash(resources.get(resources.locate(n)))} for n in names}
        (output/'scenes').mkdir()
        export_scene(spot,resources.locations,sources,resources.clear,public=output/'scenes',release='runtime-smoke')
        return {'scene':spot['_id'],'status':'passed'}
    for name,operation in [('image',image),('score',score),('audio',audio),('live2d',model),('scene',scene)]:
        print('Verifying extractor:',name,flush=True)
        results[name]=operation();gc.collect()
    report={'status':'passed','catalogSha256':resources.report['catalogSha256'],'apkSha256':decoder['apkSha256'],'checks':results}
    write_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','profile','cache','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.snapshot,args.profile,args.cache,args.output),indent=2))
