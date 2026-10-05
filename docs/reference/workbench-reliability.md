# 工作台稳定性与可用性：2026-10-04 至 05 加固记录

当前不能认定商用达标。此前验收证明了受控功能路径和部分真实进程行为，尚未证明长期运行、真实负载下的恢复能力与业务可用性。本轮继续修复实际故障，保持本机个人使用、独立客户仓库和具名验收边界；不增加课程必做前置条件。

## 已修复的故障

| 故障 | 修复及判断依据 |
|---|---|
| 网络或 JSON 响应挂起，提交按钮一直锁住 | 所有请求都有涵盖网络和 JSON 读取的期限；GET 10 秒、普通 POST 30 秒、项目克隆/执行方案准备 120 秒。写请求超时保留结果未知，不自动重放。 |
| A 事项晚到响应覆盖新页面或解锁 B 的提交 | 按事项和请求 token 管理待处理写；视图版本隔离响应。返回 A 后仍需读取当前记录，旧响应不能覆盖证据或草稿。 |
| 刷新后丢掉未知提交键，可能再发一次副作用 | 运行、发布、预览、项目计划/配置、迁移和草稿生成等经统一高级提交入口的请求，发送前按数据实例保存最小待核对记录，只含请求路径、提交键、开始时间与固定标签。刷新只恢复提示；手动 GET 核对回执后可明确结束提示。完整成功响应可清除自己的提示；失败、未知和未找到回执都不自动清除。普通讨论、接受等旧 workflow 写请求尚未全部使用这份日志。 |
| 慢请求无限占用线程或拖延请求体读取 | 工作台最多接收 32 个连接，超额在分派前返回 503；连接空闲期限 10 秒，请求体总期限 10 秒，滴流不能持续延长期限。拒绝含冲突长度/分块传输的请求；Windows 拒绝路径有有界排空，避免用 TCP reset 吞掉正常 503。 |
| 服务活着却读不了数据库，仍给绿色健康结论 | `/api/health/live` 只证明进程可响应；`/api/health/ready` 核对数据库、实例、恢复阻断和至少 256 MiB 空间。旧 `/api/health` 也投影真实就绪结论。数据库缺失、损坏或身份不符时拒绝数据 API，不创建替代空库；低空间阻断新操作，仍允许可核对的暂停/取消。 |
| 存储或内部异常只导致断连，无法定位结果 | 返回结构化 503/500 与请求编号，日志记录编号、方法、路径及异常类型；响应不暴露异常原文。写入可能已有副作用时标记结果未知，不能自动重试。 |
| 关闭后仍能启动，审批线程交接与关闭竞争 | 关闭门闩先停止新运行和授权；线程登记与启动同锁。关闭按已拥有的事件、进程和线程收尾，撤销未消费授权，保留中断。 |
| 预览等待健康探针时，关闭被同一把锁阻塞 | 通用及旧 FlowERP 兼容预览在启动阶段就登记真实进程；独立关闭信号可先停止进程，健康等待可中断。旧入口也拒绝关闭后的启动，并在关闭时收尾拥有的日志 reader；失败不追加启动成功事件，不重放。 |
| Windows 拒绝慢滴流或过大请求时，用 TCP reset 吞掉错误回执 | 未读完请求体不再标记为已消费。先 flush 完整错误回执并半关闭发送端，再按总 0.2 秒及 1 MiB 上限排空输入。业务体积上限不变；慢滴流仍按原期限停止，拒绝路径不进入业务处理。超出有界排空量或客户端已断连仍可能收不到响应，应保留结果未知并核对。 |
| 崩溃恢复重置未落盘时间或把未知调用按零 Token 续跑 | 恢复记录 UTC 起止，保守向上结转耗时并包括停机间隔；缺起点或时钟倒退耗尽旧时间。已发出但未终结的调用标记用量未知，不能恢复旧预算或自动启动后续步骤，须重新确认新方案。 |
| 缺库或关闭持久化失败，留下进程或补出空库 | 关闭使用禁止创建的数据库连接；先发送停止信号，存储失败仍继续停止受管资源。一项收尾失败也不跳过其它组件及监听 socket 的关闭。 |
| 原库丢失后重启，自动建立空库掩盖历史缺失 | 已有会话目录、恢复标记或数据库日志但缺原库时，在初始化前拒绝启动；恢复原库后才可正常启动。首次新目录仍可初始化；明确创建替代库后具有新的数据实例身份，不能沿用旧页面授权。 |
| 同名备份包覆盖原包，发布失败破坏历史 | 临时包由本次独占创建，同卷 no-clobber 发布；碰撞或卷不支持时安全失败，源数据与已有包保留。 |
| 恢复写入/清理失败留下可启动的半套数据 | 安装前持久化未完成标记；成功才移除。失败尽力清理所有安装路径，保留原异常及阻断标记；失败目录不能被当作完整恢复启动。 |

