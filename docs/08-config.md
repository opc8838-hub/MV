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
