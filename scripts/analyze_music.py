"""Analyze a local song or video audio track into beatmap.json and structure.png:
BPM, beats, estimated 4/4 bar lines, strong onsets, silence and phrase suggestions.
Signals are heuristic; listen and correct drop/phrase labels before editing.
"""
import argparse
from pathlib import Path
import tempfile

import librosa
import numpy as np
from PIL import Image, ImageDraw
from common import run, save_json, font, PAPER, RED


def analyze(source,out,phrase_beats=8,max_seconds=600):
    if phrase_beats<1 or max_seconds<=0:
        raise ValueError('Positive phrase length and analysis limit required')
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    # Decode audio through ffmpeg, including compressed reference-video soundtracks.
    with tempfile.TemporaryDirectory(prefix='nobody-audio-') as tmp:
        wav=Path(tmp)/'analysis.wav'
        run(['-i',source,'-t',max_seconds,'-vn','-ac','1','-ar','22050',wav])
        y,sr=librosa.load(wav,sr=22050,mono=True)
    dur=len(y)/sr; hop=256
    if dur<1 or np.max(np.abs(y))<1e-7:
        raise ValueError('Audio is silent or shorter than one second')
    onset=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    tempo,bf=librosa.beat.beat_track(onset_envelope=onset,sr=sr,hop_length=hop,tightness=120)
    bpm=float(np.atleast_1d(tempo)[0])
    if bpm<=0 or len(bf)<2:
        raise ValueError('No reliable beat grid detected; supply a manually corrected beatmap')
    bt=librosa.frames_to_time(bf,sr=sr,hop_length=hop)
    spec=np.abs(librosa.stft(y,hop_length=hop,n_fft=2048))
    freq=librosa.fft_frequencies(sr=sr,n_fft=2048)
    low=spec[(freq>=30)&(freq<150)].sum(axis=0)
    strength=np.array([low[max(0,b-2):b+3].max() for b in bf])
    phase=int(np.argmax([strength[p::4].mean() if len(strength[p::4]) else 0 for p in range(4)]))
    peaks=librosa.util.peak_pick(onset,pre_max=6,post_max=6,pre_avg=40,post_avg=40,
                                delta=max(.01,onset.std()*.7),wait=8)
    ts=librosa.times_like(onset,sr=sr,hop_length=hop)
    hits=[dict(time=round(float(ts[p]),6),strength=round(float(onset[p]/max(onset.max(),1e-6)),3)) for p in peaks if ts[p]<dur]
    rms=librosa.feature.rms(y=y,hop_length=hop)[0]
    tr=librosa.times_like(rms,sr=sr,hop_length=hop)
    db=20*np.log10(rms+1e-9)
    quiet=db<max(-60,float(np.median(db)-18))
    silences=[]; begin=None
    for i,q in enumerate(np.r_[quiet,False]):
        time=min(dur,i*hop/sr)
        if q and begin is None:
            begin=time
        if not q and begin is not None:
            if time-begin>=.12:
                silences.append([round(begin,4),round(time,4)])
            begin=None
    harmonic,percussive=librosa.effects.hpss(y)
    phrases=[]
    for i in range(phase,len(bt),phrase_beats):
        start=float(bt[i]); end=float(bt[min(i+phrase_beats,len(bt)-1)]) if i+phrase_beats<len(bt) else dur
        a,b=int(start*sr),int(end*sr)
        hr=float(np.sqrt(np.mean(harmonic[a:b]**2))) if b>a else 0
        pr=float(np.sqrt(np.mean(percussive[a:b]**2))) if b>a else 0
        energy=float(np.sqrt(np.mean(y[a:b]**2))) if b>a else 0
        label='breath' if energy<np.median(rms)*.6 else 'swell' if hr>pr*1.25 else 'chop'
        length=end-start
        phrases.append(dict(start=round(start,4),end=round(end,4),suggestion=label,
            suggested_edit=[dict(kind='swell',start=round(start,4),end=round(start+length*.5,4)),
                            dict(kind='chop',start=round(start+length*.5,4),end=round(start+length*.75,4)),
                            dict(kind='breath',start=round(start+length*.75,4),end=round(end,4))]))
    outdata=dict(version=1,duration=round(dur,6),bpm=round(bpm,4),meter='4/4 (estimate)',
        beats=[round(float(t),6) for t in bt],downbeat_phase=phase,
        bars=[round(float(t),6) for t in bt[phase::4]],hits=hits,silences=silences,phrases=phrases,
        analysis_limit_seconds=max_seconds,notes='Estimated beat/downbeat/phrase grid. Confirm by ear; suggested_edit is the nobody pattern, not a transcription.')
    save_json(out/'beatmap.json',outdata)
    w,h=1600,460; im=Image.new('RGB',(w,h),PAPER); d=ImageDraw.Draw(im)
    d.text((30,20),f'{bpm:.1f} BPM | {dur:.2f}s | estimated 4/4 | listen & correct',font=font(24,600),fill=(17,17,17))
    def x(t): return 30+t/dur*(w-60)
    for i in range(1,len(rms)):
        d.line((x(tr[i-1]),260-min(180,rms[i-1]*450),x(tr[i]),260-min(180,rms[i]*450)),fill=(17,17,17))
    for t in bt:
        d.line((x(t),270,x(t),295),fill=(120,120,120))
    for t in bt[phase::4]:
        d.line((x(t),270,x(t),330),fill=(17,17,17),width=2)
    for hit in hits:
        d.line((x(hit['time']),75,x(hit['time']),100),fill=RED,width=2)
    for a,b in silences:
        d.rectangle((x(a),340,x(b),355),fill=RED)
    d.text((30,385),'top: strong hits | curve: RMS | short: beats | long: bars | red: quiet gaps',font=font(20,500),fill=(17,17,17))
    im.save(out/'structure.png')
    print(f'{bpm:.2f} BPM, {len(bt)} beats, {len(hits)} strong hits, {len(phrases)} estimated phrases')
    return outdata


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--phrase-beats',type=int,default=8,help='8 beats is about four seconds at 120 BPM')
    p.add_argument('--max-seconds',type=float,default=600,help='Bound audio memory; analyze this many seconds')
    a=p.parse_args(); analyze(a.source,a.out,a.phrase_beats,a.max_seconds)
