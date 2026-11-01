"""Split one or more local videos into 1.6-second candidates and an offline
click-to-select HTML gallery. Optional group JSON or face filtering; exports IDs
and a config-relative source map. No network service or upload is involved.
"""
import argparse
import html
import json
from pathlib import Path
import re
import os

import cv2
from common import Reader, Writer, duration, load_json, save_json

PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Nobody 选片与角色</title>
<style>body{margin:0;background:#eeebe4;color:#111;font:16px system-ui}header{position:sticky;top:0;background:#111;color:white;padding:16px;z-index:2}button{padding:10px;background:#ff3b1f;color:white;border:0;cursor:pointer}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;padding:20px}article{border:4px solid transparent;background:white}article.on{border-color:#ff3b1f}video{display:block;width:100%}label{display:block;padding:6px}textarea{width:100%;height:90px}select{padding:6px}</style>
<header><b>Nobody · 选中镜头并标角色</b> <span id="count">0</span>
<button id="copy">复制我的选择（JSON）</button><button id="clear">清空</button>
<p>将 JSON 保存为 picks.json；来源使用完整本地路径，可保存到任意私有工作目录。可用秒数只填写已检查的连续范围。</p>
<textarea id="selection" aria-label="选片 JSON" readonly></textarea></header><main>__CARDS__</main>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.querySelector('#data').textContent);
const cards=[...document.querySelectorAll('article')], key='nobody-role-picks:'+location.pathname;
let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}
function output(){return cards.filter(c=>c.querySelector('.pick').checked).map(c=>{
 const id=c.dataset.id,d=data[id];return {id,...d,role:c.querySelector('select').value,
 hero:c.querySelector('.hero').checked,star:c.querySelector('.hero').checked?1:0,
 freeze:c.querySelector('.freeze').checked,allow_zoom:c.querySelector('.zoom').checked,
 duration:Number(c.querySelector('.duration').value)};})}
function update(){const result=output();for(const c of cards)c.classList.toggle('on',c.querySelector('.pick').checked);
 document.querySelector('#count').textContent=result.length;
 document.querySelector('#selection').value=JSON.stringify(result,null,2);
 try{localStorage.setItem(key,JSON.stringify(Object.fromEntries(cards.map(c=>[c.dataset.id,{
 selected:c.querySelector('.pick').checked,role:c.querySelector('select').value,
 hero:c.querySelector('.hero').checked,freeze:c.querySelector('.freeze').checked,
 allow_zoom:c.querySelector('.zoom').checked,duration:Number(c.querySelector('.duration').value)}]))))}catch(e){}
}
for(const c of cards){const v=saved[c.dataset.id];if(v){
 c.querySelector('.pick').checked=!!v.selected;c.querySelector('select').value=v.role||'process';
 for(const name of ['hero','freeze'])c.querySelector('.'+name).checked=!!v[name];
 c.querySelector('.zoom').checked=!!v.allow_zoom;c.querySelector('.duration').value=v.duration||data[c.dataset.id].duration;}
 c.onchange=update;const video=c.querySelector('video');
 c.onmouseenter=()=>video.play().catch(()=>{});c.onmouseleave=()=>video.pause();}
document.querySelector('#copy').onclick=async()=>{const t=document.querySelector('#selection');t.select();
 try{await navigator.clipboard.writeText(t.value)}catch(e){document.execCommand('copy')}};
