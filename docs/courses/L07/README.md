# L07｜用 Codex Hooks 建立本地护栏

订单已经写完，最后一次改动却没有经过检查。本讲从这个遗漏出发，将统一 Harness 接到 Codex 生命周期中，并通过工作台交付草稿订单。

配套资料：[辅导资料](辅导资料.md)、[实践操作手册](实践操作手册.md)，可按需查阅。

先读[辅导资料](辅导资料.md)，理解触发时点、协议、重入与信任，再按[实践操作手册](实践操作手册.md)完成实验和自己的候选。课堂执行可用[行动卡](行动卡.md)，分阶段委托见[提示词](prompts/README.md)，交接使用[提交模板](SUBMISSION.md)。

配套两个可运行实验：[真实订单状态](examples/order_state_lab.py)、[参考处理器协议](examples/hook_protocol_lab.py)。前者使用临时数据库，后者使用子进程替身，都不启动真实 Codex 会话。自己的项目还须验证真实事件与修复后的候选。

本讲将可复用判断提炼为 [hook-evidence-review](skills/hook-evidence-review/SKILL.md)。它帮助核对证据，不执行 Hook 或代替人审。

当前投影通过 `hook_staging/` 交付待审查 Hook，人工安装后再验证真实事件，保留 `.codex` 执行保护。操作与证据边界见[手册第 5～6 节](实践操作手册.md)。

[33 页 PPT（全套参考第 06 讲）](slides/L07-用CodexHooks建立本地护栏-全套参考L06-33页.pptx)用于对照讲义学习。L08 将继续把同一套检查放到独立环境中复验，并处理库存原子预占。

新增 [订单合同检查](examples/order_contract_checks.py)与[真实子进程证据](assets/README.md)，将金额失败、重入仍红和恢复结果对应到 7 个连续案例。
