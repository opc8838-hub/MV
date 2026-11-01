# 配置字段与命令约定

所有 JSON 使用 UTF-8。路径相对**该 JSON 文件目录**，绝对路径也可供私人制作使用，但不得进入公开模板。输出由 `--out` 指定。所有时间单位除带 `_beat` 的字段外均为秒。

## 来源表

```json
{"sources":{"FACE_A":{"path":"input.mp4","start":10,"x_offset":0}}}
```

`start` 是素材秒数，`x_offset` 是源宽度比例（例如 0.03 向右偏移）；一段内始终不变。9:16 画面通过固定裁切铺满，不加额外放大。分辨率由 CLI `--width/--height` 决定；所有段落输出相同尺寸和 fps。

## 时间线

顶层 `bpm` 默认 120；可选 `beatmap:"music/beatmap.json"`、`beat_origin:14`。没有 beatmap 时拍点均匀。读真实拍表时本地 beat 0 对应原音乐 beat_origin，随后按相邻拍细分，并减去原点秒数；因此正片单独从 0 开始。音乐首个检测拍可能晚于 0 秒，开头长度要与它的绝对位置匹配。

`segments` 必须从本地拍 0 开始连续覆盖，无空隙或重叠。每段有 `type`、`start_beat`、`end_beat`，最终量化到最近输出帧；不足一帧报错。

| type | 必需/可选字段 | 行为 |
|---|---|---|
| clip | source；style、offset、transition_frames、wipe | 真速连贯；固定裁切；可进出显影、叠扫描线 |
| chop | source、cuts | 一个连贯来源；cuts 是 `{beat:0,style:"raw"}` 数组，beat 相对本段；至少半数 raw |
| hero | source；box、label、magnifier | 图形框模板匹配；box 为输出画面归一化 x/y/宽/高，初始框需人工定位 |
| grid | n=2/3、tiles | 4/9 个来源别名；重复别名可同步显示多种风格 |
| freeze | source、authorized:true；label | 明确授权的静帧红框；仅读一次源帧 |
| black | 无 | 黑场；不自动将音乐静音 |
| text_word | word；source、style | 有来源时叠在真实视频上；无来源时用纸色底 |

所有带来源的段落可设 `offset`（在 source.start 上加秒数）；每段需要衔接时显式加前一段的时长。每段可带 `word` 放左下 1/3，`word_color` RGB 三元组，`fade_out_frames` 压暗末端。style 使用 [风格库](03-风格库.md) 中名称。

grid 可设 `tile_styles`，长度必须 n*n；`mode:"reveal"` 配 `reveal_beats` 控制中心螺旋亮起；`mode:"flip"` 配 `flip_to`（n*n 个新来源）、`flip_beats` 控制按行分组翻面。所有隐藏来源也持续读帧，素材时间不倒回。默认原片格，格间纸色。

chop 示例（120 BPM 时每 1/4 拍约 3 帧）：

```json
{"type":"chop","start_beat":0,"end_beat":1,"source":"FACE_A",
 "cuts":[{"beat":0,"style":"raw"},{"beat":0.25,"style":"dots3"},
         {"beat":0.5,"style":"raw"},{"beat":0.75,"style":"negative"}]}
```

render 输出 `.trace.ndjson`：每个输出帧、段落类型、style、可见来源 alias 与秒数。grid 未显示格不计入可见来源，但解码时钟仍前进。跨段衔接需用正确的 offset，不会自动猜测同一镜头是否继续。

## 开头

顶层 `beatmap` 指分析结果，`duration` 是开头秒数，`sources` 同上，`slots` 是每次重击的画面。每槽用 `hit`（hits 数组从 0 开始）或 `at`（明确秒数），第一个槽必须 `at:0`。重击超过 duration 或量化后重复需先修正。

每槽可设 source、offset、style、background（paper/red/black）、text、size（文字字号为画宽比例）、color、big、scan、slices、question。scan 将处理从左向右揭开，slices 将问题纸页切成六条滑开，下面视频持续播放。输出 `.cuts.json` 记录实际帧边界。模板中的 hit 编号须试听后调整，不假定每首歌重击数一样。

## 拼接和自测

assemble 重新流式编码输入段至统一尺寸后加音轨，避免不同参数的 concat-copy 失败。`--insert-at` 是全片秒数，插入时固定上一帧；`--insert-beats` 是整数；音乐复制随后完整 N 拍，视频和音轨后段同步平移。AAC 可能有编码延迟，以 MP4 音轨时间戳和实际解码样本检查时长。

