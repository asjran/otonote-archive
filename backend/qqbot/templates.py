"""Five distinct image compositions built from shared, measured drawing primitives."""
from __future__ import annotations
import io
import math
import re
from PIL import Image, ImageDraw, ImageOps
from .query import clean
from .theme import INK, MUTED, PAPER, PINK, NAVY, mix, stage, spotlight, floating_panel, masthead, heading

WIDTH, BODY, PAD = 900, 828, 36
LINE = '#DAE4ED'
DIFFICULTY = {'easy':'#41A88E','normal':'#388FCE','hard':'#DC9634','expert':'#C95786'}


class Templates:
    def __init__(self, renderer, reply):
        self.r, self.reply, self.v = renderer, reply, reply.visual
        self.accent = reply.accent if re.fullmatch(r'#[0-9a-fA-F]{6}',reply.accent) else '#3388BB'
        self.label_color = mix(self.accent, NAVY, .36)

    def block(self, height, color='white'):
        return Image.new('RGB',(BODY,int(height)),color)

    def text(self, image, xy, value, size=26, color=INK):
        self.r.text(ImageDraw.Draw(image),xy,clean(value),size,color)

    def lines(self, value, width, size=26):
        return self.r.wrap(clean(value),width,size)

    def paragraph(self, image, x, y, value, width, size=26, color=INK):
        for line in self.lines(value,width,size):
            self.text(image,(x,y),line,size,color);y+=size+12
        return y

    def art(self, canvas, path, box, *, background=None):
        x,y,w,h=map(int,box)
        draw=ImageDraw.Draw(canvas)
        if background:spotlight(canvas,(x,y,w,h),self.accent)
        if path and path.is_file():
            try:
                with Image.open(path) as source:
                    art=source.convert('RGBA')
                    bounds=art.getbbox()
                    if bounds:art=art.crop(bounds)
                    picture=ImageOps.contain(art,(w,h),Image.Resampling.LANCZOS)
                canvas.paste(picture,(x+(w-picture.width)//2,y+(h-picture.height)//2),picture)
                return
            except (OSError,ValueError,Image.DecompressionBombError):pass
        self.text(canvas,(x+max(8,(w-130)//2),y+h//2-15),'暂无图片',20,MUTED)

    def logo(self, image, band, x, y, w=220, h=65):
        if band.get('image'):self.art(image,band['image'],(x,y,w,h))
        else:self.paragraph(image,x,y,band.get('name') or 'Our Notes',w,24,self.accent)

    def badges(self,image,x,y):
        for index,key in enumerate(('attribute','rarity')):
            badge=self.v.get(key,{})
            if badge.get('image'):
                self.art(image,badge['image'],(x+index*182,y,68 if key=='attribute' else 108,68))
            else:self.text(image,(x+index*182,y+15),badge.get('label','未收录'),24,MUTED)
            if key=='attribute' and badge.get('image'):
                self.text(image,(x+76,y+22),badge.get('label',''),22,MUTED)

    def title_block(self, eyebrow=None):
        lines=self.lines(self.reply.title,BODY-48,38)
        image=self.block(48+len(lines)*50+(32 if eyebrow else 0),NAVY)
        draw=ImageDraw.Draw(image)
        draw.polygon([(BODY-120,0),(BODY,0),(BODY,120)],fill=mix(self.accent,NAVY,.55))
        draw.rectangle((24,image.height-9,110,image.height-6),fill=PINK)
        y=20
        if eyebrow:self.text(image,(24,y),eyebrow,20,mix(self.accent,'#FFFFFF',.65));y+=32
        for line in lines:self.text(image,(24,y),line,38,'white');y+=50
        return image

    def stats(self):
        image=self.block(118);draw=ImageDraw.Draw(image)
        for i,(label,value) in enumerate(self.v.get('stats',[])):
            x=24+i*272
            color=(PINK,'#409DD4','#9271CA')[i%3]
            draw.rounded_rectangle((x-8,12,x+242,106),radius=10,fill=mix(color,'#FFFFFF',.94))
            draw.rounded_rectangle((x+2,24,x+7,43),radius=2,fill=color)
            self.text(image,(x+18,19),label,22,MUTED)
            self.text(image,(x+2,51),str(value) if value is not None else '—',44,INK)
            draw.line((x+152,91,x+226,91),fill=mix(color,'#FFFFFF',.6),width=3)
        return image

    def text_panels(self,title,text,icon=None,tag=''):
        lines=self.lines(text,BODY-48,26)
        title_lines=self.lines(title,BODY-132 if icon else BODY-48,28)
        heading_height=max(70,24+len(title_lines)*40)+(30 if tag else 0)
        result=[]
        for start in range(0,max(1,len(lines)),24):
            chunk=lines[start:start+24]
            image=self.block(heading_height+len(chunk)*38+34)
            heading(image,heading_height,self.accent)
            if icon:
                ImageDraw.Draw(image).rounded_rectangle((16,14,92,90),radius=13,fill='white',outline=mix(self.accent,'#FFFFFF',.7),width=2)
                self.art(image,icon,(22,20,64,64))
            x=104 if icon else 24;y=16
            if tag:self.text(image,(x,y),tag+(' · 续' if start else ''),20,self.label_color);y+=30
            for line in title_lines:self.text(image,(x,y),line,28);y+=40
            y=heading_height+10
            for line in chunk:self.text(image,(24,y),line,26);y+=38
            result.append(image)
        return result

    def skills(self):
        blocks=[]
        for skill in self.v.get('skills',[]):
            text=clean(skill.get('summary')) or '技能资料暂未收录。'
            if skill.get('interpretationStatus')!='identified':text+='\n部分条件待核验，请以游戏内描述为准。'
            blocks+=self.text_panels(skill.get('name','技能'),text,skill.get('image'),f"{skill['category']}  /  Lv.{skill.get('level','?')}")
        return blocks or self.text_panels('技能','技能资料暂未收录。')

    def member(self):
        image=self.block(518);draw=ImageDraw.Draw(image)
        spotlight(image,(16,16,350,486),self.accent)
        self.art(image,self.reply.image,(24,24,334,470))
        self.logo(image,self.v.get('band',{}),394,24,384,74)
        draw.line((394,109,794,109),fill=LINE,width=2)
        names=' / '.join(c['name'] for c in self.v.get('characters',[]))
        y=self.paragraph(image,394,120,names or self.reply.title,400,44)
        title=self.reply.title
        for sep in ('｜','|'):
            if sep in title:title=title.split(sep,1)[1].strip();break
        y=self.paragraph(image,394,y+12,title,400,28)
        self.badges(image,394,max(y+20,285))
        growth=self.v.get('growth',{})
        draw.rounded_rectangle((390,415,802,496),radius=12,fill=mix(self.accent,'#FFFFFF',.93))
        self.text(image,(406,423),'满级资料值',20,MUTED)
        self.text(image,(406,456),f"Lv.{growth.get('maxLevel','—')}  ·  ID {self.v['id']}",24,self.label_color)
        # Long names retain full content in a separate title block.
        if y>270:
            image=self.block(518);self.art(image,self.reply.image,(20,18,350,480),background=PAPER)
            self.logo(image,self.v.get('band',{}),400,40,380,90);self.badges(image,400,190)
            self.text(image,(400,350),'满级资料值',24,MUTED);self.text(image,(400,397),f"ID {self.v['id']}",26,MUTED)
            return [self.title_block(),image,self.stats(),*self.skills()]
        return [image,self.stats(),*self.skills()]

    def support(self):
        image=self.block(455,NAVY)
        self.art(image,self.reply.image,(14,12,800,430),background=PAPER)
        identity=self.block(108)
        self.badges(identity,24,18)
        names=' / '.join(c['name'] for c in self.v.get('characters',[]))
        self.paragraph(identity,400,20,names,398,26)
        return [self.title_block('SNAP / 留影档案'),image,identity,self.stats(),*self.skills()]

    def song(self):
        v=self.v
        vocal='演唱  '+(v.get('vocal') or '未收录')
        vocal_h=len(self.lines(vocal,444,26))*38
        hero=self.block(max(335,244+vocal_h))
        draw=ImageDraw.Draw(hero)
        draw.ellipse((30,20,340,330),fill=NAVY)
        for inset in (12,20,29,39):
            draw.ellipse((30+inset,20+inset,340-inset,330-inset),outline='#435572',width=1)
        self.art(hero,self.reply.image,(16,18,283,283),background=PAPER)
        bands=v.get('bands',[])
        if bands:self.logo(hero,bands[0],350,24,435,88)
        self.paragraph(hero,350,140,vocal,444,26)
        bpm=v.get('bpm',{});a,b=bpm.get('min'),bpm.get('max');label=str(a) if a==b and a is not None else f'{a or "—"}–{b or "—"}'
        self.text(hero,(350,189+vocal_h),'BPM',22,MUTED);self.text(hero,(425,173+vocal_h),label,44,self.accent)
        self.text(hero,(350,244+vocal_h),v.get('type') or '歌曲资料',22,MUTED)
        charts=v.get('charts',[])
        table=self.block(94+len(charts)*104);draw=ImageDraw.Draw(table)
        heading(table,65,self.accent)
        self.text(table,(24,22),'谱面难度',28);self.text(table,(443,24),'等级',22,MUTED);self.text(table,(622,24),'物量',22,MUTED)
        y=82
        for chart in charts:
            name=chart.get('difficulty','?').lower();color=DIFFICULTY.get(name,self.accent)
            draw.rounded_rectangle((20,y,802,y+86),radius=14,fill=mix(color,'#FFFFFF',.92))
            draw.polygon([(20,y),(291,y),(260,y+86),(20,y+86)],fill=color)
            self.text(table,(40,y+21),name.upper(),28,'white')
            self.text(table,(443,y+17),str(chart.get('displayLevel',chart.get('level','—'))),38)
            value=chart.get('fullComboCount');self.text(table,(622,y+12),str(value) if value is not None else '—',32)
            if chart.get('fullComboStatus')=='conflict':self.text(table,(566,y+54),f"Master {chart.get('masterFullComboCount','—')} · 待核验",18,MUTED)
            y+=104
        credits='\n'.join(label+'  '+value for label,value in v.get('credits',[]))
        return [self.title_block('TRACK / 歌曲档案'),hero,table,*self.text_panels('制作信息',credits)]

    def tiles(self, items, *, command='查角色卡', label=''):
        blocks=[]
        if label:blocks+=self.text_panels(label,'')
        for start in range(0,len(items),3):
            group=items[start:start+3]
            title_height=max((len(self.lines(x['title'],236,22))*32 for x in group),default=32)
            image=self.block(332+title_height);draw=ImageDraw.Draw(image)
            for i,item in enumerate(group):
                x=18+i*270
                spotlight(image,(x,12,250,242),self.accent)
                self.art(image,item.get('image'),(x+5,17,240,232))
                rarity=item.get('rarity') or {};attr=item.get('attribute') or {}
                if rarity.get('image'):self.art(image,rarity['image'],(x+150,211,94,39))
                if attr.get('image'):self.art(image,attr['image'],(x+6,211,40,40))
                self.paragraph(image,x+6,268,item['title'],236,22)
                draw.rounded_rectangle((x+4,280+title_height,x+244,316+title_height),radius=8,fill=mix(self.accent,'#FFFFFF',.92))
                self.text(image,(x+12,284+title_height),f"{command} {item['id']}",20,self.label_color)
            blocks.append(image)
        return blocks

    def gacha(self):
        hero=self.block(314,NAVY);self.art(hero,self.reply.image,(12,12,804,290),background=PAPER)
        times=self.block(176)
        heading(times,55,self.accent)
        self.text(times,(24,13),'招募时间',28,INK)
        for index,key in enumerate(('start','end')):
            self.text(times,(24,63+index*45),'开始' if key=='start' else '结束',22,MUTED)
            self.text(times,(112,60+index*45),self.v[key],28)
        blocks=[self.title_block('GACHA / 招募档案'),hero,times]
        cards=self.v.get('pickups',[])
        blocks+=self.tiles(cards,label=f'PICK UP  /  {len(cards)} 张角色卡') if cards else self.text_panels('PICK UP','本快照没有标记 UP 角色卡。')
        if self.v.get('missingPickups'):blocks+=self.text_panels('资料提示',f"{self.v['missingPickups']} 张 UP 卡资料暂缺。")
        blocks+=self.text_panels('时间说明','配置时间，时区未核验；不代表实时开放状态。')
        return blocks

    def character(self):
        v=self.v;p=v.get('profile',{});birth=v.get('birthday',{})
        hero=self.block(620)
        self.art(hero,self.reply.image,(16,18,344,575),background=PAPER)
        self.logo(hero,v.get('band',{}),385,24,418,90)
        self.paragraph(hero,385,140,self.reply.title,417,44)
        y=223
        fields=[('担当',v.get('role','未收录')),('生日',f"{birth.get('month','?')}月{birth.get('day','?')}日")]
        fields += [(label,p[k]) for label,k in [('CV','voiceActor'),('身高','height'),('星座','constellation'),('学校','school'),('班级','schoolClass')] if p.get(k)]
        overflow=[]
        for label,value in fields:
            value=value.removeprefix('CV. ') if label=='CV' else value
            lines=self.lines(value,302,24);h=max(44,len(lines)*34+8)
            if y+h>593:overflow.append((label,value));continue
            self.text(hero,(385,y),label,20,MUTED);self.paragraph(hero,482,y-2,value,302,24);y+=h
        blocks=[hero]
        if p.get('catchphrase'):blocks+=self.text_panels('她的声音',p['catchphrase'])
        if p.get('description'):blocks+=self.text_panels('人物简介',p['description'])
        profile=overflow+[(label,p[k]) for label,k in [('喜欢','favoriteFood'),('兴趣','hobby'),('血型','bloodType')] if p.get(k)]
        if profile:blocks+=self.text_panels('个人档案','\n'.join(label+'  '+value for label,value in profile))
        a,b=v.get('counts',(0,0));blocks+=self.text_panels('关联资料',f"角色卡 {a} 张  ·  留影 {b} 张\n查角色卡 {self.reply.title}\n查留影 {self.reply.title}")
        if v.get('related'):blocks+=self.tiles(v['related'])
        return blocks

    def listing(self):
        blocks=[self.title_block(self.reply.subtitle)]
        blocks+=self.tiles(self.v['items'],command=self.v['command'])
        if self.v.get('next'):blocks+=self.text_panels('下一页',self.v['next'])
        return blocks

    def render(self):
        functions={'memberCards':self.member,'supportCards':self.support,'musicTracks':self.song,'gachaPools':self.gacha,'characters':self.character,'list':self.listing}
        blocks=functions[self.reply.layout]()
        if self.reply.notice:blocks+=self.text_panels('资料说明',self.reply.notice)
        pages=[];page=[];height=220
        for block in blocks:
            if block.height>2250:raise ValueError('template block exceeds page budget')
            if height+block.height+16>2500:
                pages.append(page);page=[];height=220
            page.append(block);height+=block.height+16
        if page:pages.append(page)
        if len(pages)>4:raise ValueError('template exceeds page budget')
        output=[]
        for index,page in enumerate(pages):
            height=max(620,220+sum(b.height+16 for b in page))
            image=stage((WIDTH,height),self.accent);draw=ImageDraw.Draw(image)
            masthead(image,self.accent)
            self.text(image,(PAD,20),'OUR NOTES',32,'white')
            self.text(image,(PAD,66),self.reply.kind+'  /  国际服',20,'#CFDDF0')
            identity=str(self.v.get('id',''));self.text(image,(690,40),('ID '+identity) if identity else '资料查询',20,'white')
            y=136
            for block in page:
                floating_panel(image,block,(PAD,y));y+=block.height+16
            draw.line((PAD,height-72,WIDTH-PAD,height-72),fill=LINE,width=2)
            self.text(image,(PAD,height-55),f'资料快照 {self.r.snapshot} · 游戏内信息为准',18,MUTED)
            self.text(image,(760,height-55),f'{index+1} / {len(pages)}',18,MUTED)
            buffer=io.BytesIO();image.save(buffer,format='PNG',optimize=True);output.append(buffer.getvalue())
        return output
