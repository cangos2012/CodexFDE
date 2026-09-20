# L08｜把同一套 Eval 接入 CI

配套资料：[辅导资料](辅导资料.md)、[实践操作手册](实践操作手册.md)，可按需查阅。

先读[辅导资料](辅导资料.md)，再按[实践操作手册](实践操作手册.md)完成本地实验、个人候选与真实远程复验。配套[行动卡](行动卡.md)、[提交模板](SUBMISSION.md)、[提示词](prompts/README.md)及 [skill](skills/ci-candidate-evidence-review/SKILL.md)已集中。

本讲只围绕一个交接判断展开：原子预占是客户交付，A 假绿 → B 可信红用于证明检查流程能诚实暴露失败，B 可信红 → C 可信绿用于证明业务在同一标准下恢复正确。候选身份、运行环境、报告归档和信封哈希都用于核对这次对照是否可信。

[完整课堂 PPT：图解课堂版](L08-把同一套Eval接入CI-图解课堂版.pptx)共 30 页，其中 16 页使用 ImageGen 图（新增 8 张，复用 8 张），围绕一张订单展开：先算业务结果，再拆开 A/B/C 的两次修复，最后交给同伴独立复验。图页以机制图、结果对照和情境提问展开，每页保留一句讲解，并标明辅导资料小节。状态表、短代码和行动步骤仍可编辑，四节开始前保留完整目录。长命令与操作细节由实践手册承接。[图文对应索引](assets/imagegen-classroom-20260917/README.md)和[教学覆盖安排](../教师资料/L08/slides/PPT大纲.md)列出页码、来源、实践动作与提交证据。原版与前一版保留供对照；课件中的教师本地实验不代表学生已经完成远程 CI。

## 先理解整单预占

客户要 A 两件、B 三件。若 A 足够、B 不足，系统应拒绝整张订单的预占。只显示“库存不足”还不够：如果 A 已经被占用，其他订单会失去这两件可用库存。我们需要同时观察库存余额、预占记录、订单明细和订单状态。

[原子预占实验](examples/atomic_reservation_lab.py)调用真实的正式销售服务 `SalesService`，使用临时数据库，不调用 Codex，不连接远程平台，也不读取个人运行数据库。

在项目根目录激活本项目 `.venv` 后，分别执行：

```bash
python -X utf8 docs/courses/L08/examples/atomic_reservation_lab.py pass
python -X utf8 docs/courses/L08/examples/atomic_reservation_lab.py shortage
python -X utf8 docs/courses/L08/examples/atomic_reservation_lab.py write-error
```

| 模式 | 起点与操作 | 预期观察 |
|---|---|---|
| pass | A、B 各 5 件，申请 2 与 3 | reserved 为 2、3；available 为 3、2；订单 reserved |
| shortage | A 有 5 件，B 仅 2 件，仍申请 2 与 3 | 拒绝；预占均为 0；available 仍为 5、2 |
| write-error | 两种库存均足够，在第二条预占记录插入时注入故障 | 报错；预占均为 0；available 仍为 5、5 |

后两种模式比较运行前后的 `stock_balance`、`stock_reservations`、`sales_document_lines` 和 `sales_documents`，要求完整观察结果相等，订单仍为 confirmed。包装实验退出 0 表示这些预期已得到验证，不表示缺货请求成功。

## 为什么还要第二次写入故障

当前服务先规划所有明细，再写入。普通缺货可能在任何预占写入之前就被发现。因此，“缺货之后没残留”还没有直接检验写到一半时的回滚。

`write-error` 在本次临时数据库安装一个明确标注的 SQLite 触发器，让 B 的预占记录插入失败。它触发在真实写入路径中；事务应撤销前面已经发生的相关变化。这个实验能补充顺序检查遗漏的观察，但不等于已经证明所有并发竞争、中断或发布故障都安全。

## 明确自己测的是哪个服务

L07 的入门例子使用 `ERPService` 创建草稿。这里跟随 L08 正式销售用例，使用 `SalesService`；正式订单需要先 confirm 再 reserve，因此失败后保持 confirmed。这两个服务的接口与底层表不同，不能把一边的状态名称或报告当成另一边的实现证据。

个人候选应在 Spec 写明实际交付入口；若同时保留入门门面和正式产品入口，就分别核对相关数据和状态。当前 `sales_credit_and_atomic_reservation` 默认检查是一行缺货，不能替代本实验的两行及中途写入故障覆盖。

运行前先预测三组结果，再打开源码找到独立期望和四表比较。将数量改为新组合后重新手算；保留实际运行结果和本人判断，不能把这里的预期表抄成自己的执行记录。
