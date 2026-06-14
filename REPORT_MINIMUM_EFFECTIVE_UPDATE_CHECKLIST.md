# eMAS Report Critical Update Checklist

Source report checked: `C:\Users\dilun\Downloads\1211110326_HoSinBan_FYP1_Report.pdf`  
Project root checked: `C:\Users\dilun\OneDrive\Documents\eMas APi`  
Updated: 2026-06-14

## Goal

Reduce the report changes to the critical minimum. The report does **not** need a full rewrite. Keep the original research story, literature review, and most theory sections. Only update sections that are clearly inconsistent with the current project.

## Current Project Reality To Mention

Use this short description when updating critical sections:

> eMAS is now implemented as a full-stack manufacturing management prototype with a React/Vite frontend, Go/Gin backend API, MySQL database, and a Python FastAPI Factory Agent using LangGraph-style agent workflow, RAG support, backend tool execution, SSE updates, and human approval for business-changing actions.

Avoid making the report sound like a finished enterprise APS/MES product. Call it a **prototype** or **research prototype**.

## Critical Changes Only

| Priority | Section | Why it must change | Minimum change |
| --- | --- | --- | --- |
| P0 | Abstract | It says the system is based on openGauss, BDI, and Kunpeng/x86 comparison. This no longer matches the project. | Rewrite the abstract only. Mention current full-stack prototype, Factory Agent, scheduling/reporting/visualization, RAG or knowledge support if needed, and evaluation using simulated data/tests/user tasks. Remove openGauss/Kunpeng unless still required. |
| P0 | 1.4 Objectives of the Research | Objectives are too small compared with the current project. | Replace the objective list with 4-5 updated objectives covering full-stack eMAS, natural-language AI assistant, scheduling/reporting/data visualization, safe approval-controlled actions, and evaluation. |
| P0 | 1.5 Research Questions | Current questions only ask about simple NLP/menu comparison. | Replace with 4-5 questions about natural-language understanding, automation of scheduling/reporting/data queries, decision support usefulness, safety/approval, and usability versus manual/menu workflow. |
| P0 | 1.6 Project Scope | Scope says basic AI functions and does not mention the actual frontend/backend/agent system. | Rewrite only enough to state included modules: React frontend, Go API, database, Factory Agent, scheduling, reporting, dashboard, inventory/machine/job data, RAG/advisory support, approval workflow. State exclusions: no real machine control, no live factory deployment. |
| P0 | 4.3.2 System Architecture Design | This is the biggest technical mismatch. It describes Huawei ECS/ELB/IAM/HSS/OBS/GaussDB/ModelArts/openGauss, but the repo uses React, Go API, Factory Agent, MySQL, Redis, Docker/Nginx. | Replace the architecture paragraph and Figure 4.3. Use current architecture only: frontend -> Go API -> MySQL; frontend -> Factory Agent -> Go API tools/RAG; SSE for updates; approval for writes. |
| P0 | 4.3.4 Tools and Technologies | Current tools listed are wrong. | Replace the stack list. Use React, Vite, Tailwind, Go, Gin, GORM, MySQL, FastAPI, LangGraph/LangChain, RAG/Chroma or document retrieval, Redis, Docker Compose, Nginx, Playwright/Go tests. |
| P1 | 4.3.3 Development Stages | Current stages still describe generic BDI/MAS build order. | Light rewrite only. Say development moved through backend API/domain modules, frontend pages, Factory Agent integration, scheduling/shortage workflows, approval flow, and testing. |
| P1 | 4.4 Evaluation Framework | Evaluation is still too generic and misses actual validation surfaces. | Add only current metrics: task completion time, interaction count, scheduling correctness, report/query accuracy, approval safety, RAG answer usefulness, and automated test/scenario pass rate. |
| P1 | 4.5 Data Collection Methods | Does not mention actual test artifacts/logs/scenarios. | Add simulated/seeded data, API logs, Factory Agent session traces, frontend interaction records, automated test results, and optional user/proxy-user feedback. |
| P1 | 5.8 Tools and Software | Analysis tools only mention Python/Pandas/SciPy/Excel. | Add Go tests, Node tests, Playwright, pytest/RAG eval if used, Docker logs. Keep Python/Pandas/SciPy for analysis. |
| P1 | 6.1 Summary of Achievements | Says only design/prototype are established, but project has more implementation. | Update to say the prototype includes frontend, backend API, AI assistant/Factory Agent, scheduling/shortage/reporting/data modules, approval flow, and tests. |
| P1 | 6.2 Future Work | Says next work is to transform design into working prototype, which is already done. | Replace with final evaluation, user testing, deployment hardening, real factory data validation, performance/security improvement, and production-readiness work. |

## Do Not Change Unless You Have Extra Time

These sections can stay mostly as they are:

- Copyright, declaration, acknowledgement
- 1.1 Background of Research
- 1.2 Problem Statement
- 1.3 Research Purpose
- 1.7 Significance of the Research
- 1.8 Summary, except minor wording after objectives/scope are updated
- Most of Chapter 2 Literature Review
- 2.4 comparison section, except only update the eMAS column/table if it directly contradicts the new architecture
- 3.1 to 3.6 theoretical framework
- 4.1 Research Methodology introduction
- 4.2 Research Design
- 4.3.1 Requirements Collection
- 4.4.1 to 4.4.4 subsections, unless you need them to match the revised 4.4
- 4.6 Data Analysis Techniques
- 4.7 Reliability and Validity
- 5.1 to 5.7, except small wording if your evaluation metrics changed
- References, except add references only if you introduce new cited claims
- Appendices

## One Figure To Replace

Only replace **Figure 4.3: eMAS System Architecture Diagram**.

Minimum new figure should show:

```text
React Frontend
  -> Go/Gin API -> MySQL
  -> Factory Agent API -> LangGraph workflow
       -> OpenAPI Tool Registry -> Go/Gin API
       -> RAG / document retrieval
       -> Approval + SSE updates -> React Frontend
```

Do not redraw every figure. Regenerate the List of Figures only after replacing Figure 4.3.

## Suggested Updated Objectives

Use this compact version for Section 1.4:

1. To develop eMAS as a full-stack manufacturing management prototype with frontend, backend API, database, and AI assistant components.
2. To support natural-language interaction for common engineering management tasks such as scheduling, reporting, production queries, and data visualization.
3. To automate selected factory-management workflows while keeping business-changing actions under human approval.
4. To provide decision support for scheduling, shortages, machine/resource status, and operational reports.
5. To evaluate eMAS using simulated factory data, task-based usability measures, system logs, and automated test scenarios.

## Suggested Updated Research Questions

Use this compact version for Section 1.5:

1. How effectively can eMAS understand natural-language requests related to factory management tasks?
2. Can eMAS reduce manual interactions for scheduling, reporting, and production-data access compared with menu-based workflows?
3. How useful are the AI assistant's recommendations for scheduling, shortage handling, and operational decision support?
4. Does the approval workflow help keep automated business-changing actions safe and traceable?
5. How reliable is eMAS when tested with simulated factory data and representative operational scenarios?

## Final Editing Order

1. Update `Abstract`.
2. Update `1.4`, `1.5`, and `1.6`.
3. Update `4.3.2`, replace Figure 4.3, and update `4.3.4`.
4. Update `4.4`, `4.5`, and `5.8`.
5. Update `6.1` and `6.2`.
6. Refresh ToC, List of Figures, and List of Abbreviations only at the end.

That is enough. Everything else is optional polishing.
