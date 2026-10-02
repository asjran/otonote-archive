"""Read-only JP snapshot audit. Usage: python3 tools/audit_jp_snapshot.py CONTENT_STORE.

Checks published references, document hashes and model/scene dependency hashes.
This does not establish feature completeness or validate gameplay semantics.
"""
import json,pathlib,hashlib,collections,sys,urllib.parse
store=pathlib.Path(sys.argv[1]);pointer=json.loads((store/'jp/current.json').read_text());root=store/pointer['manifest'][9:];mb=root.read_bytes();root=root.parent;m=json.loads(mb);errors=[];refs=set();hashes=0;counts=collections.Counter();identities=collections.Counter();relative=0; resource_hashes={}
if hashlib.sha256(mb).hexdigest()!=pointer['sha256']:errors.append(['manifest_hash'])
def walk(v,p,key='',trail=(),reference=None):
 global relative
 if isinstance(v,dict):
  for k,x in v.items():walk(x,p,k,(*trail,k),reference)
 elif isinstance(v,list):
  for x in v:walk(x,p,key,trail,reference)
 elif isinstance(v,str):
  if key in ('contentReleaseId','sourceReleaseId'):
   if reference and trail in (('native','sourceReleaseId'),('referenceProfile','sourceReleaseId')) and v==reference:
    counts['declaredReferenceIdentities']+=1
   else:identities[v]+=1
  if v.startswith('/content/releases/'):
   refs.add(v)
   if not v.startswith(m['root']):errors.append(['foreign_snapshot',str(p),v])
   elif not (store/urllib.parse.unquote(v.split('?')[0].split('#')[0])[9:]).exists():errors.append(['missing_url',str(p.relative_to(root)),v])
  if p.name.endswith('.model3.json') and key in ('Moc','Textures','File','Physics','Pose','DisplayInfo','UserData') and v:
   relative+=1
   if not (p.parent/v).is_file():errors.append(['missing_model_file',str(p.relative_to(root)),v])
for locale,d in m['locales'].items():
 for name,r in {**d['files'],**d.get('groups',{})}.items():
  f=root/r['path']
  if not f.is_file():errors.append(['missing_record',locale,name]);continue
  b=f.read_bytes();hashes+=1
  if hashlib.sha256(b).hexdigest()!=r['sha256']:errors.append(['record_hash',locale,name])
for p in root.rglob('*'):
 if not p.is_file() or p.name=='.DS_Store':continue
 rel=str(p.relative_to(root));counts['files']+=1;counts['bytes']+=p.stat().st_size
 if p.suffix=='.json':
  counts['json']+=1
  try:
   value=json.loads(p.read_text())
   reference=None
   if p.name=='formal-scoring-rules.json' and p.parent.name=='_supplemental':
    r=value.get('referenceProfile',{});n=value.get('native',{})
    if value.get('verificationStatus')=='reference_compatible' and r.get('currentGameplayVerified') is False and r.get('sourceReleaseId')==n.get('sourceReleaseId') and r.get('nativeSha256')==n.get('nativeSha256')==value.get('nativeSha256'):
     reference=r.get('sourceReleaseId')
   walk(value,p,reference=reference)
   if p.name=='manifest.json' and rel.startswith(('public/live2d/','public/immersive/')):
    entries=value.get('files',value.get('resources',[]))
    if isinstance(entries,list):
     for entry in entries:
      if not isinstance(entry,dict) or 'sha256' not in entry:continue
      entry_path=entry.get('path',entry.get('file'))
      if not entry_path:continue
      target=(p.parent/entry_path).resolve()
      if not str(target).startswith(str(root.resolve())+'/'):errors.append(['escaped_resource',rel,entry_path]);continue
      if not target.is_file():errors.append(['missing_resource',rel,entry_path]);continue
      if target not in resource_hashes:resource_hashes[target]=hashlib.sha256(target.read_bytes()).hexdigest()
      if resource_hashes[target]!=entry['sha256']:errors.append(['resource_hash',rel,entry_path])

  except Exception as e:errors.append(['json_error',rel,str(e)])
for rid,n in identities.items():
 if rid!=m['contentReleaseId']:errors.append(['foreign_release',rid,n])
print(json.dumps({'pointer':pointer,'region':m['region'],'counts':dict(counts),'manifestRecordsHashed':hashes,'uniqueContentUrls':len(refs),'modelFileReferences':relative,'resourceFilesHashed':len(resource_hashes),'releaseIdentities':dict(identities),'errors':errors},ensure_ascii=False,indent=2))
sys.exit(bool(errors))
