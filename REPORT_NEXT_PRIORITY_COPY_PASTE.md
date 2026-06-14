# eMAS Report Next Priority Copy-Paste Sections

Created: 2026-06-14  
Purpose: sections to update **after** the critical checklist, only if there is time.

## Next Priority Order

These are not as urgent as the abstract, objectives, scope, architecture, tools, evaluation, data collection, and conclusion. However, updating them will make the report feel more consistent and mature.

| Priority | Section | Why update it |
| --- | --- | --- |
| P2 | 1.8 Summary | Chapter 1 should summarize the updated objectives, scope, and system direction. |
| P2 | 2.5 Research Gap | This section should better explain why eMAS is different from normal APS systems and simple chatbots. |
| P2 | 3.7 Integrated Theoretical Framework of eMAS | The old framework is too BDI/MAS-only and should connect theory to the current full-stack agent workflow. |
| P2 | 4.6 Data Analysis Techniques | This should match the revised evaluation and data collection sections. |
| P2 | 4.7 Reliability and Validity | This should mention simulated data, seeded scenarios, automated tests, and prototype limitations. |
| P2 | 5.1 Introduction | Chapter 5 should introduce the updated analysis plan clearly. |
| P2 | 5.2 Data Preparation | This should explain how logs, traces, test outputs, and simulated records are prepared. |
| P2 | 5.3 Descriptive Analysis | This should include actual eMAS metrics, not only generic averages. |
| P2 | 5.4 Inferential Analysis | This should be careful: statistical tests are useful only if enough user/task data is collected. |
| P2 | 5.5 Qualitative Data Analysis | This should focus on usability, trust, explanation clarity, and approval confidence. |
| P2 | 5.6 Advanced/Exploratory Analysis | This should include disruption scenarios such as shortages, machine issues, and approval cases. |
| P2 | 5.7 Data Interpretation and Reporting | This should explain how all results answer the research questions. |
| P2 | 6.3 Problems and Challenges Encountered | This should include real current engineering challenges, not only generic factory issues. |

## 1.8 Summary

In this chapter, the background, problem statement, purpose, objectives, research questions, scope, and significance of the Engineering Management AI Agentic System (eMAS) were presented. The chapter explained that modern manufacturing environments are becoming more complex and require systems that can provide faster access to operational data, better scheduling support, and more flexible decision-making. Traditional engineering management systems often depend on manual navigation, repeated data checking, and separate tools, which can increase workload and delay decision-making.

This research focuses on eMAS as an AI-assisted manufacturing management prototype that combines a frontend interface, backend operational API, database, and AI assistant service. The system is designed to help users interact with factory information through both normal interface pages and natural-language requests. The scope includes functions such as job scheduling, production data access, reports, dashboard visualization, inventory and machine-resource queries, shortage analysis, and approval-controlled AI-assisted actions. The study does not aim to replace human decision-makers or directly control factory machines. Instead, it investigates how AI assistance can reduce manual interaction and support safer, more informed engineering management decisions in a simulated manufacturing environment.

## 2.5 Research Gap

The literature review shows that Industry 4.0 technologies, multi-agent systems, natural-language processing, and AI-based decision support systems have each contributed to modern manufacturing management. However, many existing systems address these areas separately. Advanced planning and scheduling systems are strong in optimization and production planning, but they often require structured input, technical knowledge, and manual configuration. On the other hand, chatbot-based systems may improve user interaction, but they are often limited to answering questions and may not be deeply connected to operational factory data or safe workflow execution.

This creates a gap between intelligent conversation and practical manufacturing management. Factory users need systems that can not only understand natural-language requests, but also retrieve accurate operational data, support scheduling and reporting tasks, explain recommendations, and prevent unsafe automated changes. In many existing tools, natural-language interaction, backend operational integration, approval control, and decision support are not combined into one lightweight prototype.

This research addresses the gap by developing eMAS as an AI-assisted engineering management prototype. eMAS connects a natural-language Factory Agent with backend manufacturing APIs, simulated factory data, scheduling and reporting functions, and approval-controlled actions. The research therefore explores how an agentic system can support practical manufacturing workflows while still keeping human users involved in important business-changing decisions.

## 3.7 Integrated Theoretical Framework of eMAS