## 2026-10-05 冗余收敛

本轮收敛重复入口、重复请求和重复资源管理，保留课程合同、历史证据与必要的独立守卫。冗余减少不能单独证明商用稳定性达标。

| 重复或缺陷 | 收敛后的职责 |
|---|---|
| `WebExecution` 的日常入口自行开线程并直接交付 | 仅为已确认事项的授权适配，绑定原方案、事项版本和 Profile；由原事项工作流与 `DeliveryRuntime` 执行。重复授权读取原结果，不确定或重启中断不重放。课程隔离执行保留。 |
| 渲染、轮询和手动刷新分别发起运行/发布读取，慢响应不断过期 | 渲染只显示缓存；同一事项、视图版本与资源共享在途请求。写操作和事项切换使旧读取失效，新的手动核对走统一刷新入口。 |
| 任务面板与事项面板使用不同预览协议 | 共用读取方案与明确确认入口；登记配置的项目预览绑定持久计划、候选及配置版本，旧视图的迟到方案不能用于当前授权。旧 FlowERP 兼容预览保留当前证据检查和启动时配置守卫，尚未采用持久冻结的预览计划。 |
| FlowERP 兼容预览、通用预览和本机发布重复处理进程及日志 | `ManagedProcess` 负责管道排空、日志/有限尾部、Windows 启动门闩和 Job 子树终止，以及 reader 收尾；预览与发布各自保留证据、健康探针及状态判断。关闭失败仍保留资源所有权，可再次收尾；启动等待期间配置变化则阻断旧计划。它不新增调度队列或执行核心。 |
| 查询一条生成记录再扫描最近 1000 条 | 直接读取目标记录，列表与单条共用投影；仍核对所属事项和输入/输出哈希。1001 条合成记录实测，新旧两条目标均只执行 2 次 SELECT；清理前最新记录为 2004 次，最旧记录抛出 `StopIteration`。 |
| 8010 保留第二套写界面，与工作台授权及配置协议漂移 | 页面只查询原历史、Profile 与 Session；从成功健康响应取得真实上游入口。共享模式不构造旧自动队列；独立 Harness CLI 与历史只读能力保留。 |

主要修改位于 `workbench/web_execution.py`、`platform_api.py`、`harness_compatibility.py`、`candidate_preview.py`、`generic_preview.py`、`deployment.py`、`deployment_process.py`、`process_guard.py`、`project_configuration.py`、新增 `managed_process.py`、`learning_generation.py` 和 `workbench_server.py`，以及 `workbench_web/` 的刷新/预览逻辑和 `harness_web/` 的兼容页。同时删除已核对无引用的成员及导入，不删除授权、证据有效性、课程兼容或独立客户边界。

生成查询专项 `python -B -X utf8 -m unittest tests.test_learning_generation -v`：17/17，通过，61.947 秒，日志 `redundancy-generation-green.log`；最终查询专项 3/3，通过，0.107 秒，日志 `redundancy-generation-lookup-final.log`。查询计数来自独立合成 fixture 的 `redundancy-generation-query-proof.py` / `.json`；它不包含真实生成或真人验收。修复前红灯保留在 `redundancy-generation-red.log`。

