"""Render kinetic opening JSON: hit-indexed shots, giant words, paper and scan
reveals. Input beatmap hits provide cut times; output silent H.264 and review sheet.
"""
import argparse
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from common import (Reader, Writer, load_json, resolve, paper, RED, text,
                    video_args, contact_sheet, save_json, protect_inputs, video_options)
from render import source_spec
import styles


def build(config,out,w=360,h=640,fps=25):
    config=Path(config); cfg=load_json(config); base=config.parent
    protect_inputs(out,[config,*[resolve(base,s['path']) for s in cfg.get('sources',{}).values()]])
    beatmap=load_json(resolve(base,cfg['beatmap']))
    duration=float(cfg['duration']); total=round(duration*fps)
    hits=beatmap.get('hits',[])
    times=[float(v['time'] if isinstance(v,dict) else v) for v in hits]
    slots=[]
    for slot in cfg['slots']:
        at=times[slot['hit']] if 'hit' in slot else float(slot.get('at',0))
        slots.append((round(at*fps),slot))
    slots.sort(key=lambda v:v[0])
    if not slots or slots[0][0]!=0 or any(b[0]<=a[0] for a,b in zip(slots,slots[1:])) or slots[-1][0]>=total:
        raise ValueError('Opening slots start at 0 and increase within duration; check hit indices')
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    audit=[]
    with Writer(out,w,h,fps) as writer:
        for idx,(a,s) in enumerate(slots):
            b=slots[idx+1][0] if idx+1<len(slots) else total
            with ExitStack() as stack:
                reader=None
                if s.get('source'):
                    path,start,x=source_spec(cfg,base,s['source'],float(s.get('offset',0)))
                    reader=stack.enter_context(Reader(path,start,b-a,w,h,fps,x))
                audit.append(dict(start_frame=a,end_frame=b,hit=s.get('hit'),source=s.get('source'),style=s.get('style','raw')))
                for k in range(b-a):
                    if reader:
                        raw=reader.read()
                        frame=styles.apply(raw,s.get('style','raw'),seed=a+k,phase=(a+k)/fps*2)
                        if s.get('scan'):
                            x=round(w*min(1,(k+1)/max(1,(b-a)*.7)))
                            frame[:,x:]=raw[:,x:]; frame[:,max(0,x-1):x+1]=s.get('accent_color',RED)
                    elif s.get('background') in ('red','accent'):
                        frame=np.full((h,w,3),s.get('accent_color',RED),np.uint8)
                    elif s.get('background')=='black':
                        frame=np.zeros((h,w,3),np.uint8)
                    else:
                        frame=paper(w,h,0 if s.get('static') else a+k)
                    if s.get('text'):
                        progress=1 if s.get('static') else min(1,(k+1)/max(1,int(fps*.2)))
                        xy=(w/2,h*(.5 if s.get('big',True) else .78)+h*.015*(1-progress))
                        frame=text(frame,s['text'],xy,int(w*s.get('size',.42)),tuple(s.get('color',[17,17,17])))
                    if s.get('slices'):
                        # Graphic strips move; the live source remains unwarped underneath.
                        page=text(paper(w,h,a+k),s.get('question','who am i?'),size=int(w*.16))
                        p=(k/max(1,b-a-1))**2
                        for band in range(6):
                            y0,y1=round(band*h/6),round((band+1)*h/6)
                            dx=round((1 if band%2==0 else -1)*p*w)
                            if 0<=dx<w:
                                frame[y0:y1,dx:]=page[y0:y1,:w-dx]
                            elif -w<dx<0:
                                frame[y0:y1,:w+dx]=page[y0:y1,-dx:]
                    writer.write(frame)
    save_json(out.with_suffix('.cuts.json'),audit)
    contact_sheet(out,out.with_suffix('.sheet.png'),fps=fps)
    return total


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('config',type=Path)
    p.add_argument('--out',type=Path,required=True)
    video_args(p); a=p.parse_args()
    cfg=load_json(a.config)
    print('frames',build(a.config,a.out,*video_options(cfg,a)))
