import test from 'node:test';
import assert from 'node:assert/strict';
import {renderRankingDetail} from '../src/lib/song-ranking-detail.mjs';
import {rankingSongCover} from '../src/lib/ranking-song-cover.mjs';
class Element {
  constructor(tag,ownerDocument){this.tagName=tag;this.ownerDocument=ownerDocument;this.children=[];this.dataset={};this.attrs={};this.listeners={};this.style={setProperty(){}};}
  set textContent(text){this.text=String(text);this.children=[];}
  get textContent(){return (this.text??'')+this.children.map(child=>child.textContent).join(' ');}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  setAttribute(key,value){this.attrs[key]=value;}
  addEventListener(key,handler){this.listeners[key]=handler;}
  remove(){this.parent.children=this.parent.children.filter(child=>child!==this);}
}
const document={createElement:tag=>new Element(tag,document)};
const walk=node=>[node,...node.children.flatMap(walk)];
const row={title:'Song <one>',trackId:'global--music-a',sourceEdition:'global',difficulty:'expert',expectedScore:1000,minimumScore:900,maximumScore:1100,p10Score:920,baseScore:700,skillScoreGain:300,
  benchmark:{power:100000,skillPercent:100,skillSeconds:5},applicableEditions:['global'],pendingEditions:[],skillReference:{startsSeconds:[10,20,30,40,50]},editionChartReferences:{global:{sourceReleaseId:'release-a'}}};
test('covers reserve their shape and fall back without a broken image',()=>{
  const cover=rankingSongCover(document,'/media/cover.webp');
  const img=cover.children.find(child=>child.tagName==='img');
  assert.equal(img.src,'/media/cover.webp');assert.equal(img.loading,'lazy');assert.equal(img.alt,'');
  img.listeners.error();assert.equal(cover.children.length,1);assert.equal(cover.textContent,'♪');
  assert.equal(rankingSongCover(document,null).children.length,1);
});
test('compact details preserve links, five positions and accurate no-skill labels',()=>{
  const root=document.createElement('div');
  renderRankingDetail(root,{...row,skillProfile:Array.from({length:5},()=>({percent:0,seconds:0}))},{server:'global-hmt',artwork:'/cover.webp'});
  const nodes=walk(root),links=nodes.filter(n=>n.tagName==='a');
  assert.equal(links.length,2);assert.ok(links.every(n=>n.href.includes('server=global-hmt')&&n.href.includes('difficulty=expert')));
  assert.equal(nodes.find(n=>n.className==='ranking-skill-slots').children.length,5);
  assert.equal(nodes.filter(n=>n.tagName==='small'&&n.textContent==='无加分技能').length,5);
  assert.ok(nodes.filter(n=>n.tagName==='details').every(n=>!n.open));
  assert.match(root.textContent,/Song <one>/);assert.match(root.textContent,/release-a/);
  assert.equal(nodes.find(n=>n.tagName==='img').src,'/cover.webp');
});
test('Gekisou stage reward and section total share remain separate readings',()=>{
  const root=document.createElement('div');
  renderRankingDetail(root,{...row,sections:[{index:1,missionType:2,rankingPercent:150,rankingBonus:250,share:0.4}],sampleCount:240,standardError:5},{mode:'gekisou',server:'jp'});
  assert.match(root.textContent,/LUCK/);assert.match(root.textContent,/名次奖励 250 分 · 本段总分占全曲 40%/);
  assert.match(root.textContent,/240.*标准误 5/);
  assert.ok(walk(root).filter(n=>n.tagName==='a').every(n=>!n.href.includes('server=jp')));
});
