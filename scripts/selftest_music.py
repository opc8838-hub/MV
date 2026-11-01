"""End-to-end music-driven acceptance: analyze -> plan -> render -> mux -> audit.

Use real private role-tagged picks and music. Saves every-frame review pages,
checks.json and final.mp4 in --out; source files are never modified. Run once per
song. Automated checks complement (do not replace) watching the generated sheets.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import soundfile as sf
from analyze_music import analyze
from plan import plan
from opening import build as opening
from ending import build as ending
from render import render
from assemble import assemble
from common import Reader, contact_sheet, load_json, save_json, resolve, run


def audit(out):
    out = Path(out); bm = load_json(out/'music/beatmap.json')
    tl = load_json(out/'timeline.json'); op = load_json(out/'opening.json')
    ac = load_json(out/'assemble.json'); alloc = load_json(out/'allocation.json')
    fps = tl['fps']; intro = alloc['opening_frames']; body_end = alloc['body_end_frame']
    music_frames = alloc['total_music_frames']; total = music_frames+round(ac['shutdown_seconds']*fps)
    # Audit every actual output frame, not just planned metadata.
    black = []; frame_variance = []; grid_changes = []
    with Reader(out/'final.mp4',0,total,180,320,fps) as r:
        previous = None
        for i in range(total):
            rgb = r.read()
            if rgb.max() < 8 and i < music_frames: black.append(i)
            frame_variance.append(float(rgb.std()))
            local = i-intro
            grid = next((s for s in tl['segments'] if s['type']=='grid' and s['start_frame']<=local<s['end_frame']),None)
            if grid and local==grid['start_frame']:
                motion = np.zeros(9); observations = 0
            if grid:
                stable = grid.get('reveal_frames',0)+grid.get('flip_frames',0)
                if previous is not None and local-grid['start_frame']>stable:
                    for cell in range(9):
                        row,col=divmod(cell,3)
                        x0,x1=col*60+6,(col+1)*60-6; y0,y1=round(row*320/3)+6,round((row+1)*320/3)-6
                        motion[cell]+=np.abs(rgb[y0:y1,x0:x1].astype(float)-previous[y0:y1,x0:x1]).mean()
                    observations+=1
                if local==grid['end_frame']-1:
                    if observations<2 or min(motion)<=.1: raise AssertionError('A live grid cell did not move after reveal/flip')
                    grid_changes.append(dict(frames=[grid['start_frame'],grid['end_frame']],
                                             stable_pairs=observations,cell_motion_sum=motion.tolist()))
            previous = rgb
    if black: raise AssertionError(f'Unexpected black/empty output at frames {black[:8]}')
    # Check actual opening cut report against the source hit/gap event set.
    # The body uses beats/quarter-beats; intro may intentionally use off-grid
    # transients and silence boundaries. Do not call all intro cuts downbeats.
    ws = ac['music_start']; event_times = [ws]+[h['time'] for h in bm['hits']]
    event_times += [t for pair in bm['silences'] for t in pair]
    event_times += bm['beats']
    errors = []
    for cut in load_json(out/'opening.cuts.json'):
        t = ws+cut['start_frame']/fps
        errors.append(min(abs(t-v) for v in event_times)*fps)
    beats = np.array(bm['beats'])
    subdivisions = sorted([float(x+(y-x)*q/4) for x,y in zip(beats,beats[1:]) for q in range(4)]+[float(beats[-1])])
    for s in tl['segments']:
        errors.append(min(abs(ws+(intro+s['start_frame'])/fps-t) for t in subdivisions)*fps)
        if s['type']=='chop':
            if sum(c['style']=='raw' for c in s['cuts'])<len(s['cuts'])/2: raise AssertionError('Too few raw cuts')
            for c in s['cuts']:
                errors.append(min(abs(ws+(intro+s['start_frame']+c['frame'])/fps-t) for t in subdivisions)*fps)
        if s.get('magnifier') or s['type']=='freeze': raise AssertionError('Unexpected zoom or freeze in automatic plan')
    if max(errors)>1.00001: raise AssertionError(f'Cut misses musical event by {max(errors):.3f} frames')
    # Hidden grid clocks consume ranges too. Interval overlap catches different
    # aliases which point at the same original moment in the same physical file.
    reservations = alloc['reservations']
    for i,a in enumerate(reservations):
        for b in reservations[i+1:]:
            if a['path']==b['path'] and min(a['end'],b['end'])-max(a['start'],b['start'])>1e-5:
                raise AssertionError('Repeated source interval')
    traces = [json.loads(line) for line in (out/'body.trace.ndjson').read_text().splitlines()]
    if len(traces)!=body_end-intro: raise AssertionError('Body trace length mismatch')
    previous = {}
    for row in traces:
        for src in row['sources']:
            alias=src['alias']; t=src['seconds']
            if alias in previous and abs(t-previous[alias]-1/fps)>1e-5: raise AssertionError('Source clock jumped')
            previous[alias]=t
    # Full decoder validation and independent audio correlation, with nonzero
    # music window offsets supported. AAC encoder priming is handled by MP4 PTS.
    run(['-i',out/'final.mp4','-f','null','-'])
    with tempfile.TemporaryDirectory(prefix='nobody-audit-') as tmp:
        reference=Path(tmp)/'reference.wav'; actual=Path(tmp)/'actual.wav'
        run(['-ss',ws,'-i',resolve(out,ac['music']),'-t',ac['music_seconds'],'-ac','1','-ar','22050',reference])
        run(['-i',out/'final.mp4','-vn','-ac','1','-ar','22050',actual])
        x,sr=sf.read(reference); y,_=sf.read(actual)
        n=min(len(x),len(y))-round(.3*sr)
        corr=float(np.corrcoef(x[:n],y[:n])[0,1])
        if corr<.97 or abs(len(y)/sr-total/fps)>.06: raise AssertionError(f'Audio window drift: {corr}')
    result=dict(bpm=bm['bpm'],meter=bm['meter'],drop=bm['drop'],frames=total,fps=fps,
        duration=total/fps,grids=grid_changes,max_cut_error_frames=max(errors),
        no_black_frames=True,no_zoom=True,no_interpolation=True,no_repeated_source_ranges=True,
        audio_correlation=corr,trace_frames=len(traces),dimensions=[tl['width'],tl['height']])
    save_json(out/'checks.json',result)
    return result


def main(music,picks,out,style=None,target=30,meter='auto'):
    started=time.time(); out=Path(out); out.mkdir(parents=True,exist_ok=True)
    analyze(music,out/'music',target_seconds=target,meter=meter)
    configs=plan(out/'music/beatmap.json',picks,out,style,music)
    c=configs['opening']; w,h,fps=c['width'],c['height'],c['fps']
    opening(out/'opening.json',out/'opening.mp4',w,h,fps)
    render(out/'timeline.json',out/'body.mp4',w,h,fps)
    c=configs['ending']
    ending(resolve(out,c['source']),out/'ending.mp4',c['at'],c['word'],c['duration'],w,h,fps,
           c['shutdown'],c['shutdown_seconds'] if c['shutdown'] else 0)
    c=configs['assemble']
    assemble([resolve(out,x) for x in c['parts']],resolve(out,c['music']),out/'final.mp4',w,h,fps,
             music_start=c['music_start'],music_seconds=c['music_seconds'],
             shutdown_seconds=c['shutdown_seconds'],audio_fade_out=c['audio_fade_out'])
    result=audit(out)
    contact_sheet(out/'final.mp4',out/'every-frame.png',fps=fps,every_frame=True)
    result['elapsed_seconds']=round(time.time()-started,2); save_json(out/'checks.json',result)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--music',type=Path,required=True)
    p.add_argument('--picks',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--style',type=Path)
    p.add_argument('--target-seconds',type=float,default=30)
    p.add_argument('--meter',choices=['auto','4/4','3/4','6/8'],default='auto')
    a=p.parse_args(); main(a.music,a.picks,a.out,a.style,a.target_seconds,a.meter)
