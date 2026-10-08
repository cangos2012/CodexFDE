# L01 学习记录流程图生成提示词

工具：内置 imagegen。用途：L01 实践操作手册的个人行动与学习记录对应图。

Use case: infographic-diagram
Asset type: a Chinese beginner-friendly educational flowchart embedded in the L01 practical manual of the CodexFDE course.
Primary request: Generate one exceptionally clear diagram explaining exactly when the learner takes an action and which personal learning record to update. The audience has said the current text is confusing. Show only the learner's actions and records; omit internal program processing. All lettering must be precise and easy to read.
Style/medium: polished flat editorial infographic, restrained navy/teal accents, warm-white background, dark high-contrast type, no photographic elements. Minimal clean rounded rectangular nodes, generous spacing, a clear single vertical downward flow. Landscape composition, approximately 4:3, high resolution suitable for reading long English filenames. Do not compress or shrink filename labels.
Composition: one title at top, then SIX stacked horizontal stages. Each stage has three clearly aligned columns: a small stage/time column, a plain Chinese action column, and file labels in a third column. Connect only the stages with simple downward arrows in the left margin. Keep all file labels inside their own stage, no crossing arrows. At the bottom place a separate quiet horizontal strip for the two cross-stage index files. No invented code, UI controls, decorative icons or extra prose. Use gentle consistent fill for the six main stages; file labels look like readable document labels. Every filename below must appear verbatim, without substitutions, missing hyphens, typos or truncated text.
Exact visible text:
Title: "L01：做一步，留一份记录"
Column headings: "什么时候" | "你要做什么" | "记录在哪里"

Stage 1:
"第 1 步"
"留下最初想法"
"写清问题、首次判断与设计"
Files on separate lines:
"01-problem.md"
"01-first-judgement.md"
"02-design.md"

Stage 2:
"第 2 步"
"确认需求"
"核对范围与验收，亲自确认并签署"
Files on separate lines, with these small explanatory labels:
"WORKBENCH_SPEC.md · 需求正文"
"02-spec.md · 决定与依据"

Stage 3:
"第 3 步"
"解释真实失败"
"亲自运行测试，说明缺少哪项能力"
Files on separate lines:
"reason.md · 有效失败目录内"
"02-spec.md · 追加测试与失败索引"

Stage 4:
"第 4～5 步"
"审查与复验"
"确认修改计划 → 审查改动 → 本人复验"
File:
"04-diff.md"

Stage 5:
"第 6～7 步"
"使用新工作台"
"预测查询 → 实际操作 → 核对结果"
"检查导入前后、错误查询与恢复查询"
File:
"06-bootstrap.md"

Stage 6:
"第 8 步"
"复盘、迁移与签收"
"解释修订，尝试新场景，决定是否接受"
Files on separate lines:
"07-revision.md"
"08-transfer.md"
"09-authorship.md"

Bottom strip, separate from the six-stage arrow sequence:
"贯穿全程：00-handoff.md · 当前进度与下一步"
"最后整理：SUBMISSION.md · 全部材料的总索引"

One small clear footer:
"Codex 可协助整理；个人判断与签署由本人完成。"
"箭头表示操作顺序。"

Constraints: This is a learning-action diagram, not automatic file ingestion. Do not draw a database, command outputs, SHA-256, meta.json, output.txt, robots, ERP, app architecture or technical background. Do not imply test success equals human acceptance. Make all Chinese text correct. No watermark.
