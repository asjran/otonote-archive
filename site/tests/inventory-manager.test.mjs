import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createInventoryManager,parseDelimited} from '../src/lib/inventory-manager.mjs';
import {searchEvaluationBudget} from '../src/lib/optimizer-guidance.mjs';
const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const cards=[{id:'member-card-1',kind:'member',shortLabel:'春, "歌"',displayName:'重复名字'},
  {id:'member-card-2',kind:'member',shortLabel:'唯一名字',displayName:'重复名字'},
  {id:'support-card-1',kind:'support',shortLabel:'留影一'}];
const manager=createInventoryManager(rules,cards);

test('complete search has no budget; quick/deep/custom remain bounded',()=>{
  assert.equal(searchEvaluationBudget('complete',''),0);
  assert.equal(searchEvaluationBudget('20',200),20);
  assert.equal(searchEvaluationBudget('200',20),200);
  assert.equal(searchEvaluationBudget('custom','7'),7);
  for(const value of ['',0,-1,1.5,100001,'abc'])assert.throws(()=>searchEvaluationBudget('custom',value));
});
test('CSV quoting, BOM and spreadsheet tabs preserve names and multiline cells',()=>{
  assert.deepEqual(parseDelimited('\uFEFF名称,等级\r\n"春, ""歌""",1\r\n'),[['名称','等级'],['春, "歌"','1']]);
  assert.deepEqual(parseDelimited('名称\t等级\n"跨\n行"\t2'),[['名称','等级'],['跨\n行','2']]);
  assert.throws(()=>parseDelimited('"未闭合'),/引号/);
});
test('paste IDs and exact names; ambiguous names, duplicates and kind conflicts stay review errors',()=>{
  const rows=manager.preview('唯一名字\nmember-card-1\nsupport-card-1');
  assert.deepEqual(rows.map(r=>r.id),['member-card-2','member-card-1','support-card-1']);
  assert.equal(manager.preview('1',{kind:'support'})[0].id,'support-card-1');
  assert.match(manager.preview('重复名字')[0].error,/多张/);
  assert.match(manager.preview('不存在')[0].error,/没有找到/);
  assert.match(manager.preview('1\nmember-card-1')[1].error,/重复/);
  assert.match(manager.preview('类型,卡片ID\n留影,member-card-1')[0].error,/不一致/);
});
test('Chinese CSV and TSV headers import explicit growth and default omitted fields to one',()=>{
  const result=manager.merge(manager.empty(),manager.preview('类型\t卡片ID\t等级\t突破阶数\t觉醒阶数\t演出技能\t激奏技能\n成员\tmember-card-1\t5\t1\t1\t2\t3\n留影\tsupport-card-1\t4\t1\t\t\t'));
  assert.deepEqual(result.inventory.growth['member-card-1'],{level:5,rank:1,awake:1,skillLevel:2,gekisouSkillLevel:3});
  assert.deepEqual(result.inventory.growth['support-card-1'],{level:4,rank:1});
  const plain=manager.merge(manager.empty(),manager.preview('member-card-1')).inventory;
  assert.deepEqual(plain.growth['member-card-1'],{level:1,rank:1,awake:1,skillLevel:1,gekisouSkillLevel:1});
});
test('merge preserves existing growth by default, explicit update changes only provided fields',()=>{
  const original=manager.batch(manager.empty(),['member-card-1'],{patch:{level:5,skillLevel:3}});
  const rows=manager.preview('id,level\nmember-card-1,2\nmember-card-2,3');
  const kept=manager.merge(original,rows);
  assert.equal(kept.inventory.growth['member-card-1'].level,5);
  assert.equal(kept.changes[0].action,'保留');
  const updated=manager.merge(original,rows,{updateExisting:true});
  assert.equal(updated.inventory.growth['member-card-1'].level,2);
  assert.equal(updated.inventory.growth['member-card-1'].skillLevel,3);
  assert.equal(original.growth['member-card-1'].level,5);
  assert.equal(original.memberCardIds.length,1);
});
test('invalid growth aborts entire merge or batch without mutating the saved inventory',()=>{
  const original=manager.batch(manager.empty(),['member-card-1']),before=structuredClone(original);
  assert.throws(()=>manager.merge(original,manager.preview('id,level\nmember-card-2,1\nmember-card-3,999')));
  assert.throws(()=>manager.batch(original,['member-card-1','member-card-2'],{patch:{level:999}}));
  assert.deepEqual(original,before);
  assert.throws(()=>manager.merge(original,manager.preview('id,skillLevel\nmember-card-2,6')));
  assert.match(manager.preview('id,awake\nsupport-card-1,1')[0].error,/留影/);
});
test('growth presets use real caps for every card and current-level preset preserves other growth',()=>{
  for(const kind of ['member','support'])for(const row of rules.tables[kind==='member'?'MemberCard':'SupportCard']) {
    const id=`${kind}-card-${row._id}`,max=manager.batch(manager.empty(),[id],{mode:'maximum'});
    assert.doesNotThrow(()=>manager.validate(max));
    const low=manager.batch(manager.empty(),[id],{patch:kind==='member'?{skillLevel:2}:{} });
    const level=manager.batch(low,[id],{mode:'level'}).growth[id];
    assert.equal(level.rank,1);if(kind==='member'){assert.equal(level.awake,1);assert.equal(level.skillLevel,2);}
    assert.ok(level.level<=max.growth[id].level);
  }
});
test('JSON backups round trip, reject wrong release and do not replace other owned cards',()=>{
  const backup=manager.batch(manager.empty(),['member-card-1','support-card-1'],{mode:'maximum'});
  assert.deepEqual(manager.merge(manager.empty(),manager.preview(JSON.stringify(backup))).inventory,backup);
  const existing=manager.batch(manager.empty(),['member-card-2']);
  assert.equal(manager.merge(existing,manager.preview(JSON.stringify(backup))).inventory.memberCardIds.length,2);
  assert.throws(()=>manager.preview(JSON.stringify({...backup,sourceReleaseId:'other-release'})),/release/);
});
test('bad tables fail closed instead of silently dropping data',()=>{
  assert.throws(()=>manager.preview('id,levle\n1,50'),/表头/);
  assert.throws(()=>manager.preview('id,id\n1,2'),/重复/);
  assert.match(manager.preview('1,2')[0].error,/表头/);
  assert.match(manager.preview('id,level\n1,2,3')[0].error,/列数/);
  assert.throws(()=>manager.preview(''),/清单/);
});

