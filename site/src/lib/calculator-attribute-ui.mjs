export function attributeBadge(code,attributes=[]) {
  const attribute=attributes.find(a=>a.code===code),node=document.createElement('span');node.className='calculator-attribute';
  if(attribute?.color)node.style.setProperty('--attribute-color',attribute.color);
  if(attribute?.iconUrl){const img=document.createElement('img');img.src=attribute.iconUrl;img.alt='';img.width=16;img.height=16;node.append(img);}
  node.title=attribute?.name??`属性 ${code??'未知'}`;node.setAttribute('aria-label',node.title);
  if(!attribute?.iconUrl)node.textContent='●';return node;
}
