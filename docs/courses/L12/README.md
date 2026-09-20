# L12 用 Graph 显式表达状态、回退和人工审核

本讲把研发过程中的移交、打回、等待和异常写成明确状态，并用采购审批后入库检验这些控制是否对应真实业务。研发交付审核接受的是软件候选，采购审批批准的是业务单据，两者不能合并。

配套资料：[辅导资料](辅导资料.md)、[实践操作手册](实践操作手册.md)，可按需查阅。

新版[辅导资料](辅导资料.md)已展开 Graph 的组成、执行器、运行轨迹与实际边界，配套[实践操作手册](实践操作手册.md)、[行动卡](行动卡.md)、[提交模板](SUBMISSION.md)、[三阶段提示词](prompts/README.md)和 [state-handoff-review Skill](skills/state-handoff-review/SKILL.md)。[29 页主线自学 PPT](slides/L12-用Graph显式表达状态回退和人工审核-主线自学版-29页-定稿.pptx)保留六章目录，以八幅 imagegen 方法图讲解 Graph，包含可编辑正文、实验表格、总结思考和 L13 衔接。讲义末尾提供新版页码对应；旧版课件和 Word 保持原文件。教学实验不替代个人真实交付或跨事项闭环。

## Graph 控制实验

在项目根目录激活 `.venv` 后运行：

```bash
python -X utf8 docs/courses/L12/examples/graph_control_lab.py wait
```

[graph_control_lab.py](examples/graph_control_lab.py)调用真实 `agent.graph`，报告与审核人输入明确为教学替身。它不调用 Codex 开发，也不产生真实人审。十六种模式均已运行：

| 模式 | 当前实际观察 |
|---|---|
| demo | 无持久化、无人审要求的演示策略自动 completed |
| wait / resume | 等待具名审核；再次运行保持等待，不重新检查 |
| approve | 从等待批准后 completed，不重新运行 Eval |
| reject | 返回 develop，再检查后重新等待 |
| reject-at-limit | 上限 1 时打回，轮数字段变为 2 后 stopped，未再检查 |
| blocking-failure | 三轮阻断失败后 stopped；未发生真实开发 |
| eval-exception | 检查抛异常，Graph 保存 failed 与错误 |
| empty-report | 合成空结果、零阻断数也进入等待；消费者缺完整校验 |
| unknown-state | 未知状态进入 failed |
| malformed-state | 读取阶段 JSONDecodeError 直接抛出 |
| save-error | 保存阶段 FileExistsError 直接抛出 |
| stale-approval | 修改教学候选标记后仍可批准，未绑定候选或重新检查 |
| approval-without-wait | 新运行传入批准不会直接批准，仍进入等待 |
| terminal-rerun | 已完成状态再次读取保持完成，不重新执行 |
| unchecked-move | 直接调用 move 可从 develop 跳到 completed，方法未校验边 |

实验包装退出 0 表示实际行为符合观察，不表示这些行为均满足最终交付设计。真实 Harness 自身拒绝空套件，empty-report 是消费者接口反例。教学审核人字符串不提供身份认证。

## 采购审批与入库实验

```bash
python -X utf8 docs/courses/L12/examples/purchase_approval_lab.py approved --report-path .runtime/l12-first/approved.json
```

[purchase_approval_lab.py](examples/purchase_approval_lab.py)使用真实服务、临时数据库和统一 Harness。A 原来在库／预占／可用为 10／2／8，PR-TARGET 申请七件，OTHER 和 PR-OTHER 应保留。

| 模式 | 实际观察 | Harness 退出 |
|---|---|---|
| approved | 具名字段审批后 received，库存 17／2／15，一条 +7 流水 | 0 |
| unapproved / rejected | ApprovalRequired，拒绝后五表不变 | 0 |
| blank-reviewer | ValueError，五表不变 | 0 |
| replay | 相同键再次请求，五表不变 | 0 |
| different-key | 已入库后换键再请求被拒绝，五表不变 | 0 |
| status-write-failure | 教学触发器阻止单据改 received；库存已为 17，单据仍 approved，原子性检查失败 | 1 |
| recovery-same-key | 同样故障后移除触发器，使用原键重试，补齐单据状态且不重复增加库存 | 0 |
| key-collision | 使用既有 opening 键，单据 received 但库存仍 10，状态对账失败 | 1 |

两个失败来自当前实际服务行为，保留报告供学习；本次未修复产品代码。恢复同键成功不能证明第一次操作具有原子性。完整讲义将这些结果用于推导状态对账、恢复与验收，而不以流程标签代替业务事实。

## 本轮更新与下载边界

已复跑 16 种 Graph 控制实验和 9 种采购实验，新增各阶段五表快照及[三张运行记录截图](assets/README.md)。讲义和实践手册已加入逐图解释。30 页新版 PPT 与两份 Word 已同步，并完成全部 48 页的逐页检查。截图是实际运行记录的排版截图，非工作台原生界面；教学控制输入与真实业务记录已分别标明。
