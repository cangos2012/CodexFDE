# 系统架构解释图：生成记录

生成方式：Codex 内置 `image_gen.imagegen`，一次生成、两次内置编辑。未调用 CLI/API fallback，未编辑像素。

用途：解释工作台的模块职责、调用方向与数据归属。图按当前源码简化，完整调用与存储说明见[工作台具体设计](../../工作台具体设计.md)。配图是设计说明，不能替代真实交付、运行或验收证据。

最终项目图片：[workbench-system-architecture-imagegen-v1.png](workbench-system-architecture-imagegen-v1.png)。

内置最终输出：`C:\Users\Administrator\.codex\generated_images\01a10189-ea10-79b1-b8f2-8552c9478568\exec-88ad86be-fdec-454a-b878-8a6aa295816f.png`。

尺寸：1672 × 941。SHA-256：`12108ab08dd55609d436cb3911f45a760b9c29c310286dba4e0514d8dc80846f`。

检查：已逐字核对标题、模块、端口、数据库与文件名称；已核对人的入口、事项到执行与检查、采用与结果回流、执行器调用 Codex、FlowERP 独立数据边界。首稿的调用与数据连线错误在内置工具中修正。最终项目图片与内置输出哈希相同。

## 1. 原始生成提示词

```text
Use case: infographic-diagram
Asset type: 中文工程教材的系统架构解释图，供初学者理解个人 AI 研发工作台的真实模块职责和数据归属。
Primary request: 生成全新的横向 16:9 信息图。精确标题“系统架构：工作台组织研发，客户项目运行业务”。这是职责与数据架构图，不是开发步骤时间轴。
Style: 高质量中文教材平面信息图；暖白背景，深蓝文字，蓝色控制模块，青绿色执行模块，橙色数据与证据，浅灰色外部项目；大字号中文黑体，清晰横向文字，留白充足。不要照片、3D、无关机器人或装饰。
Composition: 主体分为左侧“人的入口”、中间一个大圆角容器“工作台（8001）”、右侧两个彼此独立的外部区“Codex CLI”和“客户项目：FlowERP（8000）”。工作台容器宽约全图一半。下方为工作台数据区域，右下方为客户业务数据区域。必须表现工作台是同一个本机应用，内部服务共享 SQLite，不是独立微服务。
Nodes and exact labels:
左侧：“人”；其下两行小字“确认与授权”“验收与决定”。
工作台顶部：“页面与 HTTP 入口”。
工作台中部左节点：“事项服务”，小字“问题 · 方案 · 轮次”。
工作台中部右节点：“经验与流程治理”，小字“来源 · 审核 · 采用”。
工作台下部并列两个节点：“执行器”，小字“复制候选 · 调用 Codex”；“项目检查”，小字“候选中运行质量命令”。
工作台数据区两张橙色卡片：“workbench.db”，小字“研发状态与决定”；“候选与证据文件”，小字“Spec · 源码 · Diff · 报告”。
右侧上区：“Codex CLI”，小字“读取源码，修改候选”。
右侧下区：“客户项目：FlowERP（8000）”，内含“独立仓库与运行环境”“业务服务”“flowerp.db：库存 · 订单 · 采购”。
Arrows and accuracy:
人通过双向箭头与“页面与 HTTP 入口”连接，箭头分别清晰表达提交动作与显示状态。
“页面与 HTTP 入口”指向“事项服务”和“经验与流程治理”。
“事项服务”指向“执行器”与“项目检查”，表示组织执行和检查。
“经验与流程治理”向“事项服务”提供“采用版本”，另从事项服务收到“交付结果”；两根短箭头方向清楚。
“事项服务”和“经验与流程治理”向 workbench.db 保存记录。
“执行器”调用右侧 Codex CLI；Codex CLI 与“候选与证据文件”之间清晰标明“修改候选”，不能画成直接修改 flowerp.db 或原项目。
“项目检查”指向候选与证据文件，标“检查与报告”。
客户项目的“独立仓库与运行环境”通过一根细箭头向“执行器”提供“源码与检查入口”；客户业务服务连接自己的 flowerp.db，不能连接 workbench.db。
底部总结精确文字：“研发记录属于工作台，业务状态属于客户项目。”
最底小字：“按当前源码简化职责关系；不表示内部依赖已完全单向化。”
Constraints: 所有文字必须准确，workbench.db、flowerp.db、Codex CLI、FlowERP 拼写正确。箭头尽量短，禁止绕图交叉的杂乱连线。所有节点都必须连接到正确所属区域。不要把工作台画成拥有或修改客户运行数据库。图示表达控制与数据归属，不暗示自动部署或真实验收已完成。
```

