# 库存口径怎样成为验收条件：ImageGen 生成记录

- 生成日期：2026-10-04（Asia/Shanghai）。
- 生成方式：内置 `image_gen.imagegen`；未使用外部 API、CLI 或代码绘图。
- 用途：为 FDE 导读解释库存口径、Spec 条件与同一数据复验的关系。
- 性质：教学示例图，不构成真实运行、检查通过、客户验收或提效证据。
- 生成次数：1 次全新生成；未进行修订。
- 原始输出路径：`C:\Users\Administrator\.codex\generated_images\01a106e9-671f-74d3-809f-b589000318cc\exec-f9069974-1a19-44cc-acda-b53206cb7f3e.png`。
- 工作区 PNG：`docs/reference/assets/fde/fde-inventory-acceptance-imagegen-v1.png`。
- PNG 尺寸：1672 × 941 像素（横向 16:9 构图）。
- 原始 PNG SHA256：`A185D5FB7CE18B9917F7807FDDFA4571A5A5430EDA9350B60C097B6573752308`。
- 工作区 PNG SHA256：`A185D5FB7CE18B9917F7807FDDFA4571A5A5430EDA9350B60C097B6573752308`。
- 复制核对：原始与工作区 PNG 哈希一致；保留原始输出。
- 工具参数：`transparent_background: false`；全新生成，未传入参考图参数。
- 视觉核对：已查看原始 PNG。中文及 10/4/6 口径一致，三种数量同时呈现且无状态迁移箭头；Spec 明确可用量为 6；导出 10、导出 6、数据或解释器报错分别对应不符预期、符合本条条件、未能验证业务规则；橙色反馈从不符预期结果指向修复后按同一条件再查。
- 写入范围：仅本 PNG 与本提示词记录；未修改正文、索引或其他资产。

## 提示词序列 1：全新生成（实际完整提示词）

```text
Use case: infographic-diagram
Asset type: Chinese educational illustration for docs/reference/FDE与个人AI研发工作台.md.
Primary request: Generate a brand-new, landscape 16:9 Chinese textbook infographic explaining how one inventory definition becomes an acceptance condition. Match a restrained course illustration style: warm off-white background, very large readable dark navy Chinese sans-serif text, blue and teal progression arrows, orange failure and feedback, functional light isometric drawings of inventory records, a person checking a clipboard, and a specification sheet. Clear generous spacing, rounded panels, subtle shadows, no realistic app UI.

Title exactly: “库存口径怎样成为验收条件”
Subtitle exactly: “同一组数据：在库 10 · 预占 4 · 可用 6”

Composition: three large panels from left to right, connected by clear teal arrows. Each panel has a large heading. Small illustrations support the meaning and do not compete with the text.
LEFT panel heading exactly “用途与数据”. At its top a business person and speech bubble with exact text “还能接多少订单？”. Below are three adjacent or stacked DATA cards, shown simultaneously as different inventory quantities, with exact text “在库 10”, “预占 4”, “可用 6”. These are different definitions of the same moment, NOT successive states: DO NOT put arrows between the three data cards. A person with a clipboard confirms the records. Bottom text exactly “人确认用途、范围和验收”.
CENTER panel heading exactly “规则与条件”. Show the exact formula prominently “可用 = 在库 − 预占”, and directly below it “6 = 10 − 4”. Below the formula is a specification document labeled exactly “Spec”. Its large readable two-line statement is exactly “在库 10、预占 4 时” and “导出可用量应为 6”. A short vertical teal arrow links the formula to the specification sheet. The left-to-center teal arrow is labeled “核对并确认”.
RIGHT panel heading exactly “同一数据检查”. The center-to-right teal arrow is labeled “按条件检查”. This panel shows hypothetical possible outcomes, with a clear smaller heading exactly “可能结果”. Use three separate well-spaced result cards with no celebratory checkmarks or stamps. Card 1 has an orange accent and exact text “导出 10” and “不符合预期 6”. Card 2 has a teal accent and exact text “导出 6” and “符合本条条件”. Card 3 has a neutral light gray background with orange accent and exact text “数据或解释器报错” and “未能验证业务规则”. Show the distinction clearly: business output 10 is a rule mismatch; an execution/data/interpretation environment error provides no validated business result. Never label an environment error as a business rule failure.

Below the right panel, a single orange feedback arrow starts from the “导出 10” result and points to a small lower-band label exactly “修复实现后，用同一条件再查”. Keep this arrow short and its start and end clear; do not point this failure feedback at the formula as if changing the business rule were the fix.
Footer exactly “教学示例；实际检查须保留输入、候选与结果”.

Constraints: Chinese labels must be verbatim and fully legible. Preserve all 10/4/6 values and subtraction logic. The same input data remains constant across the wrong-output and correct-output possibilities. Do not add extra lessons or dense technical vocabulary. This is a conditional teaching illustration, not a claimed real test run. No real runtime interface, no green success seal, no “已完成”, no fabricated evidence, no automatic publication, no changing 10 into 4 into 6 with state transition arrows. All arrows have clear endpoints. Avoid English except “Spec”.
```
