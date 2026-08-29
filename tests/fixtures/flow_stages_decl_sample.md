---
name: 流程声明样例技能
description: 测试夹具：flow.stages 数组形态（自定义三步结构）声明样例
schema_version: 3
kind: pipeline
flow:
  stages:
    - key: draft_script
      title: 剧本草稿
      probe: analysis
    - key: review_draft
      title: 草稿评审
      review: true
    - key: finalize_spec
      title: 规格定稿
      probe: spec
      executor: document_write
      deterministic: true
---

# 流程声明样例技能

> 调用规则：测试

任务#14 flow.stages 数组形态（workflow 结构声明）测试夹具：
声明自定义三步结构（探针节点 + 评审暂停节点），不套默认 8 节点模板。
