---
name: bohr-reading-nanopublication
description: 当需要把论文结论拆成可独立判断真假的断言、绑定最小证据与来源元数据，并导出可机器读取结构时使用。本题范围：Nanopublication（断言拆解、证据绑定、来源追踪、结构化导出）。产出 result.json，包含运行时 output_contract 要求的全部字段，每条断言附原文段落与逐字短引，来源不完整或无法判断的部分如实写入 uncertainty。
---

# 阅读14｜Nanopublication：科研阅读：回答问题，也给出依据

## 用途

本题属于 **literature-reading（reading）** 赛道，题目是「Nanopublication」。目标能力：把论文中的关键结论拆成**单一、可独立判断真假**的科研断言，为每条断言绑定**最小充分证据**与可回溯的来源元数据，并导出下游程序可直接解析的结构。

重点覆盖四个问题（题面原文）：

- **拆得细**：一段结论拆成若干条各自可判断真假的断言，而不是把整段话塞进一个字段。
- **对得上**：每条断言找到真正支撑它的最小证据片段，并能指出原文位置。
- **追得回**：断言、证据、论文、作者、年份、版本之间的链路完整，他人可据此回到原文。
- **读得懂**：导出结构符合约定字段与序列化形态，下游程序无需人工清洗即可解析。

可选择断言拆解、证据绑定、来源元数据、质量检查、结果复核与复用中的一个方向，形成能够真实运行、独立验证的最小成果，不要求完整 Nanopublication 系统。

本 Skill 在 DeepSeek Harness 中被加载到 `/skills/weekly-skill`。
Harness 会在 3 个固定科研案例上分别调用它；每个案例的输入是
`/input/case.json`（含 `task_instruction` 与 `output_contract`）、`task.md`
与同目录下的科研材料。

## 任务要求（来自题面）

1. 先识别输入材料与问题边界，读取实际论文文本，不依据文件名或领域标签臆测内容。
2. **断言拆解**：把复合句拆成单一主谓结构；保留条件、限定范围、否定与比较对象；并列与因果结构分别成条，不把多个事实塞进一条断言。
3. **主体与关系**：每条断言给主体、关系/谓词、客体（或数值）、方向与条件；主体混淆或关系方向不明时标注，不强行断言。
4. **证据绑定**：为每条断言关联**最小充分**原文片段与段落定位；区分直接证据与间接推论，间接推论必须标注。
5. **来源元数据**：记录论文标识（DOI/标题）、作者、年份、版本、数据来源与许可证；信息缺失时留空并写入 `uncertainty`，不编造。
6. **质量检查**：检测断言过宽、证据不足、关系类型错误、主体混淆与来源缺失，给出可复现的判定依据。
7. **结构化导出**：断言、证据、来源以稳定字段输出，保持可机器读取；无法判断或源内冲突要保留，不合并成一个结论。

本题可预知的契约键（来自题面「Skill 运行后的输出要求」，另有部分键按**同赛道兄弟题的公开接口推断**；**实际以运行时 `/input/case.json` 为准**，下表仅供预热）：

- `case_id`
- `case_identifiers`
- `assertions`
- `evidence`
- `source_metadata`
- `nanopublication`
- `quality_checks`
- `coverage`
- `status`
- `uncertainties`

题面没有规定固定的 JSON 键名；因此**不要硬编码**，按运行时契约键名语义填充。

## 交付物

result.json（契约齐全：断言、证据、来源、质量检查、不确定性）、run-review.md（证据索引 + 质量检查记录）、anomaly-report.json（异常自报，输入提供 `target-fields.json` 时）。

交付物的**内容契约**由运行时 `output_contract` 决定（见下）；下面「交付物落盘
要求」给出的是必须真实存在的**文件**。

## 执行方式

入口脚本：`scripts/sk_entry.py`。它会读取 `/input`，产出 `/app/output/result.json`。

