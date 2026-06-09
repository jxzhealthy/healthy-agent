---
name: translate
description: Translate text to another language using LLM.
parameters:
  - name: text
    type: string
    description: Text to translate
    required: true
  - name: target_lang
    type: string
    description: Target language
    required: true
---

# System
Output only the {target_lang} translation. Nothing else.

# Prompt
Translate to {target_lang}:

{text}
