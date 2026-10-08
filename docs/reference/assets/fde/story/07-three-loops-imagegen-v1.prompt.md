# FDE 三循环故事图：ImageGen 生成记录

- 生成日期：2026-10-04（Asia/Shanghai）。
- 生成方式：内置 `image_gen.imagegen`；未使用 API、CLI 或代码绘图。
- 工具调用：2 次（1 次全新生成、1 次必要定点编辑）；均为 `transparent_background: false`。
- 用途：少字圆环图，以返回箭头解释现场、交付、能力循环及相互支持。
- 事实边界：教学示意；不构成真实交付、跨事项验收、提效或模型进化证据。

## 最终选用输出

- 原始输出路径：`C:\Users\Administrator\.codex\generated_images\01a106e9-671f-74d3-809f-b589000318cc\exec-bee768ed-7890-4c3a-913e-85eb8762f80e.png`。
- PNG 大小：1438034 字节。
- PNG 尺寸：1672 × 941 像素（横向 16:9 构图）。
- 原始 PNG SHA256：`529D55F4ADECC89ECCEEC254914D996C426D8CCCD8C5FBF2FC2D3811DBCA9403`。
- 工作区副本：`docs/reference/assets/fde/story/07-three-loops-imagegen-v1.png`。
- 副本 SHA256：`529D55F4ADECC89ECCEEC254914D996C426D8CCCD8C5FBF2FC2D3811DBCA9403`；复制核对一致，原始输出保留。
- 视觉核对：使用 `view_image(detail: original)` 查看。三个环的阶段与返回箭头明确，返工回到修改；现场要求进入交付，交付结果进入能力；能力“复验与修订”向下出发、沿底线向左，两个箭头分别返回现场与交付。未逐机制配对，无自动进化或虚构完成标记。
- 写入范围：仅本 PNG 与本记录；未改正文、索引和其他图片。

## 初版输出与修订原因

- 原始输出路径：`C:\Users\Administrator\.codex\generated_images\01a106e9-671f-74d3-809f-b589000318cc\exec-94a7e962-a20c-4098-b47c-1cc541bc6c58.png`。
- PNG 大小：1235176 字节。
- PNG 尺寸：1672 × 941 像素（横向 16:9 构图）。
- 原始 PNG SHA256：`4E402B380896223D564E63D979F79302B6FFAE327832223818184CAEA4961FE9`。
- 初版未复制为项目最终资产，保留工具原始输出。
- 修订原因：底部回流初版有三个向上端点，能力来源不清；交付环底部的“接受”标签容易误读为接受后仍须回到修改。仅修正两处箭头/标签。

## 提示词序列 1：全新生成（实际完整提示词）

- 参数：全新生成，未传入参考图参数。

```text
Use case: infographic-diagram
Asset type: a minimal Chinese story diagram explaining why the three FDE cycles are cycles.
Primary request: Generate a brand-new landscape 16:9 course illustration. Warm off-white background, deep navy Chinese large typography, pale blue/teal/orange accents, functional light isometric person and business-object illustrations. Large visuals, extremely sparse exact Chinese labels, generous whitespace. Same restrained course style as illustrated FDE diagrams. Avoid any dense text, table, or complicated workflow.

Title verbatim: “为什么是三个循环？”
Subtitle verbatim: “新结果，会改变下一次的判断与做法”

Main composition: three equally sized, SEPARATE circular loops horizontally across the canvas. Each loop has its own visible closed arrow path with three well-separated stage labels spaced around the circumference; arrowheads follow one consistent clockwise direction within that loop. Illustrate each of the three loops with one small functional vignette in its center, occupying less than half the loop: humans and an inventory table in the field loop, a human inspecting a small order document in the delivery loop, and a human reviewing a reusable method notebook in the capability loop. These illustrations never look like real app screens. The loop paths must be closed and must actually return to the first stage.

LEFT circle title verbatim “现场循环”. Exact three stage labels in clockwise order: “判断”, “使用反馈”, “重新判断”. The closure from “重新判断” returns to “判断”. The return segment is orange to emphasize feedback.
CENTER circle title verbatim “交付循环”. Exact three stage labels in clockwise order: “修改”, “检查”, “返工或接受”. The circular return arrow from “返工或接受” to “修改” is orange and labeled exactly “返工”; a short teal departure from the same stage is labeled exactly “接受” and joins the main connection toward the capability loop. This makes the circular return conditional on rework and avoids suggesting accepted work must be modified again. Keep the circular form recognizable.
RIGHT circle title verbatim “能力循环”. Exact three stage labels in clockwise order: “提炼”, “后续采用”, “复验与修订”. The closure from “复验与修订” returns to “提炼”. The return segment is orange. Nothing implies automatic model learning.

Connections BETWEEN loops: a short teal arrow from the field loop to the delivery loop, label verbatim “确认的要求”. A short teal arrow from the delivery loop to the capability loop, label verbatim “交付结果”. Use a single simple orange return line BELOW all three separate circles that starts at capability’s revised-method end and has two clear upward endpoints, one into the field loop and one into the delivery loop. Its only label verbatim “支持后续判断与交付”. Keep inter-loop connections outside circles so they cannot be mistaken for stage order within a circle.
Footer exactly “教学示意”.

Constraints: All exact Chinese text must be fully readable and unchanged. Total Chinese copy is very short; no additional paragraphs. Show three real closed feedback loops connected by a few arrows, not one long straight process. Human judgment stays visible through the small center illustrations. Do not map the three loops one-to-one to Harness, memory, and workflow; do not write any of those mechanism names. No fake completion record, no success seal, no automatic evolution, no weight updates or automatic publishing. Preserve visible arrow direction and clear endpoints.
```

## 提示词序列 2：定点编辑（实际完整提示词）

- 参数：`referenced_image_paths` 为初版原始输出路径 `C:\Users\Administrator\.codex\generated_images\01a106e9-671f-74d3-809f-b589000318cc\exec-94a7e962-a20c-4098-b47c-1cc541bc6c58.png`；未使用 `num_last_images_to_include`。

```text
Edit only the two arrow defects in this exact existing image. Preserve the title, subtitle, all three separate circular loops, all stage-node labels, illustrations, colors, proportions, and sparse readable style unchanged.
1. Fix the bottom orange inter-loop return path: it must START from the right capability loop's “复验与修订” node, run DOWN from that node and then LEFT along the existing bottom horizontal line. Remove the upward-pointing arrowhead at the RIGHT endpoint under the capability circle: that endpoint is the SOURCE, not a destination. Make the orange line visibly attach to the capability “复验与修订” node without any arrowhead pointing back into capability. The same orange line has exactly TWO upward destination arrowheads: one into the left field circle, one into the middle delivery circle. Keep its label verbatim “支持后续判断与交付”. Add one small LEFT-pointing arrowhead on the bottom horizontal line near the right side, so the direction from capability toward the other two cycles is unmistakable. Do not add a third upward arrowhead into capability.
2. Remove ONLY the small teal word “接受” placed on the inside/bottom arc of the middle delivery circle. It incorrectly labels a return route. Keep the stage node “返工或接受” exactly unchanged, keep the orange return segment labeled “返工”, and keep the between-loop teal connector labeled “交付结果” unchanged. The delivery circle continues to show 修改 → 检查 → 返工或接受, with the orange rework route returning to 修改.
Do not change any other visual element. Do not add extra explanatory text or complexity. Footer remains “教学示意”.
```