```bash
# 在案例环境中执行（Harbor 会自动调用；手动复现同一条命令）
python /skills/weekly-skill/scripts/sk_entry.py \
  --input /input --work /app/work --out /app/output
```

执行结束后必须存在且可解析：

- `/app/output/result.json` —— 契约字段齐全的最终结果
- `/app/output/run-review.md` —— 人类可读的证据索引与不确定性清单（复核用）

### 单次运行即产出完整交付（判断内置，可选覆盖）

脚本是**确定性**的，但**不是只做取证的半成品**：一次运行就完成
「读材料 → 建证据索引 → 抽出术语定义 / 结论句 / 章节篇幅预算 / 一致性发现
→ 逐字段抽取（当 `/input/target-fields.json` 存在）→ 选取关键事实锚点
→ 给出实质判断（claims / answers）」。正常用法只有一条命令：

```bash
python /skills/weekly-skill/scripts/sk_entry.py \
  --input /input --work /app/work --out /app/output
```

- **判断内置**：哪条是定义、哪句是结论、每个章节该写多少、哪些术语/编号
  不一致、哪些数值/单位/图表/引用不能丢，都由本 Skill 基于材料判定，并逐条
  挂段落定位与逐字短引；实质交付物成形即 `status=answered`。
- **reading 字段表**：若 `/input/target-fields.json` 存在，逐 `field_id` 抽取并
  给出 reported / not_reported / source_conflict / extraction_failed 四态；该清单
  是任务说明而非论文材料，不会被当正文读入证据索引。
- 材料不足时才停在 `partial`，并在 `status_reason` 写明**具体**缺什么
  （而不是"等 Agent 判断"）。

**可选覆盖**（只有执行 Agent 想给出更强判断时才需要）：把判断写到
`/app/work/agent_judgement.json`，或直接改 `/app/output/result.json`，再跑一次；
脚本会逐条校验引文后合并，未通过校验的条目退回并记录原因。判断文件结构：

```json
{
  "case_id": "必须与 case.json 一致",
  "claims": [
    {"text": "你判断为结论的陈述",
     "evidence": [{"paragraph_id": "P002", "quote": "原文里逐字出现的片段"}]}
  ],
  "answers": [
    {"question": "被问的问题", "answer": "你的回答",
     "evidence": [{"paragraph_id": "P002", "quote": "原文里逐字出现的片段"}]}
  ],
  "deliverable": "本题最终交付物的正文",
  "contract_fields": {"契约键名": "该键的内容（可选，直接填契约键）"},
  "uncertainties": [
    {"kind": "machine_readable_category", "item": "具体对象",
     "detail": "客观描述", "resolution": "你做了什么或为何无法继续"}
  ]
}
```

**覆盖时的校验闸门（脚本强制执行）**：

- 每条 `quote` 必须能在材料原文里**逐字找回**（允许空白差异）—— 找不到就**退回**，
  并把退回理由写进 `uncertainty`；
- 每条 claim / answer 必须至少有一个证据锚点 —— 没有锚点的条目被退回；
- `contract_fields` 的值不能是 `null` 或空容器 —— 空值被退回；
- 被退回的条目**不会**进入最终结果，脚本保留自己的确定性抽取作为兜底。

> 判断可以自由，**证据不可以自由**。这条闸门是本 Skill 的可信度基础。
> 跳过覆盖不会降级 —— 脚本自己的判断就是最终判断。

### 脚本职责

| 脚本 | 职责 |
|---|---|
| `scripts/sk_entry.py` | 入口：定位输入、发现材料、执行 `topic.run()`、装配 `result.json`、自检并写复核产物 |
| `scripts/sk_base.py` | 公共库：契约解析、材料发现、证据构造、结果装配、自检工具 |
| `scripts/topic.py` | 题目逻辑：读材料 → 建证据索引 → 按契约键名语义产出字段 → 校验并合并你的判断 |
| `scripts/specialize.py` | reading / writing 引擎：逐 `field_id` 抽取（四态状态）；可编辑稿件 + 改动记录 + 来源映射 |
| `scripts/artifacts.py` | graphics 引擎：实体—连接—步骤 IR → 分层 SVG → 渲染 PNG + 来源记录 |
| `scripts/pptxgen.py` | slides 引擎：stdlib-only 真实 PPTX + 逐页 SVG/PNG + 独立讲稿备注 |

