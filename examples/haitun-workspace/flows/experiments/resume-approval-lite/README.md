# Resume Approval Lite

这是 `resume-approval` 的独立精简实验版，不覆盖或注册为生产 Workflow。源文件为：

```text
flows/experiments/resume-approval-lite/resume-approval-lite.workflow
```

它可以通过显式文件路径手动运行，但不会被 `/workflow:<slug>` 的生产保存目录自动发现。

## 结构

```text
准备上下文 (Program)
  -> 提取本批统一评估政策 (Agent)
  -> 逐份简历初评 (Agent foreach)
  -> 逐份独立复核并一次纠正 (Agent foreach)
  -> 一次集中硬校验 (Program)
  -> 写入人才库并交给 Human 初审 (Agent)
```

静态节点共 6 个：2 个 Program、4 个 Agent；没有 `assert_*` 节点，没有两轮 repair build/merge，也不生成文档或简历内容哈希。

## 保留的五条质量底线

1. **事实准确**：初评 Agent 和独立复核 Agent 都必须读取原简历。最终陈述必须有原文证据和位置；缺失事实标记为 `unknown`，不得自行补全。
2. **标准遵循**：整批只生成一份 `evaluation_policy`。每个维度输出 `score/max_score`，集中校验器验证维度集合、上限、总分求和、0–100 范围和评级区间。
3. **证据追溯**：匹配点、不匹配点和各维度评分均包含证据与位置，并显式区分 `known`、`unknown`、`inference`；最终匹配点不接受推测作为肯定证据。
4. **业务完整**：集中校验器生成并检查 15 个字段的完整写入计划。附件字段在写入阶段由输入文件上传结果替换，其他 14 个字段不得缺失。
5. **Human 边界**：新行只能将 `备注` 初始化为空、将 `初审状态` 初始化为 `待审批`；复用已有行时不更新这两个字段。Agent 不得填写 `通过`、`不通过` 或任何审批结论。

## 相比生产版删掉的内容

- 每个 Program 后的独立 Program-error guard；
- 简历暂存、内容哈希、按哈希去重与清理；
- 在线文档内容哈希和 revision 链；
- 岗位目录的独立 Program 校验节点；
- 两轮“构建修复请求 -> Agent 修复 -> Program 合并”流水线；
- 初筛 handoff 的本地不可变文件和文件哈希验证。

## 明确的权衡

精简版保留业务质量门槛，但降低了工程审计强度：

- `source_ref` 使用本次输入列表中的精确文件引用和顺序，不再使用内容 SHA-256；输入文件在运行中被替换时无法由内容哈希发现。
- 在线标准在批次开始时读取一次，但不记录内容 revision；之后难以证明历史批次使用的是哪一字节版本。
- 写入仍按 12 个 AI 字段的完整可见指纹避免覆盖 Human 字段，但不再提供生产版的完整附件哈希绑定和不可变跨 Workflow handoff。
- `initial_review_handoff` 是 Lite schema，不兼容现有 `resume-interview-preparation` 的严格生产 handoff loader。不要把它直接作为生产 A2 输入。

因此，本版本适合验证“更少节点是否仍能满足业务质量”，不应在未经真实简历回归和飞书沙箱验收前替代生产版本。

## 验证状态

截至 2026-08-20，`tests/test_lite_workflow.py` 的 21 项隔离测试全部通过。测试直接编译并通过 FusionFlow `execute_workflow()` 执行本文件，不使用第二份简化 Workflow。覆盖范围包括：

- 真实 6 节点图完整执行，两个 foreach 对两份输入正确展开、聚合并保持源顺序；
- Agent 单次瞬态失败按 `max_attempts=2` 重试，终态失败阻断复核、校验和写入；
- 四个 Markdown instruction 路径真实解析，两个 Program 路径和 Agent 工具白名单通过编译检查；
- `validate_batch.py` 通过真实 Python 子进程接收 runtime JSON stdin，并以严格多 Artifact JSON stdout 返回；
- 五项质量签核逐项失败均被拒绝，同时拒绝分数/评级漂移、无已知证据得分、来源错配、未知事实确定化、非当前岗位要求、隐私或受保护信息及 Agent 填写 Human 决策；
- 完整生成 15 字段计划，`备注=""`、`初审状态="待审批"`，最终写入 Agent 缺少任一约定输出时重试后失败；
- 在线标准的隔离传输层确认每批只读取一次，不生成或传播 SHA-256/revision 字段。

复现命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  examples/haitun-workspace/flows/experiments/resume-approval-lite/tests

.venv/bin/ruff check --no-cache \
  examples/haitun-workspace/flows/experiments/resume-approval-lite/programs \
  examples/haitun-workspace/flows/experiments/resume-approval-lite/tests
```

这些测试不会向飞书写入数据。仓库中未发现明确的飞书沙箱配置或脱敏 PDF/DOCX/TXT 回归样本，因此尚未验证真实 Agent 对三种文件格式的内容读取质量，也未验证真实飞书的上传、查重、复用、创建和附件回填。完成这两类沙箱验收前，只能认定本地 Workflow 编排和确定性业务合同完整，不能宣称生产外部集成已经端到端通过。

## 配置

为避免复制密钥和私有配置，Lite 读取同一 workspace 下现有的：

```text
flows/workflows/resume-approval/resume-approval.defaults.json
```

输入格式与原版一致：

```json
{
  "resume_files": [
    "C:/Users/example/Downloads/.psi/2026-08-19/candidate.pdf"
  ]
}
```