test('skill-only maximum preserves level, rank, awakening and unselected cards',()=>{
  const original=manager.batch(manager.empty(),['member-card-1','member-card-2'],{patch:{level:7,skillLevel:2,gekisouSkillLevel:3}});
  const saved=structuredClone(original);
  const next=manager.batch(original,['member-card-1'],{mode:'skills'});
  assert.deepEqual(next.growth['member-card-1'],{...original.growth['member-card-1'],skillLevel:5,gekisouSkillLevel:5});
  assert.deepEqual(next.growth['member-card-2'],original.growth['member-card-2']);
  assert.deepEqual(original,saved);
  assert.throws(()=>manager.batch(original,['support-card-1'],{mode:'skills'}),/留影/);
});

test('per-card maximum level uses each cards own stage and preserves every other field',()=>{
  let original=manager.batch(manager.empty(),['support-card-1','support-card-2']);
  original=manager.batch(original,['support-card-2'],{patch:{rank:2}});
  const next=manager.batch(original,original.supportCardIds,{patch:{level:'maximum'}});
  for(const id of original.supportCardIds) {
    assert.equal(next.growth[id].level,manager.preset(id,'support','level',original.growth[id]).level);
    assert.equal(next.growth[id].rank,original.growth[id].rank);
  }
  assert.notEqual(next.growth['support-card-1'].level,next.growth['support-card-2'].level);
});

test('mixed field selections resolve stage maximum before level and can update one skill only',()=>{
  const original=manager.batch(manager.empty(),['member-card-1','member-card-2'],{patch:{level:7,skillLevel:2,gekisouSkillLevel:3}});
  const skills=manager.batch(original,original.memberCardIds,{patch:{skillLevel:'maximum'}});
  for(const id of original.memberCardIds)assert.deepEqual(skills.growth[id],{...original.growth[id],skillLevel:5});
  const changes={level:'maximum',rank:'maximum',awake:'maximum',skillLevel:'maximum',gekisouSkillLevel:'maximum'};
  const full=manager.batch(original,original.memberCardIds,{patch:changes});
  assert.deepEqual(full,manager.batch(original,original.memberCardIds,{mode:'maximum'}));
});

test('choice lists reflect real per-card limits and invalid batch stays atomic',()=>{
  for(const kind of ['member','support'])for(const row of rules.tables[kind==='member'?'MemberCard':'SupportCard']) {
    const id=`${kind}-card-${row._id}`,base=manager.preset(id,kind);
    for(const field of kind==='member'?['level','rank','awake','skillLevel','gekisouSkillLevel']:['level','rank']) {
      const options=manager.choices(id,kind,field,base);
      assert.ok(options.length>0);
      for(const value of options)assert.doesNotThrow(()=>manager.batch(manager.empty(),[id],{patch:{[field]:value}}));
    }
  }
  const original=manager.batch(manager.empty(),['member-card-1','support-card-1']),saved=structuredClone(original);
  assert.throws(()=>manager.batch(original,['member-card-1','support-card-1'],{patch:{level:999,rank:'maximum'}}));
  assert.deepEqual(original,saved);
  assert.throws(()=>manager.batch(original,['member-card-1'],{mode:'typo'}),/未知/);
});
