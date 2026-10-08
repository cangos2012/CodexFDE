# L07 分阶段提示词

先由本人完成首次预测，再按[调查](01-确认事件与来源.md)、[实现](02-连接检查与候选.md)、[复核](03-核对触发与恢复.md)委托。填入实际候选和允许范围；提示词中的任务不会因阅读而执行。

[Hook 证据审查 skill](../../../examples/skills/hook-evidence-review/SKILL.md)可直接作为本次审查参考。若希望通过名称调用，将完整 `hook-evidence-review` 文件夹安装到自己已配置的技能目录，按当前 Codex 的技能发现方式确认加载，再明确调用该名称。只有实际加载与响应才算采用记录，复制文件不等于行为有效。

先用[三个反例](../../../examples/skills/hook-evidence-review/references/review-cases.md)检查判断，再提供真实材料。保留 AI 初稿和本人修订，不让模型填造事件或同伴签名。
