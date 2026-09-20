# L11 用 Codex 原生 Subagents 并行处理独立任务

配套资料：[辅导资料](辅导资料.md)、[实践操作手册](实践操作手册.md)，可按需查阅。

采购申请既需要测试补全，也需要风险审查。本讲先固定业务与接口，再组织两个独立子任务，最后由主 Agent 回查证据、串行整合并统一复验。

从[辅导资料](辅导资料.md)理解采购状态、读写依赖、上下文与执行边界、结果追溯和成本判断。按[实践操作手册](实践操作手册.md)完成本地实验及个人协作，使用[行动卡](行动卡.md)、[提交模板](SUBMISSION.md)、[三阶段提示词](prompts/README.md)和 [parallel-task-review Skill](skills/parallel-task-review/SKILL.md)。[29 页主线自学课件](slides/L11-用Codex原生Subagents并行处理独立任务-主线自学版-29页-定稿.pptx)以同一张采购申请贯穿六个章节，保留完整目录、方法图解、总结思考与 L12 衔接。

## 两类可运行实验

在项目根目录激活 `.venv` 后运行：

```bash
python -X utf8 docs/courses/L11/examples/schedule_lab.py independent
python -X utf8 docs/courses/L11/examples/purchase_request_lab.py normal --report-path .runtime/l11-first/normal.json
```

[声明实验](examples/schedule_lab.py)有十种模式，调用真实冲突检查器，展示同写、读写、目录、路径别名和共享报告冲突。漏报真实读取时可能返回允许，所以声明通过不能替代独立性判断。

[采购实验](examples/purchase_request_lab.py)有七种模式，使用真实服务和临时数据库。正常申请保留编号、商品、数量与原因，库存仍为 10／2／8；五种拒绝验证五表不变；premature-stock 提前增加库存，应被 Harness 判为失败。重复编号当前抛数据库完整性错误，不是幂等成功。

以上 17 种实验已在参考环境实际运行；它们不调用原生子代理，不修改个人候选，也不证明学员已经完成并行交付。真实活动、个人实现与整合复验按手册留存。

## 同版整合案例

[新增实验](examples/integration_lab.py)已经实际运行：同一错误候选的原采购检查通过，独立库存检查失败；教师移除提前入库动作后，整合版本七项检查通过。[三张截图与原始记录](assets/README.md)支持逐条回查。本轮讲义补入案例原因、操作与判断，实践、提示词和 Skill 同步加入。

29 页主线自学 PPT 按优化后的 Markdown 讲义重新组织，教师实验与 imagegen 方法示意分别标注。《辅导资料》Word 已同步最新主线，实践操作手册 Word 保持原版。原生并行仍需要本人实际子任务活动，不能用上述顺序实验代替。
