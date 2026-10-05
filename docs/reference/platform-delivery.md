# 2026-10-04 个人研发平台实现与验收记录

本轮完成四阶段代码和首页接线：共享运行与证据门、项目计划和受管多 AI、辅助草稿与 v2 流程、本机预览发布和迁移。高级能力须显式启用；默认日常入口仍为 8001 根路径。自动测试、真实进程运行、客户交付和真人验收分别判断。

功能接线不证明商用稳定性。后续故障修复、恢复边界、短时并发及本轮复验见[工作台稳定性与可用性记录](workbench-reliability.md)。

## 修改范围

| 能力 | 实现位置与变化 |
|---|---|
| 统一执行 | `delivery_runtime.py` 接管日常提交与子任务；`workbench_server.py` 在持有运行目录租约时标记中断，不重放；`harness_compatibility.py`、`platform_server.py`、`platform_api.py`、两个 CLI 让 8010 新操作转交工作台，旧库只读。 |
| 授权和证据 | `evidence_gate.py`、`project_delivery.py`、`course_workspace.py`、`task_store.py` 绑定任务、冻结 Spec、质量配置、候选、报告和进程回执；`mutation_receipts.py` 先登记幂等收据，再执行副作用；`tool_registry.py`、`project_runner.py` 和运行核心核对一次性工具授权。`shell_provider.py` 拒绝 Git 诊断输出文件和外部转换，回执区分原请求与实际执行 argv。 |
| 项目与分工 | `project_plan.py` 保存目标、里程碑、依赖和架构基线，检测循环和阻塞；`subagent_coordination.py` 拒绝冲突；`execution.py` 使用候选独立锁和受管进程；worker 默认 2，可准备为 3/4，串行合并后复验父候选。 |
| 经验和流程 | `learning_generation.py` 隔离只读生成，保留独立输入、输出与取消记录；`learning.py`、`daily_delivery.py`、`initiative_workflow.py` 执行 v2 四阶段约束、缺失证据停止和独立复验；v1 原始版本不改写。 |
| 预览与发布 | `project_configuration.py`、项目登记和存储保存版本化 JSON argv；`generic_preview.py` 管理非 FlowERP 候选服务；`deployment.py`、`deployment_process.py` 管理具体制品、具名授权、进程、禁止重定向的健康探针、业务复核和明确回退。 |
| 迁移与备份 | `migration.py`、`reference_paths.py`、`workbench_backup.py` 保留数据库和证据原文，以独立映射解析路径，并复验源码、Git、解释器及当前依赖；环境复验绑定映射文件哈希，映射变化后必须重新复验。进程及退出回执纳入哈希校验。`file_io.py` 为短暂 Windows 文件锁提供有界读重试和原子控制文件替换。 |
| 首页 | `workbench_web/platform.js`、`platform.css`、首页及既有事项/草稿/经验脚本提供上述入口；请求带预期服务和数据实例。读取失败、错误事项、缺失实例头或实例变化会冻结关键操作，保留人工草稿。 |

新增专项覆盖执行控制、授权消费、子任务与预算、生成隔离、v1/v2、通用预览、发布失败、迁移及恢复。既有文件锁测试保留实际等待再检查当前磁盘内容，避免把全进程 `time.sleep` 改成无等待；并未更改报告合同、接受条件或课程裁判。

## 实际命令与结果

命令在本仓库执行，使用 `.venv\Scripts\python.exe`；独立 FlowERP 命令在 `D:\work\flowERP` 执行。完整运行日志保存在忽略的 `.runtime/platform-acceptance/`，不加入源码交付。

| 检查 | 实际命令或证据 | 结果及含义 |
|---|---|---|
| 首轮全量 | `python -X utf8 -m unittest discover -s tests -v`；`full-unittest.log` | 630 项，6 失败、14 错误、2 跳过；保留原始失败。 |
| 中间全量 | `python -B -X utf8 -m unittest discover -s tests -v`；`full-unittest-final.log` | 658 项，3 失败、2 错误、2 跳过；除两项课程资料问题外，出现 Windows 文件锁及受干扰的读重试检查，随后修复或单独复验。 |
| 文件锁与相关门闩 | `python -B -X utf8 -m unittest tests.test_file_io tests.test_project_report_file_io tests.test_runtime_file_io_integration tests.test_course_workspace tests.test_workbench_migration tests.test_personal_platform -q` | 54/54 通过；包括永久拒绝保留旧文件、当前报告与回执、课程隔离、迁移和接受拒绝路径。 |
| 前端 | `node --test tests/*.test.cjs` | 114/114 通过。 |
| 工作台阻断 Eval | `python -B -X utf8 -m eval.harness --suite blocking --no-report`；最终冻结后 `blocking-release.log` | 12/12 通过，退出码 0；第一次并行检查出现本地夹具超时，失败日志保留，未放宽超时。 |
| 独立 FlowERP 基线 | `python -B -X utf8 -m eval.harness --suite blocking --report-path D:/work/CodexFDE/.runtime/platform-acceptance/flowerp-readiness/blocking-report.json` | 19/19 通过，仅证明既有业务基线。 |
| 最后全量 | `python -B -X utf8 -m unittest discover -s tests -v`；`full-unittest-release.log` | 667 项，663 通过、2 失败、2 跳过；995.847 秒，退出码 1。剩余两项均为下述课程资料问题，没有代码测试失败。 |
| 最后增量复验 | 迁移后的运行上下文、证据与命令投影等 19 个模块；`platform-affected-final.log` | 200/200 通过；310.139 秒，退出码 0。这组检查覆盖全量启动后补入的迁移隔离门闩。 |
| 映射身份复验 | `python -B -X utf8 -m unittest tests.test_workbench_migration -q` | 18/18 通过；17.833 秒，退出码 0。覆盖复验后映射变化、原库与历史证据保持不变。 |
| 工具诊断补验 | `python -B -X utf8 -m unittest tests.test_shell_provider tests.test_tool_registry tests.test_providers tests.test_delivery_runtime -q` | 43/43 通过；73.230 秒，退出码 0。真实 Git 正常诊断可执行，危险参数在写入前拒绝，登记源码字节不变。 |
| 差异检查 | `git diff --check` | 通过；仓库只提示既有 LF/CRLF 转换策略。 |

