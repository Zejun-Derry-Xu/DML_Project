# ReturnFlow 集成验证与待开发清单

日期：2026-10-14。基于 MVP/RAG 分支及公开数据评测分支集成，未引入早期的复杂实验分支。

## 已接入实际项目

- 原有聊天状态机、规则优先 + 可选 Qwen 提取、确定性退货判断保持分层。
- 网页新增 **Ask policy**：调用真实 `/api/v1/policy/ask`，显示版本、来源和降级提示；不代替用户回答退货追问，也不修改退货状态。
- 默认使用本地词法检索 + 政策原文回答，无需模型或向量数据库。可选 Qdrant/Ollama 路径仍保留，但本轮不启动 Qdrant。
- `make demo` 统一启动 API、网页、独立 SQLite 演示库，自动迁移和幂等创建十个虚构订单，不修改 `.env`。
- 公开数据清洗/评测代码作为独立工具纳入项目，数据和逐条轨迹不进入 Git，也不会导入业务订单表。

## 真实运行验证

不是只有 TestClient：实际启动了 Uvicorn、Vite 和文件型 SQLite，通过 HTTP 和浏览器进行了验证。

| 检查 | 实际结果 |
| --- | --- |
| 规则模式 HTTP 冒烟 | 32/32 通过，修复后的实测耗时约 0.10 秒；不是负载测试 |
| 混合模式 HTTP 冒烟 | 32/32 通过，最终可观测版本约 6.70 秒；7 次模型成功、3 次规则充分，不是逐请求 p95 |
| 模型停止后的真实请求 | HTTP 200，回退规则、继续问退货原因，无模拟 RMA；记录 `model_error_rules_fallback` |
| API/UI 关闭后同库重启 | 先前会话恢复为 `return_created`，模拟 RMA ID 相同 |
| 网页 | 实际提交政策问题、显示 P-WINDOW；完成追问/确认/创建；刷新后只显示一次恢复消息 |
| 数据库迁移 | 新库应用 0001→0002；`alembic check` 无模型漂移 |
| 前端 | 构建与 ESLint 通过 |
| 回归与静态检查 | 178 项测试通过；Ruff、应用与新增脚本的严格 mypy 通过；保留一条现有测试客户端弃用警告 |

逐项 HTTP 结果保留在忽略目录：
`data/evaluation_runs/live-integration/rules-final.json`、`hybrid-final.json`。
这些是虚构订单上的应用冒烟测试，不是 ABCD/OR-ShARC 分数，更不是完整 tau2 成绩。
公开数据的规模、结果及限制见 [公开评测报告](public-data-evaluation.md)。
便于版本追踪的汇总见 [本轮集成结果](results/integration-live-2026-10-14.json)。

## 本轮发现并修复

1. **跨会话重复退货**：旧版本只按 case/幂等键防重复，换会话仍能为同一商品创建多个模拟 RMA。现在同事务条件更新商品退货状态，数据库唯一索引再兜底；两个已获得确认问题的会话也只能成功一个。
2. **错误的就绪信号**：原 `/ready` 仅确认数据库能连接，现在还确认必需业务表存在。它不替代迁移版本审查或依赖端到端检查。
3. **否定事实漏记**：`used=false/opened=false/damaged=false` 是有效事实，现在保留在提取记录里；默认的 `wants_human=false` 不冒充客户显式提供的事实。
4. **静默模型回退难追踪**：工具记录新增提取路径，区分规则充分、模型成功及失败后规则回退。尚未接入完整 token/费用监控。
5. **网页刷新重复恢复消息/异步竞态**：恢复请求增加取消保护，恢复完成前不允许提交或重开会话。
6. **轻量启动细节**：检查占用端口，启动失败或 Ctrl+C 时只停止本命令创建的进程；刚停止服务后的端口检测不再误判 TIME_WAIT。

### 迁移注意

