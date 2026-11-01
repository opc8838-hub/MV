"""Read a real-video frame at --at and generate six labeled local PNG style
samples and a comparison sheet. Outputs contain personal imagery; keep them local.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from common import Reader, font, video_args
import styles


def build(source,out,at=0,w=360,h=640,x_offset=0):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    with Reader(source,at,1,w,h,x_offset=x_offset) as r:
        raw=r.read()
    names=['raw','thermal_silhouette','dots3','one_bit','mono_m3','ascii_face']
    sheet=Image.new('RGB',(w*3,(h+32)*2),(238,235,228))
    for i,name in enumerate(names):
        im=Image.fromarray(styles.apply(raw,name,seed=i))
        im.save(out/f'S{i+1}-{name}.png')
        x,y=i%3*w,i//3*(h+32)
        sheet.paste(im,(x,y))
        ImageDraw.Draw(sheet).text((x+8,y+h+4),f'S{i+1} {name}',font=font(16,500),fill=(17,17,17))
    sheet.save(out/'style-sheet.png')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--at',type=float,default=0)
    p.add_argument('--out',type=Path,required=True,help='Local output directory')
    p.add_argument('--x-offset',type=float,default=0,help='Fixed offset as a fraction of source width')
    video_args(p); a=p.parse_args()
    build(a.source,a.out,a.at,a.width,a.height,a.x_offset)
