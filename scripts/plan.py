"""Beatmap + role-tagged picks + optional style -> four runnable configs and plan.md.

No fixed song timings: window, hits, phrases and climax own the edit. Media is
read-only. Refuse exhausted approved ranges rather than loop/repeat/freeze them.
Run with --music to bind assemble.json to a local track (or set style.music).
"""
import argparse
import os
from pathlib import Path

import numpy as np
from common import load_json, save_json, duration, resolve
from analyze_music import recommend_window
from styles import NAMES

ROLES = ('before', 'process', 'after', 'enter', 'profile', 'hero', 'detail', 'exit')


def relative(path, base):
    try:
        return os.path.relpath(Path(path).resolve(), Path(base).resolve()).replace(os.sep, '/')
    except ValueError:  # Windows cross-volume source, only in private configs
        return Path(path).resolve().as_posix()


class Pool:
    """Reserve disjoint intervals by physical file, including overlapping picks.

    Hero/star preference applies after role matching. Grid clocks also consume
    hidden intervals. Reuse is allowed only at unused source seconds, never by
    resetting an alias. A picked interval is a permission boundary, not merely
    a hint that the rest of a long recording may be used.
    """
    def __init__(self, picks, base):
        self.picks = []; self.used = {}; self.sources = {}; self.reservations = []; self.notes = []
        metadata = {}
        for i, p in enumerate(picks):
            if p.get('selected', True) is False: continue
            role = p.get('role', 'process')
            if role not in ROLES: raise ValueError(f'Unknown pick role: {role}')
            path = resolve(base, p.get('path', p.get('file', '')))
            if not path.is_file(): raise ValueError(f'Missing pick file: {path.name}')
            if path.suffix.lower() not in ('.mp4','.mov','.mkv','.avi','.m4v','.webm'):
                raise ValueError('Only real local video picks are accepted')
            if path not in metadata: metadata[path] = duration(path)
            start = float(p.get('start', p.get('t', 0)))
            length = float(p.get('duration', p.get('candidate_duration', p.get('clip_len', 1.6))))
            end = min(metadata[path], start+length)
            if start < 0 or end <= start: raise ValueError('Invalid approved pick range')
            self.picks.append(dict(p, id=str(p.get('id', f'P{i}')), role=role, path=path,
                                   start=start, end=end, hero=bool(p.get('hero', role=='hero'))))
        if not self.picks: raise ValueError('No selected video picks')

    def available(self, p):
        spans = [(p['start'], p['end'])]
        for a, b in sorted(self.used.get(p['path'], [])):
            spans = [(x, min(a,y)) for x,y in spans if x < min(a,y)] + [
                     (max(b,x),y) for x,y in spans if max(b,x) < y]
        return spans

    def take(self, roles, seconds, out, fallback=True):
        ordered = sorted(self.picks, key=lambda p:(p['role'] not in roles,
            roles.index(p['role']) if p['role'] in roles else 99,
            -int(p.get('hero', False)), -float(p.get('star', p.get('rating', 0))),
            sum(b-a for a,b in self.used.get(p['path'], []))))
        for p in ordered:
            if not fallback and p['role'] not in roles: continue
            for a, b in self.available(p):
                if b-a+.00001 < seconds: continue
                end = a+seconds
                self.used.setdefault(p['path'], []).append((a, end))
                alias = f'S{len(self.sources)+1:04d}'
                self.sources[alias] = dict(path=relative(p['path'],out), start=round(a,6),
                    x_offset=p.get('x_offset',0), pick_id=p['id'], role=p['role'],
                    allow_zoom=bool(p.get('allow_zoom',False)), freeze=bool(p.get('freeze',False)))
                self.reservations.append(dict(alias=alias,pick=p['id'],path=relative(p['path'],out),
                                              start=a,end=end,requested_roles=list(roles)))
                if p['role'] not in roles:
                    note=f'没有足够长的未用 {"/".join(roles)} 片段，暂用 {p["role"]}（{p["id"]}），请复核角色和内容。'
                    if note not in self.notes: self.notes.append(note)
                return alias
        raise ValueError(f'No unused approved {"/".join(roles)} interval of {seconds:.2f}s. '
                         'Select more footage or extend reviewed pick.duration; never loop a used interval.')


