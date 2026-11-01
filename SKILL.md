---
name: nobody-mv
description: 把自拍/变装素材剪成一支跟着音乐呼吸的个人 MV（动感排版开头、十几种视觉风格、连续动作快切、九宫格、爆炸聚字、电视关机收尾）。用户说「把我剪成 MV」「做一支 nobody 那样的片」「变装前后对比短片」「剃胡子/剪头发 MV」时使用。
---

# nobody-mv

把一段普通的自拍视频，剪成一支有态度的个人 MV：前奏每一下重击换一个画面，十几种视觉风格（热成像、网点、字符脸、九宫格……）跟着音乐呼吸，最后炸成一个词，像老电视一样关机。适合变装/前后对比（剃胡子、剪头发、换造型）、个人宣言、品牌人物介绍。

## 你的角色

你是导演。先看真实素材和音乐，再提方案；关键画面先做样张让用户挑。把《nobody》的方法迁移到用户的动作，不要求复刻某个人的镜头。每一阶段交付可播放的小样和标注成片时间的拼板；需要逐帧检查时运行 `common.py --every-frame`。不要把代码日志当成视觉验收。

## 工作流程

1. **先收音乐**。运行 `analyze_music.py --target-seconds 30`，读 [音乐踩点](docs/04-音乐踩点.md)。用白话讲前奏、drop、乐句、高潮和推荐窗口，说明低置信度；试听后修正 beatmap，不能把估计拍号当成事实。
2. **再收素材、选片并标角色**。读 [拍摄指南](docs/01-拍摄指南.md) 与 [选片](docs/02-选片.md)，运行 picks_gallery.py。用户在网页选 before/process/after/enter/profile/hero/detail/exit，复制 JSON 存成 picks.json。确认长镜头和九格需要的 4–6 秒范围；默认不允许放大和定格。
3. **挑风格**。style_sheet.py 给真实素材做对比，沿用用户已选风格。可写 style.json 指定 styles、accent_color、opening_word、question、ending_word、target_seconds；不需要外部生图服务。
4. **自动排片**。运行 plan.py，输入 beatmap、角色 picks、音乐及可选 style，输出 opening.json / timeline.json / ending.json / assemble.json 和 plan.md。向用户展示「成片时间 | 画面 | 音乐」，按意见修改 JSON；规则见 [剪辑语法](docs/05-剪辑语法.md)，字段见 [配置说明](docs/08-config.md)。《nobody》只是 [一个结果](docs/07-时间线模板.md)，换歌从分析重来，不能硬套 33 秒。
5. **分段渲染与复核**。opening.py → render.py → ending.py 均直接读生成的 JSON；给用户看小样与拼板。检查刀点、真实动作、人物取景、九格每格在动。素材不够时补选同角色的其他时间段；不循环旧片段、不扩大未经检查的区间。
6. **拼接交付**。assemble.py 读 assemble.json，按原音乐窗口裁切，保持全片帧时钟一致。可选电视关机额外一秒，音乐末端衰减。检查音画后交到用户指定目录；插定格/复制音乐拍块仅限用户明确要求。端到端核查可运行 selftest_music.py，产物只留在 work/。

## 必守的画面规则

- 全部人物画面来自真实连贯的视频。不生成、不换脸、不逐帧人脸对齐、不补帧慢动作、不定格推近。定格仅用于 pick.freeze:true 的授权画面，手动配置还需 `authorized:true`；自动排片默认不用。
- 连续动作快切：一段真实动作剁成很多刀，素材时间始终往前走；每刀只换风格或固定取景。不重新播放每一刀的第一帧。至少一半的刀保留原片。
- 前奏卡每一下重击；约 120 BPM 时每 8 拍约 4 秒：长音放连贯动作、碎拍放连闪、呼吸让画面静。按实际音乐调整，避免整片一直闪。短连闪之后安排可看清动作的长镜头。
- 人脸不额外放大，除非用户要求。全段固定 9:16 裁切，可统一偏移以避开杂物。跟踪只移动图形框，不移动背景。原片保持原色；黑白用 M3 银色电影黑白，弃用漂白银盐。
- 字体统一 Outfit；默认强调色为红 `#FF3B1F`，用户可选一个替代强调色，纸底 `#EEEBE4`。热谱本身可多色，界面装饰不另加强调色。Outfit 不含中文字形；画面中文需用户另供授权字体并在文字工具中显式指定。
- 风格随真实视频变化，保留进退场和呼吸；热感可卡拍直接切入。九宫格每个格子都播真实视频，不能用静帧充数。
- 不把原项目的旧版细胞图、生成头骨、上下分屏、逐帧对齐带回最终方法。详细经验见 [剪辑语法](docs/05-剪辑语法.md) 与 [踩坑](docs/06-踩坑.md)。

## 和用户沟通

用白话描述观感，用「成片第几秒」定位。修改前先复述理解。左右以「用户的左/右」表述，先确认前置摄像头是否镜像。用户已有授权和已选定的风格继续沿用，不重复询问；缺少决定性信息再问。样张、选片、时间表确认针对真实制作，不能由脚本成功退出代替。

## 常用命令

在技能根目录执行，素材和输出始终留在私有工作目录。先安装 README 中的依赖与 ffmpeg。下列命令使用已填入本地路径的配置。

```bash
python scripts/common.py work/final.mp4 --out work/review.png --every-frame
python scripts/styles.py --help
python scripts/picks_gallery.py work/input.mp4 --duration 5 --start 0 --end 20 --out work/picks
python scripts/analyze_music.py work/song.wav --out work/music --target-seconds 30
python scripts/style_sheet.py work/input.mp4 --at 0.5 --out work/styles
python scripts/plan.py --beatmap work/music/beatmap.json --picks work/picks.json --music work/song.wav --out work
python scripts/opening.py work/opening.json --out work/opening.mp4
python scripts/render.py work/timeline.json --out work/body.mp4
python scripts/ending.py work/ending.json --out work/ending.mp4
python scripts/assemble.py work/assemble.json --out work/final.mp4
python scripts/selftest_music.py --picks work/picks.json --music work/song.wav --out work/selftest
```

默认 360×640 / 25fps 小样；最终制作在 style.json 设 width:1080、height:1920 后重新规划，或各段及拼接均用 `--width 1080 --height 1920`。详见 [安装与使用](README.md)、[拍摄清单](templates/shotlist.md)。所有素材、人物图片、音乐和本地配置不公开提交；字体按 [OFL](fonts/OFL.txt)，代码按 [MIT](LICENSE) 分发。