The integrated theoretical framework of eMAS combines AI agent theory, the Belief-Desire-Intention (BDI) model, Natural Language Processing (NLP), Decision Support System (DSS) theory, and smart manufacturing concepts. These theories are not applied as separate ideas, but as connected foundations that guide the design of the system. AI agent theory supports the idea that the system should be able to interpret a user request, reason about available information, and select suitable actions. The BDI model is used as a conceptual explanation of this reasoning process, where beliefs represent the current factory data, desires represent operational goals, and intentions represent selected actions or recommendations.

NLP provides the human-agent interface by allowing users to express factory-management requests in natural language. These requests are transformed into structured tasks that can be handled by the Factory Agent. DSS theory supports the role of eMAS as a system that assists human decision-makers by presenting relevant information, recommendations, and explanations. Smart manufacturing and Industry 4.0 concepts provide the operational context, where production data, scheduling, inventory, machines, and reports must be connected to support timely decisions.

In the implemented prototype, these theories are represented through a layered architecture. The frontend allows user interaction, the backend API provides access to structured factory data, the database stores operational records, and the Factory Agent performs natural-language interpretation, tool selection, information retrieval, and response preparation. For business-changing actions, human approval is required before execution. This integrated framework ensures that eMAS remains both intelligent and controlled, supporting automation while preserving human oversight.

## 4.6 Data Analysis Techniques

The collected data will be analyzed using both quantitative and qualitative techniques. Quantitative analysis will be used to measure system performance, task efficiency, automation benefits, and reliability. The main quantitative measures include task completion time, number of user interactions, response time, successful task completion rate, scheduling correctness, report or query accuracy, approval workflow completion, and automated test pass rate. Descriptive statistics such as mean, minimum, maximum, standard deviation, and percentage improvement will be calculated to summarize these results.

Where suitable, comparative analysis will be performed between normal menu-based workflows and AI-assisted workflows. For example, the number of steps required to find a report or check scheduling information can be compared with the number of steps required when using the AI assistant. If enough user or proxy-user task data is collected, statistical tests such as paired sample t-tests or non-parametric alternatives may be used to check whether the observed differences are meaningful. However, if the sample size is small, the analysis will focus more on descriptive comparison and practical improvement rather than strong statistical claims.

Qualitative analysis will be used to interpret user feedback, observations, and comments about the system. The feedback will be grouped into themes such as ease of use, clarity of AI responses, trust in recommendations, usefulness of approval control, and perceived workload reduction. Automated test results and system traces will also be reviewed to identify common failure patterns, reliability issues, and areas for improvement. By combining quantitative metrics with qualitative interpretation, the analysis can provide a balanced view of both technical performance and user experience.

## 4.7 Reliability and Validity

Reliability is supported by using repeated and controlled evaluation procedures. The system is tested using simulated factory data, seeded manufacturing scenarios, backend API tests, frontend tests, and end-to-end workflow tests. These testing methods help ensure that the same inputs and scenarios can be repeated to observe whether eMAS behaves consistently. Automated tests are especially important because they allow important system functions, such as scheduling, reporting, inventory queries, AI assistant responses, and approval workflows, to be checked repeatedly during development.

Validity is supported by aligning the evaluation measures with the research objectives and research questions. Since the goal of eMAS is to reduce manual interaction, improve access to factory information, support decision-making, and maintain safe AI-assisted actions, the evaluation focuses on task completion time, interaction count, recommendation usefulness, correctness of retrieved data, approval traceability, and system reliability. These measures are directly related to the intended contribution of the project.

The study also acknowledges several limitations. The evaluation is conducted in a simulated or sample-data environment rather than a live industrial factory. Therefore, the results may not fully represent all real-world production conditions. Proxy users may also not have the same experience as professional factory operators. To reduce this limitation, the simulated data and scenarios are designed to represent typical manufacturing-management tasks, and the system outputs are compared with known backend records and expected scenario results. This helps improve the trustworthiness of the evaluation while recognizing that future testing with real factory data would be needed for stronger industrial validation.

## 5.1 Introduction

This chapter explains how the collected data will be analyzed to evaluate the Engineering Management AI Agentic System (eMAS). Since eMAS is designed as both a manufacturing management prototype and an AI-assisted decision support system, the analysis must consider more than only technical performance. The analysis will examine whether the system improves usability, reduces manual work, supports better access to operational information, provides useful recommendations, and behaves reliably under representative manufacturing scenarios.

