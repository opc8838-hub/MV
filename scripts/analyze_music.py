"""Local song/video -> beatmap.json, structure.png and report.md.
All times are source seconds. Drop/meter/phrases are listening suggestions.
"""
import argparse
from pathlib import Path
import tempfile
import librosa
import numpy as np
from PIL import Image, ImageDraw
from common import run, save_json, font, PAPER, RED


def recommend_window(data, target):
    """Bar-aligned window, preferring intro, drop and climax coverage."""
    dur = data['duration']
    if target <= 0:
        raise ValueError('target-seconds must be positive')
    if dur <= target:
        return dict(start=0., end=dur, reason='whole track fits target')
    candidates = sorted(set([0.] + [t for t in data['bars'] if t <= dur-target]))
    def score(a):
        b = a+target; drop = data.get('drop'); intro = data['intro']
        return (4*(drop is not None and a <= drop < b)
                + 3*(a <= (data.get('climax') or {}).get('start', -1) < b)
                + 2*max(0, min(b, intro['end'])-max(a, intro['start']))/max(1, intro['end'])
                + sum(p['energy'] for p in data['phrases'] if a <= p['start'] < b) - a/dur*.05)
    start = max(candidates, key=score)
    return dict(start=round(start, 6), end=round(start+target, 6),
                reason='bar-aligned start; maximize intro/drop/climax coverage')


def phrase_parts(points, energy, times, hits):
    """Ordered beat-boundary search; inconclusive audio gets explicit 2:1:1 fallback."""
    a, b = points[0], points[-1]
    def mean(x, y):
        values = energy[(times >= x) & (times < y)]
        return float(values.mean()) if len(values) else 0.
    best = None
    for i in range(1, len(points)-2):
        for j in range(i+1, len(points)-1):
            x, y = points[i], points[j]
            es, ec, eb = mean(a, x), mean(x, y), mean(y, b)
            contrast = (ec-max(es, eb))/max(ec, .0001)
            density = sum(x <= h['time'] < y for h in hits)/max(.1, y-x)
            value = contrast + .025*density - .1*abs((x-a)/(b-a)-.5)
            if best is None or value > best[0]: best = (value, contrast, x, y)
    confident = best is not None and best[1] > .12
    bounds = [a, best[2], best[3], b] if confident else [a, a+(b-a)*.5, a+(b-a)*.75, b]
    return ([dict(kind=k, start=round(x, 6), end=round(y, 6))
             for k, x, y in zip(('swell','chop','breath'), bounds, bounds[1:])],
            round(min(.9, .5+best[1]), 3) if confident else .25,
            'energy/onset contrast' if confident else 'fallback 2:1:1')