执行适配最终相关检查 44/44，通过，27.622 秒；运行核心及课程/终端兼容检查 63/63，通过，67.262 秒。实际命令分别为 `python -B -X utf8 -m unittest tests.test_execution_consolidation tests.test_daily_delivery tests.test_web_execution tests.test_harness_compatibility tests.test_harness_platform -v` 和 `python -B -X utf8 -m unittest tests.test_delivery_runtime tests.test_execution_streams tests.test_harness_terminal tests.test_course_initiative_binding tests.test_maintenance_workers -v`；日志 `execution-consolidation-compatibility-final.log`、`execution-consolidation-core-green.log`。红灯与未知授权回执故障均保留，使用独立 fixture，不调用真实模型或修改客户源码。

前端 `node --test tests/*.test.cjs` 最终 144/144，通过；日志 `frontend-redundancy-all-node-final.log`。兼容页 Python 合同 `python -X utf8 -m unittest tests.test_harness_web_dashboard -v` 为 8/8，通过；日志 `harness-compatibility-page-tests.log`。旧 8010 写界面的合同由日常工作台已有事项、授权、执行和验收测试承接，新合同保留只读、客户边界和非官方产品等价检查。内嵌浏览器在实际 8010 核对入口指向 8101、两项 Profile、零项新 Session 和旧库只读历史，error/warn 为空；记录 `refactoring-compatibility-browser.json`。原浏览器草稿未重载，没有代填业务验收。

8010 的 JS、HTML 与 CSS 三文件相对 HEAD 从 4312 行收敛为 176 行，删除第二套写界面及其样式；准确计数和当前文件哈希见 `refactoring-source-proof.json`。该数字只描述这三个文件，不代表整个仓库的冗余比例或商用品质。

备份门闩专项 `python -B -X utf8 -m unittest tests.test_workbench_reliability -v`：15/15，通过，11.408 秒；日志 `preview-backup-busy-green.log`。关闭失败的 fixture 即使父进程已退出且没有成功预览记录，残留资源也阻止真实备份；二次关闭成功后，实际创建 ZIP 并通过校验。修复前误判可备份的红灯保留在 `preview-backup-busy-red.log`。

进程专项 `python -B -X utf8 -W error::ResourceWarning -m unittest tests.test_managed_process tests.test_candidate_preview tests.test_generic_preview_reliability tests.test_deployment -v`：45/45，通过，51.471 秒，退出码 0，无 ResourceWarning；日志 `.tmp/process-consolidation-learning-audit/final-extended-tests.log`。覆盖日志写入失败后继续排空、reader 部分启动失败、关闭失败保留所有权及重试、残留资源的繁忙状态，以及通用和兼容预览等待期间的配置竞争；实际备份阻断由上述 15 项专项另外核对。失败发布仍保存原执行回执和独立清理失败回执。新增竞争与清理故障的红灯保留在同目录 `cleanup-and-configuration-red.log`。进程树终止的本轮现场证据限于 Windows Job；POSIX 当前只终止直属进程，同等启动门闩和子树守卫尚未实现，也未完成跨系统验证。

本轮独立现场复验使用 `python -B -X utf8 .runtime/platform-acceptance/final_http_check.py before-refactoring-restart.json refactoring-final-services.json`：14 项读取均为 200；重新启动 8101 后原数据实例保持不变，旧服务实例写入返回 409。8010 的健康响应包含真实上游 8101 与兼容标记。临时浏览器页核对 8101 首页、8100 客户链接、09:07:01 读取时间及桌面截图，error/warn 为空；证据 `refactoring-workbench-browser.json`。用户原标签和草稿未重载，临时检查标签已关闭。本轮没有操作 8001 制造服务，也没有修改独立 FlowERP 源码；这些检查没有产生真实事项或真人业务验收。

首轮全量 `python -B -X utf8 -m unittest discover -s tests -v`：752 项，747 通过、3 失败、1 错误、2 跳过；1094.736 秒，退出码 1，日志 `full-unittest-refactoring.log`。两项失败仍为下表所列课程材料问题。新增 Graph 错误明确为保存临时状态时 `PermissionError`；另一项失败为 V0 的 Spec 读取返回 400，原回执仅说明无法读取，未保留更细的底层原因，不能直接断言同一原因。