The data analysis plan is connected directly to the research questions. For natural-language interaction, the analysis considers whether users can complete factory-management tasks more easily through the AI assistant. For automation, the analysis compares the amount of manual interaction required with and without AI assistance. For decision support, the analysis checks whether the system provides relevant and correct responses based on the simulated factory data. For safety, the analysis reviews whether approval-controlled actions are handled properly. For reliability, the analysis uses system logs, automated tests, and scenario results to determine whether the prototype behaves consistently.

The analysis combines descriptive statistics, comparative analysis, qualitative feedback review, and scenario-based evaluation. This mixed approach is suitable because eMAS involves both measurable system behavior and user experience. Quantitative results show performance trends, while qualitative findings explain how users perceive the system and where improvements are needed.

## 5.2 Data Preparation

Before analysis is performed, the collected data must be prepared to ensure that it is complete, consistent, and suitable for evaluation. The data used in this research may come from simulated manufacturing records, seeded test scenarios, backend API responses, Factory Agent session traces, frontend interaction records, automated test outputs, and user or proxy-user feedback. Each data source must be organized so that it can be compared against the relevant research question.

For simulated factory records, the data is checked to ensure that important fields such as job identifiers, machine identifiers, schedule times, inventory quantities, production records, and report values are complete and correctly formatted. Any incomplete or duplicated records are removed or corrected before analysis. For API responses and system logs, the outputs are reviewed to confirm that the request, response status, timestamp, and relevant result values are available. This allows the researcher to trace whether a task was completed successfully and whether the data returned by the system matched the expected backend record.

Factory Agent session traces are prepared by identifying the user request, detected intent, selected backend tool, retrieved data, generated response, and approval status where applicable. Frontend task observations are prepared by recording task completion time, number of interactions, and whether the task was completed successfully. Automated test outputs are grouped by test type, such as backend tests, frontend tests, end-to-end tests, and AI assistant workflow tests. After preparation, the data can be analyzed consistently across usability, automation, decision support, safety, and reliability dimensions.

## 5.3 Descriptive Analysis

Descriptive analysis is used to summarize the overall behavior and performance of eMAS during evaluation. The purpose of this analysis is to provide a clear picture of how the system performs across common manufacturing-management tasks. The main descriptive measures include average task completion time, number of user interactions, response time, successful task completion rate, number of AI-assisted tasks completed, and automated test pass rate.

For usability, descriptive analysis can show whether users complete tasks faster or with fewer interactions when using the AI assistant compared with normal menu navigation. For example, tasks such as checking a job schedule, finding a report, or asking about inventory status can be summarized using average completion time and average number of clicks or steps. For automation, the analysis can show how many tasks were completed through natural-language requests and how many manual steps were reduced.

For decision support, descriptive analysis can summarize how often the system provides correct or useful recommendations based on the simulated factory data. This may include scheduling-related responses, shortage explanations, production summaries, and report-based answers. For reliability, descriptive analysis can summarize test pass rates, error counts, failed scenarios, and repeated workflow success rates. These descriptive results help identify general trends before deeper interpretation is performed.

## 5.4 Inferential Analysis

Inferential analysis may be used if enough repeated task data is collected from user or proxy-user testing. The purpose of inferential analysis is to determine whether the differences observed between menu-based workflows and AI-assisted workflows are likely to be meaningful rather than caused by random variation. For example, if users perform the same task using both the normal interface and the AI assistant, their task completion times and number of interactions can be compared.

If the data is normally distributed and the same users complete both workflow types, a paired sample t-test can be used to compare task completion time or interaction count. If the data does not meet normality assumptions or the sample size is small, a non-parametric test such as the Wilcoxon signed-rank test may be more suitable. These tests can help evaluate whether the AI assistant significantly reduces user effort for selected tasks.

However, inferential analysis will be applied carefully because this project is a prototype study and may have limited access to a large number of real factory users. If the available sample size is small, the analysis will focus more on descriptive statistics, practical improvement, and scenario-based evidence. Automated test results will not be treated in the same way as human survey data. Instead, they will be interpreted using pass rates, failure counts, and scenario outcomes. This ensures that the analysis remains appropriate for the type and amount of data collected.

## 5.5 Qualitative Data Analysis

Qualitative data analysis is used to understand the user experience and the perceived usefulness of eMAS. While quantitative data can show time reduction or test success rates, qualitative feedback helps explain why users find the system helpful, confusing, trustworthy, or difficult to use. The qualitative data may come from user or proxy-user comments, observation notes, questionnaire responses, and feedback collected during task-based evaluation.

