# RAG Evaluation Question Bank

Created: 2026-05-25

Scope: Phase 1 only. This bank contains 50 document-only questions grounded in the five PDFs registered in `rag_sources/00_metadata_templates/source_register.json`.

Run 1 constraints:

- 10 questions per PDF.
- Per PDF: 4 direct fact, 3 section-summary, 2 multi-chunk, 1 unanswerable/boundary.
- No cross-document questions.
- No eMAS application-specific questions.
- Mostly clean English, with a few messy real-user phrasings.
- Current answer citations expose `doc_id` and `page`, but not section metadata yet. Section names below are still recorded for later scoring.

Machine-readable source: `tests/rag_eval/cases.json`

## Coverage Summary

| Doc ID | Direct Fact | Section Summary | Multi-Chunk | Boundary | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| `nist_ams_300_1` | 4 | 3 | 2 | 1 | 10 |
| `nist_ams_300_11` | 4 | 3 | 2 | 1 | 10 |
| `osha_3120_lockout_tagout` | 4 | 3 | 2 | 1 | 10 |
| `osha_machine_guarding_checklist` | 4 | 3 | 2 | 1 | 10 |
| `nist_csf_2_0` | 4 | 3 | 2 | 1 | 10 |

## `nist_ams_300_1` - Reference Architecture for Smart Manufacturing Part 1

| ID | Type | Query | Expected Source | Gold Answer / Boundary Expectation |
| --- | --- | --- | --- | --- |
| `nist-ams300-1-df-01` | direct fact | What manufacturing enterprise areas are in scope for the NIST smart manufacturing reference architecture? | Introduction, p. 3 | It covers design engineering, manufacturing engineering, production systems engineering, and production activities; product planning, distribution, and maintenance are outside scope except where they affect those activities. |
| `nist-ams300-1-df-02` | direct fact | In the activity model, what does A0: Realize Products represent? | A0: Realize Products, p. 12 | A0 is the top-level activity for the principal technical work of manufacturing products, including design, manufacturing engineering, production planning/engineering, production activities, and related technical management. |
| `nist-ams300-1-df-03` | direct fact | What does A4: Produce Products include in the NIST functional model? | A4: Produce Products, p. 31 | A4 produces parts/products to the Manufacturing Data Package and includes schedules, material flow, process scheduling/control/execution, resource assignment, tooling/materials, WIP/job tracking, utilization, and yield. |
| `nist-ams300-1-df-04` | direct fact | Name the four subactivities under A232: Specify Instrumentation and Control Systems. | A232, p. 24 | Identify Control Requirements; Identify Instrumentation Requirements; Identify Communications Requirements; Integrate System Specifications. |
| `nist-ams300-1-ss-01` | section summary | Summarize the main point of the Overview of the Model section. | Overview of the Model, p. 6 | The section presents a high-level model of common manufacturing engineering and production activities, focused on production systems engineering, required activities, information flows, and architecture definition. |
| `nist-ams300-1-ss-02` | section summary | Give me a concise summary of A2: Engineer Manufacture of Product. | A2, pp. 15-16 | A2 turns product design information into manufacturable materials, routings, setups, resource needs, facility changes, and per-part manufacturing plans that drive production planning or facility reengineering. |
| `nist-ams300-1-ss-03` | section summary | Can you summarize how Appendix A says to read the IDEF0 diagrams? | Appendix A, pp. 46-47 | IDEF0 diagrams show labeled activities, refinements, and information/resource flows. Labels show hierarchy, not time. Flows are inputs, outputs, and controls; resources are treated mostly as static information resources here. |
| `nist-ams300-1-mc-01` | multi-chunk | How does A23's production system design work connect to A232's instrumentation and control system work? | A23 and A232, pp. 21, 24 | A23 defines the facility/system design, including equipment and supporting instrumentation/control/communications/information systems. A232 narrows that into controller, measurement, communication, and integrated system specifications. |
| `nist-ams300-1-mc-02` | multi-chunk | What's the difference between resource availability, resource status, and resource usage in this document? | Information Flows, p. 42 | Availability is planned/expected equipment and personnel capacity over time; status is current up/down or personnel state; usage is in-service time and process-condition history for maintenance, utilization, or cost analysis. |
| `nist-ams300-1-un-01` | unanswerable | Can this NIST architecture tell me whether machine M12 is available right now for a rush job? | Introduction; Information Flows, pp. 3, 42 | Boundary answer: no live machine availability or scheduling decision is supported. The source can explain reference-architecture resource availability/status concepts, but current status must come from a live production system or authorized process. |

## `nist_ams_300_11` - Recommendations for Collecting, Curating, and Re-Using Manufacturing Data

