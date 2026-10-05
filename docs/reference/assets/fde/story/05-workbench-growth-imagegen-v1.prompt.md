# 一个现场问题，为什么带来两种改进 — ImageGen 生成记录

- 日期：2026-10-04（Asia/Shanghai）
- 用途：FDE 导读连续故事配图。图中业务数字和前后情形均为教学示例。
- 生成方式：内置 `image_gen.imagegen`；一次独立新图生成，一次定点编辑，均为 `transparent_background=false`。未使用 CLI、外部 API 或代码绘图。
- 初稿原始输出：`C:\Users\Administrator\.codex\generated_images\01a10708-3506-7203-bd7a-574aeff23c0d\exec-d7e9a5f7-6898-40a4-91ea-799b6175192d.png`
- 定点编辑输入：上述初稿，使用 `referenced_image_paths` 单张引用。
- 最终原始输出：`C:\Users\Administrator\.codex\generated_images\01a10708-3506-7203-bd7a-574aeff23c0d\exec-9557bfc9-834a-4239-8b8a-dd6cb3566d4a.png`
- 工作区原样副本：`docs/reference/assets/fde/story/05-workbench-growth-imagegen-v1.png`
- 尺寸：1672 × 941 px，约 16:9。
- 大小：1,679,265 字节。
- SHA-256：`1411B69C9BD360BF1FD2772BBA10698DA674336BAED24ADB4A208F8FC1A192F4`
- 复制验证：最终原始 PNG 与工作区副本 SHA-256 完全相同，保持字节一致。

## 提示词序列 1：全新生成

```text
Use case: scientific-educational.
Asset type: 中文 FDE 教学导读连续故事图中的第 5 张。独立全新横向图，16:9。
Primary request: 画“一个现场问题，为什么带来两种改进”，以插画为主、少量中文大字解释因果。让初学者一眼看懂：同一次现场发现既推动 FlowERP 客户业务结果改进，也推动个人研发工作台的检查方法改进；工作台是组织后续研发的工具。不能画成 ERP 业务功能自动搬进工作台。
Style: 浅暖白背景，深蓝大字，青绿色推进箭头，橙色强调失败原因。成熟的功能性等距插画，库存箱、库存导出文档、研发者、工作台检查文档。图画占主体至少70%，卡片少而大，留白宽，不要密集文字，不要软件截屏、代码、哈希、复杂术语、装饰性文案。
Composition: 顶部简短大标题。上半部是一个仓库工作人员和研发者共同核对库存的场景：一个导出文档只显示“10”，旁边真实库存背景中有10箱，其中4箱带橙色“已预占”束带，剩余6箱为青绿色可用。箱子数量要简化但数字标签准确；一张小口径标签清楚写“在库10 · 预占4 · 可用6”。这一场景下方唯一原因说明：“检查只看在库量，漏了预占”。不要把预占误画成库存消失。
从上部原因向下分出两条清楚的青绿箭头，分别指向下方两块大型功能插画，不画下方两块互相导入数据。左侧为 FlowERP 客户业务导出文档及业务人员，文档突出青绿大数字6，文案原文“FlowERP：导出可用量6”。右侧为研发工作台中的研发者和一张带库存预占示意的小检查卡，旁边后续任务文档，文案原文“工作台：把含预占检查用于后续交付”。右侧画的是检查方法随人走向后续任务，不是增加库存或ERP业务模块。
Text exact and only these labels:
“一个现场问题，为什么带来两种改进”
“在库10 · 预占4 · 可用6”
“检查只看在库量，漏了预占”
“FlowERP：导出可用量6”
“工作台：把含预占检查用于后续交付”
“教学示例”
A small footer says “教学示例”. Do not add explanations, English slogans, completion stamp, passed badges, or claims of actual delivery. Ensure Chinese text is exact, highly readable and large.
```

## 提示词序列 2：定点修订

```text
Edit this teaching illustration only in its bottom-right Workbench panel. Remove the green circular checkmark badge beside the inventory check card, and replace all three green checked squares on the “后续任务” document with empty outline squares. Those future-task checkboxes must be visibly pending, not passed. Keep all titles, every Chinese label, every digit including 10,4,6, every other illustration, the two cause-to-improvement arrows, overall composition, colors and 16:9 aspect ratio exactly unchanged. Do not add any text. The image remains a “教学示例”.
```

## 视觉核对

初稿和修订图均使用 `view_image` 的 `detail=original` 查看。现场插画为 10 箱，其中 4 箱已预占、6 箱可用；漏预占的检查原因准确。两条向下分支分别指向 FlowERP 的导出结果与工作台的后续检查方法，未把 ERP 业务功能搬入工作台。修改后后续任务是空复选框，未表示已通过。中文、数字与教学示例标记清晰。

该图只解释方法与期望结果，不证明真实 FlowERP 业务完成、后续任务通过或工作台已提效。