**这些引擎会真的写文件。** 每条赛道具体落盘哪些文件、每个文件里有什么、
如何回挂到契约键，见 `references/artifact-pipeline.md`。

### 运行时契约是唯一权威

`output_contract` **只在运行时可见**（`/input/case.json`）。
不要硬编码任何字段名，也不要凭题面示例臆造字段：

1. 读取 `/input/case.json` 的 `output_contract`；
2. 对每个契约键，按**键名语义**判断它应该承载什么（证据 / 结论 / 不确定性 /
   交付物 / 覆盖度 / 变更记录 …）；
3. 产出对应内容，**不允许**留下 `null` 或"未产出"占位；
4. 若该键确实无法从材料得出，填入结构化的"无法判断"条目（带 `kind`、`item`、
   `detail`、`resolution`），而不是留空。

## 交付物落盘要求

除 `result.json` 外，**可编辑的交付物源文件与其渲染预览必须真实存在**：

| 赛道 | 必须落到 `/app/output` 的文件 |
|---|---|
| reading | `result.json`（契约齐全的结构化结果） |
| reading | `run-review.md`（证据索引 + 不确定性清单） |
| reading | `answers[]` / `target_fields[]`：若输入提供 `target-fields.json`，则逐 `field_id` 一项，状态取 `reported` / `not_reported` / `source_conflict` / `extraction_failed` |
| reading | `anomaly-report.json` —— 异常自报：各状态计数、逐条异常原因、正文与表格取值冲突、每个取值的表格行列定位 |

平台提供的 `office-renderer` / `pdf-render-tool` / `latex-compiler` 可用来渲染预览。
**只有规格描述、没有真实文件，等于没交付** —— 评审要打开文件看。

### 导出前合规检查（pre-export compliance）

导出件落盘后，本 Skill 会**自动核对**并在 `*-export-checks.json` 里留档，
让评审不必逐个打开文件猜：

| 检查维度 | 记什么 |
|---|---|
| 目标格式 | 期望的 SVG / PNG / PDF 是否齐全、各自字节数、是否是**真矢量** |
| 画布与分辨率 | 像素尺寸 → pt → mm 换算，实测 dpi，目标 dpi |
| 字体 | 字体清单、嵌入情况、中文回退策略、是否存在方框/缺字风险 |
| 色彩空间 | 色彩空间标注（sRGB 等）与是否有嵌入配置 |
| 线宽 / 分层 | 线宽是否过细、图层是否可拆、图层清单 |
| 数据一致性 | 图上出现的数值与源数据表的比对结果 |
| 讲稿隔离 | 备注文字是否混进页面文字（逐页最大重叠片段） |
| 人工确认 | 需人眼确认的项一律标 `pending_human_review`，**不代签** |

失败的检查项会**原样保留为 fail**，不会被改写成通过；不可用的工具（如运行时
没有矢量转换器或 LibreOffice）也如实记为 `unavailable`，不做假成功。

## 质量红线

- **一条断言一个事实**：每条断言只回答一个可判真假的命题；复合句的并列、因果、比较分别成条，不把整段摘要塞进一个字段。
- **条件不可丢**：保留温度、电流密度、循环次数、样本、对照等限定范围；去掉条件会导致断言过宽，必须显式记录。
- **证据最小充分**：每条断言给出一段能直接支撑它的原文短引 + 段落定位；引文过长或只沾边不算。
- **直接/间接分清**：直接引用与推断分别标注；推断不能伪装成原文陈述。
- **来源真实**：DOI、标题、作者、年份、版本、许可证按材料登记；材料未提供时留空并写入 `uncertainty`，不编造标识符。
- **导出可解析**：字段名稳定、JSON 可解析、无重复 id；断言 id 与证据 id 可互相引用。
- **质量检查留痕**：断言过宽、证据不足、主体混淆、关系方向错误、来源缺失逐条记录判定依据。
- 每条 claim 都有 paragraph_id + 原文 quote。