document.querySelector('#clear').onclick=()=>{for(const c of cards)c.querySelector('.pick').checked=false;update()};update();
</script></html>"""



def build(videos,out,groups=None,seconds=1.6,step=None,faces=False,start=0,end=None):
    if seconds<=0 or (step is not None and step<=0):
        raise ValueError('duration and step must be positive')
    out=Path(out); (out/'clips').mkdir(parents=True,exist_ok=True)
    step=step or seconds
    specs=load_json(groups) if groups else [dict(source=str(p.resolve()),prefix=f'V{i+1}',
            title=f'Video {i+1}',start=start,end=end) for i,p in enumerate(videos)]
    if faces and not hasattr(cv2,'CascadeClassifier'):
        raise RuntimeError('Face filtering needs OpenCV 4; install the pinned requirements in a virtual environment.')
    face=None
    if faces:
        # OpenCV's native filename API on Windows may reject non-ASCII paths.
        model=Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'
        storage=cv2.FileStorage(model.read_text(encoding='utf-8'),cv2.FILE_STORAGE_READ|cv2.FILE_STORAGE_MEMORY)
        face=cv2.CascadeClassifier()
        face.read(storage.getFirstTopLevelNode())
        storage.release()
        if face.empty():
            raise RuntimeError('Could not load the bundled OpenCV frontal-face detector')
    cards=[]; picks={}; exported={}
    for group in specs:
        source=(Path(groups).parent/group['source']).resolve() if groups else Path(group['source'])
        if out.resolve() in source.resolve().parents:
            raise ValueError('Keep input videos outside the generated gallery directory')
        prefix=group['prefix']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',prefix):
            raise ValueError('prefix must be a safe unique identifier')
        stop=min(float(group.get('end') or duration(source)),duration(source))
        t=float(group.get('start',0)); index=1
        while t+seconds<=stop+1e-6:
            skips=group.get('skip',[])
            if any(t<b and t+seconds>a for a,b in skips):
                t+=step; continue
            alias=f'{prefix}{index:03d}'; index+=1
            if alias in picks:
                raise ValueError('Duplicate candidate ID; use unique group prefixes')
            if face is not None:
                ok=True
                for offset in (0,seconds/2,seconds-.08):
                    with Reader(source,t+offset,1,180,320) as r:
                        gray=cv2.cvtColor(r.read(),cv2.COLOR_RGB2GRAY)
                    if not len(face.detectMultiScale(gray,1.1,4,minSize=(24,24))):
                        ok=False; break
                if not ok:
                    t+=step; continue
            clip=out/'clips'/f'{alias}.mp4'
            with Reader(source,t,round(seconds*25),180,320,25,group.get('x_offset',0)) as r, Writer(clip,180,320) as writer:
                for _ in range(round(seconds*25)):
                    writer.write(r.read())
            # Relative paths make IDs directly usable after copying sources into a config.
            try:
                source_path=os.path.relpath(source,out).replace(os.sep,'/')
            except ValueError:
                # Windows sources on another drive cannot have a relative path.
                source_path=source.as_posix()
            picks[alias]=dict(path=source_path,start=round(t,6),
                              x_offset=group.get('x_offset',0),candidate_duration=seconds)
            exported[alias]=dict(picks[alias],path=source.resolve().as_posix(),duration=seconds)
            label=html.escape(f"{alias} · {group.get('title',prefix)} · {t:.2f}s")
            roles=[('before','变化前'),('process','变化过程'),('after','变化后'),('enter','进场/走近'),('profile','侧脸'),('hero','英雄镜头'),('detail','细节'),('exit','离场/擦除')]
            options=''.join(f'<option value="{r}" {"selected" if r=="process" else ""}>{r} · {title}</option>' for r,title in roles)
            cards.append(f'<article data-id="{alias}"><video src="clips/{alias}.mp4" muted loop playsinline preload="metadata" controls></video><label><input type="checkbox" class="pick">选中 · {label}</label><label>角色 <select aria-label="镜头角色">{options}</select></label><label><input type="checkbox" class="hero">★ hero</label><label><input type="checkbox" class="freeze">允许定格</label><label><input type="checkbox" class="zoom">允许放大</label><label>可用秒数 <input class="duration" type="number" min="0.04" step="0.04" value="{seconds}" aria-label="已检查的可用秒数"></label></article>')
            t+=step
    if not picks:
        raise ValueError('No candidates; expand the time window or turn off --faces')
    (out/'index.html').write_text(PAGE.replace('__CARDS__','\n'.join(cards)).replace('__DATA__',json.dumps(exported,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    save_json(out/'picks.json',picks)
    print(f'{len(picks)} candidates -> {out / "index.html"}')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('videos',nargs='*',type=Path)
    p.add_argument('--groups',type=Path,help='JSON array: source/prefix/title/start/end/skip/x_offset')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--duration',type=float,default=1.6)
    p.add_argument('--step',type=float)
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--end',type=float)
    p.add_argument('--faces',action='store_true',help='Keep candidates with a frontal face at three sample times')
    a=p.parse_args()
    if not a.videos and not a.groups:
        p.error('Provide videos or --groups')
    build(a.videos,a.out,a.groups,a.duration,a.step,a.faces,a.start,a.end)