def analyze(source, out, phrase_beats=8, max_seconds=600, target_seconds=30, meter='auto'):
    if phrase_beats < 3 or max_seconds <= 0 or target_seconds <= 0:
        raise ValueError('phrase-beats >= 3 and positive limits required')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nobody-audio-') as tmp:
        wav = Path(tmp)/'analysis.wav'
        run(['-i',source,'-t',max_seconds,'-vn','-ac','1','-ar','22050',wav])
        y, sr = librosa.load(wav, sr=22050, mono=True)
    dur = len(y)/sr; hop = 256
    if dur < 1 or np.max(np.abs(y)) < 1e-7:
        raise ValueError('Audio is silent or shorter than one second')
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, _ = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop)
    detected = float(np.atleast_1d(tempo)[0])
    if detected <= 0: raise ValueError('No reliable beat; supply corrected beatmap')
    candidates = [detected*2**i for i in range(-2,3) if 60 <= detected*2**i <= 180]
    bpm = min(candidates, key=lambda v:(not .35 <= 60/v <= .75, abs(np.log2(v/detected))))
    _, bf = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop,
                                    bpm=bpm, tightness=120, trim=False)
    bt = librosa.frames_to_time(bf, sr=sr, hop_length=hop); bt = bt[bt < dur]
    if len(bt) < 2: raise ValueError('Not enough beats; supply corrected beatmap')
    notes = [f'Tempo detected {detected:.2f}, selected {bpm:.2f} BPM; half/double alternatives prefer 0.35-0.75 seconds per editing beat.']
    peaks = librosa.util.peak_pick(onset, pre_max=6, post_max=6, pre_avg=40, post_avg=40,
                                  delta=max(.01,onset.std()*.7), wait=8)
    ts = librosa.times_like(onset, sr=sr, hop_length=hop)
    hits = [dict(time=round(float(ts[p]),6), strength=round(float(onset[p]/max(onset.max(),1e-6)),4)) for p in peaks if ts[p] < dur]
    et = np.arange(0,dur,.25)
    ev = np.array([np.sqrt(np.mean(y[int(t*sr):min(len(y),int((t+.25)*sr))]**2)) for t in et])
    db = 20*np.log10(ev+1e-9)
    energy = [dict(time=round(float(t),6), rms=round(float(v),7), db=round(float(d),3)) for t,v,d in zip(et,ev,db)]
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    quiet = 20*np.log10(rms+1e-9) < max(-60,float(np.median(db)-18))
    silences = []; begin = None
    for i,q in enumerate(np.r_[quiet,False]):
        t = min(dur,i*hop/sr)
        if q and begin is None: begin = t
        if not q and begin is not None:
            if t-begin >= .12: silences.append([round(begin,6),round(t,6)])
            begin = None
    # Sustained rise rejects isolated intro stabs. No convincing rise => null.
    rises = []
    for i,t in enumerate(et):
        if t < 1 or t+1 > dur: continue
        pre = ev[max(0,i-6):i].mean(); post = ev[i:i+4].mean()
        rise = 20*np.log10((post+1e-7)/(pre+1e-7))
        sustained = np.quantile(ev[i:i+4],.25) > max(pre*1.3,np.quantile(ev,.5)*.65)
        if rise >= 4 and post-pre > ev.max()*.12 and sustained:
            rises.append((rise*(post-pre),float(t)))
    drop = None
    if rises:
        rough = max(rises)[1]
        near = [h for h in hits if abs(h['time']-rough) <= .35]
        drop = min(near,key=lambda h:abs(h['time']-rough))['time'] if near else rough
        nearest = float(bt[np.argmin(abs(bt-drop))])
        if abs(nearest-drop) < .08: drop = nearest
    accent = np.array([onset[min(len(onset)-1,int(t*sr/hop))] for t in bt])
    def meter_score(n):
        means = np.array([accent[p::n].mean() if len(accent[p::n]) else 0 for p in range(n)])
        return float((means.max()-means.mean())/(means.mean()+1e-6)),int(means.argmax())
    s3,_ = meter_score(3); s4,_ = meter_score(4)
    fractions = [(float(np.interp(h['time'],bt,np.arange(len(bt))))%1,h['strength']) for h in hits]
    triple = sum(v for f,v in fractions if min(abs(f-1/3),abs(f-2/3))<.09)/2
    duple = sum(v for f,v in fractions if abs(f-.5)<.09)
    estimate = '6/8' if triple>duple*1.35 and triple>.5 else '3/4' if s3>s4*1.25 and s3>.15 else '4/4'
    chosen = estimate if meter=='auto' else meter
    bar_beats = 3 if chosen=='3/4' else 2 if chosen=='6/8' else 4
    phase = meter_score(bar_beats)[1]
    group = 6 if chosen=='3/4' and phrase_beats==8 else 4 if chosen=='6/8' and phrase_beats==8 else phrase_beats
    notes.append(f'Meter {chosen} is an accent estimate; 3/4 and 6/8 can share accents. Using {bar_beats} editing beats/bar, {group} beats/phrase. Override --meter after listening; 6/8 uses dotted-quarter beats.')
    bars = [round(float(t),6) for t in bt[phase::bar_beats]]
    anchor = drop if drop is not None else float(bt[phase])
    grid = sorted(set([anchor]+[float(t) for t in bt if t > anchor+.08]+[dur]))
    phrases = []
    for i in range(0,len(grid)-1,group):
        pts = grid[i:min(i+group+1,len(grid))]
        if len(pts)<2: continue
        parts,confidence,method = phrase_parts(pts,ev,et,hits)
        values = ev[(et >= pts[0]) & (et < pts[-1])]
        phrases.append(dict(id=len(phrases),start=round(pts[0],6),end=round(pts[-1],6),
            energy=round(float(values.mean()) if len(values) else 0,7),confidence=confidence,method=method,
            suggested_edit=parts,**{p['kind']:dict(start=p['start'],end=p['end']) for p in parts}))
    climax = max(phrases,key=lambda p:p['energy']) if phrases else None
    strong = [float(t) for t,v in zip(bt,accent) if v >= np.quantile(accent,.55) and dur-t >= .35]
    intro_end = drop if drop is not None else 0.
    data = dict(version=2,duration=round(dur,6),bpm=round(bpm,5),detected_bpm=round(detected,5),
        meter=chosen,meter_confidence='low; confirm by ear',bar_beats=bar_beats,phrase_beats=group,
        beats=[round(float(t),6) for t in bt],bars=bars,downbeat_phase=phase,hits=hits,silences=silences,
        energy=energy,drop=drop,intro=dict(start=0.,end=intro_end,
        hits=sorted([h for h in hits if h['time']<intro_end],key=lambda h:-h['strength']),
        gaps=[[a,min(b,intro_end)] for a,b in silences if a<intro_end]),phrases=phrases,
        climax=({k:climax[k] for k in ('id','start','end','energy')} if climax else None),
        ending_hit=round(strong[-1],6) if strong else round(float(bt[-1]),6),
        analysis_limit_seconds=max_seconds,notes=notes)
    data['window'] = recommend_window(data,target_seconds)
    save_json(out/'beatmap.json',data)
    (out/'report.md').write_text('# Music analysis\n\n'+'\n\n'.join(notes)+f'\n\nDrop: {drop}; climax: {data["climax"]}; window: {data["window"]}.\n',encoding='utf-8')
    draw_structure(data,out/'structure.png')
    print(f'{bpm:.2f} BPM | {chosen} | drop={drop} | {len(phrases)} phrases | window={data["window"]}')
    return data


