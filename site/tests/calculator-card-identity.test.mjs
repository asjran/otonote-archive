import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {cardIdentity} from '../src/lib/calculator-card-ui.mjs';

const catalog=JSON.parse(readFileSync(new URL('../src/data/generated/catalog.json',import.meta.url)));
// A future catalog entry ensures components follow data instead of a copied enum.
const rarities=[...catalog.cardTaxonomy.rarities,{code:99,label:'FUTURE'}];
const fixture={...catalog,cardTaxonomy:{...catalog.cardTaxonomy,rarities}};
for(const kind of ['member','support']) {
  const sample=catalog[`${kind}Cards`][0];
  fixture[`${kind}Cards`]=[...rarities,{code:98}].map(({code})=>({
    ...sample,id:`${kind}-card-${code}`,masterId:code,rarity:code
  }));
}
// Compile the real catalog lookup and inventory projection; only unrelated
// skill data is stubbed. Do not inject rarityLabel into the cards under test.
const compiled=await build({
  entryPoints:[fileURLToPath(new URL('../src/lib/inventory-catalog.ts',import.meta.url))],
  bundle:true,format:'esm',platform:'node',write:false,plugins:[{
    name:'rarity-fixture',setup(builder){
      builder.onResolve({filter:/^@projection-data\/catalog\.json$/},()=>({path:'catalog',namespace:'rarity-fixture'}));
      builder.onResolve({filter:/^\.\/game-database$/},()=>({path:'skills',namespace:'rarity-fixture'}));
      builder.onLoad({filter:/.*/,namespace:'rarity-fixture'},({path})=>path==='catalog'
        ? {contents:JSON.stringify(fixture),loader:'json'}
        : {contents:'export const cardDetailProjections={memberCards:[],supportCards:[]}; export const publicSkills=[];',loader:'js'});
    }
  }]
});
const projected=await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
class Element {
  children=[]; textContent=''; style={setProperty(){}};
  append(...children){this.children.push(...children);}
  setAttribute(){}
}
function useDom(t) {
  const previous=Object.getOwnPropertyDescriptor(globalThis,'document');
  Object.defineProperty(globalThis,'document',{configurable:true,value:{createElement:()=>new Element()}});
  t.after(()=>{if(previous)Object.defineProperty(globalThis,'document',previous);else delete globalThis.document;});
}
for(const kind of ['member','support'])for(const rarity of rarities) {
  test(`${kind} rarity ${rarity.code} displays the catalog label ${rarity.label}`,t=>{
    useDom(t);
    const card=projected[`${kind}Cards`].find(card=>card.rarity===rarity.code);
    assert.equal(card.rarityLabel,rarity.label);
    const before=structuredClone(card);
    const node=cardIdentity({data:{attributeVisuals:[]}},card);
    const identity=node.children.find(child=>child.children.length===3);
    assert.equal(identity.children[0].textContent,`${kind==='member'?'成员':'留影'} · ${rarity.label} · #${card.masterId}`);
    assert.deepEqual(card,before);
  });
}
for(const kind of ['member','support'])test(`${kind} unknown rarity remains visibly unknown`,t=>{
  useDom(t);
  const card=projected[`${kind}Cards`].find(card=>card.rarity===98);
  const node=cardIdentity({data:{}},card);
  const identity=node.children.find(child=>child.children.length===3);
  assert.match(identity.children[0].textContent,/RARITY 98/);
});
