"""Stream-concatenate opening/body/ending and mux local music. Optional explicit
freeze insertion duplicates an integral beat block of the same music at the same
time. Outputs MP4 plus an edit report; temporary media is cleaned automatically.
"""
import argparse
from pathlib import Path
import tempfile

from common import Reader, Writer, run, duration, video_args, save_json, contact_sheet, Beats, load_json, protect_inputs, resolve, video_options


def assemble(parts,music,out,w=360,h=640,fps=25,insert_at=None,insert_beats=0,bpm=120,beatmap=None,
             music_start=0,music_seconds=None,shutdown_seconds=0,audio_fade_out=0):
    protect_inputs(out,[*parts,music])
    if insert_beats<0 or int(insert_beats)!=insert_beats:
        raise ValueError('insert-beats must be a whole positive number, or zero')
    lengths=[round(duration(p)*fps) for p in parts]; base_total=sum(lengths)
    if not base_total:
        raise ValueError('Input videos have no frames')
    insert_frame=None; hold=0; block=0; block_start=0
    if insert_beats:
        if insert_at is None:
            raise ValueError('--insert-at is required for a freeze insertion')
        if beatmap:
            grid=Beats(load_json(beatmap),bpm)
            if not grid.points:
                raise ValueError('Beatmap needs beat timestamps for insertion')
            bi=min(range(len(grid.points)),key=lambda i:abs(grid.points[i]-insert_at))
            block_start=grid.sec(bi); block=grid.sec(bi+insert_beats)-block_start
        else:
            if bpm<=0:
                raise ValueError('bpm must be positive')
            block_start=round(insert_at*bpm/60)*60/bpm; block=insert_beats*60/bpm
        insert_frame=round(block_start*fps); hold=round(block*fps)
        if not 0<insert_frame<base_total or hold<1:
            raise ValueError('Insertion must fall inside the assembled video')
        if abs(hold/fps-block)>.5/fps+1e-9:
            raise ValueError('Insertion cannot be quantized to this fps')
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    total=(base_total+hold)/fps
    audio_needed=music_seconds if music_seconds is not None else base_total/fps
    if music_start<0 or duration(music)+.5/fps<music_start+audio_needed or (insert_beats and block_start+block>duration(music)):
        raise ValueError('Music too short; choose a valid integral-beat source block or longer track')
    with tempfile.TemporaryDirectory(prefix='nobody-assemble-') as tmp:
        silent=Path(tmp)/'silent.mp4'; edited=Path(tmp)/'music.wav'
        if music_start or music_seconds is not None or shutdown_seconds:
            if insert_beats: raise ValueError('Window configuration cannot also insert beats')
            filters=f'atrim=start={music_start}:duration={audio_needed},asetpts=PTS-STARTPTS'
            if audio_fade_out:
                filters+=f',afade=t=out:st={max(0,audio_needed-audio_fade_out)}:d={audio_fade_out}'
            filters+=f',apad,atrim=duration={base_total/fps}'
            windowed=Path(tmp)/'window.wav'
            run(['-i',music,'-vn','-af',filters,windowed])
            music=windowed
        count=0; previous=None
        with Writer(silent,w,h,fps) as writer:
            for path,n in zip(parts,lengths):
                with Reader(path,0,n,w,h,fps) as reader:
                    for _ in range(n):
                        frame=reader.read()
                        if count==insert_frame:
                            for _ in range(hold):
                                writer.write(previous)
                        writer.write(frame); previous=frame; count+=1
        if hold:
            # Insert a copy of the following N-beat audio block and then resume
            # the original at the same point. Padding only covers <= half a frame.
            a=insert_frame/fps; b=block_start+block
            filt=(f'[0:a]asplit=3[a][b][c];[a]atrim=end={a},asetpts=PTS-STARTPTS[x];'
                  f'[b]atrim=start={block_start}:end={b},asetpts=PTS-STARTPTS,apad,atrim=duration={hold/fps}[y];'
                  f'[c]atrim=start={a},asetpts=PTS-STARTPTS[z];[x][y][z]concat=n=3:v=0:a=1[out]')
            run(['-i',music,'-filter_complex',filt,'-map','[out]',edited])
            audio=edited
        else:
            audio=music
        run(['-i',silent,'-i',audio,'-map','0:v:0','-map','1:a:0','-t',total,
             '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',out])
    report=dict(frames=base_total+hold,fps=fps,duration=total,insert_frame=insert_frame,
                inserted_frames=hold,music_block_start=block_start,music_block_seconds=block,
                music_start=music_start,music_seconds=audio_needed,shutdown_seconds=shutdown_seconds)
    save_json(out.with_suffix('.assembly.json'),report)
    contact_sheet(out,out.with_suffix('.sheet.png'),fps=fps)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('parts',nargs='+',type=Path,help='Silent parts in playback order')
    p.add_argument('--music',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--insert-at',type=float,help='Explicitly requested freeze time, snapped to nearest beat')
    p.add_argument('--insert-beats',type=int,default=0,help='Number of whole beats to freeze and duplicate in audio')
    p.add_argument('--bpm',type=float,default=120)
    p.add_argument('--beatmap',type=Path,help='Use actual beat intervals for insertion')
    video_args(p); a=p.parse_args()
    if len(a.parts)==1 and a.parts[0].suffix.lower()=='.json':
        path=a.parts[0]; cfg=load_json(path)
        print(assemble([resolve(path.parent,x) for x in cfg['parts']],resolve(path.parent,cfg['music']),a.out,
            *video_options(cfg,a),
            music_start=cfg.get('music_start',0),music_seconds=cfg.get('music_seconds'),
            shutdown_seconds=cfg.get('shutdown_seconds',0),audio_fade_out=cfg.get('audio_fade_out',0)))
    else:
        if a.music is None: p.error('--music is required without assemble.json')
        print(assemble(a.parts,a.music,a.out,a.width,a.height,a.fps,a.insert_at,a.insert_beats,a.bpm,a.beatmap))
