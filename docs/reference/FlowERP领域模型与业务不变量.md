# FlowERP 领域模型与业务不变量

FlowERP 是课程的真实验证场。它不是为了把 16 讲写成 ERP 功能目录，而是用库存、订单、采购中的真实冲突检验工作台能否把一次 AI 生成变成可信交付。

## 领域对象

| 对象 | 关键字段/状态 | 课程中验证什么 |
|---|---|---|
| 商品与库存 | SKU、在手、预占、可用 | 口径唯一、非负、并发原子性 |
| 入库 | 幂等键、数量、发生时间 | 重试不能重复生效 |
| 销售订单 | draft、reserved、confirmed、cancelled | 状态机合法，取消释放预占 |
| 采购申请 | requested、approved、received | 未经人工审批不得入库 |
| 任务与证据 | task_id、case、decision、reviewer | 失败不可伪装成成功，结论可追溯 |

## 五条不可破坏规则

### 1. 可用库存不得为负

课程统一使用：

```text
available = on_hand - reserved
```

预占必须在同一事务中检查并写入。先读余额、稍后再扣减会留下并发窗口；单线程测试通过不能证明原子性。

### 2. 同一入库幂等键只生效一次

网络会重试，消息会重复。幂等不是“尽量不重复”，而是同一业务键再次到达时不改变权威库存。正确证据同时包含返回结果和数据库状态。

### 3. 订单只能按状态机迁移

非法跳转必须明确失败，且失败后订单、库存和证据账保持一致。取消已预占订单必须释放预占；不能只改订单状态而留下库存悬挂。

### 4. 采购入库必须经过具名人工审批

Eval 绿色说明质量门通过，不代表采购业务被批准。Agent、自动化或匿名布尔值不能代替审批人。审核打回后要保留理由和可恢复状态。

### 5. 任务、Eval、反馈必须可追溯

任务 ID、需求来源、Diff、用例、报告、审核和反馈之间需要稳定引用。观察级告警不能偷偷升级为阻断规则，原始反馈也不能未经审核直接改代码。

## 失败后状态怎么验

只断言“抛出了异常”不够。业务失败实验至少核对：

1. API/函数返回了预期错误；
2. 事务没有留下半写入；
3. 库存、订单或采购权威状态未被污染；
4. 错误与任务证据可追溯；
5. 同一复现命令可由他人再次运行。

## 逐讲业务增长

| 讲次 | FlowERP 验证点 |
|---|---|
| L01～L03 | 冻结边界和口径，不抢跑产品功能 |
| L04 | 工作台首次交付稳定库存导出 |
| L05～L08 | 幂等入库、可用库存、订单和原子预占成为质量资产 |
| L09～L12 | 取消释放、合法迁移、采购申请和具名审批检验协作控制 |
| L13～L15 | 补货任务、操作页和反馈小改进检验产品化链路 |
| L16 | 现场交付此前未实现的小需求，并证明旧账不受损 |

## 推荐复验入口

**Windows（PowerShell）：**

```powershell
Set-Location $env:FLOWERP_PROJECT_ROOT
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m eval.harness --suite blocking
```

**macOS（zsh）：**

```zsh
(
  cd "${FLOWERP_PROJECT_ROOT:?请先设置独立 FlowERP 仓库绝对路径}" || exit 1
  ./.venv/bin/python -X utf8 -m unittest discover -s tests -v
  printf '测试退出码：%s\n' "$?"
  ./.venv/bin/python -X utf8 -m eval.harness --suite blocking
  printf 'Eval 退出码：%s\n' "$?"
)
```

参考仓库全绿只能说明参考实现当前满足门禁，不能证明学生亲手构造了能力。

## 一手资料（核验：2026-09-04）

- [SQLite：Atomic Commit](https://www.sqlite.org/atomiccommit.html)：事务原子性与持久化边界。
- [RFC 9110：HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)：方法、状态码和幂等语义。
- [Google SRE：Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)：面向症状、可行动信号和监控边界。
