# nobody-mv

把一段普通的自拍视频，剪成一支有态度的个人 MV：前奏每一下重击换一个画面，十几种视觉风格（热成像、网点、字符脸、九宫格……）跟着音乐呼吸，最后炸成一个词，像老电视一样关机。

适合变装/前后对比（剃胡子、剪头发、换造型）、个人宣言和品牌人物介绍。这是从一支约 33 秒个人 MV 中提炼的公开 Skill：给 AI 的导演手册、给人的操作说明，以及可以独立运行的 Python 工具。仓库仅分发代码、文档、配置模板和有授权的 Outfit 字体；效果样张由你用自己的素材在本地生成。

## 它是怎么工作的

音乐决定结构，真实素材按角色填进去。换歌后重新分析并自动排片，不用手工重排每一拍。

```mermaid
flowchart LR
  A[用户提供音乐] --> B[节拍结构：前奏 / drop / 乐句 / 高潮]
  B --> C[plan.py 自动排片]
  P[真实视频：选片并标角色] --> C
  S[用户选择风格] --> C
  C --> D[plan.md 确认与修改]
  D --> E[渲染开头 / 正片 / 结尾]
  E --> F[拼接音乐窗口，交付成片]
```

## 画面方法

真实视频 → 重击上的大字开场 → 连续动作快切 → 热感/三档点阵/字符脸与原片交替 → 九格同时运动 → 点阵炸开、撞成一个词 → 老电视关机。

始终保持真实动作连续：不生成脸、不换脸、不逐帧对齐、不补帧慢动作、不定格推近。原片不统一调色，人脸不额外放大；黑白采用不显老的 M3 银色电影黑白。连续动作快切里至少一半的刀是原片，素材时间不中断。音乐长音给动作时间，碎拍放连闪，呼吸处让画面安静。统一 Outfit、红色 `#FF3B1F` 和纸底 `#EEEBE4`。

## 安装

需要 Python 3.10–3.12、带 libx264 的 ffmpeg。推荐 Python 3.12 与虚拟环境。ffmpeg 可从系统包管理器安装，或设置环境变量 `FFMPEG` 为可执行文件；未设置时从 PATH 查找。不需要 API 密钥。

```bash
git clone https://github.com/opc8838-hub/MV.git
cd MV
python -m venv .venv
```

Windows PowerShell 激活：`.venv\Scripts\Activate.ps1`；macOS/Linux：`source .venv/bin/activate`。然后：

```bash
python -m pip install -r requirements.txt
ffmpeg -version
python scripts/render.py --help
```

固定的 MediaPipe 版本提供 `solutions` 人物分割；接口无法初始化时（例如部分 Windows 中文安装路径）会提示并退回白墙亮度蒙版，因此白墙拍摄很重要。OpenCV 与其 contrib 依赖固定为相同版本，避免安装时互相覆盖。`--faces` 使用 OpenCV 随包人脸检测，无需下载模型，侧脸可能漏检。音乐分析默认最多读 600 秒音频，视频始终逐帧流式处理。macOS 使用同一组 Python 命令；本机验证环境为 Windows，其他平台需按上述依赖自行验证。

将整个仓库文件夹安装为 `nobody-mv`：Codex 放在 `~/.codex/skills/nobody-mv`，Claude Code 放在 `~/.claude/skills/nobody-mv`，或项目内对应的技能目录。保留 `SKILL.md`、`docs`、`scripts`、`templates`、`fonts` 的相对位置。两个客户端都可以读 [SKILL.md](SKILL.md)。

## 使用

对 AI 说：「把我剪成一支 nobody 那样的 MV。用我的真实视频，先让我选镜头和风格，再给我看按音乐排的时间表。」提供有权使用的视频和音乐；这些文件留在本地。

独立运行时先分析音乐，再选片并标角色：

```bash
python scripts/analyze_music.py work/song.wav --out work/music --target-seconds 30
python scripts/picks_gallery.py work/input.mp4 --duration 5 --start 0 --end 20 --out work/gallery
python scripts/style_sheet.py work/input.mp4 --at 0.5 --out work/styles
```

打开选片页，选择角色并复制 JSON，保存成 `work/picks.json`。默认 1.6 秒候选适合看动作；自动排片的连贯镜头和九格建议确认 4–6 秒可用范围。准备足够多的 before/process/after，以及 enter 与 exit；hero、星标优先。素材时长不足会明确报错，不自动循环同一段。