## 2. 职责连线修订提示词

```text
Edit this architecture infographic. Keep the exact title, the warm white/blue/teal/orange teaching style, Chinese typography, the human role, all responsibility labels, and the independent FlowERP business boundary. Correct misleading wiring by redesigning the interior layout with fewer, unambiguous arrows. Every arrow must touch the box it really connects.

Layout:
Human remains at far left and connects bidirectionally only to the page.
Workbench is a single large center container. Top is “页面与 HTTP 入口”.
Second row: “事项服务” on the left, “经验与流程治理” on the right.
Third-to-fifth rows on the right half of workbench: vertically stack “执行器”, then “项目检查”, then “候选与证据文件”.
Under “事项服务” in the left half: “workbench.db”, subtitle “研发状态与决定”.
Codex CLI is outside workbench at the right, level with “执行器”, so execution can call it with a short straight horizontal arrow.
FlowERP independent container is below Codex at far right. Keep its three labels “独立仓库与运行环境”“业务服务”“flowerp.db：库存 · 订单 · 采购”. At the top of that container add the small caption “登记源码路径与质量入口”.

Only these call/data arrows:
人 ↔ 页面与 HTTP 入口.
页面与 HTTP 入口 → 事项服务; 页面与 HTTP 入口 → 经验与流程治理.
经验与流程治理 → 事项服务, label “采用版本”; 事项服务 → 经验与流程治理, label “交付结果”.
事项服务 → 执行器, label “组织执行”; 事项服务 → 项目检查, label “组织检查”. These must reach two different boxes.
事项服务 → workbench.db, label “保存记录”.
执行器 → Codex CLI, label “调用 Codex”. This must start at 执行器, never at 项目检查 or FlowERP.
执行器 → 候选与证据文件, label “源码副本与输出”.
项目检查 → 候选与证据文件, label “检查与报告”.
Inside FlowERP: 独立仓库与运行环境 → 业务服务 → flowerp.db.
No other arrows. In particular, remove the unlabeled vertical FlowERP-to-Codex arrow and any project-check-to-execution arrow. Do not draw cross-boundary arrows between business databases and workbench.

Do not label the evidence files as SQLite data. DB and files are separate storage items inside the workbench boundary.
Codex CLI subtitle must be “在候选目录修改代码”, to explain its work location without extra wiring.
Footer exact: “研发记录属于工作台，业务状态属于客户项目。”
Small footer exact: “按当前源码简化职责关系；不表示内部依赖已完全单向化。”
All Chinese and English text must be exact and highly readable. Plenty of blank space; no crossed arrows. This is a responsibility architecture diagram, not a time-sequence pipeline.
```

## 3. 调用箭头局部修正提示词

```text
Make exactly ONE local wiring correction to this image. Preserve every card, word, layout, color, and every other arrow.
The blue horizontal arrow labeled “调用 Codex” starts at the right edge of “执行器”, but its arrowhead incorrectly ends on the “客户项目：FlowERP(8000)” container.
Replace only that call arrow with a clean orthogonal path:
start at exactly the same right edge of 执行器;
move right into the blank vertical gap between 工作台 and the two external containers;
turn upward in that blank gap;
then turn right and finish with ONE arrowhead at the LEFT EDGE of the TOP “Codex CLI” green card.
The endpoint must visibly touch Codex CLI, around its vertical center, NOT FlowERP.
At native 1672×941 dimensions, roughly route from (1016,480) to (1195,480) to (1195,280) to (1246,280). Coordinates are only placement guidance and MUST NOT appear as printed text.
Keep the label “调用 Codex” next to the correct path and keep the path away from all card text.
There must be no call arrow entering the FlowERP card. No other pixel region, diagram text, or node position should be changed.
This arrow means 执行器 calls Codex CLI; it never means 执行器 calls FlowERP to modify the live business database.
```
