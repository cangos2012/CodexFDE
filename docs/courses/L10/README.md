# L10 建立有停止条件的修复 Loop

自动重复“修改，再检查”可以减少人工搬运报告，但重复本身不会证明进展。本讲以订单合法发货与非法迁移为案例，学习一轮检查怎样决定下一轮，以及停止之后应保留哪些事实。

工作台要组织有边界的返工，FlowERP 要同时恢复合法状态迁移与非法状态拒绝。只有合法路径也通过，才能排除“把所有请求都拒绝”的错误修复。人决定目标、文件范围和资源约定，Codex 执行，Harness 独立复验。

配套资料：[辅导资料](辅导资料.md)、[实践操作手册](实践操作手册.md)，可按需查阅。

先读[辅导资料](辅导资料.md)，再按[实践操作手册](实践操作手册.md)完成实验和个人交付。配套[行动卡](行动卡.md)、[提交模板](SUBMISSION.md)、[三阶段提示词](prompts/README.md)与 [loop-stop-review Skill](skills/loop-stop-review/SKILL.md)。[29 页主线自学课件](slides/L10-建立有停止条件的修复Loop-主线自学版-29页-插图重设计.pptx)从同一个 FlowERP 发货失败展开，依次讲清决策轮、停止依据、真实轨迹和学生交付。课件中的参考记录不代表真实 Codex 完成修复，也不代表学员达成或具名接受。

## 观察真实 Loop 的十二种控制路径

[loop_control_lab.py](examples/loop_control_lab.py)调用实际 `agent.loop.run_loop`，使用明确标注的合成报告和执行器替身。没有真实模型调用，用量也是合成数值，时间边界使用替身时钟。

在项目根目录激活项目 `.venv` 后运行，将模式替换为下表各项：

```bash
python -X utf8 docs/courses/L10/examples/loop_control_lab.py converge
```

| 模式 | 实际观察 | 检查次数／替身执行次数 |
|---|---|---|
| already-green | 第一轮 converged | 1／0 |
| converge | 修改后下一轮检查通过 | 2／1 |
| repeated | stopped_no_progress | 2／1 |
| changed-reason | 名称相同、原因变化仍停止 | 2／1 |
| oscillating | A、B、A 交替失败，到轮数上限 | 3／3 |
| last-repair | 最后一轮已修改，尚无后续检查 | 1／1 |
| token-budget | 预算 100，单次使用 150 后停止 | 1／1 |
| missing-usage | 没有正用量时停止 | 1／1 |
| time-budget | 替身时钟显示超时，未调用执行器 | 1／0 |
| executor-error | TimeoutExpired 直接抛出，无结构化结果 | 1／1 |
| empty-report | 注入空 results，参考 Loop 返回 converged | 1／0 |
| dry-run | 只生成草案，两轮同名失败后停止 | 2／0 |

包装实验退出 0 表示观察与当前实现一致，不表示所有处理都符合最终设计。尤其空报告、异常退出和末轮未复验，需要在个人实现与验收中进一步处理。真实 Harness 自身会拒绝无可执行用例，empty-report 是替换报告生产者的接口反例，不应写成默认 Harness 会产生空绿灯。

## 连接订单的真实状态

[订单迁移实验](examples/order_transition_lab.py)使用真实 ERPService、临时数据库和 Harness。A 在库 10，OTHER 已预占 2，TARGET 申请 4。

```bash
python -X utf8 docs/courses/L10/examples/order_transition_lab.py legal --report-path .runtime/l10-order-01/legal.json
```

合法预占后发货应得到 TARGET=shipped，在库／总预占／可用为 6／2／4，OTHER 不变。将模式换为 draft-ship、cancelled-ship 或 double-ship，并分别使用新报告路径，应拒绝非法动作且四表不变。refuse-all 是教学错误修复：连合法发货也拒绝，Harness 应失败。

每个模式先预测，再运行并解释。参考实验不修改自己的产品候选；自己的 Loop 交付还须保留真实失败、实际修复、独立复验和停止记录。


## 本轮新增的真实代码轨迹

[候选实验](examples/candidate_loop_lab.py)用真实 Loop 和新进程 Harness 检查同一候选：两次检查一次补丁后收敛；不改文件后停止；末轮补丁后停止、循环外审计才通过。配套讲义和实践已补入逐步解释与三张截图，详见[证据说明](assets/README.md)。这是预设补丁实验，不是 Codex 自动修复。新版讲义 Word 共 11 页、7 幅图，实践手册共 6 页、3 幅图；两份 Word 和 30 页 PPT 均已逐页检查。