随后复用已有文件守卫补齐两处遗漏：`agent/graph.py` 保存使用原子替换，临时 Windows 分享锁可有限重试，永久拒绝保留原待审字节；`TaskStore.create_v0` 使用当前文件的有限重读，永久拒绝及重读后无效合同仍不创建任务。Graph 新增及原相关检查 14/14，通过，5.409 秒；命令 `python -B -X utf8 -m unittest tests.test_graph_persistence tests.test_persisted_state_file_io tests.test_workbench.WorkbenchTests.test_graph_persists_human_review_and_resumes_with_named_approval tests.test_workbench.WorkbenchTests.test_graph_trace_reaches_human_review tests.test_workbench.WorkbenchTests.test_graph_rejects_anonymous_review -v`，日志 `graph-persistence-green.log`。Spec、V0 与 HTTP 组合 40/40，通过，18.941 秒；命令 `python -B -X utf8 -m unittest tests.test_runtime_file_io_integration tests.test_workbench_v0 tests.test_workbench_optimizations_http -v`，日志 `v0-spec-read-green.log`。分享锁故障注入可重现遗漏，原失败分别保留在 `graph-persistence-red-final.log`、`v0-spec-read-red.log`；没有增加第二套重试实现或放宽检查。

加载文件守卫修复后再次只重启本任务的 8101 验收服务，先以只读数据库核对活动计数均为零，再核对监听与进程命令身份。最终 HTTP 命令为 `python -B -X utf8 .runtime/platform-acceptance/final_http_check.py before-io-guards-restart.json refactoring-io-guards-services.json`，14 项读取均为 200，原数据实例保留、旧服务实例写请求仍为 409；它不代替前述浏览器核对或真人业务验收。

第二次全量 `python -B -X utf8 -m unittest discover -s tests -v`：758 项，753 通过、3 失败、2 跳过；1085.040 秒，退出码 1，日志 `full-unittest-refactoring-after-io.log`。Graph 恢复和 V0 的原失败均通过；除两项课程问题外，新增生成用例失败：新 `input.json` 的过程证据哈希读取遭 `PermissionError`，覆盖了原有“引用不在登记证据内”的错误。来源任务仍保持不变，该生成仍为失败；它不能被记为全量绿灯或成功生成。

随后把生成模块的四处读取接到已有文件守卫；已解析的物理路径用空映射范围保护，避免其它运行目录的迁移映射再次重定向。临时文件锁有限重读，永久读取失败仍阻断采用，同时保留原生成错误及其它已保存证据。使用真实 Windows 排他文件句柄覆盖临时锁与永久锁，来源任务不变；`python -B -X utf8 -W error::ResourceWarning -m unittest tests.test_learning_generation -v` 为 19/19，通过，82.215 秒，退出码 0，无 ResourceWarning。红灯、绿灯及源码哈希分别保存在 `.tmp/generation-file-lock-learning-audit/red.log`、`green.log`、`frozen-validation.json`。

Spec 读取进一步明确为本次传入的物理文件，不接受其它运行目录的迁移映射重定向。新增映射隔离用例先出现红灯；实现时曾把字符串数据库路径误当作 `Path` 使用，组合检查产生 2 失败、26 错误，原日志 `v0-spec-read-physical-green.log` 保留，文件名不代表成功。修正类型转换后，原 Spec、V0 与 HTTP 组合最终 41/41，通过，18.998 秒，退出码 0；日志 `v0-spec-read-physical-final.log`，实际命令仍为 `python -B -X utf8 -m unittest tests.test_runtime_file_io_integration tests.test_workbench_v0 tests.test_workbench_optimizations_http -v`。

加载最终生成和 Spec 修复后，只重启本任务的空闲 8101 服务。只读数据库活动计数均为零，监听 PID 和命令身份已核对；`python -B -X utf8 .runtime/platform-acceptance/final_http_check.py before-generation-io-restart.json refactoring-generation-io-services.json` 的 14 项读取均为 200，数据实例不变，旧服务实例写入返回 409。此时 8001 由制造业服务监听，本任务没有操作该进程；独立 FlowERP 仓库 `git status --short` 为空。现场读取不代表完成真实业务交付或真人验收。

