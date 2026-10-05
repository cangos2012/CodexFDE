# L13 图解与运行截图

`diagrams/` 为机制示意；`latest/` 为实际 HTTP 记录的排版截图，不是工作台原生界面。

- accept-query：按同一任务核对 202、evaluating、review。
- retry-conflict：同键重放与三次内容冲突；观察任务和 Spec 文件的不同结果。
- completed-restart：三个真实服务进程中的中断恢复与完成后重启。

原始响应在 latest/http-report.json、latest/restart-report.json；全部来自隔离任务库与真实课程 Eval。教学审核字段不代表实际人员批准，未执行 Codex 开发或采购入库。首次扩展实验的响应结构断言失败保留在私有 restart-r1；修正查询对象后 restart-r2 通过，未修改产品行为。
