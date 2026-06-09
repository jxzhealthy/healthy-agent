---
name: summarize
description: Summarize text into a concise summary using LLM.
parameters:
  - name: text
    type: string
    description: Text to summarize
    required: true
  - name: max_sentences
    type: integer
    description: Maximum number of sentences
    required: false
---

# System
Write exactly {max_sentences} sentences. Be concise and accurate.

# Prompt
Summarize the following text:

{text}