| ID | Type | Query | Expected Source | Gold Answer / Boundary Expectation |
| --- | --- | --- | --- | --- |
| `nist-ams300-11-df-01` | direct fact | What is the purpose of NIST AMS 300-11? | Purpose, p. 8 | It provides general recommendations for collecting, curating, and re-using manufacturing data from additive and subtractive processes, especially for people collecting shop-floor equipment data. |
| `nist-ams300-11-df-02` | direct fact | What manufacturing processes and data formats are in scope or out of scope for the recommendations? | Scope, p. 8 | In scope: network-based shop-floor data collection using open consensus standards for CNC subtractive and CNC metal additive processes. Out of scope: proprietary formats, polymer additive processes, and mass-conserving processes such as casting/forging. |
| `nist-ams300-11-df-03` | direct fact | What are the four steps for getting a manufacturing data connectivity solution going? | Connectivity: Getting Started, p. 11 | Define the use case, identify supported devices, evaluate network infrastructure, and execute integration activities. |
| `nist-ams300-11-df-04` | direct fact | Which four information models does MTConnect define? | ANSI MTConnect, p. 16 | Devices, Streams, Assets, and Interfaces. |
| `nist-ams300-11-ss-01` | section summary | Summarize why the report says manufacturers should collect manufacturing data. | Motivation, pp. 9-10 | Data supports performance measurement, metrics, dashboards, reporting, scheduling, and higher-value uses such as predictive maintenance, but it must be contextualized for the relevant lifecycle viewpoint and use case. |
| `nist-ams300-11-ss-02` | section summary | Summarize the guidance in Connectivity: Getting Started. | Connectivity, pp. 10-12 | Start from the use case, not just available data. Define requirements, identify devices/data, evaluate the network, plan integration, use a data management plan, and prefer standard formats to avoid brittle proprietary connections. |
| `nist-ams300-11-ss-03` | section summary | Give a short section summary of the relevant standards reviewed in the report. | Overview of Relevant Standards, pp. 12-18 | The section reviews open consensus standards that carry manufacturing-process inputs or outputs, including STEP AP242, AMF, G-code, MTConnect, QIF, and PDF/PRC. |
| `nist-ams300-11-mc-01` | multi-chunk | Why does the report prefer data interoperability standards over lots of proprietary machine-data connections? | Connectivity; Standards, pp. 11-12 | Proprietary connections scale poorly and can create vendor lock-in; open interoperability standards reduce long-term integration cost and keep future sources and applications easier to connect. |
| `nist-ams300-11-mc-02` | multi-chunk | Compare how MTConnect and QIF help turn manufacturing data into reusable context. | MTConnect; QIF, pp. 15-17 | MTConnect contextualizes equipment and process data through equipment information models. QIF contextualizes metrology and inspection data through quality-focused XML models for plans, resources, results, and statistics. |
| `nist-ams300-11-un-01` | unanswerable | Which vendor platform should I buy for connecting all my shop-floor machines? | Disclaimer; Connectivity, pp. 8, 11 | Boundary answer: the report does not endorse a vendor. It gives use-case-driven, standards-oriented guidance: define requirements, identify devices/data, evaluate the network, plan integration, and prefer open consensus standards where suitable. |

## `osha_3120_lockout_tagout` - Control of Hazardous Energy Lockout/Tagout

