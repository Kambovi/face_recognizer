"""HR chatbot: answers company-policy questions (RAG over a policy folder)
and gives confirmed attendance / payroll summaries from the database.

  policy.py   policy folder -> chunks -> BM25 search
  llm.py      one interface over Anthropic / OpenAI / Ollama (tool calling)
  targets.py  find people / departments / cameras / contractors by name or ID
  report.py   the attendance + payroll table for a confirmed target
  engine.py   the conversation loop

Numbers (attendance, salary) are never produced by the language model: the
model only finds *who* the user means; the table is computed here, after
the user confirms the choice. So salaries never leave the premises even
with a cloud model, and the model cannot hallucinate a figure.
"""