def draw_structure(data,path):
    w,h = 1600,650
    im = Image.new('RGB',(w,h),PAPER); d = ImageDraw.Draw(im)
    x = lambda t:35+t/data['duration']*(w-70)
    label = lambda xy,value,size=18:d.text(xy,value,font=font(size,500),fill=(17,17,17))
    label((35,15),f'{data["bpm"]:.2f} BPM | {data["meter"]} (estimate) | confirm by ear',24)
    vals = data['energy']; maximum = max(v['rms'] for v in vals)
    for a,b in zip(vals,vals[1:]):
        d.line((x(a['time']),250-a['rms']/maximum*155,x(b['time']),250-b['rms']/maximum*155),fill=(17,17,17),width=2)
    for t in data['beats']: d.line((x(t),260,x(t),280),fill=(140,140,140))
    for t in data['bars']: d.line((x(t),260,x(t),300),fill=(17,17,17),width=2)
    for hit in data['hits']: d.line((x(hit['time']),65,x(hit['time']),65+hit['strength']*25),fill=RED)
    for a,b in data['intro']['gaps']: d.rectangle((x(a),315,x(b),330),fill=RED)
    d.rectangle((x(0),345,x(data['intro']['end']),370),outline=RED,width=2)
    label((35,375),'INTRO / gaps above')
    for p in data['phrases']:
        for part,color in zip(p['suggested_edit'],[(191,201,195),RED,(214,207,192)]):
            d.rectangle((x(part['start']),420,x(part['end']),455),fill=color)
        label((x(p['start']),465),f'P{p["id"]} {p["confidence"]:.2f}',13)
    for name,t in [('DROP',data['drop']),('CLIMAX',(data['climax'] or {}).get('start')),('ENDING',data['ending_hit'])]:
        if t is not None:
            d.line((x(t),95,x(t),340),fill=RED,width=2)
            label((min(w-130,x(t)),100 if name=='DROP' else 130 if name=='CLIMAX' else 160),name)
    window = data['window']; d.rectangle((x(window['start']),515,x(window['end']),545),outline=RED,width=3)
    label((35,560),'Curve: 0.25s RMS | ticks: beats/bars | phrase: swell / chop / breath | outline: window')
    label((35,595),'Low-confidence phrase = 2:1:1 fallback. Meter and drop are suggestions.')
    im.save(path)


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--phrase-beats',type=int,default=8)
    p.add_argument('--max-seconds',type=float,default=600)
    p.add_argument('--target-seconds',type=float,default=30)
    p.add_argument('--meter',choices=['auto','4/4','3/4','6/8'],default='auto')
    a = p.parse_args(); analyze(a.source,a.out,a.phrase_beats,a.max_seconds,a.target_seconds,a.meter)
