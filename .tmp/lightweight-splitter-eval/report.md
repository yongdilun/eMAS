# Lightweight LLM Splitter Evaluation

- Model: `bartowski/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M`
- Endpoint: `http://127.0.0.1:901/v1`
- Cases: 20
- Verdict: **do_not_upgrade**
- Reason: lightweight LLM accuracy is lower than current splitter

| Variant | Avg Accuracy | Perfect | >=0.8 | Errors | Avg ms | P95 ms | Total Tokens | Avg Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| current | 0.8713 | 12 | 13 | 0 | 0.69 | 2.36 | 0 | 0.0 |
| lightweight_llm | 0.8154 | 11 | 11 | 0 | 690.25 | 1261.95 | 8546 | 427.3 |

## Case Details

| Case | Current | LLM | Current Roles | LLM Roles |
| --- | ---: | ---: | --- | --- |
| `simple-machine-status` | 1.0 | 1.0 | required_requirement | required_requirement |
| `filtered-job-list` | 1.0 | 1.0 | required_requirement | required_requirement |
| `document-rag-loto` | 1.0 | 0.45 | required_requirement | answer_instruction |
| `job-priority-mutation` | 1.0 | 1.0 | mutation_or_approval_request | mutation_or_approval_request |
| `machine-active-job-cascade` | 0.725 | 1.0 | required_requirement, required_requirement | required_requirement, conditional_branch |
| `conditional-follow-up` | 0.725 | 0.4583 | required_requirement, required_requirement | required_requirement |
| `formatting-table` | 0.625 | 0.725 | required_requirement | required_requirement, answer_instruction |
| `missing-machine-id` | 1.0 | 1.0 | clarification_need | clarification_need |
| `pronoun-current-job-deadline` | 0.725 | 0.625 | required_requirement, required_requirement | required_requirement |
| `read-job-product-summary` | 1.0 | 1.0 | required_requirement, conditional_branch, answer_instruction | required_requirement, conditional_branch, answer_instruction |
| `job-status-short-table` | 1.0 | 1.0 | required_requirement, formatting_instruction | required_requirement, formatting_instruction |
| `machine-status-explain` | 1.0 | 1.0 | required_requirement, answer_instruction | required_requirement, answer_instruction |
| `bulk-priority-change-approval` | 0.6 | 0.6 | required_requirement, mutation_or_approval_request, mutation_or_approval_request, mutation_or_approval_request | required_requirement, mutation_or_approval_request, mutation_or_approval_request, answer_instruction |
| `field-sort-limit-continuation` | 1.0 | 1.0 | required_requirement | required_requirement |
| `blocked-row-condition` | 0.725 | 0.425 | required_requirement, answer_instruction | required_requirement, answer_instruction, mutation_or_approval_request, answer_instruction |
| `machine-result-job-id` | 1.0 | 1.0 | required_requirement, conditional_branch | required_requirement, conditional_branch |
| `machine-result-job-cause` | 1.0 | 0.75 | required_requirement, conditional_branch, answer_instruction | required_requirement, answer_instruction |
| `unsupported-destructive-action` | 0.45 | 1.0 | required_requirement | mutation_or_approval_request |
| `multi-read-with-formatting` | 0.85 | 0.65 | required_requirement, required_requirement, required_requirement, formatting_instruction | required_requirement, answer_instruction |
| `approval-preview-before-apply` | 1.0 | 0.625 | required_requirement, mutation_or_approval_request | mutation_or_approval_request |
