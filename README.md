# Runtime contract

Bohrium Playground Period 4 submission — challenge `product-arena-09-0e8befd4` (track: `literature-reading`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `bohr-reading-nanopublication`
- Summary: 当需要把论文结论拆成可独立判断真假的断言、绑定最小证据与来源元数据，并导出可机器读取结构时使用。本题范围：Nanopublication（断言拆解、证据绑定、来源追踪、结构化导出）。产出 result.json，包含运行时 output_contract 要求的全部字段，每条断言附原文段落与逐字短引，来源不完整或无法判断的部分如实写入 uncertainty。

## Contents

| File |
|------|
| `LICENSE` |
| `README.md` |
| `SKILL.md` |
| `assets/contract-aliases.json` |
| `assets/policy.json` |
| `assets/result-schema.md` |
| `environment/resources.yaml` |
| `environment/runtime.txt` |
| `examples/demo-case/agent_judgement.example.json` |
| `examples/demo-case/case.json` |
| `examples/demo-case/material.md` |
| `examples/demo-case/task.md` |
| `examples/quickstart.md` |
| `references/artifact-pipeline.md` |
| `references/contract-handling.md` |
| `references/evidence-discipline.md` |
| `references/failure-modes.md` |
| `scripts/artifacts.py` |
| `scripts/pptxgen.py` |
| `scripts/reading_ext.py` |
| `scripts/sk_base.py` |
| `scripts/sk_entry.py` |
| `scripts/sk_selftest.py` |
| `scripts/skill_profile.json` |
| `scripts/specialize.py` |
| `scripts/topic.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