| ID | Type | Query | Expected Source | Gold Answer / Boundary Expectation |
| --- | --- | --- | --- | --- |
| `osha-loto-df-01` | direct fact | What does lockout/tagout mean according to the OSHA booklet? | What is lockout/tagout?, pp. 7-8 | LOTO protects employees during service or maintenance by disconnecting equipment from hazardous energy, applying lockout/tagout devices, verifying isolation, and controlling stored energy. |
| `osha-loto-df-02` | direct fact | What energy sources does the OSHA lockout/tagout standard apply to? | OSHA Coverage, p. 9 | It applies to hazardous energy sources including mechanical, electrical, hydraulic, pneumatic, chemical, and thermal energy when unexpected energization or release could injure employees. |
| `osha-loto-df-03` | direct fact | What must an energy-control procedure include? | Energy-control procedure, p. 13 | It must define scope, purpose, authorization, rules, techniques, enforcement, shutdown/isolation/blocking/securement steps, device responsibilities, and testing/verification requirements. |
| `osha-loto-df-04` | direct fact | When OSHA allows power for testing or positioning, what sequence must happen before reenergization? | Testing or positioning, p. 21 | For limited testing/positioning: clear tools/materials, clear employees, remove devices as specified, energize for the task, then deenergize, isolate, and reapply controls if work continues. |
| `osha-loto-ss-01` | section summary | Summarize OSHA's basic requirements for an energy-control program. | OSHA requirements, p. 12 | Employers must establish procedures, train employees, and inspect procedures at least annually so machinery is isolated and inoperative before service or maintenance; tagout on lockable equipment needs extra equivalent-protection measures. |
| `osha-loto-ss-02` | section summary | Summarize the booklet's guidance on tagout limitations and lockout/tagout device requirements. | Tagout limitations; device requirements, pp. 18-19 | Tagout is warning-only and does not physically restrain energy-isolating devices, so lockout is more secure. Devices must be dedicated, identified, durable, standardized, substantial, and labeled. |
| `osha-loto-ss-03` | section summary | Summarize what employees need to know and when retraining is required under lockout/tagout. | Training, pp. 19-20 | Training is role-specific for authorized, affected, and other employees; retraining is needed after relevant job, machine, process, or procedure changes, or when inspections or employer knowledge reveal shortcomings. |
| `osha-loto-mc-01` | multi-chunk | If service happens during normal production, when does the lockout/tagout standard still apply? | General industry service and maintenance, pp. 10-11 | LOTO still applies when servicing exposes workers to hazardous energy, such as bypassing guards or entering point-of-operation/danger zones. Minor-servicing exceptions require effective alternative protection; otherwise isolation, lockout/tagout, verification, and residual-energy controls apply. |
| `osha-loto-mc-02` | multi-chunk | How should an employer handle contractor work, group lockout, and shift changes? | Contractors; group; shift changes, p. 22 | Contractor work requires procedure exchange and onsite employee compliance. Group work requires personal control for each authorized employee. Shift changes require continuous protection, orderly transfer, and incoming-shift verification. |
| `osha-loto-un-01` | unanswerable | press 4 is locked out rn, can i just start it if no one is around? | Removal/reenergization, pp. 14-15 | Boundary answer with safety warning: no live status or permission is supported. Do not start or bypass lockout/tagout; follow site procedure and contact the authorized employee or safety person. |

## `osha_machine_guarding_checklist` - Machine Guarding Checklist

| ID | Type | Query | Expected Source | Gold Answer / Boundary Expectation |
| --- | --- | --- | --- | --- |
| `osha-guarding-df-01` | direct fact | Under Requirements for All Safeguards, what does the checklist ask safeguards to prevent or allow? | Requirements for All Safeguards, p. 1 | It asks whether safeguards meet OSHA minimums, prevent body contact and falling objects, are secure, allow safe operation and oiling without removal, and require shutdown before safeguard removal. |
| `osha-guarding-df-02` | direct fact | What point-of-operation questions are included in the machine guarding checklist? | Mechanical Hazards, p. 1 | The checks ask whether a point-of-operation safeguard exists, keeps operators out of danger, shows tampering/removal, could be improved, or could be eliminated by machine changes. |
| `osha-guarding-df-03` | direct fact | Which electrical hazard checks appear on the machine guarding checklist? | Electric Hazards, p. 1 | The electrical checks cover NFPA/NEC installation, loose conduit fittings, grounding, fused/protected power supply, and whether workers receive minor shocks. |
| `osha-guarding-df-04` | direct fact | What lockout/tagout-related maintenance checks are listed in the machine guarding checklist? | Machinery Maintenance and Repair, p. 2 | Maintenance workers should lock out power before repairs, use multiple lockout devices for multiple maintenance persons, and have 29 CFR 1910.147 training and procedures before tasks. |
| `osha-guarding-ss-01` | section summary | Summarize the Requirements for All Safeguards section. | Requirements for All Safeguards, p. 1 | Safeguards should meet OSHA minimums, prevent contact and falling objects, stay secured, support safe operation and maintenance, require shutdown before removal, and be reviewed for improvement. |
| `osha-guarding-ss-02` | section summary | Summarize the Mechanical Hazards part of the checklist. | Mechanical Hazards, p. 1 | The section covers point-of-operation guarding, power transmission hazards, control placement, and safeguards for all hazardous moving and auxiliary parts. |
| `osha-guarding-ss-03` | section summary | Summarize the training and worker-readiness checks in this machine guarding checklist. | Training; Maintenance and Repair, p. 2 | Workers should be trained on safeguard use, location, purpose, guard removal, damaged/missing guards, machine-specific maintenance, and lockout/tagout readiness. |
| `osha-guarding-mc-01` | multi-chunk | Before maintenance repairs around moving parts, which checklist areas should be reviewed? | Safeguards; moving parts; training; maintenance, pp. 1-2 | Review moving-part safeguards, shutdown before removal, training, machine-specific maintenance instruction, lockout before repair, multiple lockout devices, safe repair equipment, guarded maintenance equipment, and 29 CFR 1910.147 procedures. |
| `osha-guarding-mc-02` | multi-chunk | for a guarding audit, how do PPE/clothing checks connect with the nonmechanical hazards section? | Nonmechanical Hazards; PPE and clothing, pp. 1-2 | Nonmechanical hazards cover noise and harmful substances, including guards, enclosures, or PPE where needed. PPE/clothing checks verify appropriate, clean, maintained equipment and no unsafe loose clothing or jewelry. |
| `osha-guarding-un-01` | unanswerable | If every answer on this checklist is Yes, can I certify the machine as OSHA-compliant? | Checklist/disclaimer, pp. 1-2 | Boundary answer with safety/legal caveat: no. A completed checklist can support inspection review, but this PDF does not grant OSHA compliance certification; use applicable OSHA requirements and qualified safety review. |

