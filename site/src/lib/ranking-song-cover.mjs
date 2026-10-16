export function rankingSongCover(document,url,size=44) {
  const cover=document.createElement('span');cover.className='ranking-cover';cover.setAttribute('aria-hidden','true');
  const note=document.createElement('span');note.textContent='♪';cover.append(note);
  if(url){const image=document.createElement('img');image.src=url;image.alt='';image.width=image.height=size;image.loading='lazy';image.decoding='async';image.addEventListener('error',()=>image.remove(),{once:true});cover.append(image);}
  return cover;
}
