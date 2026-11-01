"""Render a beat-based timeline JSON into silent H.264, an NDJSON source trace
and timestamped contact sheets. Each live segment streams forward in source time.
Config-relative paths, source aliases and schema are documented in docs/08-config.md.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from common import (Beats, Reader, Writer, PAPER, RED, font, load_json, resolve,
                    text, video_args, contact_sheet, protect_inputs, video_options)
import styles


class Tracker:
    """Local template tracking for graphics only; never warp the video frame."""
    def __init__(self, box):
        self.box = tuple(map(int, box))
        self.prev = None

    def update(self, rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h,w = gray.shape
        x,y,bw,bh = self.box
        bw,bh = max(2,min(bw,w)),max(2,min(bh,h))
        x,y = max(0,min(x,w-bw)),max(0,min(y,h-bh))
        if self.prev is not None:
            pad=max(8,round(w*.06))
            sx,sy=max(0,x-pad),max(0,y-pad)
            search=gray[sy:min(h,y+bh+pad),sx:min(w,x+bw+pad)]
            scores=cv2.matchTemplate(search,self.prev,cv2.TM_CCOEFF_NORMED)
            _,score,_,loc=cv2.minMaxLoc(scores)
            if score>.45:
                x,y=sx+loc[0],sy+loc[1]
        self.prev=gray[y:y+bh,x:x+bw].copy()
        self.box=(x,y,bw,bh)
        return self.box


def overlay_box(rgb, box, label='', magnifier=False, accent=RED):
    x,y,bw,bh=map(int,box); h,w=rgb.shape[:2]
    im=Image.fromarray(rgb); d=ImageDraw.Draw(im)
    d.rectangle((x,y,x+bw,y+bh),outline=tuple(accent),width=max(1,w//540))
    d.text((x,max(0,y-20)),label,font=font(max(9,w*.025),500),fill=tuple(accent))
    if magnifier:
        side=min(w//3,h//4)
        roi=rgb[max(0,y):min(h,y+bh),max(0,x):min(w,x+bw)]
        inset=Image.fromarray(roi).resize((side,side),Image.Resampling.LANCZOS)
        im.paste(inset,(w-side-10,h-side-10))
        d.rectangle((w-side-10,h-side-10,w-10,h-10),outline=tuple(accent),width=1)
    return np.array(im)


def get_beats(cfg, base):
    raw=Beats(load_json(resolve(base,cfg['beatmap'])) if cfg.get('beatmap') else None,cfg.get('bpm',120))
    origin=float(cfg.get('beat_origin',0))
    class LocalBeats:
        bpm=raw.bpm
        def sec(self, beat):
            return raw.sec(origin+beat)-raw.sec(origin)
    return LocalBeats()


def source_spec(cfg, base, alias, offset=0):
    s=cfg['sources'][alias]
    return resolve(base,s['path']),float(s.get('start',0))+offset,float(s.get('x_offset',0))


def compile_segments(cfg, beats, fps):
    segments=cfg['segments']
    previous=0
    result=[]
    for s in segments:
        a=int(s['start_frame']) if 'start_frame' in s else round(beats.sec(s['start_beat'])*fps)
        b=int(s['end_frame']) if 'end_frame' in s else round(beats.sec(s['end_beat'])*fps)
        if a!=previous or b<=a:
            raise ValueError('Segments must cover time from 0, without gaps/overlaps, at least one frame each')
        if s['type']=='freeze' and not s.get('authorized'):
            raise ValueError('freeze needs authorized=true from an explicit user request')
        result.append((a,b,s)); previous=b
    if not result:
        raise ValueError('Timeline is empty')
    return result


def render(config, out, w=360, h=640, fps=25, review=True):
    config=Path(config); cfg=load_json(config); base=config.parent
    protect_inputs(out,[config,*[resolve(base,s['path']) for s in cfg.get('sources',{}).values()]])
    beats=get_beats(cfg,base); rows=compile_segments(cfg,beats,fps)
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    with Writer(out,w,h,fps) as writer, out.with_suffix('.trace.ndjson').open('w',encoding='utf-8') as trace:
        for a,b,s in rows:
            kind=s['type']; n=b-a
            if kind not in ('clip','chop','hero','grid','freeze','black','text_word'):
                raise ValueError(f'Unknown segment type: {kind}')
            with ExitStack() as stack:
                readers={}; specs={}
                aliases=list(s['tiles']) if kind=='grid' else ([s['source']] if s.get('source') else [])
                if s.get('flip_to'):
                    aliases+=s['flip_to']
                for alias in dict.fromkeys(aliases):
                    path,start,x=source_spec(cfg,base,alias,float(s.get('offset',0)))
                    specs[alias]=(start,x)
                    readers[alias]=stack.enter_context(Reader(path,start,1 if kind=='freeze' else n,w,h,fps,x))
                if kind=='grid':
                    side=int(s.get('n',3))
                    if len(s['tiles'])!=side*side or (s.get('flip_to') and len(s['flip_to'])!=side*side):
                        raise ValueError('grid tile count must be n*n, including flip_to')
                frozen=readers[s['source']].read() if kind=='freeze' else None
                tracker=None
                cuts=[]
                if kind=='chop':
                    cuts=s['cuts']
                    bounds=[int(c['frame']) if 'frame' in c else round((beats.sec(s['start_beat']+c['beat'])-beats.sec(s['start_beat']))*fps) for c in cuts]
                    if not bounds or bounds[0]!=0 or any(y<=x for x,y in zip(bounds,bounds[1:])) or bounds[-1]>=n:
                        raise ValueError('chop cuts start at local beat 0 and increase within segment')
                    if sum(c.get('style','raw')=='raw' for c in cuts)<len(cuts)/2:
                        raise ValueError('At least half of chop cuts must be raw')
                for k in range(n):
                    frames={alias:r.read() for alias,r in readers.items()} if kind!='freeze' else {}
                    phase=(a+k)/fps*beats.bpm/60
                    style=s.get('style','raw')
                    used=[]
                    if kind=='black':
                        frame=np.zeros((h,w,3),np.uint8)
                    elif kind=='grid':
                        tiles=[]; side=s.get('n',3)
                        order=[4,5,8,7,6,3,0,1,2] if side==3 else [0,1,3,2]
                        reveal=int(s.get('reveal_frames',max(1,round(float(s.get('reveal_beats',1))*60/beats.bpm*fps))))
                        flip_span=int(s.get('flip_frames',max(1,round(float(s.get('flip_beats',2))*60/beats.bpm*fps))))
                        for cell,alias in enumerate(s['tiles']):
                            flip_at=(reveal if s.get('flip_after_reveal') else 0)+round((cell+1)*flip_span/(side*side))
                            if s.get('flip_to') and (s.get('mode')=='flip' or s.get('flip_after_reveal')) and k>=flip_at:
                                alias=s['flip_to'][cell]
                            tile_style=s.get('tile_styles',['raw']*(side*side))[cell]
                            tile=styles.apply(frames[alias],tile_style,seed=a+k+cell,phase=phase)
                            if s.get('mode')=='reveal' and k<round(order.index(cell)*reveal/max(1,side*side-1)):
                                tile=np.full((h,w,3),PAPER,np.uint8)
                            else:
                                used.append(alias)
                            tiles.append(tile)
                        frame=styles.grid(tiles,side,max(2,round(w*8/1080)))
                    elif frozen is not None:
                        frame=overlay_box(frozen.copy(),[w*.18,h*.2,w*.64,h*.6],s.get('label','HOLD'))
                        used=[s['source']]
                    elif s.get('source'):
                        raw=frames[s['source']]; used=[s['source']]
                        if kind=='chop':
                            idx=max(i for i,v in enumerate(bounds) if v<=k)
                            style=cuts[idx].get('style','raw')
                        frame=styles.apply(raw,style,seed=a+k,phase=phase)
                        transition=int(s.get('transition_frames',0))
                        if transition and style!='raw':
                            alpha=min(1,(k+1)/transition,(n-k)/transition)
                            frame=np.uint8(raw*(1-alpha)+frame*alpha)
                        if kind=='hero':
                            if tracker is None:
                                box=s.get('box',[.3,.25,.3,.25])
                                tracker=Tracker([box[0]*w,box[1]*h,box[2]*w,box[3]*h])
                            if s.get('magnifier') and not cfg['sources'][s['source']].get('allow_zoom'):
                                raise ValueError('magnifier needs source.allow_zoom=true')
                            frame=overlay_box(frame,tracker.update(raw),s.get('label','TRACK'),s.get('magnifier',False),s.get('accent_color',RED))
                        if s.get('wipe'):
                            x=round(w*k/max(1,n-1)); frame[:,max(0,x-1):x+1]=s.get('accent_color',RED)
                    else:
                        frame=np.full((h,w,3),PAPER,np.uint8)
                    if s.get('word'):
                        frame=text(frame,s['word'],(w*.08,h*.7),int(h*.045),
                                   fill=tuple(s.get('word_color',[17,17,17])),anchor='lt')
                    if kind=='text_word' and not s.get('word'):
                        raise ValueError('text_word needs word')
                    if s.get('fade_out_frames') and k>=n-s['fade_out_frames']:
                        frame=np.uint8(frame.astype(float)*max(0,(n-1-k)/s['fade_out_frames']))
                    writer.write(frame)
                    trace.write(json.dumps(dict(frame=a+k,type=kind,style=style,sources=[dict(
                        alias=alias,seconds=round(specs[alias][0]+(0 if kind=='freeze' else k/fps),6),
                        x_offset=specs[alias][1]) for alias in used]))+'\n')
    if review:
        contact_sheet(out,out.with_suffix('.sheet.png'),fps=fps)
    return rows[-1][1]


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('config',type=Path,help='Timeline JSON (paths relative to this file)')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--no-sheet',action='store_true')
    video_args(p); a=p.parse_args()
    cfg=load_json(a.config)
    print('frames',render(a.config,a.out,*video_options(cfg,a),not a.no_sheet))
