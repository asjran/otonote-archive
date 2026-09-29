import test from 'node:test';
import assert from 'node:assert/strict';
import { createSpeakerResolver } from '../src/lib/story-speaker.mjs';
test('resolves canonical, short, multilingual and stage names exactly',()=>{
 const character={id:'6',displayName:'Doloris / 三角初华',shortName:'初华',aliases:['Uika','初華'],localizedText:{ja:'ドロリス / 三角 初華'}};
 const resolve=createSpeakerResolver([character]);
 for(const name of ['初华','初華','三角 初華','Doloris','Uika','ドロリス'])assert.equal(resolve(name),character);
 for(const name of ['初华的同学','初华、睦','经纪人',''])assert.equal(resolve(name),null);
});
test('ambiguous aliases never borrow another character avatar',()=>{
 const resolve=createSpeakerResolver([{id:'1',displayName:'甲',aliases:['同名']},{id:'2',displayName:'乙',aliases:['同名']}]);
 assert.equal(resolve('同名'),null);
});
