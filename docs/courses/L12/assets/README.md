# L12 图解与运行记录

`diagrams/` 是机制与设计示意。`latest/` 的三张 PNG 是本地实际运行数据的排版截图，不是工作台原生界面，也不是人的批准凭证。

- [采购状态、库存与流水对照](latest/receipt-compare.png)：正常、部分提交和旧键冲突来自各自独立数据库。
- [同键恢复三个时点](latest/same-key-recovery.png)：来自同一次 recovery-same-key 运行，教师移除故障后使用原键重试。
- [等待、恢复与打回](latest/wait-and-return.png)：真实 Graph 使用合成 Eval 报告与教学 reviewer；没有 Codex 开发动作。

教师旧索引及原始报告保留本机，不随 Git 发布。学生按[实践手册](../实践操作手册.md)运行已提交的[Graph 控制实验](../examples/graph_control_lab.py)与[采购批准实验](../examples/purchase_approval_lab.py)，生成本人本轮记录。需要一次采集各模式时，在仓库根目录使用已激活的课程虚拟环境，完成手册中的独立 FlowERP 项目准备后，运行[实验采集入口](../../../../scripts/audit_course_experiments.py)：

```text
python -B -X utf8 scripts/audit_course_experiments.py --lesson 12 --output-dir .runtime/l12-reference-01
```

输出目录必须尚不存在；重跑更换名称，保留失败。`summary.json` 汇总本轮结果，各 `L12-*.json` 保存对应命令、退出码、标准输出和错误。采购模式目录另有 `report.json` 与 `report.states.json`；状态快照由临时库运行后生成，包含采购申请、库存、库存流水、订单和订单明细，不是启动实验前需要的输入。新输出用于核对同类行为，不是教师历史索引及报告的原样重现。

教师历史运行中，status-write-failure 与 key-collision 的 Harness 退出码为 1，其余采购实验为 0；判断本人结果须读取本轮实际输出。Graph 包装实验使用合成 Eval 与教学 reviewer，其退出 0 只证明观察符合参考行为，不证明设计缺口已修好、Codex 已开发或真人已批准。采购实验使用真实服务与临时数据，教学批准字符串不代表具名业务验收；恢复成功也不能倒推第一次写入原子化。