最终第三次全量 `python -B -X utf8 -m unittest discover -s tests -v`：761 项，757 通过、2 失败、2 跳过；1211.434 秒，退出码 1，日志 `full-unittest-refactoring-final.log`。没有新增错误或失败；Graph、V0 和生成读取的原故障均通过。两项失败仍分别来自本机忽略的旧 L16 手册引用，以及 HEAD 中缺失的两份治理文档；两项跳过是未显式启用的本地 PPT 检查。检查与原失败保留，全量不能记为全绿。

最终阻断 `python -B -X utf8 -m eval.harness --suite blocking --report-path .runtime/platform-acceptance/blocking-refactoring-final.json`：12/12，通过，退出码 0；日志 `blocking-refactoring-final.log`。默认只检查工作台契约，不证明独立 FlowERP 业务通过或真实 A→B→C 闭环完成。

Graph 实际 CLI 在新的独立目录 `.runtime/platform-acceptance/graph-cli-refactoring-final/` 运行 `D:\work\CodexFDE\.venv\Scripts\python.exe -B -X utf8 -m agent.graph --max-rounds 3 --require-human-review --state-file delivery.json`。原子保存的状态为 `awaiting_human_review`，一轮，报告 12/12；退出码 3 表示待具名审核，审核人、决定与时间均为空，没有代填批准。日志 `graph-cli-refactoring-final.log`，持久状态及报告哈希核对见 `graph-cli-refactoring-final-proof.json`；不覆盖其它 Graph 运行现场。

测试完成后，`python -B -X utf8 .runtime/platform-acceptance/final_http_check.py before-generation-io-restart.json refactoring-after-tests-services.json` 再次核对 14 项读取均为 200、原数据实例保留、旧服务实例写入被 409 拒绝。8101 为本次验收进程；8010 兼容页、8100 独立客户服务与 8001 制造服务的监听 PID 均保持本次最终重载前的值，记录 `refactoring-listeners-final.json`。这只证明检查时的响应与监听，不是长期可用性指标；独立 FlowERP 仓库仍无源码修改。

## 用户遇到故障时

页面出现“结果待核对”时，先读取原回执和当前事项。回执“已受理”只证明请求登记完成，不证明编码、发布或业务验收完成；“未找到”也不能证明没有副作用。核对后可以结束本机提示，但它不撤销授权、不删除证据，也不改变验收结果。待核对记录不保存署名、授权正文、业务正文或调用参数。浏览器存储不可写时，相关高级提交在发送前停止。

服务返回 503 时，保留输入并查看 `/api/health/ready`。数据库或恢复状态不完整时停服修复原数据，不能让新空库替代历史。请求编号用于在当前服务日志中定位异常，日志不记录请求正文。没有确认结果的写请求不要通过刷新或换键强行重发。

启动提示“缺少原数据库”时，保留整个目录及数据库日志，核对原库或经过验证的备份。不要删除会话目录、恢复标记或日志来绕过检查。所有历史目录及标记都被人为删除的情况，目前无法仅凭剩余空目录识别；此检查不替代独立备份。

备份发布卷需要支持同卷硬链接；不支持时本次备份失败，不覆盖历史包。失败恢复目录和标记应作为证据保留，使用经过核验的包在新的空目录重试。备份校验只证明包内完整性，不能代替外部项目、解释器、客户数据和密钥的恢复。

## 商用仍缺的依据

- 没有持续多日的运行及真实任务负载记录；短时并发请求不等于可用性承诺。
- 没有定义并实测故障恢复时间、允许丢失数据的时间窗口、异机独立备份恢复和断电持久化；目前仍为本机备份及有界故障注入。
- 进程由本机命令启动，尚无经过故障演练的操作系统服务托管、监测告警与版本升级流程。不会自动重放写入来伪装恢复成功。
- 当前具名操作是本机个人工具的记录边界。若作为多人联网产品提供服务，仍需真实账号、身份认证、权限隔离和受保护的审计存储。
- 预算仍在可核验用量返回后停止后续步骤，不能严格封顶已在途的模型请求。
- 调研等旧链路还需逐条完成受管关闭与中断演练；POSIX 同等子树守卫尚未实现，长时间负载和跨系统行为也待实测。
- 服务关闭统一请求预览收尾，失败仍需继续处理；尚缺单项预览的显式停止界面。预览和长期部署均缺持续退出观察器与资源状态自动回收；自然退出后，未收尾登记仍可能阻断备份，需显式操作完成清理。长期部署页面可能仍显示原待业务审核记录；业务复核会再次检查进程和健康，失败时阻断，需人工核对或回退。
- 旧 FlowERP 兼容预览仍在启动时核对当前证据与配置，不保存并消费浏览器展示的冻结预览计划；不能据此宣称所有历史预览均已采用通用计划协议。
- 真实 FlowERP A→B→C、独立具名审核和发布后的业务效果尚待完成，不能用故障测试或演示数据替代。