`0002_one_return_per_item.py` 为模拟退货表增加商品唯一索引，并补写已有商品的退货状态。
如果旧库已经有同一商品的多条退货记录，迁移会**明确失败**，不会自动删除历史。
先备份并人工核对重复数据，再决定如何修复。代码回滚并不等于数据状态回滚；不要盲目执行 downgrade。
本轮旧的有问题测试库被保留，后续使用了新的独立库；未改动用户已有 PostgreSQL 数据。

## 你现在如何启动和停止

在项目根目录，首次准备 Python 与前端依赖后运行：

```bash
make demo
```

打开 <http://127.0.0.1:5173>，使用 `june@example.com` + `ORD-1010`。
输入 `Return ORD-1010 because the shirt doesn't fit.`，然后回答使用状态、确认。
网页下方单独的政策框可输入 `What is the return deadline?`，无需提供邮箱。

每次启动只需 `make demo`；终端 `Ctrl+C` 停止 API/UI。数据库默认在
`data/local_demo/returnflow.db`，不会在关闭或重新启动时清空。
同一商品创建过退货后再次请求会被拒绝，这是正确行为；日期也会随时间变旧。
需要一套新的演示订单时指定新文件名，不必删除旧库：

```bash
uv run python -m scripts.local_demo --database data/local_demo/my-next-demo.db
```

模型不会自动启动。需要混合模式时先自行启动本地 Ollama，再运行：

```bash
uv run python -m scripts.local_demo --provider ollama
```

在 16 GB Mac 上只加载一个模型，不并发跑评测，也不要同时启动 Docker。
示例订单/邮箱的准确对应关系来自 `data/seed_orders.json`，例如 final-sale 订单
`ORD-1004` 的邮箱是 `dev@example.com`，不是 `emma@example.com`。

### 重跑真实接口检查

先启动一个**新路径**的测试库，避免已退货订单和旧日期影响结果：

```bash
uv run python -m scripts.local_demo --database data/local_demo/my-smoke.db
```

另一个终端：

```bash
uv run python -m scripts.smoke_app --allow-demo-writes \
  --summary data/evaluation_runs/live-integration/my-smoke.json
```

这会创建一个模拟 RMA。工具仅允许 loopback 地址，且目标必须标为 `local-demo`；
不要通过 SSH 隧道把它指向真实业务库。`--api-port`/`--ui-port` 可避开端口冲突。

## 还缺什么：按优先级

| 优先级 | 工作 | 当前限制 |
| --- | --- | --- |
| P0，公开部署前 | 真正的用户认证、会话授权与隐私保护 | 现在是课程演示；知道邮箱并非真正身份验证，不能直接暴露为生产退货服务 |
| P1 | PostgreSQL 上的并发确认/回滚/失败重试测试 | 本机只实际验证 SQLite；增加了原子认领与唯一索引，但不宣称 PostgreSQL 高并发已经验证 |
| P1 | Jetstream2 部署验收、持久卷、TLS、健康探针、备份、资源限制 | 本轮没有部署/重启云实例，没有容器运行或压测；这些仍是课程 deployment 主任务 |
| P1 | 政策检索质量及引用忠实度 | 公开数据检索可复现，但现有零售补充集 top-3 政策命中仅 70%；引用正确不代表推理正确 |
| P1 | 数据标注与领域适配 | ABCD 不是完整 ReturnFacts 金标；缺失条件字段不能自动编造。小份补充标注仍需人工确认 |
| P2 | native ReturnFlow ↔ tau2 工具/agent 适配 | 现有官方 generic agent 冒烟超时；不是 ReturnFlow 全流程 benchmark 成绩 |
| P2 | 完整线上模型观测 | 已有提取路径/工具耗时，尚缺 token/费用、模型失败率聚合、排队/超时预算与看板 |
| P2 | 用户层面的评估 | 还需完成率、平均追问轮数、误批准率、操作耗时和可用性测试，不仅是 recall/F1 |

建议下一阶段优先补齐部署验收与 PostgreSQL 并发测试，不先扩成多 agent。
当前小模型不应接管确定性退货政策判断；RAG 用于提供可核对的依据。