`scripts/selftest.py --help` 给出可重复自测参数；产物、来源指纹、命令与报告只留在私有输出目录。自测不要求网络、不更改输入媒体。

## 音乐驱动的自动排片（新入口）

```bash
python scripts/plan.py --beatmap work/music/beatmap.json --picks work/picks.json --style work/style.json --music work/song.wav --out work/plan
```

--style 可省略；--music 覆盖 style.music。未指定音乐时，assemble.json 明确使用输出目录旁的 music.wav，并在 plan.md 提示放置原曲。beatmap 不记录私人音频路径。所有生成配置可原样交给相应脚本，路径均以生成配置文件所在目录为基准；picks 的输入路径相对 picks 文件，style.music 相对 style 文件，--music 相对命令所在目录。Windows 跨盘路径在私人配置中可为绝对路径，不得提交。

选片文件是数组（或 `{ "picks": [...] }`）：

```json
[
  {"id":"P01","path":"input.mp4","start":10,"duration":5,"role":"enter","hero":true,"star":1,"freeze":false,"allow_zoom":false,"x_offset":0},
  {"id":"P02","path":"input.mp4","start":20,"duration":5,"role":"process","hero":false,"freeze":false,"allow_zoom":false}
]
```

以上是格式示意，实际还要有足够的其他角色与时间。也兼容编号到对象的来源表，旧 file/t/clip_len 字段会被归一化。支持八种 role，未知角色拒绝；duration 只表示用户已检查批准的可用范围。先按角色，再按 hero、star（或 rating）优先级选；缺角色可用其他真实片段，实际分配角色和请求角色写进 allocation.json，需复核内容。终局 after 翻面要求足够的 after，不能随意用别的角色代替。

style.json（全部可选）：

```json
{
  "styles":["mono_m3","dots3","thermal_silhouette"],
  "accent_color":"#FF3B1F",
  "opening_word":"WHO",
  "question":"who am i?",
  "ending_word":"nobody.",
  "target_seconds":30,
  "shutdown":false,
  "width":360,"height":640,"fps":25
}
```

修改 target_seconds 会在原分析范围内重新推荐小节起点窗口；省略时直接使用 beatmap.window（适合已手动校对的窗口）。窗口至少八秒，任务建议 15–60 秒。shutdown 默认 false；为 true 时结尾额外一秒关机，音乐先在原窗口末端淡出再补静音。实际成片音乐时长四舍五入到最近帧。

四份输出：

- opening.json：duration、slots（at 为开头本地秒数）和 sources；static 的纸页/文字不做噪声/位移动画。
- timeline.json：segments 使用正片本地 start_frame/end_frame；chop.cuts 使用段内 frame。保留原 beat 字段配置兼容性，帧字段优先。这些帧是按配置 fps 计算的，改 fps 必须重新运行 plan.py，不能只在渲染命令加另一个 fps。
- ending.json：source（默认 body.mp4）、at、word、duration、shutdown、shutdown_seconds、width/height/fps。ending.py 检测输入为 JSON 时读取；旧的直接输入视频入口保留。
- assemble.json：parts、music、music_start（原曲窗口起点）、music_seconds、audio_fade_out、shutdown_seconds、width/height/fps。assemble.py 单个 JSON 参数直接读取；旧 parts + --music 入口保留。不能把窗口配置与插拍同时使用。

还有 plan.md（全片时间）、allocation.json（所有原文件占用区间、开头帧数、正片结束帧、音乐总帧和说明）。按物理文件排除所有时间重叠，包括不同 pick 指向同一段、九格尚未亮起的帧。出现不足报错时补选素材，不能设置循环来绕过。

渲染配置可带 width/height/fps；显式 CLI 参数优先。改变尺寸可以覆盖，改变 fps 则必须重新规划帧级时间线。所有段落和拼接使用相同设置。

grid 新增 reveal_frames / flip_frames（段内帧数），覆盖按 BPM 换算的旧字段；mode:reveal 与 flip_after_reveal:true、flip_to 可以先逐格亮起，再逐格翻面，之后持续运动。自动生成的九格无定格。手工放大镜需要来源 allow_zoom:true。

`scripts/selftest_music.py` 运行完整音乐分析/自动排片/三段渲染/音频窗口拼接，附带每一帧的分页拼板和独立核查。`scripts/test_plan.py` 用合成时间结构覆盖多速度、拍号、片长、窗口、短前奏与源区间去重，无需私人媒体。
