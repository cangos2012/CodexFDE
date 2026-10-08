# L04｜分步 Prompt

先读实践操作手册，再按顺序使用下面四个 Prompt。每一步都消费上一步的真实材料，不一次性要求 Codex 生成整份作业。

1. `01-设计能力信封并留下TicketA红灯.md`：调查并建设 Ticket A。
2. `02-独立验收V0再授权库存导出.md`：整理可交给真实复验者的材料。
3. `02b-引用Spec执行TicketB.md`：用有效 A 和 L03 确认版 Spec 启动 Ticket B。
4. `03-独立复验inventory_export.md`：在同一候选核对实际 CSV、业务状态和范围。

使用时把示例路径、姓名和任务编号替换为真实值。Codex 可以调查、起草、修改和整理证据；需求确认、执行授权与接受／打回仍由实际人员决定。

需要持续协助时，采用 [controlled-delivery-handoff](../../../examples/skills/controlled-delivery-handoff/SKILL.md)。它会根据当前成果选择 V0 建设、独立复验或首次客户执行阶段，承接 AGENTS 与两类 Spec，并指导实际改动、检查和过程截图。已有 V0 的部分直接复用；尚未建好的部分先在 A 补齐。

可直接输入：“请使用 L04 的 controlled-delivery-handoff skill，根据我前几讲的 AGENTS、工作台 Spec 和已有代码，定位 V0 缺口，在已授权范围补齐并展示执行过程。先完成 A，再判断是否满足通过 V0 执行 B 的条件。”
