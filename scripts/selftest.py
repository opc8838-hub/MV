"""Reproducible local end-to-end test using user-provided real video and music.

Creates an offline gallery, beatmap, six-style sheet, 10-second demo, additional
segment tests and SELFTEST.md. All artifacts are private and belong under work/.
The input files are read only; their size and modification time are rechecked.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np
import soundfile as sf
from PIL import Image
from common import (ROOT, Reader, Writer, ffmpeg, run, duration, save_json,
                    load_json, contact_sheet)
import analyze_music
import assemble
import ending
import opening
import picks_gallery
import render
import style_sheet
import styles


def fingerprint(path):
    stat=Path(path).stat()
    return dict(bytes=stat.st_size,mtime_ns=stat.st_mtime_ns)


def decode_check(path,expected):
    p=subprocess.run([ffmpeg(),'-v','error','-i',str(path),'-map','0:v:0','-f','framemd5','-'],
                     capture_output=True,check=True)
    lines=[s for s in p.stdout.decode().splitlines() if s and not s.startswith('#')]
    if len(lines)!=expected:
        raise AssertionError(f'{path.name}: {len(lines)} decoded frames, expected {expected}')
    return dict(frames=len(lines),unique_frames=len(set(s.split(',')[-1].strip() for s in lines)),
                duration=duration(path))


def main(video,music,out,at=0,w=360,h=640):
    started=time.time(); out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True)
    video=Path(video).resolve(); music=Path(music).resolve()
    before={str(p):fingerprint(p) for p in (video,music)}
    checks={}
    for script in (ROOT/'scripts').glob('*.py'):
        p=subprocess.run([sys.executable,str(script),'--help'],capture_output=True)
        if p.returncode:
            raise AssertionError(f'--help failed: {script.name}')
    checks['help']='all scripts exit 0'
    picks_gallery.build([video],out/'picks',start=at,end=at+3.2)
    picks_gallery.build([video],out/'face-picks',start=at,end=at+3.2,faces=True)
    checks['gallery_candidates']=len(load_json(out/'picks'/'picks.json'))
    bm=analyze_music.analyze(music,out/'music')
    checks['music']=dict(bpm=bm['bpm'],beats=len(bm['beats']),hits=len(bm['hits']))
    style_sheet.build(video,out/'styles',at,w,h)
    with Reader(video,at,1,w,h) as r:
        frame=r.read()
    for name in styles.NAMES:
        f=styles.apply(frame,name)
        if f.shape!=frame.shape or f.dtype!=np.uint8:
            raise AssertionError(f'Invalid style output {name}')
        Image.fromarray(f).save(out/'styles'/f'{name}.png')
    if not np.array_equal(styles.apply(frame,'raw'),frame):
        raise AssertionError('raw altered pixels')
    checks['styles']=list(styles.NAMES)
    sources={f'S{i}':dict(path=str(video),start=at+i*.12,x_offset=0) for i in range(9)}
    # Choose actual analyzed hits in the first four seconds for the opening.
    hits=[i for i,x in enumerate(bm['hits']) if .15<x['time']<3.8][:5]
    slots=[dict(at=0,background='black',text='|',color=[238,235,228])]
    for j,hit in enumerate(hits):
        slots.append(dict(hit=hit,source=f'S{j}',style=['raw','red_halftone','dots3','mono_m3','thermal_silhouette'][j],
                          text=['who','am i?','who','am i?','?'][j],scan=j==4))
    if len(slots)<2:
        raise AssertionError('Selftest song needs strong hits during first four seconds')
    save_json(out/'opening.json',dict(beatmap='music/beatmap.json',duration=4,sources=sources,slots=slots))
    opening.build(out/'opening.json',out/'opening.mp4',w,h)
    segments=[dict(type='clip',start_beat=0,end_beat=3,source='S0'),
        dict(type='chop',start_beat=3,end_beat=5,source='S0',offset=round(1.5*25)/25,
             cuts=[dict(beat=i*.25,style=['raw','thermal_silhouette','raw','dots3','raw','negative','raw','mono_m3'][i]) for i in range(8)]),
        dict(type='grid',start_beat=5,end_beat=8,n=3,tiles=list(sources),mode='reveal',reveal_beats=1)]
    save_json(out/'timeline.json',dict(bpm=120,sources=sources,segments=segments))
    render.render(out/'timeline.json',out/'body.mp4',w,h)
    trace=[json.loads(s) for s in (out/'body.trace.ndjson').read_text().splitlines()]
    for row in trace:
        for src in row['sources']:
            start=sources[src['alias']]['start']
            expected=start+(row['frame']/25 if row['type'] in ('clip','chop') else (row['frame']-62)/25)
            # Grid starts on rounded frame 62 (2.5 seconds at 25fps).
            if abs(src['seconds']-expected)>1e-5:
                raise AssertionError('Source clock jumped during clip/chop/grid')
    checks['source_clock']='clip/chop continuity and every visible grid tile advance by 1/25s'
    ending.build(out/'body.mp4',out/'ending.mp4',3.92,'nobody.',2,w,h)
    parts=[out/'opening.mp4',out/'body.mp4',out/'ending.mp4']
    checks['demo_assembly']=assemble.assemble(parts,music,out/'demo.mp4',w,h)
    checks['demo_decode']=decode_check(out/'demo.mp4',250)
    checks['insert_assembly']=assemble.assemble(parts,music,out/'extended.mp4',w,h,insert_at=4,insert_beats=1)
    checks['insert_decode']=decode_check(out/'extended.mp4',262)
    # AAC timing and copied-block correspondence, excluding codec edges.
    audio=out/'extended-audio.wav'
    run(['-i',out/'extended.mp4','-vn','-ac','1','-ar','22050',audio])
    decoded,sr=sf.read(audio)
    run(['-i',music,'-t','11','-vn','-ac','1','-ar','22050',out/'reference-audio.wav'])
    original,_=sf.read(out/'reference-audio.wav')
    shift=checks['insert_assembly']['inserted_frames']/25
    samples=[]
    for dest,src,span in [(1,1,1),(4.05,4.05,.3),(5,5-shift,1)]:
        a=decoded[round(dest*sr):round((dest+span)*sr)]
        b=original[round(src*sr):round((src+span)*sr)]
        samples.append(float(np.corrcoef(a,b)[0,1]))
    if min(samples)<.95 or abs(len(decoded)/sr-10-shift)>.06:
        raise AssertionError(f'Inserted music alignment failed: {samples}')
    checks['audio']=dict(correlations=samples,decoded_seconds=len(decoded)/sr)
    # Exercise the remaining renderer types, four-grid styles, flip and wipe.
    more=[dict(type='hero',start_beat=0,end_beat=2,source='S0',box=[.3,.3,.15,.15],magnifier=True,label='TOOL'),
          dict(type='grid',start_beat=2,end_beat=4,n=2,tiles=['S0']*4,tile_styles=['raw','thermal_silhouette','dots3','ascii_face']),
          dict(type='grid',start_beat=4,end_beat=6,n=3,tiles=list(sources),mode='flip',flip_to=list(reversed(sources)),flip_beats=1),
          dict(type='freeze',start_beat=6,end_beat=7,source='S0',authorized=True),
          dict(type='black',start_beat=7,end_beat=8),
          dict(type='text_word',start_beat=8,end_beat=9,word='unknown.',source='S0',wipe=True)]
    save_json(out/'features.json',dict(bpm=120,sources=sources,segments=more))
    count=render.render(out/'features.json',out/'features.mp4',w,h)
    checks['features']=decode_check(out/'features.mp4',count)
    with Reader(out/'features.mp4',3,1,w,h) as r:
        first=r.read()
    with Reader(out/'features.mp4',3.4,1,w,h) as r:
        last=r.read()
    if np.mean(np.abs(first.astype(float)-last))>2:
        raise AssertionError('Authorized freeze is not stable')
    # Verify all nine image regions actually move, beyond the source-clock trace.
    with Reader(out/'body.mp4',3.12,2,w,h) as r:
        f0,f1=r.read(),r.read()
    deltas=[]
    for cell in range(9):
        row,col=divmod(cell,3)
        y0,y1=round((row+.15)*h/3),round((row+.85)*h/3)
        x0,x1=round((col+.15)*w/3),round((col+.85)*w/3)
        deltas.append(float(np.mean(np.abs(f0[y0:y1,x0:x1].astype(float)-f1[y0:y1,x0:x1]))))
    if min(deltas)<.01:
        raise AssertionError(f'A grid tile appears still: {deltas}')
    checks['grid_motion_mean_abs_delta']=deltas
    # Pure white and red roundtrip under an explicit BT.709 decoding matrix.
    color=np.full((h,w,3),255,np.uint8)
    with Writer(out/'white.mp4',w,h) as writer:
        for _ in range(3): writer.write(color)
    rgb=subprocess.run([ffmpeg(),'-v','error','-i',str(out/'white.mp4'),'-frames:v','1','-vf',
        'scale=in_color_matrix=bt709:in_range=tv:out_range=pc','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
    white=np.frombuffer(rgb,np.uint8).reshape(h,w,3).mean(axis=(0,1))
    if white.min()<254 or white.max()-white.min()>1:
        raise AssertionError(f'White roundtrip failed: {white}')
    checks['white_rgb']=white.tolist()
    for malformed in [dict(type='freeze',start_beat=0,end_beat=1,source='S0'),
                      dict(type='clip',start_beat=1,end_beat=2,source='S0')]:
        try: render.compile_segments(dict(segments=[malformed]),render.get_beats({},out),25)
        except ValueError: pass
        else: raise AssertionError('Invalid timeline was accepted')
    checks['invalid_inputs']='unauthorized freeze and uncovered timeline rejected'
    after={str(p):fingerprint(p) for p in (video,music)}
    if before!=after: raise AssertionError('Input media changed')
    checks['inputs_unchanged']=True
    checks['elapsed_seconds']=round(time.time()-started,2)
    checks['dimensions']=[w,h]
    checks['python']=sys.version.split()[0]
    checks['inputs']=before
    save_json(out/'checks.json',checks)
    contact_sheet(out/'demo.mp4',out/'demo-every-frame.png',every_frame=True)
    (out/'SELFTEST.md').write_text('# Local self-test\n\nPASS: gallery → music analysis → styles → opening + one phrase + ending → music mux.\n\n'
        'See checks.json for decoded frames, audio insertion alignment, continuous source clocks, live grid movement, '
        'white roundtrip and unchanged input fingerprints. Review the generated sheets and gallery in a browser.\n\n'
        f'Demo: 250 frames / 25fps / 10 seconds / {w}×{h}. Extended: 262 frames / 10.48 seconds '
        '(one 0.5-second beat rounds to 12 frames at 25fps).\n\n'
        f'Elapsed: {checks["elapsed_seconds"]} seconds.\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in checks.items() if k!='inputs'},ensure_ascii=True,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--music',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--at',type=float,default=0)
    p.add_argument('--width',type=int,default=360)
    p.add_argument('--height',type=int,default=640)
    a=p.parse_args(); main(a.video,a.music,a.out,a.at,a.width,a.height)
