"""Deterministic planner invariants; no personal media, network or encoders needed.

Run: python -m unittest discover -s scripts -p test_plan.py
"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import save_json, load_json
from plan import plan, Pool
from analyze_music import recommend_window


def beatmap(bpm=120,seconds=30,drop=4,meter='4/4'):
    period=60/bpm; beats=[i*period for i in range(int(seconds/period)+1) if i*period<seconds]
    bar=3 if meter=='3/4' else 2 if meter=='6/8' else 4
    phrases=[]; start=drop if drop is not None else 0
    group=6 if meter=='3/4' else 4 if meter=='6/8' else 8
    while start<seconds:
        end=min(seconds,start+group*period); span=end-start
        phrases.append(dict(start=start,end=end,energy=.5,
            swell=dict(start=start,end=start+span*.5),chop=dict(start=start+span*.5,end=start+span*.75),
            breath=dict(start=start+span*.75,end=end)))
        start=end
    return dict(duration=seconds,bpm=bpm,bar_beats=bar,meter=meter,beats=beats,bars=beats[::bar],
        drop=drop,intro=dict(start=0,end=drop or 0,gaps=[]),silences=[],
        hits=[dict(time=t,strength=.9) for t in beats],phrases=phrases,
        climax=dict(start=phrases[1]['start'],end=phrases[1]['end']),ending_hit=beats[-2],
        window=dict(start=0,end=seconds))


class PlannerTests(unittest.TestCase):
    def setup_case(self,root,bm):
        picks=[]
        for role in ['before','process','after','enter','exit','hero','profile','detail']:
            p=root/f'{role}.mp4'; p.touch()
            picks.append(dict(id=role,path=p.name,start=0,duration=300,role=role,hero=role=='hero'))
        save_json(root/'picks.json',picks); save_json(root/'beats.json',bm)
        return root/'beats.json',root/'picks.json',root/'plan'

    def test_tempos_lengths_and_meters(self):
        for bpm in (60,86,120,180):
            for seconds in (15,24,30,60):
                for meter in ('4/4','3/4','6/8'):
                    with self.subTest(bpm=bpm,seconds=seconds,meter=meter), tempfile.TemporaryDirectory() as tmp:
                        root=Path(tmp); args=self.setup_case(root,beatmap(bpm,seconds,None,meter))
                        with patch('plan.duration',return_value=300),contextlib.redirect_stdout(io.StringIO()):
                            result=plan(*args)
                        alloc=load_json(args[2]/'allocation.json'); rows=result['timeline']['segments']
                        self.assertEqual(rows[0]['start_frame'],0)
                        self.assertEqual(rows[-1]['end_frame']+alloc['opening_frames'],alloc['body_end_frame'])
                        self.assertTrue(all(a['end_frame']==b['start_frame'] for a,b in zip(rows,rows[1:])))
                        grids=[s for s in rows if s['type']=='grid']
                        self.assertEqual(len(grids),2 if seconds>=25 else 1)
                        self.assertTrue(all(s['end_frame']-s['start_frame']>=50 for s in grids))
                        if alloc['reversal_frame'] is not None:
                            self.assertIn(alloc['reversal_frame']-alloc['opening_frames'],[s['start_frame'] for s in rows])
                        for s in grids:
                            if s.get('flip_to'):
                                sources=result['timeline']['sources']
                                self.assertTrue(all(sources[k]['role']!='after' for k in s['tiles']))
                                self.assertTrue(all(sources[k]['role']=='after' for k in s['flip_to']))
                        self.assertEqual(result['opening']['sources'][rows[0].get('source',rows[0].get('tiles',[''])[0])]['role'],'enter')
                        ranges=alloc['reservations']
                        self.assertTrue(all(a['path']!=b['path'] or min(a['end'],b['end'])-max(a['start'],b['start'])<1e-6
                                            for i,a in enumerate(ranges) for b in ranges[i+1:]))

    def test_short_intro_and_reversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); args=self.setup_case(root,beatmap(drop=1.5))
            with patch('plan.duration',return_value=300),contextlib.redirect_stdout(io.StringIO()): result=plan(*args)
            self.assertLessEqual(len(result['opening']['slots']),5)
            alloc=load_json(args[2]/'allocation.json'); reversal=alloc['reversal_frame']
            rows=result['timeline']['segments']; sources=result['timeline']['sources']
            self.assertIsNotNone(reversal)
            for s in rows:
                if s['start_frame']+alloc['opening_frames']<reversal:
                    self.assertFalse(s.get('flip_to'))
                    for alias in s.get('tiles',[s.get('source')]):
                        self.assertNotEqual(sources[alias]['role'],'after')

    def test_pool_exhaustion_and_overlapping_picks(self):
        with tempfile.TemporaryDirectory() as tmp,patch('plan.duration',return_value=20):
            root=Path(tmp); (root/'input.mp4').touch()
            pool=Pool([dict(id='A',path='input.mp4',role='process',start=0,duration=3),
                       dict(id='B',path='input.mp4',role='process',start=1,duration=3)],root)
            pool.take(['process'],2,root); pool.take(['process'],2,root)
            with self.assertRaisesRegex(ValueError,'No unused approved'): pool.take(['process'],.1,root)

    def test_long_window_bar_and_target(self):
        data=beatmap(seconds=120,drop=52); data['climax']=dict(start=60,end=64)
        window=recommend_window(data,30)
        self.assertIn(window['start'],data['bars']); self.assertEqual(window['end']-window['start'],30)
        self.assertLessEqual(window['start'],52); self.assertGreater(window['end'],60)


if __name__=='__main__': unittest.main()
