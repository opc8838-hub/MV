"""Turn a user-supplied video frame (including a live grid) into dot particles,
explode, slam into a configurable word and power off like a CRT. Output silent MP4.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from common import Reader, Writer, paper, text, INK, video_args, contact_sheet, protect_inputs


def build(source,out,at=0,word='nobody.',seconds=2,w=360,h=640,fps=25):
    protect_inputs(out,[source])
    if seconds<=0 or not word.strip():
        raise ValueError('Positive duration and a nonempty word required')
    with Reader(source,at,1,w,h,fps) as r:
        raw=r.read()
    step=max(4,round(w*14/1080))
    gray=cv2.cvtColor(raw,cv2.COLOR_RGB2GRAY)/255
    yy,xx=np.mgrid[step//2:h:step,step//2:w:step]
    dark=1-gray[yy,xx]; keep=dark>.25
    pos=np.column_stack([xx[keep],yy[keep]]).astype(float)
    if not len(pos):
        raise ValueError('Selected frame has no visible dark points; choose another frame')
    rad=np.where(dark[keep]<.48,.18,np.where(dark[keep]<.66,.32,.47))*step
    mask=cv2.cvtColor(text(np.zeros_like(raw),word,fill=(255,255,255),size=int(w*.22)),cv2.COLOR_RGB2GRAY)
    ty,tx=np.nonzero(mask>128)
    if not len(tx):
        raise ValueError('Word has no renderable glyphs; provide --font support in common.font for other scripts')
    rng=np.random.default_rng(9)
    picks=rng.choice(len(tx),len(pos),replace=len(pos)>len(tx))
    dest=np.column_stack([tx[picks],ty[picks]])
    centre=np.array([w/2,h/2])
    burst=centre+(pos-centre)*rng.uniform(1.8,3.4,(len(pos),1))+rng.normal(0,w*.1,pos.shape)
    solid=text(paper(w,h),word,size=int(w*.22))
    total=round(seconds*fps)
    with Writer(out,w,h,fps) as writer:
        for k in range(total):
            p=k/max(1,total-1)
            if p>=.62:
                q=(p-.62)/.38; frame=np.zeros_like(raw)
                if q<.35:
                    hh=max(2,round(h*(1-q/.35)**2)); y=(h-hh)//2
                    frame[y:y+hh]=cv2.resize(solid,(w,hh))
                elif q<.68:
                    ww=max(2,round(w*(1-(q-.35)/.33)**2)); x=(w-ww)//2
                    frame[h//2-1:h//2+1,x:x+ww]=255
                elif q<.85:
                    cv2.circle(frame,(w//2,h//2),max(1,w//180),(255,255,255),-1)
                writer.write(frame); continue
            if p<.08:
                xy=pos; rr=rad
            elif p<.3:
                e=1-(1-(p-.08)/.22)**3; xy=pos+(burst-pos)*e; rr=rad*(1-.3*e)
            elif p<.5:
                e=((p-.3)/.2)**2.6; xy=burst+(dest-burst)*e; rr=rad*.7*(1-e)+step*.3*e
            else:
                xy=dest; rr=rad*max(0,1-(p-.5)/.1)
            im=Image.fromarray(paper(w,h,k)); d=ImageDraw.Draw(im)
            for (x,y),r in zip(xy,rr):
                if r>.2 and -step<x<w+step and -step<y<h+step:
                    d.ellipse((x-r,y-r,x+r,y+r),fill=INK)
            frame=np.array(im)
            if p<.08:
                alpha=p/.08; frame=np.uint8(raw*(1-alpha)+frame*alpha)
            if p>=.5:
                alpha=min(1,(p-.5)/.1); frame=np.uint8(frame*(1-alpha)+solid*alpha)
            if .08<=p<.08+1/max(1,total-1):
                frame=np.uint8(frame*.35+255*.65)
            writer.write(frame)
    contact_sheet(out,Path(out).with_suffix('.sheet.png'),fps=fps,every_frame=True)
    return total


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--at',type=float,default=0,help='Source seconds of the chosen grid/frame')
    p.add_argument('--word',default='nobody.')
    p.add_argument('--duration',type=float,default=2)
    video_args(p); a=p.parse_args()
    print('frames',build(a.source,a.out,a.at,a.word,a.duration,a.width,a.height,a.fps))