运行排片并读 `work/plan.md`，先确认时间表，再按意见修改四份 JSON：

```bash
python scripts/plan.py --beatmap work/music/beatmap.json --picks work/picks.json --music work/song.wav --out work
python scripts/opening.py work/opening.json --out work/opening.mp4
python scripts/render.py work/timeline.json --out work/body.mp4
python scripts/ending.py work/ending.json --out work/ending.mp4
python scripts/assemble.py work/assemble.json --out work/final.mp4
python scripts/common.py work/final.mp4 --out work/review.png --every-frame
```

可加 `--style work/style.json`，配置用户选中的 styles、accent_color、question、opening_word、ending_word、target_seconds、shutdown、width/height/fps。示例与路径规则见 [配置说明](docs/08-config.md)。开头、正片、结尾自动共用全片帧时钟，音乐按推荐窗口的原始起点裁切；默认最后 1–2 拍聚字，电视关机可另加一秒。

默认 360×640 / 25fps 小样；最终制作在 style.json 设 width:1080、height:1920 后重新排片，或所有渲染及拼接统一指定 `--width 1080 --height 1920`。旧 [开头模板](templates/opening.nobody.json) 和 [时间线模板](templates/timeline.nobody.json) 仅作一个历史结果的参考，不再是换歌入口。

用户明确要求插入定格时，例如在第 4 秒插入 2 拍，并复制同一段音乐：

```bash
python scripts/assemble.py work/opening.mp4 work/body.mp4 work/ending.mp4 --music work/song.wav --insert-at 4 --insert-beats 2 --bpm 120 --out work/extended.mp4
```

可加 `--beatmap work/music/beatmap.json` 按真实拍间隔插入。工具会将插点吸附到最近拍，并写出实际插入帧与音频块长度。

## 本地自测

```bash
python scripts/selftest_music.py --picks work/picks.json --music work/song.wav --out work/selftest
python -m unittest discover -s scripts -p test_plan.py
```

端到端自测生成分析图、四份配置、时间表、完整成片、逐帧分页拼板和 checks.json，检查音乐事件误差 ≤1 帧、源区间不重复、九格逐格运动、无额外放大/默认定格、无意外黑帧、音频窗口相关性。它需要真实已确认范围足够多的角色镜头；人眼还须检查空镜、角色内容与取景。`scripts/selftest.py` 保留旧版十秒渲染器冒烟测试。

本轮用约 120.19 BPM 与 86.13 BPM 两首音乐完成 30.00 秒 / 23.76 秒端到端小样。两片分别两次 / 一次运动九格，实测刀点最大误差 0.77 / 0.84 帧；全部私人素材、截图、音乐和报告只留在被忽略的 work/，不随公开仓库分发。拍号和 drop 属于估计，尤其六八拍感歌曲需试听或 `--meter` 覆盖，不能把自动标签当成编曲事实。

## 文档

- [01 拍摄指南](docs/01-拍摄指南.md)：机位、动作、镜像
- [02 选片](docs/02-选片.md)：分组、去空镜、编号映射
- [03 风格库](docs/03-风格库.md)：用途、参数、样张
- [04 音乐踩点](docs/04-音乐踩点.md)：BPM、重击、乐句与插拍
- [05 剪辑语法](docs/05-剪辑语法.md)：连贯动作、英雄镜头、九格与结尾
- [06 踩坑](docs/06-踩坑.md)：真实感、白底色彩、内存
- [07 时间线模板](docs/07-时间线模板.md)：历史结果与另一首不同速度音乐的自动排片表
- [08 配置字段](docs/08-config.md)：脚本实际接受的 JSON

代码与文档使用 [MIT](LICENSE)。Outfit 字体使用 [SIL OFL 1.1](fonts/OFL.txt)，来源为 [Outfit](https://github.com/Outfitio/Outfit-Fonts)；字体文件沿用制作项目中的原版。音乐和人物素材由使用者提供并确认权利。

## English

Turn continuous selfie or transformation footage into a personal music video: beat-synced kinetic typography, warm thermal silhouettes, halftone and ASCII treatments, live video grids, an explosive word reveal and a CRT shutdown. The core rule is real motion: fixed framing, forward source time, no generated faces, alignment warps or interpolated slow motion. Includes a Codex/Claude Code skill, local Python tools, beat-based templates and an OFL-licensed font. Bring your own footage and music; no personal media or credentials are distributed.
