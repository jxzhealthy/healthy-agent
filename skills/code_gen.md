---
name: code_gen
description: Generate code for a given task using LLM.
parameters:
  - name: task
    type: string
    description: What code to write
    required: true
  - name: language
    type: string
    description: Programming language
    required: false
---

# System
Output only raw code. No markdown fences, no explanation.

# Prompt
Write {language} code: {task}
