# 工作台机制共同支撑 FDE 三循环：ImageGen 提示记录

- 日期：2026-10-04（Asia/Shanghai）
- 用途：`docs/reference/FDE与个人AI研发工作台.md` 的机制说明配图
- 生成方式：内置 `image_gen.imagegen`；新图生成，无输入图片；未使用 CLI/API
- 透明背景：`false`
- 实际提示词次数：1；未执行图像编辑
- 原始输出：`C:\Users\Administrator\.codex\generated_images\01a106f3-2927-7a20-84d8-f872f4402f05\exec-d7dd3aeb-f336-4446-b0dd-488401097299.png`
- 工作区副本：`docs/reference/assets/fde/fde-mechanisms-imagegen-v1.png`
- 实际 PNG 尺寸：1672 × 940 像素（接近 16:9）
- PNG 大小：1603599 字节
- 原始输出与工作区副本 SHA-256 均为：`d68c5510e480ce787e3f2aa60e674fd6bea109c132cbe8e64b6298caf31c1a7a`
- 保存方法：`Copy-Item -LiteralPath` 原样复制；复制后用 `Get-FileHash -Algorithm SHA256` 核对，相同；未修改像素或重新编码

## 实际发送的完整提示词

```text
Use case: scientific-educational
Asset type: Chinese course reference-document infographic, new raster image, 16:9 landscape, target 2048 × 1152 pixels.
Primary request: Create a clear explanatory diagram titled “工作台机制怎样共同支撑 FDE 三循环”. It must explain causality and evidence, not be a terminology poster.
Style/medium: polished functional editorial infographic with subtle lightweight illustrations of documents, execution traces, and human review. Flat panels with restrained depth; ample breathing space. Warm off-white background, large dark navy Simplified Chinese type comparable to Microsoft YaHei, teal forward arrows, orange feedback arrows. Readable at normal Markdown article width.
Composition: four horizontal bands, no clutter.
Band 1: the title. Below it, a single shared rounded background encloses a left-to-right chain of three large stages with clear teal arrowheads and endpoints: “现场判断” → “受控交付” → “后续事项检验”. Small secondary labels under these three stages respectively: “人确认问题、范围与验收”, “工作台组织人与 Codex”, “采用旧版本，检验新结果”.
Band 2: a full-width shared support beam, clearly spanning the entire three-stage chain, labelled “共同支撑整条事项链”. Under this beam, place three mechanism cards inside ONE common support background. There must be NO three separate vertical connections to the three stages above: the mechanisms work together across the whole chain, never mapped one-to-one to the cycles. Use only the broad common support surface to convey the relationship.
Mechanism card exact text:
“Harness”
“确认 · 授权 · 执行 · Eval · 人审”
“留下可核查的交付轨迹”
Second mechanism card:
“记忆系统”
“来源 · 边界 · 版本”
“由人选择采用；经验可单独采用”
Third mechanism card:
“工作流蒸馏”
“整理步骤 → 独立审核 → 先试用”
“跨事项复验与具名验收后，才发布”
Band 3: a compact but explanatory evidence row with heading “能力增长，须接受下一事项检验”. Draw four connected wide panels with teal arrows:
“真实交付轨迹” with subtext “保留失败和反馈”
→ “人提炼与选择” with subtext “经验有边界，流程有版本”
→ “后一事项采用与复验” with subtext “新执行结果 + 具名人审”
→ “版本治理” with subtext “修订或停用；有效流程可发布”.
An orange feedback arrow clearly returns from “版本治理” around the row to “人提炼与选择”, labelled “按新结果修订”. The forward and feedback arrows must clearly attach to their source and target panel borders, never float loosely.
Band 4: two unobtrusive but readable exact footer sentences:
“共同支撑多个循环；不涉及模型训练或权重更新”
“教学示意；效果须由跨事项记录证明”
Accuracy constraints: FlowERP / ERP business acceptance is not equivalent to passing workbench checks. Human choice, independent review, trial, actual cross-matter verification, named acceptance, then publication are required in that order for workflows. Memory experience may be adopted separately and must not inherit workflow publication gates. The governance panel must not imply publication immediately after initial review. Real records, not icons or stamps, establish completion.
Avoid: automatic extraction, automatic publication, model training, weight update imagery, success stamps, seals, checkmark trophies, fake interface screenshots, tiny footnotes, decorative robots, logos, watermarks. Do not add extra text. Render all given Simplified Chinese text accurately, with large type, distinct arrowheads, no clipping or label overlap.
```

## 本轮视觉核对

内置 `generatedImage(result)` 原生返回图显示完整。中文标题和各卡片文字清楚；上方事项链有明确端点，三个机制位于同一共享支撑背景，没有将机制分别对应三个循环。记忆经验可以单独采用；流程按独立审核、先试用、跨事项复验与具名验收、发布的顺序说明。橙色反馈从版本治理回到人的提炼与选择，底部注明教学示意及跨事项证据边界，没有成功印章或自动发布表述。

已按要求调用 `view_image` 读取原始输出及工作区副本；工具显示的缩略图异常偏白，本轮视觉结论依据内置 ImageGen 的完整原生显示。工作区副本保留原始 PNG 字节，留待主任务独立视觉复核。