def plan(beatmap, picks, out, style=None, music=None):
    beatmap = Path(beatmap).resolve(); picks = Path(picks).resolve()
    out = Path(out).resolve(); cfg = load_json(style) if style else {}
    bm = load_json(beatmap); raw = load_json(picks)
    rows = raw.get('picks', raw) if isinstance(raw, dict) else raw
    if isinstance(rows, dict): rows = [dict(v,id=k) for k,v in rows.items()]
    pool = Pool(rows,picks.parent)
    fps = int(cfg.get('fps',25)); w = int(cfg.get('width',360)); h = int(cfg.get('height',640))
    if fps <= 0 or min(w,h) <= 0 or w%2 or h%2: raise ValueError('Positive fps/even dimensions required')
    selected = cfg.get('styles',['mono_m3','dots3','thermal_silhouette'])
    if not selected or any(s not in NAMES for s in selected): raise ValueError(f'Choose styles from {NAMES}')
    accent = cfg.get('accent_color',[255,59,31])
    if isinstance(accent,str): accent = list(bytes.fromhex(accent.lstrip('#')))
    if len(accent)!=3 or any(not 0<=int(v)<=255 for v in accent): raise ValueError('accent_color must be RGB or hex')
    window = recommend_window(bm,float(cfg['target_seconds'])) if 'target_seconds' in cfg else bm['window']
    ws,we = float(window['start']),float(window['end'])
    beats = np.array(bm['beats'],float)
    if len(beats)<2 or np.any(np.diff(beats)<=0): raise ValueError('Need increasing beat timestamps')
    if ws<0 or we>bm['duration']+.00001 or we-ws<8: raise ValueError('Choose a valid music window of at least 8 seconds')
    # Quantize absolute music-relative boundaries ONCE, then subtract frame
    # origins. Independently rounding each rendered part accumulates drift.
    total = round((we-ws)*fps)
    frame = lambda t:max(0,min(total,round((float(t)-ws)*fps)))
    sec = lambda f:ws+f/fps
    snap = lambda t:float(beats[np.argmin(abs(beats-float(t)))])
    beat_frames = sorted(set(frame(t) for t in beats if ws <= t <= we))
    notes = []
    drop = bm.get('drop')
    real_intro = drop is not None and ws < drop < we
    if real_intro:
        opening_end = frame(drop)
        if drop-ws<2: notes.append('前奏不足两秒：压缩为 3–5 个真实重击事件，不虚构拍点。')
    else:
        # No drop / window begins after it: first two local bars are the intro.
        n = 2*int(bm.get('bar_beats',4))
        local = [t for t in beats if t>=ws]
        opening_end = frame(local[min(n,len(local)-1)])
        notes.append('窗口内没有可用前奏：用前两小节开场，在边界处安排进场。')
    opening_end = max(1,min(opening_end,total-round(5*fps)))
    # Last 1–2 beats own the word explosion. Prefer the supplied last strong
    # beat if it lies in that tail; otherwise take the nearest valid tail beat.
    tail = [f for f in beat_frames if total-2.15*60/bm['bpm']*fps <= f <= total-.7*60/bm['bpm']*fps]
    ending_start = min(tail,key=lambda f:abs(sec(f)-bm.get('ending_hit',we))) if tail else total-round(60/bm['bpm']*fps)
    ending_start = max(opening_end+round(3*fps),min(ending_start,total-1))
    end_seconds = (total-ending_start)/fps
    # Slots follow actual intro hits, with quiet ranges replacing the image
    # by a question/cursor page. Rank only affects visual emphasis, not timing.
    intro_hits = [v for v in bm.get('hits',[]) if ws <= v['time'] < sec(opening_end)]
    short_intro = real_intro and sec(opening_end)-ws<2
    if short_intro:
        intro_hits = sorted(sorted(intro_hits,key=lambda v:-v['strength'])[:4],key=lambda v:v['time'])
    elif intro_hits:
        heavy = max(.3,float(np.quantile([v['strength'] for v in intro_hits],.6)))
        intro_hits = [v for v in intro_hits if v['strength']>=heavy]
    marks = {0:dict(strength=0.)}
    for v in intro_hits: marks[frame(v['time'])] = dict(v)
    gaps = bm.get('intro',{}).get('gaps',[]) if real_intro else bm.get('silences',[])
    for a,b in ([] if short_intro else gaps):
        if b>ws and a<sec(opening_end):
            marks[frame(max(a,ws))] = dict(quiet=True)
            if b<sec(opening_end): marks[frame(b)] = dict(strength=0.)
    marks = {f:m for f,m in marks.items() if f<opening_end}
    top = sorted((m.get('strength',0) for m in marks.values()),reverse=True)[:3]
    threshold = min(top) if top else 1
    slots = []; description = []
    keys = sorted(marks)
    for i,a in enumerate(keys):
        b = keys[i+1] if i+1<len(keys) else opening_end
        s = dict(at=a/fps,accent_color=accent)
        if marks[a].get('quiet') or (short_intro and any(x<=sec(a)<y for x,y in gaps)):
            s.update(text=cfg.get('question','who am i?')+' |',size=.16,background='paper',static=True)
            view = '静止问题句 + 光标'
        elif i%3==1 and marks[a].get('strength',0)>=threshold:
            s.update(text=cfg.get('opening_word','WHO'),size=.48,background='accent')
            view = '强击：强调色大字'
        else:
            s.update(source=pool.take(['before','profile','hero'],(b-a)/fps,out),
                     style=selected[i%len(selected)] if marks[a].get('strength',0)>=threshold else 'raw')
            view = f'人物 / {s["style"]}'
        slots.append(s); description.append((a,b,view,'intro 重击 / 空隙'))
    # Clip and snap all phrase boundaries to actual detected beats. This also
    # makes low-confidence 2:1:1 boundaries useful without off-beat cuts.
    phrases = []
    for p in bm['phrases']:
        a,b = max(opening_end,frame(p['start'])),min(ending_start,frame(p['end']))
        if b<=a: continue
        parts = []
        for kind in ('swell','chop','breath'):
            part = p.get(kind) or next(v for v in p['suggested_edit'] if v['kind']==kind)
            x,y = max(a,frame(snap(part['start']))),min(b,frame(snap(part['end'])))
            if y>x: parts.append((x,y,kind))
        phrases.append(dict(start=a,end=b,parts=parts,original=p))
    if not phrases: raise ValueError('No body phrases in music window')
    # Pad any uncovered prefix/suffix with continuous video, never black frames.
    base = [(opening_end,ending_start,'swell',0)]
    for i,p in enumerate(phrases):
        base.extend((a,b,k,i) for a,b,k in p['parts'])
    climax_end = (bm.get('climax') or {}).get('end',we)
    reversal = next((p['start'] for p in phrases if sec(p['start'])>=climax_end-.5/fps),None)
    if reversal is None: notes.append('窗口内高潮之后没有下一乐句：暂不虚构反转；请延长或调整窗口，才能揭开变化后的画面。')
    # A grid owns >=2 seconds and ends at a phrase breath/end. Borrow backwards
    # from chop/swell if breath is too short. Never stretch or freeze video.
    grid_count = 2 if total/fps>=25 else 1
    candidates = []
    for p in phrases:
        b = p['end']
        breath = next((a for a,y,k in p['parts'] if k=='breath'),b)
        # A fast 6/8 phrase can itself be <2s. Borrow across the preceding
        # phrase too, while keeping at least one beat of the drop/entry visible.
        options = [f for f in beat_frames if opening_end+60/bm['bpm']*fps-.5<=f<=min(b-2*fps,breath)
                   and (reversal is None or not f<reversal<b)]
        if options: candidates.append((max(options),b,p))
    if not candidates: raise ValueError('Body too short for a two-second live grid plus entry')
    final = next((g for g in reversed(candidates) if g[2] is not phrases[-1]),candidates[-1])
    chosen = [final]
    if grid_count==2:
        options = [g for g in candidates if g[1]<=final[0] or g[0]>=final[1]]
        if not options: raise ValueError('Body too short for two non-overlapping live grids')
        chosen = [min(options,key=lambda g:abs((g[0]+g[1])/2-total*.5)),final]
    grids = [(a,b,g is final) for g in sorted(chosen,key=lambda g:g[0]) for a,b,_ in [g]]
    boundaries = {opening_end,ending_start}
    for a,b,_,_ in base: boundaries.update([a,b])
    for a,b,_ in grids: boundaries.update([a,b])
    if reversal is not None: boundaries.add(reversal)
    # Merge grid intervals, preserving a single reservation and reveal clock.
    boundaries = sorted(f for f in boundaries if opening_end<=f<=ending_start and
                        not any(a<f<b for a,b,_ in grids))
    segments = []; style_index = 0
    for a,b in zip(boundaries,boundaries[1:]):
        if b<=a: continue
        grid = next((g for g in grids if g[0]==a and g[1]==b),None)
        state = 'after' if reversal is not None and a>=reversal else 'before' if a==opening_end else 'process'
        roles = ['enter'] if a==opening_end else [state,'hero','profile','detail']
        kind = next((k for x,y,k,i in reversed(base) if x<=a and b<=y),'swell')
        s = dict(start_frame=a-opening_end,end_frame=b-opening_end,accent_color=accent)
        seconds = (b-a)/fps
        if grid:
            # Flip only after the climax reversal; earlier recap grids remain
            # narrative-safe. Reveal always lasts the first quarter.
            final_flip = grid[2] and reversal is not None and a>=reversal
            grid_roles = ['process','before'] if final_flip else [state,'process','before']
            tiles = [pool.take(grid_roles,seconds,out) for _ in range(9)]
            s.update(type='grid',n=3,tiles=tiles,mode='reveal',reveal_frames=max(1,(b-a)//4),
                     tile_styles=['raw']*9)
            if final_flip:
                s['flip_to'] = [pool.take(['after'],seconds,out,fallback=False) for _ in range(9)]
                s['flip_frames'] = max(1,(b-a)//4); s['flip_after_reveal'] = True
            view = '九宫格终局：逐格亮起 / after 翻面' if s.get('flip_to') else '九宫格回顾：逐格亮起，九格持续运动'
        else:
            if a==reversal:
                # Prefer a genuine exit/wipe; otherwise expose after with a
                # graphic wipe over real video. No face synthesis or zoom.
                try:
                    alias = pool.take(['exit'],seconds,out,fallback=False)
                    view = '反转：真实离场 / 擦除揭开'
                except ValueError:
                    alias = pool.take(['after'],seconds,out)
                    view = '反转：after 连贯镜头 + 擦除扫描线'
                s.update(type='clip',source=alias,style='raw',wipe=True)
            else:
                alias = pool.take(roles,seconds,out)
            if a==reversal:
                pass
            elif kind=='chop':
                # Subdivide real beat intervals into quarters; one source
                # reader advances throughout, >= half cuts stay raw.
                points = sorted(set([a]+[frame(t) for t in beats if a<frame(t)<b]+[b]))
                cut_frames = sorted(set(round(x+(y-x)*q/4)-a for x,y in zip(points,points[1:]) for q in range(4)))
                cuts = []
                for n,f in enumerate(cut_frames):
                    if f>=b-a: continue
                    style_name = 'raw' if n%2==0 else selected[style_index%len(selected)]
                    if n%2: style_index+=1
                    cuts.append(dict(frame=f,style=style_name))
                s.update(type='chop',source=alias,cuts=cuts)
                view = f'{state} 连续动作快切（至少半数原片）'
            else:
                hero = pool.sources[alias]['role']=='hero' or next(p for p in pool.picks if p['id']==pool.sources[alias]['pick_id']).get('hero')
                s.update(type='hero' if kind=='swell' and hero and a!=opening_end else 'clip',source=alias,style='raw',magnifier=False)
                view = 'DROP / 最佳进场' if a==opening_end else f'{state} / {"连贯英雄镜头" if s["type"]=="hero" else "安静连贯画面" if kind=="breath" else "连贯动作"}'
        segments.append(s); description.append((a,b,view,f'{kind} / 拍点对齐'))
    out.mkdir(parents=True,exist_ok=True)
    video = dict(width=w,height=h,fps=fps)
    opening = dict(beatmap=relative(beatmap,out),duration=opening_end/fps,sources=pool.sources,slots=slots,**video)
    timeline = dict(bpm=bm['bpm'],sources=pool.sources,segments=segments,**video)
    # Source is a real last body frame; subsequent dots are an explicit graphic
    # animation, never an unauthorized held human shot.
    ending = dict(source='body.mp4',at=max(0,(ending_start-opening_end-1)/fps),
                  word=cfg.get('ending_word','nobody.'),duration=end_seconds,
                  shutdown=bool(cfg.get('shutdown',False)),shutdown_seconds=1.,**video)
    track = music or cfg.get('music')
    if track is None:
        track = 'music.wav'
        notes.append('尚未指定音乐文件：请将原曲放在 assemble.json 旁命名为 music.wav，或显式指定音乐路径。')
    elif not music: track = resolve(Path(style).parent,track)
    assembly = dict(parts=['opening.mp4','body.mp4','ending.mp4'],music=relative(track,out) if music or cfg.get('music') else track,
                    music_start=ws,music_seconds=total/fps,audio_fade_out=.2,
                    shutdown_seconds=1. if ending['shutdown'] else 0.,**video)
    description.append((ending_start,total,'点阵爆炸 → '+ending['word'],'末 1–2 拍 / ending_hit'))
    if ending['shutdown']: description.append((total,total+fps,'电视关机','额外 1 秒 / 音乐衰减'))
    notes.extend(pool.notes)
    for name,data in [('opening',opening),('timeline',timeline),('ending',ending),('assemble',assembly)]: save_json(out/f'{name}.json',data)
    save_json(out/'allocation.json',dict(reservations=pool.reservations,window=window,reversal_frame=reversal,
              opening_frames=opening_end,body_end_frame=ending_start,total_music_frames=total,notes=notes))
    md = ['# 自动排片方案','',f'{bm["bpm"]:.2f} BPM · {bm.get("meter","估计拍号")} · 音乐窗口 {ws:.3f}–{we:.3f}s · {fps}fps',
          '', '| 成片时间 | 画面 | 音乐 |','|---|---|---|']
    md += [f'| {a/fps:.2f}–{b/fps:.2f}s | {view} | {sound} |' for a,b,view,sound in sorted(description)]
    md += ['','说明：所有人物来自真实视频；固定裁切，无放大、补帧或默认定格。']+['- '+n for n in notes]
    (out/'plan.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(f'Planned {total/fps:.2f}s: opening {opening_end/fps:.2f}s, body {(ending_start-opening_end)/fps:.2f}s, ending {end_seconds:.2f}s; {len(grids)} live grids -> {out}')
    return dict(opening=opening,timeline=timeline,ending=ending,assemble=assembly)


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--beatmap',type=Path,required=True)
    p.add_argument('--picks',type=Path,required=True)
    p.add_argument('--style',type=Path)
    p.add_argument('--music',type=Path,help='Original local music; overrides style.music')
    p.add_argument('--out',type=Path,required=True,help='Private directory for configs, plan and rendered parts')
    a = p.parse_args(); plan(a.beatmap,a.picks,a.out,a.style,a.music)
