# 交付完成，要看用户能否正确使用：ImageGen 实际提示记录

- 日期：2026-10-04（Asia/Shanghai）
- 方式：内置 `image_gen.imagegen`；未使用 CLI/API 或代码绘图
- 透明背景：`false`
- 生成/编辑调用次数：2
- 最终原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-72b8c2af-7049-4dee-ac56-14f6bb90d771.png`
- 工作区副本：`docs/reference/assets/fde/story/04-delivery-to-user-imagegen-v1.png`
- 实际 PNG 尺寸：1672 × 941 像素（接近 16:9）
- PNG 大小：1864266 字节
- 原始输出与工作区副本 SHA-256 均为：`c0fdbcaff894ba6cb1a7df6eb77e80351006e4f11e508a267967d171c5c05d3a`
- 保存方法：`Copy-Item -LiteralPath` 原样复制；使用 Python 标准库逐字节比较与 SHA-256 核对，两份完全一致；未修改像素或重新编码

## 调用 1：新图生成

- 输入：`无输入图片`
- 原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-255128a2-a011-4eaa-a65b-79ed1f1bc694.png`

```text
Use case: scientific-educational
Asset type: one new raster story illustration for a beginner Chinese engineering course, 16:9 landscape, target 2048 × 1152 pixels.
Primary request: Show that engineering delivery is judged by whether the customer can correctly use it, with human participation through the entire process. Show FOUR causally connected illustrated work scenes, with an explicit wrong-result rework route and a target-result route to customer review. This is an expected teaching process, not a claim that tests actually ran or acceptance happened.
Exact title: “交付完成，要看用户能否正确使用”
Style: warm off-white background, very large dark navy Simplified Chinese labels, teal forward arrows, orange rework arrow. High-quality editorial business-person illustration with gentle realistic depth and functional paper documents. Use the same customer in a green shirt and same engineer in a blue jacket with glasses in each relevant scene. Large illustrated actions should convey meaning; do not make a text-heavy flowchart or card poster.
Composition: title on top; four equal-height illustrated scenes left to right; short process labels above each scene; a single orange return arrow in the lower margin; only “教学示例” in the footer. Keep body Chinese text under 70 characters besides the title. No paragraphs or extra text.
Scene 1 exact label: “确认可用量6”
The engineer and customer jointly inspect one simple inventory sheet with “库存 10”, “预占 4”, “可用 6”. They point at the available quantity 6 together. The engineer does not impose the requirement alone.
Scene 2 exact label: “Codex协助修改”
The engineer works on a laptop labelled only “Codex”, supervising a proposed modification; show a small inventory export sheet next to the laptop, not a wall of code and not an autonomous robot. Codex is assisting, and the engineer stays present.
Scene 3 exact label: “用同一数据检查”
Same engineer compares the inventory values 10, 4, 6 to two potential output cards. One candidate card shows “10” in orange with a plain diagonal strike indicating an incorrect available quantity. One target card shows “6” in teal, labelled “目标6”. Do not use a test-passed stamp, green checkmark badge, actual execution report, or release icon.
A clear orange arrow MUST start at the orange 10 card in scene 3, travel around the bottom margin, and end at the engineer's laptop in scene 2. Its only label is “返工”. Make the start and end explicit and preserve arrow direction.
The teal forward arrow from scene 3 to scene 4 MUST originate at the “目标6” output card. The orange 10 output must not flow to customer acceptance.
Scene 4 exact label: “用户核对并具名接受”
Customer and engineer are together. The customer actively compares an incoming-order card showing quantity “4” against the target available quantity “6” on the export, to judge whether the information supports the business decision. The engineer is nearby explaining and listening. Include a small review document with a blank signature line only, without a fabricated real name or completed success seal. This is an expected human review and acceptance step.
Use clear teal arrows linking scenes 1 → 2 → 3, and the target-6 branch of scene 3 → scene 4. Arrowheads touch their illustrated source and destination areas. Leave sufficient space to avoid crossings and text overlap.
Exact footer: “教学示例”
Accuracy: stock 10, reserved 4, available 6. User checks the business decision, not merely whether the interface has appeared. Do not imply the proposed expected process actually ran, passed, deployed, or received a real signature. Do not skip customer review after a correct candidate output.
Avoid: additional subtitles, dense cards, Harness/Spec/Eval jargon, unattended AI decision making, fake full-name signatures, actual acceptance claims, release stamps, official seals, checkmark trophies, success medals, tiny text, watermark, logos.
```

## 调用 2：内置 ImageGen 定点编辑

- 输入：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-255128a2-a011-4eaa-a65b-79ed1f1bc694.png`
- 原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-72b8c2af-7049-4dee-ac56-14f6bb90d771.png`

```text
Use case: precise-object-edit
Edit target: the provided four-scene Chinese teaching illustration “交付完成，要看用户能否正确使用”.
Make only these targeted semantic corrections, while preserving the same title, four scene arrangement, warm off-white palette, people, inventory values, large text, Codex laptop, unfilled signature line, and “教学示例” footer.
1. Correct the orange rework route: it must be ONE single-direction arrow. Its plain tail starts at the lower border of the crossed-out orange 10 output card in scene 3; from there the path travels DOWN and LEFT around the lower margin, then UP to scene 2. There is exactly ONE orange arrowhead, pointing UP and ending at the Codex laptop in scene 2. REMOVE the upward orange arrowhead currently near the 10 card. Replace that end with a plain attached tail. Keep only the label “返工”.
2. Between scene 3 and scene 4, DELETE the upper teal generic forward arrow at torso height. KEEP exactly one teal arrow from the lower “目标6” output card in scene 3 to the target-6 export used by the customer in scene 4. This communicates that only the target 6 result moves to customer review; incorrect 10 returns for modification.
3. Change the label “入库单” on the customer's order card in scene 4 to “待接订单”. Preserve quantity 4. Customer is deciding whether to take a new order, not checking an inbound receipt.
4. Reduce repetitive tiny Chinese annotations. In scene 2's small export sheet, preserve the big proposed number 6 but remove its miniature table words and heading, replacing them with simple neutral document lines. In scene 3's background input sheet, preserve the input values 10, 4, 6 as three numeric rows, but remove the small heading “库存数据” and repeated Chinese row words. In scene 1, preserve the clear labelled inventory table unchanged, so those three input numbers remain interpretable. All key four-stage labels stay unchanged.
Do not add new text, arrows, claims, stamps, marks of a test passing, or real signatures. Do not alter the surrounding illustration beyond these corrections. The finished figure remains a teaching example and expected process.
```

## 视觉核对

已用 `generatedImage(result)` 返回内置 ImageGen 原生图，并以 `view_image(detail: original)` 读取最终 PNG。

首图发现返工线有双向箭头，以及待接订单被标成入库单，故执行一次定点编辑；同时删除绕过目标 6 的重复前进箭头、减少重复表格文字。最终返工线以错误 10 为尾端，单向返回 Codex 修改；仅可用 6 前进到用户核对。工程师各阶段参与，用户对照待接订单数量 4 与可用量 6，签名线为空；没有表示真实执行通过或已发生具名验收，底部注明教学示例。

完成生成与保存后由主任务独立视觉复核；本图只表示教学预期，不是实际运行或客户验收证据。
