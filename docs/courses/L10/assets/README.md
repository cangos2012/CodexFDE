# L10 图示与真实记录

`diagrams/` 是机制示意，解释发货状态、循环顺序、停止条件与历史保存设计，不能当成运行截图。

教师历史记录曾汇总 17 次参考过程：12 项控制实验明确使用合成报告、替身执行器或时钟；5 项订单实验调用实际入门服务与临时数据库。前四项订单路径退出 0，refuse-all 退出 1。旧索引及原始报告保留在教师本机，不随 Git 发布。学生按[实践手册](../实践操作手册.md)运行[控制实验](../examples/loop_control_lab.py)和[订单实验](../examples/order_transition_lab.py)，在自己的新目录保存本轮输出。控制包装器退出 0 表示观察符合参考行为，不表示所有控制分支设计正确；旧退出码不能替代本轮结果。

## 三条代码候选轨迹

- [修复并收敛：repair 模式](../examples/candidate_loop_lab.py)：历史参考运行中，循环内两次检查、一次预设补丁，四项原检查最后通过。
- [不改动而停止：no-change 模式](../examples/candidate_loop_lab.py)：历史参考运行中，两次检查、一次不改文件动作，相同失败与相同服务内容，停止后审计仍失败。
- [末轮修复后停止：last-repair 模式](../examples/candidate_loop_lab.py)：历史参考运行中，一次检查、一次补丁；Loop 带旧失败返回达到上限，之后循环外审计才通过。

在本仓库根目录使用已激活的课程虚拟环境，先按实践手册完成独立 FlowERP 项目准备，再生成自己的三条轨迹：

```text
python -X utf8 docs/courses/L10/examples/candidate_loop_lab.py repair --run-dir .runtime/l10-candidate-01/repair
python -X utf8 docs/courses/L10/examples/candidate_loop_lab.py no-change --run-dir .runtime/l10-candidate-01/no-change
python -X utf8 docs/courses/L10/examples/candidate_loop_lab.py last-repair --run-dir .runtime/l10-candidate-01/last-repair
```

每个 `--run-dir` 必须尚不存在；重跑更换 `l10-candidate-01`，不覆盖旧过程。脚本在本轮目录写入 `index.json`、逐轮报告、子进程输出、可取得的前后状态、任务、Diff、Loop 结果与循环外审计。新输出用于核对同类行为，不是教师历史记录的原样重现。

已发布的 `loop-converged.png`、`loop-stopped.png`、`loop-last-repair.png` 是教师历史记录的排版截图，不是原生工作台界面；截图对应的原始报告及排版 HTML 保留本机，不作为公开下载材料。

候选由教师复制并注入总是拒绝发货的条件，执行器是确定的教学补丁，不是 Codex。用量 1 是明确的协议占位，不是实测 Token。报告来自真实 Harness 的四项显式用例，不是全套 blocking；核心 Loop 未修改。新增适配器将每轮写入新目录并验证报告，这不能证明默认 Loop 已具备同样的记录隔离与输入校验。

错误版本的重复用例在首次发货阶段已经失败，尚未保存后续快照；因此该文件缺失不能被填成“重复拒绝已验证”。修复后四项结果、状态和检查指纹可对账。

教师一次 no-change 准备候选遇到临时文件读取拒绝，尚未进入业务检查。失败目录保留在教师工作区；随后改为读取原始源内容并在新目录运行成功，未覆盖失败记录。重跑应使用全新目录，脚本拒绝覆写。

这些材料不证明真实模型修复、实际模型预算、执行器逐文件强制权限、正式销售页面或负责人具名接受。个人交付需另外保存本人实现和真实调用。