通用红线（违反即失分）：

- **不编造**：材料没有的数字、引用、图表、方法、结论，一律不写。写不出来就进
  `uncertainty`，并在 `status_reason` 里说明。
- **可回溯**：每条结论必须能指回原文的段落 id 与短引；引文必须是原文片段，
  不做改写、不做拼接。
- **不提前交卷**：材料可能读不全。若只读到部分文件，`status` 应为 `partial`，
  并在 `coverage.not_read` 写明未读的部分。
- **不自评**：不要在结果里写"质量良好""得分很高"这类自评语句。

## 失败与边界

| 情况 | 正确处理 |
|---|---|
| 材料是扫描件、无文本层 | 用 `scripts/sk_base.py` 的 PDF 解析；仍无文本则 `status=unsupported` 并在 `uncertainty` 写明"无文本层" |
| 材料是图片/图表 | 用平台提供的 `pdf-render-tool` / `ocr-tool`；OCR 结果标注为推断 |
| 材料格式未知 | 记录文件路径与可读性，不猜测内容 |
| 契约键无法解读 | 产出该键的结构化说明而非空值，并记录在 `uncertainty` |

详见 `references/failure-modes.md` 与 `references/evidence-discipline.md`。

## 一致性清单产出（v15）

引擎在同一次运行里从已加载材料确定性地产出下列清单，条目均为逐字引文 +
段落/来源定位，不做语义改写、不编造：

| 产物 | `result.json` 键 | 依据 |
|---|---|---|
| 术语表 | `glossary` | 显式定义句式、缩写全称展开、高频缩写兜底（标注 `first_use_context`） |
| 符号与单位 | `symbols`、`units` | 希腊字母、下标变量与常见单位串 |
| 结论清单 | `conclusions` | 因此/综上/结果表明/we conclude 等提示句 |
| 章节预算 | `section_plan` | 大纲或 Markdown 标题；无大纲时 `derived: true` |
| 跨章一致性 | `consistency_audit` | 术语写法变体、图表编号重复或跳号、重复定义 |
| 术语-章节图 | `graph` | 术语为节点，出现章节为边 |

材料中确实没有定义句或结论句时，对应列表为空，并在 `uncertainty` 写
`no_explicit_definitions` 说明原因；不要为了填满字段而杜撰条目。

## 自检

`result.json` 写完后由 `scripts/sk_entry.py` 自动自检（结构、契约覆盖、
证据完整性）。自检失败时以 `partial` 提交并在 `status_reason` 写明原因，
不要伪造 `answered`。

除自动自检外，人工复核以下各项：每条断言是否只含一个事实；条件是否保留；
证据是否为最小充分片段；直接证据与推断是否分开；来源元数据是否真实完整；
断言 id 与证据 id 是否可互相引用；`quality_checks` 是否记录了过宽/缺证/冲突。

```bash
python /skills/weekly-skill/scripts/sk_selftest.py --input /input
```

## 参考

- `references/evidence-discipline.md` —— 证据与不确定性纪律
- `references/contract-handling.md` —— 运行时契约的读法与字段语义表
- `references/two-phase-workflow.md` —— 两阶段工作流协议与校验闸门
- `references/failure-modes.md` —— 常见失败模式与正确退路
- `references/artifact-pipeline.md` —— 每条赛道真实落盘哪些文件、怎么回挂契约键
- `assets/result-schema.md` —— `result.json` 的字段说明
- `assets/policy.json` —— 不编造承诺与来源声明
- `examples/demo-case/` —— 一个可离线复现的最小案例
