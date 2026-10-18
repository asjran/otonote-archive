import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {validateScreenshot} from '../src/lib/card-recognition/observations.mjs';
const context=vm.createContext({});
vm.runInContext(readFileSync(new URL('../src/lib/card-recognition/layout.js',import.meta.url),'utf8'),context);
const {fromEdges,sizes}=context.CardLayout;

function fixture(kind,cols,{scale=1,x=51,y=73,rows=2,partial=false,missing=false}={}){
  const width=1280,height=905,vertical=new Uint8Array(width*height),horizontal=new Uint8Array(width*height),expected=[];
  const w=Math.round(sizes[kind].w*scale),h=Math.round(sizes[kind].h*scale),pad=Math.round(2*scale);
  const gap=Math.round(w*.14),dy=h+Math.round(h*.13);
  function pixel(map,x,y){if(x>=0&&x<width&&y>=0&&y<height)map[y*width+x]=255;}
  for(let row=0;row<rows+(partial?1:0);row++)for(let col=0;col<cols;col++){
    if(missing&&row===1&&col===cols-1)continue;
    const left=x+col*(w+gap),top=row===rows?height-Math.round(h*.5):y+row*dy;
    if(top+h<height)expected.push({x:left,y:top,w,h});
    for(let yy=top+pad;yy<=top+h-pad;yy++)for(let dx=-2;dx<=2;dx++){
      pixel(vertical,left+pad+dx,yy);pixel(vertical,left+w-pad+dx,yy);
    }
    for(let xx=left+pad;xx<=left+w-pad;xx++)for(let dy=-2;dy<=2;dy++){
      pixel(horizontal,xx,top+pad+dy);pixel(horizontal,xx,top+h-pad+dy);
    }
  }
  return {width,height,vertical,horizontal,expected};
}
for(const kind of ['member','support'])for(const cols of [2,3,4,5,6,7,8,9]){
  test(`${kind}: infer ${cols} columns with scaled cards and shifted margins`,()=>{
    const f=fixture(kind,cols,{scale:Math.min(1.2,1050/(cols*sizes[kind].w*1.14)),partial:true,missing:true});
    const boxes=fromEdges(f.width,f.height,f.vertical,f.horizontal,kind);
    assert.equal(boxes.length,f.expected.length);
    boxes.forEach((box,i)=>{
      for(const key of ['x','y','w','h'])assert.ok(Math.abs(box[key]-f.expected[i][key])<=3,`${i}.${key}: ${box[key]} vs ${f.expected[i][key]}`);
    });
  });
}
test('blank image and isolated border do not invent a grid',()=>{
  const empty=new Uint8Array(1280*905);
  assert.equal(fromEdges(1280,905,empty,empty,'member').length,0);
  const f=fixture('member',1);assert.equal(fromEdges(f.width,f.height,f.vertical,f.horizontal,'member').length,0);
});
test('landscape validation allows wider phones but rejects invalid and oversized images',()=>{
  for(const dimensions of [[1280,905],[2400,1080],[3000,1000]])assert.doesNotThrow(()=>validateScreenshot(...dimensions));
  for(const dimensions of [[0,905],[NaN,905],[900,1280],[10000,3000]])assert.throws(()=>validateScreenshot(...dimensions));
});
test('release packaging includes the classic worker geometry dependency',()=>{
  const build=readFileSync(new URL('../../tools/build_web_client.mjs',import.meta.url),'utf8');
  assert.match(build,/\['worker.js','shortlist.js','layout.js'\]/);
  const worker=readFileSync(new URL('../src/lib/card-recognition/worker.js',import.meta.url),'utf8');
  assert.match(worker,/importScripts\('opencv.js','shortlist.js','layout.js'\)/);
});

// Exercise row registration with pixels, including the baseline drift that
// otherwise breaks numeric ROIs and badge sampling despite finding every card.
class PixelCanvas {
  constructor(width,height){this.width=width;this.height=height;this.data=new Uint8ClampedArray(width*height*4);}
  getContext(){return {
    drawImage:(source,sx,sy,sw,sh,dx,dy,dw,dh)=>{
      for(let y=0;y<dh;y++)for(let x=0;x<dw;x++){
        const from=(Math.floor(sy+y*sh/dh)*source.width+Math.floor(sx+x*sw/dw))*4,to=((dy+y)*this.width+dx+x)*4;
        this.data.set(source.data.subarray(from,from+4),to);
      }
    },
    getImageData:(sx,sy,w,h)=>{
      const data=new Uint8ClampedArray(w*h*4);
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){
        const from=((sy+y)*this.width+sx+x)*4;data.set(this.data.subarray(from,from+4),(y*w+x)*4);
      }
      return {data};
    },
  };}
}
context.OffscreenCanvas=PixelCanvas;
for(const mode of ['member-level','member-training','support'])for(const drift of [-4,2,5]){
  test(`${mode}: register a row displaced by ${drift} pixels before reading growth`,()=>{
    const kind=mode==='support'?'support':'member',size=sizes[kind],canvas=new PixelCanvas(900,400),boxes=[];
    const glyphX=mode==='member-training'?39:34,glyphY=size.h-(mode==='support'?25:mode==='member-training'?18:20);
    for(let col=0;col<3;col++){
      const x=30+col*250,y=50;boxes.push({x,y:y+drift,w:size.w,h:size.h,row:0,col});
      for(let yy=y+glyphY;yy<y+glyphY+16;yy++)for(let xx=x+glyphX;xx<x+glyphX+8;xx++){
        canvas.data.fill(255,(yy*canvas.width+xx)*4,(yy*canvas.width+xx)*4+4);
      }
    }
    for(const explicit of [undefined,mode]){
      const result=context.CardLayout.align(canvas,structuredClone(boxes),kind,explicit);
      assert.ok(result.every(box=>box.y===50&&box.growthAligned));
    }
  });
}
test('no number anchors cannot authorize growth readings',()=>{
  const boxes=[0,1,2].map(col=>({x:20+col*180,y:60,w:148,h:194,row:0,col}));
  const result=context.CardLayout.align(new PixelCanvas(800,400),boxes,'member','member-level');
  assert.ok(result.every(box=>!box.growthAligned&&box.y===60));
});