## 冗余收敛前的加固验证

以下保留冗余收敛前的实际结果，不代表本轮最终全量绿灯。命令均使用本仓库 `.venv\Scripts\python.exe -B -X utf8`，没有操作 8001 制造业服务，测试 fixture 不代表真人验收。

| 检查 | 实际结果与日志 |
|---|---|
| 前端 `node --test tests/*.test.cjs` | 128/128，通过；`frontend-mutation-journal-tests.log`。涵盖超时、切换、刷新、未知键、隔离、存储失败及只读核对。 |
| 备份/迁移/故障专项 | 42/42，通过，19.927 秒；`.tmp/backup-reliability-learning-audit/test-results.txt`。其中新增故障 7 项，保留修复前红灯。 |
| 运行、进程、预览、发布及服务组合专项 | 75/75，通过，99.454 秒；最后守卫与缺库收尾增量 21/21，通过，19.548 秒。两组存在重叠，不相加为独立覆盖数。 |
| 缺库启动专项 | `python -m unittest tests.test_workbench_optimizations_http.WorkbenchRestoreStartupTests -v`：5/5，通过，0.760 秒；`reliability-startup-after.log`。覆盖保留原库、恢复标记、残留日志、首次与明确替换实例，以及完整恢复不自动重放。 |
| 最后 HTTP、启动、事项与项目复验 | `python -B -X utf8 -m unittest tests.test_workbench_optimizations_http tests.test_initiative_workbench tests.test_project_registration -q`：24/24，通过，7.939 秒；`reliability-startup-projects-final.log`。首次组合发现超限中文请求也被重置连接，以及旧恢复 fixture 只有标记没有数据库；分别修复拒绝连接收尾、补齐真实恢复 fixture 的数据库，原失败日志保留。 |
| Windows 请求拒绝复验 | 34/34，通过，32.976 秒；`slow-drip-oversized-green-final.log` 第一行保存完整 argv。慢滴流用例重复 10 次，每次 3 个真实 socket；超限用例重复 5 次，每次普通 72 KiB 与超 512 KiB V0 请求；原 HTTP 超限用例重复 5 次，再跑完整 14 项服务专项。重复数不等于独立用例覆盖数；原慢滴流与超限红灯日志均保留。 |
| 旧 FlowERP 兼容预览 | `python -X utf8 -W error::ResourceWarning -m unittest tests.test_candidate_preview -v`：6/6，通过，7.152 秒；`legacy-preview-shutdown-after-final.log`。真实进程处于启动闸门或健康等待时均在 2 秒内停机，无进程、端口、日志 reader 残留；原兼容成功与重用通过。修复前 2 失败及 1 错误的日志保留。 |
| 预览基类兼容 | `python -X utf8 -W error::ResourceWarning -m unittest tests.test_generic_preview_reliability tests.test_personal_platform.PersonalPlatformTests.test_non_flowerp_preview_owns_process_and_rejects_consumed_plan -v`：3/3，通过，5.835 秒；`legacy-preview-super-close-compatibility.log`。 |
| 全量发现 | `python -m unittest discover -s tests -v`：707 项，702 通过、2 失败、1 错误、2 跳过；1041.058 秒，退出码 1；`full-unittest-reliability.log`。错误为本轮慢滴流请求被 Windows 重置连接，须以随后专项修复结果单独报告，不能把本次全量记为绿灯。 |
| 课程失败复查 | 移除本记录引入的旧路径字面值后，两项仍失败，0.668 秒；`course-baseline-reliability.log`。剩余旧路径来自本机忽略的 L16 手册；两份治理文档在 HEAD 亦缺失。保留课件与检查，不跨本轮边界还原已删除的治理材料。 |
| 阻断 Eval | `python -m eval.harness --suite blocking`：最后 12/12，通过，退出码 0；`blocking-reliability-final.log`。契约夹具通过仍不代表客户业务或商用可用性通过。 |
| 独立端口现场读取 | `python .runtime/platform-acceptance/final_http_check.py before-reliability-final-restart.json reliability-final-services.json`：最后 14 项读取均 200；工作台重新启动，数据实例保持不变，旧服务实例写入返回 409。8001、8100、8010 原服务 PID 未变。 |
| 只读并发 `python .runtime/platform-acceptance/reliability-smoke.py` | 8 并发、200/200 成功，6.422 秒，P95 0.360 秒、最大 0.406 秒；`reliability-smoke.json`。当前工作台 0 个真实事项，属于短时低数据量检查。 |
| 合成数据量检查 `python .tmp/readonly-load-learning-audit/run_read_load.py` | 独立动态端口，1000 个 Mock 事项、1000 个空闲流程和 10000 条合成事件；8 并发、200/200 GET 成功，1.806 秒，P95 121.622 ms、最大 624.142 ms。10 页取回全部 1000 条，无重复或遗漏，默认首页排除全部 Mock；读取前后数据库 SHA256 相同。结果 `.tmp/readonly-load-learning-audit/result-fixture-r3ghw8kt.json`，服务及 fixture 已清理。经分页预热的短时本机合成负载，不含真人审核、模型调用或客户写入。 |
| 首页浏览器读取 | 本轮可使用实际内嵌浏览器，最后服务重新启动后再次在临时检查页核对首页、客户地址 8100、读取时间 2026-10-05 00:07:09 和桌面截图；浏览器 error/warn 记录为空。未重载用户原页面，未创建客户验收或完成完整业务点击链。 |

