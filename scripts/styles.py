"""Real-video visual treatments: RGB uint8 in, RGB uint8 out; no generated faces.

Run --help to list supported treatment names. Segmentation uses MediaPipe when
its bundled solutions API is available, otherwise a white-wall luminance mask.
"""
import argparse
from functools import lru_cache
import warnings

import cv2
import numpy as np
from PIL import Image, ImageDraw
from common import PAPER, RED, INK, font, grain

NAMES = ('raw', 'thermal_silhouette', 'rainbow_thermal', 'dots3', 'one_bit',
         'negative', 'ascii_face', 'mono_m3', 'red_halftone', 'pixel_stretch', 'glitch')


@lru_cache(maxsize=1)
def segmenter():
    try:
        import mediapipe as mp
        return mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
    except (ImportError, AttributeError, OSError, RuntimeError):
        warnings.warn('MediaPipe segmentation unavailable; using the documented white-wall mask.',RuntimeWarning)
        return None


def person_mask(rgb):
    m = segmenter()
    if m:
        small = cv2.resize(rgb, (256, 256))
        mask = m.process(small).segmentation_mask
        return np.clip((cv2.resize(mask, rgb.shape[1::-1])-.35)/.3, 0, 1)
    # Estimate the actual wall rather than assuming pure white: phone footage
    # often records a white wall around 210, which a fixed threshold misclassifies.
    h,w=rgb.shape[:2]
    edge=max(1,w//40)
    border=np.concatenate([rgb[:h*2//3,:edge].reshape(-1,3),rgb[:h*2//3,-edge:].reshape(-1,3)])
    bg=np.median(border,axis=0)
    noise=np.linalg.norm(border.astype(float)-bg,axis=1)
    threshold=max(22,float(np.percentile(noise,95))+8)
    delta=np.linalg.norm(rgb.astype(np.float32)-bg,axis=2)
    mask = np.uint8(delta>threshold)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    count,labels,stats,centres=cv2.connectedComponentsWithStats(mask,8)
    if count>1:
        scores=stats[1:,cv2.CC_STAT_AREA]/(1+4*np.abs(centres[1:,0]/w-.5))
        mask=np.uint8(labels==1+int(np.argmax(scores)))
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.2)


def levels(rgb, mask):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    values = g[mask > .5]
    lo, hi = np.percentile(values, [5, 95]) if values.size else (0, 1)
    return np.clip((g-lo)/max(.05, hi-lo), 0, 1)


def palette(g, stops):
    stops = np.array(stops, np.float32)
    p = np.clip(g, 0, 1)*(len(stops)-1)
    i = np.minimum(p.astype(int), len(stops)-2)
    f = (p-i)[..., None]
    return stops[i]*(1-f)+stops[i+1]*f


def thermal_silhouette(rgb, mask=None, phase=0, **kw):
    mask = person_mask(rgb) if mask is None else mask
    w = rgb.shape[1]
    dist = cv2.distanceTransform(np.uint8(mask > .5), cv2.DIST_L2, 5)
    dist = (dist/(dist.max()+1e-6))**.6
    lum = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)/255,
                           (0, 0), max(1, w*28/1080))
    yy = np.linspace(0, 1, rgb.shape[0])[:, None]
    heat = (.62*dist + .22*lum + .12*np.clip((yy-.35)/.65, 0, 1)-.12)/.75
    col = palette(heat, [[58,10,5], [179,32,14], [255,74,18], [255,138,31], [255,195,77], [255,244,214]])
    m = cv2.GaussianBlur(mask, (0,0), 1.2)[...,None]
    glow = cv2.GaussianBlur(mask, (0,0), max(1,w*14/1080))[...,None]*np.array([255,74,18])*.35
    return (11*(1-m)+col*m+glow*(1-m))*(1+.06*np.sin(phase*2*np.pi))


def rainbow_thermal(rgb, mask=None, **kw):
    mask = person_mask(rgb) if mask is None else mask
    g = cv2.GaussianBlur(levels(rgb, mask), (0,0), max(1,rgb.shape[1]/120))
    col = palette(g, [[27,43,255], [138,43,226], [255,45,138], [255,59,31],
                      [255,138,0], [255,225,77], [124,255,91], [255,255,255]])
    return col*mask[...,None]+17*(1-mask[...,None])


def dots3(rgb, mask=None, step=None, phase=0, growth=1, red=False, **kw):
    h,w = rgb.shape[:2]
    mask = person_mask(rgb) if mask is None else mask
    dark = 1-cv2.GaussianBlur(levels(rgb,mask),(0,0),1)
    step = max(4, int(step or w*16/1080))
    canvas = Image.new('RGB',(w*2,h*2),RED if red else PAPER)
    d = ImageDraw.Draw(canvas)
    for y in range(step//2,h,step):
        for x in range(step//2,w,step):
            if mask[y,x] < .5 or dark[y,x] < .24:
                continue
            r = step*(.17 if dark[y,x]<.5 else .32 if dark[y,x]<.78 else .47)
            r *= growth*(1+.08*np.sin(phase*2*np.pi))
            d.ellipse(((x-r)*2,(y-r)*2,(x+r)*2,(y+r)*2),fill=(120,18,8) if red else INK)
    return np.array(canvas.resize((w,h),Image.Resampling.LANCZOS))


def one_bit(rgb, mask=None, **kw):
    g = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    return np.where(binary[...,None]>0,np.array([238,232,221]),np.array([14,20,36]))


def negative(rgb, **kw):
    return np.repeat((255-cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY))[...,None],3,2)


@lru_cache(maxsize=16)
def glyphs(cell):
    result=[]
    for ch in ' .:-=+*#%@':
        im=Image.new('L',(cell,cell),0)
        ImageDraw.Draw(im).text((cell/2,cell/2),ch,font=font(cell,800),fill=255,anchor='mm')
        result.append(im)
    return result


def ascii_face(rgb, mask=None, cell=None, light=True, **kw):
    h,w=rgb.shape[:2]
    cell=max(6,int(cell or w*14/1080))
    mask=person_mask(rgb) if mask is None else mask
    tone=1-levels(rgb,mask) if light else levels(rgb,mask)
    im=Image.new('RGB',(w,h),PAPER if light else (10,10,10))
    for y in range(0,h,cell):
        for x in range(0,w,cell):
            if mask[min(y+cell//2,h-1),min(x+cell//2,w-1)]<.5:
                continue
            ch=int(np.clip(round(tone[y:y+cell,x:x+cell].mean()*9),0,9))
            im.paste(INK if light else PAPER,(x,y,x+cell,y+cell),glyphs(cell)[ch])
    return np.array(im)


def mono_m3(rgb, seed=0, **kw):
    g=rgb.astype(np.float32)/255@np.array([.50,.38,.12],np.float32)
    sm=cv2.bilateralFilter(np.uint8(g*255),9,28,7).astype(np.float32)/255
    g=np.clip(.75*g+.25*sm,0,1)**.92
    g=(6+np.clip(.5+(g-.5)*1.14,0,1)*238)/255
    glow=cv2.GaussianBlur(np.clip((g-.55)/.45,0,1),(0,0),max(1,rgb.shape[1]/70))
    g=1-(1-g)*(1-glow*.08)
    g+=np.random.default_rng(seed).standard_normal(g.shape).astype(np.float32)*.028*(.4+.6*4*g*(1-g))
    return np.repeat(np.clip(g*255,0,255)[...,None],3,2)


def red_halftone(rgb, **kw):
    return dots3(rgb,red=True,**kw)


def pixel_stretch(rgb, seed=0, **kw):
    h,w=rgb.shape[:2]
    out=cv2.resize(cv2.resize(rgb,(max(2,w//20),max(2,h//20))),(w,h),interpolation=cv2.INTER_NEAREST)
    rng=np.random.default_rng(seed)
    for _ in range(5):
        y=int(rng.integers(h)); height=max(1,h//50)
        out[y:y+height]=np.repeat(out[y:y+height,w//2:w//2+1],w,axis=1)
    return out


def glitch(rgb, seed=0, **kw):
    h,w=rgb.shape[:2]; out=rgb.copy(); rng=np.random.default_rng(seed)
    out[:,:,0]=np.roll(out[:,:,0],max(1,w//90),1)
    for _ in range(6):
        y=int(rng.integers(h)); bh=max(1,h//35)
        out[y:y+bh]=np.roll(out[y:y+bh],int(rng.integers(-max(2,w//8),max(2,w//8))),1)
    return out


def grid(tiles, n=3, gap=3):
    if n not in (2,3) or len(tiles)!=n*n:
        raise ValueError('grid needs 4 or 9 tiles')
    h,w=tiles[0].shape[:2]; out=np.full((h,w,3),PAPER,np.uint8)
    for k,tile in enumerate(tiles):
        r,c=divmod(k,n)
        x0=gap+round(c*(w-gap)/n); x1=round((c+1)*(w-gap)/n)
        y0=gap+round(r*(h-gap)/n); y1=round((r+1)*(h-gap)/n)
        out[y0:y1,x0:x1]=cv2.resize(tile,(x1-x0,y1-y0),interpolation=cv2.INTER_AREA)
    return out


def apply(rgb, name='raw', seed=0, phase=0, texture=True, **kw):
    if name not in NAMES:
        raise ValueError(f'Unknown style: {name}; choose {NAMES}')
    if name=='raw':
        return rgb.copy()
    out=np.uint8(np.clip(globals()[name](rgb,seed=seed,phase=phase,**kw),0,255))
    if not texture or name=='mono_m3':
        return out
    h,w=out.shape[:2]; y,x=np.mgrid[-1:1:complex(h),-1:1:complex(w)]
    out=out.astype(np.float32)*(1-.075*(x*x+y*y))[...,None]
    glow=cv2.GaussianBlur(np.maximum(out-200,0),(0,0),max(1,w/90))*.04
    return grain(out+glow,seed,1.5)


if __name__=='__main__':
    p=argparse.ArgumentParser(description='Style function library; use style_sheet.py for preview images.')
    p.parse_args()
    print('\n'.join(NAMES)+ '\ngrid: 2x2 / 3x3 live tiles (render.py)')
