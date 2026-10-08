# 用户说要一张表，真正要解决什么？：ImageGen 实际提示记录

- 日期：2026-10-04（Asia/Shanghai）
- 方式：内置 `image_gen.imagegen`；未使用 CLI/API 或代码绘图
- 透明背景：`false`
- 生成/编辑调用次数：1
- 最终原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-366869c9-f55b-42d7-af9f-da3ad5596859.png`
- 工作区副本：`docs/reference/assets/fde/story/02-actual-need-imagegen-v1.png`
- 实际 PNG 尺寸：1672 × 941 像素（接近 16:9）
- PNG 大小：1779000 字节
- 原始输出与工作区副本 SHA-256 均为：`567ba66be690bf7bdc0eb21960d87889ea1c12a71bb561ae585b6dddef4b79b4`
- 保存方法：`Copy-Item -LiteralPath` 原样复制；使用 Python 标准库逐字节比较与 SHA-256 核对，两份完全一致；未修改像素或重新编码

## 调用 1：新图生成

- 输入：`无输入图片`
- 原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-366869c9-f55b-42d7-af9f-da3ad5596859.png`

```text
Use case: scientific-educational
Asset type: one new raster illustration for a beginner Chinese engineering-course story, 16:9 landscape, target 2048 × 1152 pixels.
Primary request: Explain what a forward-deployed engineer does when a customer asks for an inventory export: engineer and user investigate the user's next business action together, then confirm the real purpose with the user. It must be a visual story with two causally connected scenes, not a text-card poster.
Style: warm off-white background, large dark navy Simplified Chinese typography, teal causal arrows and restrained orange highlights. Friendly realistic editorial business-person illustrations, functional inventory documents and incoming-order cards, simple high-quality flat illustration with gentle depth. Spacious, easy to read. No decorative robot.
Composition: a title at the top, TWO large connected business scenes spanning most of the image, a single short conclusion at the bottom. The same customer in a green shirt and the same engineer in a blue jacket appear in both scenes. Scenes contain people doing work; do not replace scenes with question-and-answer rectangles.
Exact title: “用户说要一张表，真正要解决什么？”
Scene 1, left: customer asks for “导出库存” in one large speech bubble. Engineer sits next to the customer, listening and looking at the same simple inventory document. The document has only three clear headings and numbers: “库存 10”, “预占 4”, “可用 6”. The customer is the source of the request; engineer does not decide the requirement alone.
A broad teal arrow connects scene 1 to scene 2, labelled “一起核对用途”.
Scene 2, right: same customer and engineer jointly compare the inventory document against a small stack of new-order cards, one showing quantity 4 and another showing quantity 7, without extra text. Customer points at those order cards and asks “还能接多少订单？”. Engineer indicates the availability value 6 and the next business decision while listening. This remains joint verification, not an engineer announcing a settled requirement. A small label in this scene reads “与用户确认”.
Bottom conclusion, large but short, exact text: “先确认用途，再确定要交付什么”
Tiny but readable footer: “教学示例”
Text policy: use only the exact Chinese phrases specified above; do not add subheads, subtitles, paragraphs, explanatory annotations, labels, or extra UI text. Chinese body text apart from the title must stay under 70 characters. Use the large illustrated actions and correspondence between stock and incoming orders to convey meaning.
Accuracy: physical stock 10, reserved 4, available 6; using physical stock 10 as available capacity would mislead the business decision. Do not present the two order quantities as both accepted. Do not fabricate acceptance, actual runtime evidence, a successful customer case, or a signature.
Avoid: dense cards, architecture diagrams, Harness/Spec/Eval terminology, official seals, checkmark trophies, release stamps, machine-generated success claims, unattended AI decisions, code walls, tiny text, watermark, logo.
```

## 视觉核对

已用 `generatedImage(result)` 返回内置 ImageGen 原生图，并以 `view_image(detail: original)` 读取最终 PNG。

两场景中的用户与工程师一起核对用途，没有由工程师单方面确定需求；库存、预占、可用为 10、4、6。待接订单 4 与 7 只是待判断输入，没有画成已接受订单。人物动作、共同看的表及下一业务动作有对应关系；主要文字清楚，底部注明教学示例。

完成生成与保存后由主任务独立视觉复核；本图只表示教学预期，不是实际运行或客户验收证据。
