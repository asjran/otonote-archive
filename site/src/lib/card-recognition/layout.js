/* Shared by the classic recognition worker and deterministic geometry tests. */
(function(scope){
  const sizes={member:{w:148,h:194},support:{w:216,h:121}};
  const median=values=>{const a=[...values].sort((x,y)=>x-y);return a[Math.floor(a.length/2)];};

  // Infer repeated card borders, not a device's column count or screen margins.
  function fromEdges(width,height,vertical,horizontal,kind){
    const size=sizes[kind];
    if(!size)throw Error('请选择截图类型');
    const sums=new Float64Array(width),prefix=new Uint32Array(width*(height+1));
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      const value=vertical[y*width+x]?1:0;
      sums[x]+=value;prefix[(y+1)*width+x]=prefix[y*width+x]+value;
    }
    const threshold=Math.max(25,Math.max(...sums)*.15),xs=[];
    for(let x=0;x<width;x++)if(sums[x]>threshold){
      const start=x;while(x+1<width&&sums[x+1]>threshold)x++;
      xs.push(Math.round((start+x)/2));
    }
    // A noisy/non-list image must not generate unbounded geometry work.
    if(xs.length>160)return [];
    const pairs=[];
    for(const x of xs)for(const r of xs)if(r-x>=50&&r-x<=width*.4)pairs.push({x,r,weight:Math.min(sums[x],sums[r])});
    let best={score:0,columns:[]};
    const tried=new Set();
    for(const seed of pairs){
      const w=seed.r-seed.x,bucket=Math.round(w/3);if(tried.has(bucket))continue;tried.add(bucket);
      const group=pairs.filter(p=>Math.abs(p.r-p.x-w)<=Math.max(3,w*.025));
      const paths=[];
      for(const p of group){
        let previous={score:0,columns:[]};
        for(const path of paths){
          const gap=p.x-path.columns.at(-1).r;
          if(gap>w*.05&&gap<w*.35&&path.score>previous.score)previous=path;
        }
        const path={score:previous.score+p.weight,columns:[...previous.columns,p]};paths.push(path);
        if(path.columns.length>=2&&path.score>best.score)best=path;
      }
    }
    const columns=best.columns;if(columns.length<2)return [];
    const innerWidth=median(columns.map(p=>p.r-p.x));
    const pad=innerWidth*2/(size.w-4),w=Math.round(innerWidth+2*pad),h=Math.round(w*size.h/size.w);
    const innerHeight=h-Math.round(2*pad),inset=Math.round(innerWidth*.15),skip=Math.round(innerHeight*.18);
    if(innerHeight<=skip+3||h>=height)return [];
    const side=(x,y)=>(prefix[(y+innerHeight-3)*width+x]-prefix[(y+skip)*width+x])/(innerHeight-skip-3);
    const line=(p,y)=>{
      let total=0;for(let x=p.x+inset;x<p.r-inset;x++)total+=horizontal[y*width+x]?1:0;
      return total/(p.r-p.x-2*inset);
    };
    const profile=Array.from({length:height},(_,y)=>columns.reduce((sum,p)=>sum+line(p,y),0)/columns.length);
    const candidates=[];
    for(let y=Math.ceil(pad);y+innerHeight+pad<height-2;y++){
      const sides=columns.reduce((sum,p)=>sum+Math.min(side(p.x,y),side(p.r,y)),0)/columns.length;
      const bottom=profile[y+innerHeight],top=profile[y];
      if(bottom>.3&&top>.08&&sides>.35)candidates.push({y,score:bottom+.5*top+.3*sides});
    }
    const rows=[];
    for(const candidate of candidates.sort((a,b)=>b.score-a.score||a.y-b.y)){
      if(rows.every(row=>Math.abs(row.y-candidate.y)>innerHeight*.85))rows.push(candidate);
    }
    rows.sort((a,b)=>a.y-b.y);
    const result=[];
    for(const [row,{y}] of rows.entries())for(const [col,p] of columns.entries()){
      // Do not fill empty cells or infer a partial card from its neighbours.
      if(Math.max(side(p.x,y),side(p.r,y))<.3||line(p,y+innerHeight)<.15)continue;
      const x=Math.round(p.x-pad),top=Math.round(y-pad);
      if(x<1||top<1||x+w>=width-1||top+h>=height-1)continue;
      result.push({x,y:top,w,h,row,col});
    }
    return result;
  }

  // Anchor each row to its visible number baseline. The image border itself
  // has several strokes/shadows; choosing the wrong stroke moves badge samples.
  function align(canvas,boxes,kind,mode){
    const size=sizes[kind],measurements=[];
    for(const box of boxes){
      const crop=new OffscreenCanvas(size.w,size.h),ctx=crop.getContext('2d',{willReadFrequently:true});
      ctx.drawImage(canvas,box.x,box.y,box.w,box.h,0,0,size.w,size.h);
      const {data}=ctx.getImageData(25,size.h-38,52,38),mask=new Uint8Array(52*38),seen=new Uint8Array(mask.length),glyphs=[];
      for(let i=0;i<mask.length;i++){
        const lo=Math.min(data[i*4],data[i*4+1],data[i*4+2]),hi=Math.max(data[i*4],data[i*4+1],data[i*4+2]);
        mask[i]=lo>185&&hi-lo<65?1:0;
      }
      for(let start=0;start<mask.length;start++){
        if(!mask[start]||seen[start])continue;
        const pending=[start];seen[start]=1;let x0=52,x1=0,y0=38,y1=0,count=0;
        while(pending.length){
          const i=pending.pop(),x=i%52,y=Math.floor(i/52);count++;
          x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);
          for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
            const xx=x+dx,yy=y+dy,j=yy*52+xx;
            if(xx>=0&&xx<52&&yy>=0&&yy<38&&!seen[j]&&mask[j]){seen[j]=1;pending.push(j);}
          }
        }
        if(y1-y0>=11&&y1-y0<=19&&x1-x0>=1&&x1-x0<=12&&count>=20)glyphs.push({x:x0+25,y:y0+size.h-38});
      }
      for(const glyph of glyphs){
        const inferred=kind==='support'?'support':glyph.x>=30&&glyph.x<=36?'member-level':glyph.x>=37&&glyph.x<=42?'member-training':null;
        if(!inferred||(mode&&inferred!==mode))continue;
        const expected=size.h-(inferred==='support'?25:inferred==='member-training'?18:20),delta=glyph.y-expected;
        if(Math.abs(delta)<=8)measurements.push({row:box.row,col:box.col,mode:inferred,delta});
      }
    }
    for(const row of new Set(boxes.map(box=>box.row))){
      const cells=boxes.filter(box=>box.row===row),votes=measurements.filter(v=>v.row===row);
      const options=mode?[mode]:kind==='support'?['support']:['member-level','member-training'];
      const groups=options.map(candidate=>votes.filter(v=>v.mode===candidate));
      groups.sort((a,b)=>b.length-a.length);
      const group=groups[0];
      if(!group?.length||groups[1]?.length===group.length)continue;
      const delta=median(group.map(v=>v.delta)),consistent=group.filter(v=>Math.abs(v.delta-delta)<=1.5);
      if(new Set(consistent.map(v=>v.col)).size<Math.max(2,Math.ceil(cells.length/2)))continue;
      for(const box of cells){
        const y=Math.round(box.y+delta*box.h/size.h);
        if(y<1||y+box.h>=canvas.height-1)continue;
        box.y=y;box.growthAligned=true;
      }
    }
    return boxes;
  }

  function detect(canvas,cv,kind){
    const {width,height}=canvas;
    const rgba=cv.matFromImageData(canvas.getContext('2d',{willReadFrequently:true}).getImageData(0,0,width,height));
    const gray=new cv.Mat(),edges=new cv.Mat(),vertical=new cv.Mat(),horizontal=new cv.Mat();
    const axis=cv.Mat.ones(15,1,cv.CV_8U),across=cv.Mat.ones(1,5,cv.CV_8U),down=cv.Mat.ones(5,1,cv.CV_8U);
    try{
      cv.cvtColor(rgba,gray,cv.COLOR_RGBA2GRAY);cv.Canny(gray,edges,50,150);
      cv.morphologyEx(edges,vertical,cv.MORPH_OPEN,axis);cv.dilate(vertical,vertical,across);
      cv.dilate(edges,horizontal,down);
      return fromEdges(width,height,vertical.data,horizontal.data,kind);
    }finally{for(const mat of [rgba,gray,edges,vertical,horizontal,axis,across,down])mat.delete();}
  }
  scope.CardLayout={sizes,fromEdges,detect,align};
})(globalThis);
