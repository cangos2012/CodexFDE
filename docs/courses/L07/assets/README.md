# L07 图解与执行证据

`diagrams/` 为教学示意图；`screenshots/hook-control-surface.png` 为既有工作台原生参考截图，不能证明本轮订单候选或 Hook 事件。

第 6 节使用两张新增教学示意图：[接入完整链路](l07-hook-install-chain.png)与[真实 Stop 调用关系](l07-hook-runtime-cycle.png)。对应 `.drawio` 源文件可编辑，`.svg` 可放大查看；图中的状态是完成判断示意，不是软件截图或学生运行证据。本次使用同一布局生成 Draw.io XML、SVG 与 PNG，未使用本机缺失的 Draw.io CLI 导出。

`latest/` 保留本轮实际命令与输出。`hook-red.json`、`hook-green.json` 是手工事件启动真实处理器及真实 Harness 的实验；`hook-reentry.json` 与 `explicit-still-red.json` 说明重入继续后缺陷仍在；`explicit-final-green.json` 是恢复公式后的显式复验。三个 PNG 根据相应 JSON 排版截图，明确标注并非原生工作台页面。HTML 为截图源。

`protocol-*.json` 调用真实参考处理器，但模拟其子进程；`order-reference.json` 是真实服务临时库实验。`index.json` 留下来源、指纹和运行索引；`injected-defect.diff` 是教师故意漏乘数量的改动。候选注册表只声明三个 L07 检查，其他 Harness 逻辑不变，不把它称为完整回归。

没有启用控制仓库 Hook，没有真实 Codex 生命周期事件，没有学生实现或具名接受。缺陷由教师注入并恢复。此处实验用于教学和反证；学生真实事件与最终交付按实践手册另行取得。