## `nist_csf_2_0` - The NIST Cybersecurity Framework 2.0

| ID | Type | Query | Expected Source | Gold Answer / Boundary Expectation |
| --- | --- | --- | --- | --- |
| `nist-csf-2-df-01` | direct fact | What are the three main components of the NIST Cybersecurity Framework 2.0? | CSF Overview, p. 6 | CSF Core, CSF Organizational Profiles, and CSF Tiers. |
| `nist-csf-2-df-02` | direct fact | What are the six CSF Core Functions in NIST CSF 2.0? | CSF Core, pp. 8-9 | GOVERN, IDENTIFY, PROTECT, DETECT, RESPOND, and RECOVER. |
| `nist-csf-2-df-03` | direct fact | In CSF 2.0, what is the difference between a Current Profile and a Target Profile? | CSF Profiles, p. 11 | A Current Profile records currently achieved outcomes and how well they are achieved; a Target Profile records desired prioritized outcomes for risk management objectives and expected changes. |
| `nist-csf-2-df-04` | direct fact | What are the four CSF Tiers and what progression do they describe? | CSF Tiers, pp. 12-13 | Partial, Risk Informed, Repeatable, and Adaptive; they progress from informal/ad hoc to agile, risk-informed, continuously improving practices. |
| `nist-csf-2-ss-01` | section summary | Summarize the CSF Core section in plain English. | CSF Core, pp. 8-10 | The Core organizes outcomes by Functions, Categories, and Subcategories. It is not a sequential checklist; Functions work together and apply broadly across ICT environments. |
| `nist-csf-2-ss-02` | section summary | Summarize how CSF Profiles and Tiers are meant to be used. | Profiles and Tiers, pp. 11-13 | Profiles translate Core outcomes into current and target posture and support gap analysis/action planning. Tiers contextualize governance and risk management rigor without replacing existing risk methods. |
| `nist-csf-2-ss-03` | section summary | What's in the online resources section that supplements the CSF? | Online Resources, p. 14 | The section describes Informative References, Implementation Examples, and Quick Start Guides. They supplement the CSF and can be updated more frequently than the stable PDF. |
| `nist-csf-2-mc-01` | multi-chunk | How do GOVERN and IDENTIFY relate in CSF 2.0? | CSF Core and Appendix A, pp. 8, 21, 23 | GOVERN sets strategy, expectations, policy, roles, oversight, supply-chain context, and mission alignment. IDENTIFY uses that governance context to understand assets, suppliers, and risks for prioritization. |
| `nist-csf-2-mc-02` | multi-chunk | How do DETECT, RESPOND, and RECOVER fit together during cybersecurity incidents? | CSF Core and Appendix A, pp. 9-10, 26-28 | DETECT discovers and analyzes adverse events; RESPOND manages, analyzes, communicates, and mitigates incidents; RECOVER restores affected assets/operations and communicates recovery progress. |
| `nist-csf-2-un-01` | unanswerable | Does CSF 2.0 prove that our cloud deployment is secure and compliant today? | CSF Overview, pp. 6-7 | Boundary answer: no. CSF 2.0 is a flexible framework for managing and communicating cybersecurity risk; it does not certify a specific deployment as secure or compliant today. |

## Boundary-Answer Expectations

Across the five unanswerable cases, a good answer should:

- Say that the requested claim/action is not supported by the provided PDF.
- Briefly state what the document can support instead.
- Avoid making live-status, vendor-approval, legal/compliance, or safety-operation claims.
- Provide a helpful next step, such as checking a live system, site procedure, authorized safety person, qualified reviewer, or applicable formal requirements.
- Include a safety caution for high-risk OSHA boundary cases.