日志位于忽略目录 `.runtime/platform-acceptance/`，备份故障专项位于上述 `.tmp/` 路径。首轮新增就绪检查使用了错误表名且未显式关闭 SQLite 连接，复验发现后修复；服务组合命令也曾误写两个不存在的测试模块，原错误日志保留。后续按实际模块与全量发现检查，不能把这些失败改写为成功。

运行组合 75 项与增量 21 项的证据是工具原输出，没有补造文件日志。75 项的实际命令是 `python -B -X utf8 -m unittest tests.test_delivery_runtime tests.test_execution_streams tests.test_generic_preview_reliability tests.test_candidate_preview tests.test_personal_platform.PersonalPlatformTests.test_non_flowerp_preview_owns_process_and_rejects_consumed_plan tests.test_deployment tests.test_workbench_reliability -q`。备份 42 项使用 `.tmp/backup-reliability-learning-audit/run_checks.py`，前端使用 PATH 上的 `node --test tests/*.test.cjs`，合成负载脚本见上表。

## 2026-10-05 提交前核对

L13～L16 学生材料已在本地提交 `1902dbf`，L16 手册旧路径随该提交修复。课程相关复验为 61 项，60 通过、1 失败；剩余失败要求两份此前已删除的内部治理文档存在，未恢复文档或削弱检查。日志为 `.runtime/platform-acceptance/l13-l16-course-final.log`。这不改写上述历史全量的两项失败，也不是重新执行全量测试。

本次代码提交前重新运行前端 15 个 `tests/*.test.cjs` 文件，PowerShell 展开文件列表后传给 `node --test`，144/144 通过，退出码 0；日志为 `.runtime/platform-acceptance/frontend-all-code-current-node.log`，前后文件哈希一致。阻断命令为 `python -B -X utf8 -m eval.harness --suite blocking --report-path .runtime/platform-acceptance/blocking-all-code-commit.json`，12/12 通过，退出码 0。68 个待提交 Python 文件语法解析与暂存差异检查通过。未重新运行长期现场负载或真人业务验收。

上一轮证据见[平台交付记录](platform-delivery.md)，业务验收见[操作卡](platform-acceptance.md)。本轮实现纳入本地源码提交，尚未推送；运行数据库和原始报告留在本机。
