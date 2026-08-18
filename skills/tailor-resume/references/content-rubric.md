# Evidence and content rubric

## Fact ledger contract

Keep `fact-ledger.json` private. Use this shape:

```json
{
  "schema_version": 1,
  "source_index": [
    {
      "id": "SRC-001",
      "path": "sources/source-file.ext",
      "description": "User-provided source and relevant scope"
    }
  ],
  "facts": [
    {
      "id": "FACT-001",
      "category": "experience",
      "claim": "Literal claim represented by the evidence",
      "status": "usable",
      "source_ids": ["SRC-001"],
      "evidence": "Exact locator plus a short supporting excerpt or observation",
      "public_text": "Anonymized wording suitable for content.tex"
    }
  ],
  "open_questions": [
    {
      "id": "Q-001",
      "fact_id": "FACT-001",
      "status": "open",
      "question": "One focused question needed to resolve the fact",
      "answer_source_id": null
    }
  ]
}
```

Use source IDs `SRC-001` and fact IDs `FACT-001` with increasing numbers. Keep
source paths relative to the private workspace.

Use exactly these fact statuses:

- `usable`: Direct evidence supports both the claim and its public wording.
- `needs-confirmation`: A required field, scope, attribution, date, metric, or
  result is ambiguous. Leave `public_text` empty or mark it `TODO`.
- `excluded`: Evidence exists, but the claim is irrelevant, private, unsafe, or
  too weak for the resume.

Save user answers to a private source note before promoting a
`needs-confirmation` fact to `usable`. Set a resolved question's
`answer_source_id` to that note's source ID.

## Evidence rules

- Preserve the source's precision. Do not turn an estimate into an exact
  number, a team result into an individual result, correlation into causation,
  or participation into ownership.
- Preserve date granularity. Do not invent a day or month when only a year is
  known.
- Preserve units, denominators, sample windows, and comparison baselines for
  metrics.
- Distinguish production delivery, prototype work, research, coursework, and
  proposals.
- Treat skills inferred only from a project description as
  `needs-confirmation`.
- Keep confidential excerpts in the ledger; expose only approved,
  anonymized wording in public mode.

## Writing rubric

Write each bullet as a compact contribution:

1. Start with an accurate action and the owned object.
2. Add the relevant method or constraint.
3. End with an evidenced result, scale, or quality improvement.

Prefer concrete verbs such as “implemented,” “designed,” “migrated,”
“diagnosed,” or “evaluated.” Avoid vague Chinese resume filler such as
“负责相关工作,” “深度参与,” “赋能,” or “显著提升” unless the following text makes
the scope and evidence explicit.

Keep one primary claim per bullet. Use parallel tense and punctuation. Remove
repeated technology lists when the same tools are already visible in a project
tag or skills line.

## Selection and compression

Score candidate facts in this order:

1. Relevance to the target role.
2. Strength and specificity of evidence.
3. Demonstrated impact or technical difficulty.
4. Recency.

When the resume overflows, remove weak or duplicated material first, shorten
supporting clauses second, tighten spacing third, and reduce typography only as
a last resort. Never preserve density by making the page unreadable.

## Missing information

Ask one focused question at a time when an answer can materially improve the
resume. Otherwise:

- keep the fact `needs-confirmation`;
- add a non-sensitive `% TODO(FACT-NNN): ...` comment if the structural slot
  must remain;
- omit unsupported metrics or outcomes;
- report unresolved fact IDs in the final handoff.