两项课程资料问题分别是：本机忽略的 `docs/courses/L16/实践操作手册.md` 仍引用讲师侧 `PROGRESSION.json` 的旧目录；`docs/courses/国家级一流本科课程建设方案.md` 和 `docs/courses/国家级一流本科课程申报级质量门.md` 缺失。治理资料检查在独立 HEAD 文本快照重跑仍失败，旧路径检查在只包含已登记文件的 HEAD 快照通过。本轮未修改这些课件或删除检查。最后全量启动后补入的修改，由上述增量、迁移与工具诊断检查分别验证；不把专项通过写成全量绿灯。后续可靠性全量检查发现本记录也重复了旧目录字面值，现已移除该重复引用。

## 真实进程与服务现场

本轮默认端口 8001 被 `D:\work\ai-manufacturing-copilot\main.py --serve-api` 占用，保留该制造业服务。开发工作台运行于独立目录 `.runtime/platform-acceptance` 和 `http://127.0.0.1:8101/`，启用代码执行和高级运行；8010 兼容入口明确指向 8101。独立 FlowERP 基线运行于 `http://127.0.0.1:8100/`，数据放在 `flowerp-baseline`，工作台客户地址指向该真实服务；没有把 8000 上的其他服务当作 ERP。

实际启动命令：

```powershell
.venv\Scripts\python.exe -B -X utf8 -m workbench.cli serve-workbench --port 8101 --runtime-dir .runtime/platform-acceptance --enable-code-execution --enable-advanced-runtime --erp-url http://127.0.0.1:8100
.venv\Scripts\python.exe -B -X utf8 -m workbench.cli harness-serve --port 8010 --workbench-url http://127.0.0.1:8101 --bootstrap
# 以下在独立 FlowERP 仓库执行
.venv\Scripts\python.exe -B -X utf8 -m flowerp serve --port 8100 --runtime-dir D:\work\CodexFDE\.runtime\platform-acceptance\flowerp-baseline
```

最终代码重启后，`final-http.json` 记录 11 项读取检查均返回 200：工作台、兼容入口、FlowERP live/ready，以及工作台根页、平台脚本、样式、项目、Profile、指标和迁移计划。数据实例保持不变，服务实例更新；携带旧 `X-Workbench-Expected-Service-Instance` 的写请求在副作用前返回 409。现场脚本最初误写了健康路径和预期实例请求头，出现 404/400，校正后通过；不修改服务来迁就脚本。上一轮浏览器控制不可用；后续稳定性复验已读取真实首页、截图和浏览器日志，完整交付点击及业务验收仍未验证。

实际 Codex CLI `0.160.0` 在合成开发项目中启动两个 worker，各自候选得到范围内修改和独立补丁，登记源码保持不变。真实回执分别报告 183,493 和 177,250 Token，总计 360,743；本次父预算为 30,000，父运行停止后续步骤并保留失败。该记录是实际 CLI 与预算停止的验证，不是客户交付通过。预算在调用结束后核算，在途请求可能超额；没有可核验用量时也停止后续启动。

该运行的高级记录与 129 个文件完成备份、包校验和原路径恢复，恢复库与包内 SQLite 快照字节一致，全部表记录一致，未重放。最初错误地与备份前在线 SQLite 文件比较的记录也保留为 `backup-restoration-initial.json`，修正比较对象后在 `backup-restoration.json` 记录结果。

## 真人验收与剩余边界

独立 FlowERP 源码仍为 `e0088d3a11ae68b7e23c2c6986167b87768d909e`，工作区无改动。已准备真实源码、基线报告哈希、A/B/C 范围与失败治理操作卡；商品、客户、供应商空导出表头分别为 10/9/9 列。需求尚待业务确认，负责人、独立审核者和业务验收人尚无实际署名。没有创建假的接受、流程发布、客户发布或提效结论。

真实 A 来源 → 独立流程审核 → B 试用并接受 → 发布流程 → C 复用，以及真实失败停用/修订，需要按[独立 FlowERP 验收操作卡](platform-acceptance.md)在首页完成。该链仍待执行和真人验收；当前可核验机制与合成测试不能替代它。真实另一台机器的外部环境也未现场验证，迁移机制在独立本机目录复验。

操作与迁移命令见[个人研发平台运行参考](personal-platform.md)。本轮实现纳入本地源码提交，尚未推送；运行数据库、报告、客户数据和密钥不纳入 Git。
