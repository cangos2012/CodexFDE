# FDE 负责人故事图：ImageGen 生成记录

- 生成日期：2026-10-04（Asia/Shanghai）。
- 生成方式：内置 `image_gen.imagegen`；未使用 API、CLI 或代码绘图。
- 工具调用：1 次全新生成，无参考图；`transparent_background: false`。
- 用途：少字故事图，解释研发负责人贴近用户和业务数据，参与判断与交付，检验使用后果并把方法留给下一事项。
- 事实边界：教学示意；不构成已发生的客户交付、验收或提效证据。
- 原始输出路径：`C:\Users\Administrator\.codex\generated_images\01a106e9-671f-74d3-809f-b589000318cc\exec-010c436c-f0b4-4090-95a6-089dc8927900.png`。
- PNG 大小：1620929 字节。
- PNG 尺寸：1672 × 941 像素（横向 16:9 构图）。
- 原始 PNG SHA256：`FBA6F32FF702CD8963ECD572DC7895E946C23E172CA24F452C049AE6117BEBC0`。
- 工作区副本：`docs/reference/assets/fde/story/01-fde-responsibility-imagegen-v1.png`。
- 副本 SHA256：`FBA6F32FF702CD8963ECD572DC7895E946C23E172CA24F452C049AE6117BEBC0`；复制核对一致，原始输出保留。
- 视觉核对：使用 `view_image(detail: original)` 查看。同一位研发负责人和同一用户贯穿看问题、交付和下一事项；Codex 仅为辅助笔记本；使用反馈返回库存表核对；库存表与订单取消为连续业务对象；大字少字，未堆 Spec/Eval 机制词。
- 写入范围：仅本 PNG 与本记录；未改正文、索引和其他图片。

## 提示词序列 1：全新生成（实际完整提示词）

```text
Use case: infographic-diagram
Asset type: a short Chinese story illustration introducing FDE to beginner readers.
Primary request: Generate a brand-new landscape 16:9 course illustration. Very large readable navy Chinese lettering, warm off-white background, restrained pale blue/teal panels, teal progression arrows and orange feedback. Functional light isometric people, paper inventory tables and customer-order objects. The same navy-clothed human engineer with short dark hair is the clear main character in all three scenes. Codex is only a small supporting laptop/document tool, never the protagonist. Keep a lot of white space. Few words, large pictures, no dense explanation, no terminology table.

Title verbatim: “FDE：在现场把问题解决，并留下可复用的方法”
Small subtitle verbatim: “Forward-Deployed Engineering”

Three equally large, clearly separated scenes from left to right:
1) Heading verbatim “和用户看问题”. The human engineer stands together with a shop/warehouse user, looking at the same inventory sheet and shelves. The sheet is visibly an inventory table and its only short label is “库存表”. A small user speech bubble verbatim “还能接多少订单？”. The engineer is listening and verifying the actual records with the user, showing closeness to people and business data.
2) Heading verbatim “把结果交到用户手里”. The same engineer hands the corrected inventory sheet to the same user, who tries to use it beside the goods. The sheet's only prominent numerical label is “可用量 6”. The engineer stays present to observe use and check whether the result solves the user's problem. Put a tiny quiet laptop in the background labeled “Codex” as supporting tool only. No real app screen, no test pass stamp.
3) Heading verbatim “让下一次有方法可用”. The same engineer and user now review an order-cancellation sheet next to a small method notebook. Label the order sheet exactly “订单取消”, and the method notebook exactly “旧方法，新检查”. The method notebook visibly comes from the earlier inventory work; illustrate transfer without implying old checks prove new behavior. Same engineer responsible for deciding and checking the new situation.

A short teal arrow clearly connects scene 1 to scene 2 and scene 2 to scene 3. These mean one continuous customer problem leads to delivery and then supports later work. A short orange feedback arrow starts at the user's inventory use in scene 2 and returns into scene 1's shared examination, labeled exactly “使用反馈”. Its endpoints must be obvious and it must not cross people or labels.
A compact bottom line exactly “同一位负责人，持续判断、交付、检验后果”.
Footer exactly “教学示意”.

Constraints: Render all Chinese text verbatim, legible and large. Keep in-image Chinese extremely sparse; use only the exact labels above and no additional explanation. Do not add Spec, Eval, Harness, workflow/mechanism tables, automatic evolution, automatic publishing, green completion stamps or fake real delivery records. This diagram explains human FDE responsibility and consequences; do not turn it into an AI-centered process. Inventory table and the later order are continuous business objects. Do not draw three disconnected jobs with different accountable people.
```