The feedback will be reviewed and grouped into common themes. Possible themes include ease of use, clarity of interface, usefulness of AI assistant responses, trust in AI-generated recommendations, understanding of approval-controlled actions, and perceived reduction of manual workload. For example, if users report that the AI assistant makes it easier to find reports or understand scheduling problems, this supports the usability and decision-support objectives of the project. If users report confusion about an AI response or approval request, this indicates an area for improvement.

The qualitative analysis also helps evaluate whether the AI assistant communicates in a way that supports human decision-making. In manufacturing management, users need responses that are clear, grounded in data, and easy to verify. Therefore, the analysis will consider whether responses explain the reason behind recommendations and whether users feel comfortable reviewing or approving suggested actions. These qualitative findings will be used together with quantitative results to provide a more complete evaluation of eMAS.

## 5.6 Advanced/Exploratory Analysis

Advanced or exploratory analysis is used to examine how eMAS behaves under more complex or unexpected manufacturing scenarios. These scenarios may include machine downtime, urgent job changes, inventory shortages, scheduling conflicts, incomplete user requests, or approval-required actions. The goal is to evaluate whether the system can still provide useful assistance when the operating situation is less straightforward.

In shortage-related scenarios, the analysis can examine whether eMAS identifies the affected materials, jobs, or schedules and provides a useful explanation to the user. In scheduling scenarios, the analysis can check whether the system avoids obvious conflicts and presents relevant information for decision-making. In approval scenarios, the analysis can observe whether the system correctly separates read-only actions from business-changing actions and requires user approval before execution.

Exploratory analysis may also review AI assistant behavior when the user request is ambiguous or incomplete. In such cases, the system should avoid making unsupported assumptions and should provide a safe response or ask for clarification where necessary. This type of analysis is important because real users may not always provide perfectly structured commands. The findings from exploratory analysis can help identify future improvements in intent handling, response clarity, data retrieval, and workflow safety.

## 5.7 Data Interpretation and Reporting

The final interpretation of the results will combine quantitative data, qualitative feedback, system logs, and automated test outcomes. The results will be organized according to the research questions so that each question can be answered clearly. For example, natural-language understanding will be interpreted using task success rates, AI assistant traces, and user feedback. Manual workload reduction will be interpreted using task completion time and number of user interactions. Decision support usefulness will be interpreted using response correctness, recommendation relevance, and qualitative feedback.

Safety will be interpreted by reviewing how approval-controlled actions are handled. If the system consistently requires user approval before applying business-changing actions, this supports the safety objective of eMAS. Reliability will be interpreted using backend tests, frontend tests, end-to-end tests, system logs, and scenario results. These results help show whether the prototype behaves consistently across representative use cases.

The reporting of results should avoid overstating the findings. Since the system is evaluated using simulated data and prototype scenarios, the conclusion should describe eMAS as a promising research prototype rather than a fully validated industrial product. The interpretation should clearly state where eMAS performs well, where limitations remain, and what future work is needed before real factory deployment. This balanced reporting helps ensure that the evaluation is both useful and academically credible.

## 6.3 Problems and Challenges Encountered

Several challenges were encountered during the development of eMAS. One major challenge was aligning the AI assistant with real backend system data. Since an AI-generated response may sound correct even when it is not fully supported by the database, the system needs to retrieve information from backend tools and produce responses based on available operational records. This makes tool selection, response grounding, and traceability important parts of the system design.

Another challenge was ensuring safety for business-changing actions. In a manufacturing management system, actions such as changing schedules, applying proposals, or modifying operational records should not be executed automatically without user review. To address this, eMAS uses an approval workflow so that important actions can be checked by a human user before execution. However, designing this workflow requires careful handling of pending approvals, rejected actions, and clear user feedback.

A further challenge was testing the system without access to a live factory environment. Because real factory data may be confidential and difficult to obtain, simulated data and seeded scenarios were used. This makes evaluation more controlled, but it also limits how far the results can be generalized to real industrial environments. Other technical challenges included keeping the frontend and backend API consistent, testing AI assistant workflows, handling scheduling and shortage cases, and maintaining reliability across multiple system components. These challenges show that eMAS is not only an AI project, but also a full-stack software engineering project that requires integration, testing, and careful evaluation.
