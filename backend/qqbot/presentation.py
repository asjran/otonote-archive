"""Join verified entity fields and artwork into feature-specific view models."""
from __future__ import annotations


def badge(content, kind, code):
    definitions = content.catalog.get('cardTaxonomy', {}).get(kind, [])
    item = next((x for x in definitions if x.get('code', x.get('value')) == code), {})
    return {'label': item.get('names', {}).get('zh-CN') or item.get('label') or f'未识别 {code}',
            'image': content.image(item.get('iconAssetId')), 'color': item.get('color', '#64758A')}


def band_model(content, identifier):
    band = content.bands.get(identifier, {})
    return {'name': band.get('displayName', ''), 'image': content.image(band.get('logoAssetId')),
            'color': band.get('mainColor', '#3388BB')}


def tile(content, item, dataset):
    character = content.characters.get(item.get('characterId'), {})
    return {'title': item.get('displayName') or item.get('title') or item.get('name', ''),
            'id': item.get('masterId', item['id']),
            'image': content.banner(item) if dataset == 'gachaPools' else content.image(item.get('thumbnailAssetId') or item.get('primaryAssetId') or item.get('jacketAssetId') or item.get('profileAssetId')),
            'character': character.get('displayName',''),
            'rarity': badge(content,'rarities',item['rarity']) if 'rarity' in item else None,
            'attribute': badge(content,'attributes',item['attributeCode']) if 'attributeCode' in item else None}


def enrich(content, dataset, item, reply):
    reply.layout = dataset
    data = {'id': item.get('masterId',item['id'])}
    if dataset in ('memberCards','supportCards'):
        ids = [item['characterId']] if dataset=='memberCards' else item.get('featuredCharacterIds',[])
        chars = [content.characters[x] for x in ids if x in content.characters]
        data.update(rarity=badge(content,'rarities',item.get('rarity')), attribute=badge(content,'attributes',item.get('attributeCode')),
                    characters=[{'name':x['displayName'],'image':content.image(x.get('profileAssetId'))} for x in chars],
                    band=band_model(content,chars[0].get('bandId')) if chars else {},
                    stats=[(label,item.get(key)) for label,key in [('表演','performancePowerMax'),('技巧','technicPowerMax'),('视觉','visualPowerMax')]])
        detail = content.card_details.get(item['id'],{})
        data['growth'] = detail.get('growthSummary',{})
        data['skills'] = []
        labels={'leader':'队长技能','live':'演出技能','gekisou':'激奏技能','support_1':'普通支援','gekisou_support_1':'激奏支援'}
        for summary in detail.get('skillSummaries',[]):
            skill=content.skills.get(summary.get('skillId'),{})
            slot=summary.get('slot',skill.get('kind',''))
            label=labels.get(slot, '激奏支援' if slot.startswith('gekisou_support') else '普通支援' if slot.startswith('support') else '激奏技能' if 'gekisou' in slot else '技能')
            data['skills'].append({**summary,'category':label,'image':content.image(skill.get('iconAssetId'))})
    elif dataset=='musicTracks':
        data.update(bands=[band_model(content,x) for x in item.get('bandIds',[])],
                    vocal=' / '.join(item.get('vocalistLabels',[])),bpm=item.get('bpm') or {},
                    type=item.get('musicTypeLabel',''),
                    credits=[(label,item.get(k) or '未收录') for label,k in [('作词','lyricist'),('作曲','composer'),('编曲','arranger')]])
        order={'easy':0,'normal':1,'hard':2,'expert':3}
        data['charts']=sorted([x for x in content.catalog['musicCharts'] if x.get('trackId')==item['id']], key=lambda x:order.get(x.get('difficulty','').lower(),9))
    elif dataset=='characters':
        assets = {a['id']: a for a in content.catalog['assets']}
        standing = next((x for x in item.get('portraitAssetIds', []) if assets.get(x, {}).get('containerPath', '').endswith('/character_sprite.png')), None)
        if standing:
            reply.image = content.image(standing)
        data.update(band=band_model(content,item.get('bandId')),role=item.get('role') or '未收录',birthday=item.get('birthday') or {},profile=item.get('profile') or {},aliases=item.get('aliases',[]))
        cards=[x for x in content.catalog['memberCards'] if x.get('characterId')==item['id']]
        snaps=[x for x in content.catalog['supportCards'] if item['id'] in x.get('featuredCharacterIds',[])]
        data['counts']=(len(cards),len(snaps))
        data['related']=[tile(content,x,'memberCards') for x in cards[-3:]]
    elif dataset=='gachaPools':
        data.update(start=item.get('startAt') or '未配置',end=item.get('endAt') or '未配置',
                    pickups=[tile(content,content.cards[x],'memberCards') for x in item.get('pickupMemberCardIds',[]) if x in content.cards],
                    missingPickups=sum(x not in content.cards for x in item.get('pickupMemberCardIds',[])))
    if dataset == 'musicTracks' and data.get('bands'):
        reply.accent = data['bands'][0].get('color', reply.accent)
    reply.visual=data
    return reply
