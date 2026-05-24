# RAG Chunk Quality Audit

- Collection: `emas_knowledge`
- Vector DB path: `factory-agent\factory_agent\rag\vector_db`
- Total stored chunks: 382
- Source formats: {'pdf': 382}

## Executive Findings

- Current chunks are accessible from ChromaDB with `collection.get(include=["documents", "metadatas"])`.
- All stored chunks are PDF chunks. The Markdown/internal docs in `rag_sources/01_emas_internal_docs` are not in the current source register.
- PDF ingestion is page-first, then recursive character splitting is applied inside each page.
- Stored section metadata does not preserve real PDF sections today. Every chunk uses `section_title = General`.
- Adjacent same-page chunks intentionally overlap by roughly 130-199 characters, which helps retrieval continuity but means chunks are not clean paragraph or sentence units.

## Document Summary

| doc_id | chunks | PDF pages seen | PDF TOC entries | stored section titles | median chars | median words | boundary flags |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `nist_ams_300_1` | 133 | 47 | 128 | 1 | 926 | 133 | 176 |
| `nist_ams_300_11` | 52 | 20 | 16 | 1 | 933 | 131 | 61 |
| `nist_csf_2_0` | 98 | 32 | 12 | 1 | 932 | 131 | 120 |
| `osha_3120_lockout_tagout` | 93 | 44 | 54 | 1 | 950 | 138 | 116 |
| `osha_machine_guarding_checklist` | 6 | 2 | 0 | 1 | 923 | 145 | 5 |

## Per-Document Metrics

### nist_ams_300_1

- Chunks/pages: 133 chunks across 47 pages, avg 2.83 chunks/page, max 5.
- Character length min/p25/median/p75/max: 93/692/926/963/999.
- Word median/max: 133/168; rough sentence median/max: 5/32.
- Stored section titles: General: 133.
- PDF TOC sample: L1 p3 Reference Architecture for Smart Manufacturing; L1 p3 Part 1: Functional Models; L1 p3 Ed Barkmeyer, Evan Wallace, NIST; L1 p3 Abstract; L1 p3 Introduction; L1 p5 Table of Contents; L1 p6 Overview of the Model; L1 p9 1 Activities
- Flags: {'ends_without_terminal_heuristic': 104, 'header_footer_noise_high': 17, 'front_matter_or_boilerplate': 54, 'starts_mid_sentence_heuristic': 72, 'very_short': 9}.
- Adjacent same-page splits: 86 pairs, exact overlap min/median/max 92/171/199 chars.

### nist_ams_300_11

- Chunks/pages: 52 chunks across 20 pages, avg 2.60 chunks/page, max 4.
- Character length min/p25/median/p75/max: 238/697/933/958/998.
- Word median/max: 131/161; rough sentence median/max: 4/22.
- Stored section titles: General: 52.
- PDF TOC sample: L1 p8 Introduction; L2 p8 Purpose; L2 p8 Scope; L2 p8 Disclaimer; L2 p8 Overview; L1 p9 Motivation: Why Collect Manufacturing Data?; L1 p10 Connectivity: Getting Started; L1 p12 Overview of Relevant Standards
- Flags: {'ends_without_terminal_heuristic': 41, 'header_footer_noise_high': 12, 'front_matter_or_boilerplate': 22, 'starts_mid_sentence_heuristic': 20}.
- Adjacent same-page splits: 32 pairs, exact overlap min/median/max 117/169/198 chars.

### nist_csf_2_0

- Chunks/pages: 98 chunks across 32 pages, avg 3.06 chunks/page, max 5.
- Character length min/p25/median/p75/max: 195/712/932/965/1000.
- Word median/max: 131/158; rough sentence median/max: 5/12.
- Stored section titles: General: 98.
- PDF TOC sample: L1 p6 1. Cybersecurity Framework (CSF) Overview; L1 p8 2. Introduction to the CSF Core; L1 p11 3. Introduction to CSF Profiles and Tiers; L2 p11 3.1. CSF Profiles; L2 p12 3.2. CSF Tiers; L1 p14 4. Introduction to Online Resources That Supplement the CSF; L1 p15 5. Improving Cybersecurity Risk Communication and Integration; L2 p15 5.1. Improving Risk Management Communication
- Flags: {'ends_without_terminal_heuristic': 72, 'header_footer_noise_high': 3, 'front_matter_or_boilerplate': 14, 'starts_mid_sentence_heuristic': 48}.
- Adjacent same-page splits: 66 pairs, exact overlap min/median/max 119/173/197 chars.

### osha_3120_lockout_tagout

- Chunks/pages: 93 chunks across 44 pages, avg 2.11 chunks/page, max 3.
- Character length min/p25/median/p75/max: 67/630/950/982/1000.
- Word median/max: 138/183; rough sentence median/max: 5/13.
- Stored section titles: General: 93.
- PDF TOC sample: L1 p-1 Structure Bookmarks; L2 p7 Background; L2 p7 How should I use this booklet?; L2 p7 What is ?lockout/tagout??; L2 p8 Why do I need to be concerned about lockout/tagout?; L2 p9 OSHA Coverage; L2 p9 How do I know if the OSHA standard applies to me?; L2 p9 When does the standard not apply to service and maintenanceactivities performed in industries covered by Part 1910?
- Flags: {'very_short': 1, 'front_matter_or_boilerplate': 9, 'ends_without_terminal_heuristic': 82, 'starts_mid_sentence_heuristic': 34, 'header_footer_noise_high': 3}.
- Adjacent same-page splits: 49 pairs, exact overlap min/median/max 130/182/199 chars.

### osha_machine_guarding_checklist

- Chunks/pages: 6 chunks across 2 pages, avg 3.00 chunks/page, max 3.
- Character length min/p25/median/p75/max: 373/685/923/956/967.
- Word median/max: 145/150; rough sentence median/max: 15/21.
- Stored section titles: General: 6.
- PDF TOC sample: No PDF bookmark TOC detected
- Flags: {'front_matter_or_boilerplate': 6, 'ends_without_terminal_heuristic': 3, 'starts_mid_sentence_heuristic': 2}.
- Adjacent same-page splits: 4 pairs, exact overlap min/median/max 131/167/192 chars.

## Boundary Examples

### nist_ams_300_1

- `nist_ams_300_1_c0000` page 1, section `General`, starts_mid=False, ends_mid=True
  - NIST Advanced Manufacturing Series 300-1 | Reference Architecture for Smart | Manufacturing | Part 1: Functional Models | Edward Barkmeyer | Evan K. Wallace | This publication is available free of charge from: | http://dx.doi.org/10.6028/NIST.AMS.300-1
- `nist_ams_300_1_c0001` page 2, section `General`, starts_mid=False, ends_mid=True
  - NIST Advanced Manufacturing Series 300-1 | Reference Architecture for Smart | Manufacturing | Part 1: Functional Models | Edward Barkmeyer | Evan K. Wallace | Systems Integration Division | Engineering Laboratory | This publication is available free of charge from: | http://dx.doi.org/10.6028/NIST.AMS.300-1 | September 2016 | U.S. Department of Commerce | Penny Pritzker, Secretary | National Institute of Standards and Technology | Willie May, Under Secretary of Commerce for Standards and Technology and Director
- Adjacent overlap `nist_ams_300_1_c0002` -> `nist_ams_300_1_c0003` page 3 (181 exact chars)
  - left tail: r product- | and facility-specific functions in a production system, and thus for specifications for | manufacturing software/hardware systems components. Assigning these narrower functions to | components begets a systems architecture, for which the information flows described in this
  - right head: manufacturing software/hardware systems components. Assigning these narrower functions to | components begets a systems architecture, for which the information flows described in this | document identify the necessary interactions among the components. The information flow | elements a
- Adjacent overlap `nist_ams_300_1_c0003` -> `nist_ams_300_1_c0004` page 3 (191 exact chars)
  - left tail:  document is a part of the definition of a reference architecture for the integration of | manufacturing software applications in the areas of fabrication and assembly of discrete electro | mechanical parts.  The reference architecture is an element of the Smart Manufacturing Systems
  - right head: manufacturing software applications in the areas of fabrication and assembly of discrete electro | mechanical parts.  The reference architecture is an element of the Smart Manufacturing Systems | Design and Analysis program at NIST.  The scope of the program, and therefore of the ref

### nist_ams_300_11

- `nist_ams_300_11_c0000` page 1, section `General`, starts_mid=False, ends_mid=True
  - NIST Advanced Manufacturing Series 300-11 | Recommendations for Collecting, | Curating, and Re-Using Manufacturing | Data | Moneer Helu | Thomas Hedberg, Jr. | This publication is available free of charge from: | https://doi.org/10.6028/NIST.AMS.300-11
- `nist_ams_300_11_c0001` page 2, section `General`, starts_mid=False, ends_mid=True
  - NIST Advanced Manufacturing Series 300-11 | Recommendations for Collecting, | Curating, and Re-Using Manufacturing | Data | Moneer Helu | Thomas Hedberg, Jr. | Systems Integration Division | Engineering Laboratory | This publication is available free of charge from: | https://doi.org/10.6028/NIST.AMS.300-11 | July 2020 | U.S. Department of Commerce | Wilbur L. Ross, Jr., Secretary | National Institute of Standards and Technology | Walter Copan, NIST Director and Undersecretary of Commerce for Standards and Technology
- Adjacent overlap `nist_ams_300_11_c0003` -> `nist_ams_300_11_c0004` page 4 (146 exact chars)
  - left tail: cting manufacturing data, how to get started | collect it, and the relevant manufacturing data standards that may help in this process. | Key words | Additive manufacturing; Connectivity; Data collection; Data curation; Data management; | Smart Manufacturing; Subtractive manufacturing. | i
  - right head: Key words | Additive manufacturing; Connectivity; Data collection; Data curation; Data management; | Smart Manufacturing; Subtractive manufacturing. | i | ______________________________________________________________________________________________________ | This publication is available 
- Adjacent overlap `nist_ams_300_11_c0008` -> `nist_ams_300_11_c0009` page 8 (175 exact chars)
  - left tail:  to broadly- | accepted, international, open, consensus-based standards are in scope, and proprietary data | formats are not in scope. Data from computer numerical control (CNC)-based subtractive | processes (e.g., milling, turning) and CNC metal-based additive processes (e.g., direct-
  - right head: formats are not in scope. Data from computer numerical control (CNC)-based subtractive | processes (e.g., milling, turning) and CNC metal-based additive processes (e.g., direct- | energy deposition, powder-based fusion) are in scope. Data from polymer-based additive | processes and mas

### nist_csf_2_0

- `nist_csf_2_0_c0000` page 1, section `General`, starts_mid=False, ends_mid=True
  - National Institute of Standards and Technology | This publication is available free of charge from: https://doi.org/10.6028/NIST.CSWP.29 | February 26, 2024 | The NIST Cybersecurity | Framework (CSF) 2.0
- `nist_csf_2_0_c0001` page 2, section `General`, starts_mid=False, ends_mid=True
  - The NIST Cybersecurity Framework (CSF) 2.0 | i | NIST CSWP 29 | February 26, 2024 | Abstract | The NIST Cybersecurity Framework (CSF) 2.0 provides guidance to industry, government | agencies, and other organizations to manage cybersecurity risks. It offers a taxonomy of high- | level cybersecurity outcomes that can be used by any organization ? regardless of its size, | sector, or maturity ? to better understand, assess, prioritize, and communicate its | cybersecurity efforts. The CSF does not prescribe how outco
- Adjacent overlap `nist_csf_2_0_c0001` -> `nist_csf_2_0_c0002` page 2 (170 exact chars)
  - left tail: ose outcomes. This document describes CSF 2.0, its components, and | some of the many ways that it can be used. | Keywords | cybersecurity; Cybersecurity Framework (CSF); cybersecurity risk governance; cybersecurity risk | management; enterprise risk management; Profiles; Tiers. | Audience
  - right head: Keywords | cybersecurity; Cybersecurity Framework (CSF); cybersecurity risk governance; cybersecurity risk | management; enterprise risk management; Profiles; Tiers. | Audience | Individuals responsible for developing and leading cybersecurity programs are the primary | audience for the CS
- Adjacent overlap `nist_csf_2_0_c0002` -> `nist_csf_2_0_c0003` page 2 (184 exact chars)
  - left tail: hose making and influencing policy (e.g., associations, professional organizations, regulators) | who set and communicate priorities for cybersecurity risk management. | Supplemental Content | NIST will continue to build and host additional resources to help organizations implement the
  - right head: who set and communicate priorities for cybersecurity risk management. | Supplemental Content | NIST will continue to build and host additional resources to help organizations implement the | CSF, including Quick Start Guides and Community Profiles. All resources are made publicly | avail

### osha_3120_lockout_tagout

- `osha_3120_lockout_tagout_c0002` page 3, section `General`, starts_mid=False, ends_mid=True
  - Contents | Page | Background ............................................................................... 1 | How should I use this booklet? ............................................ 1 | What is ?lockout/tagout?? .................................................... 1 | Why do I need to be concerned | about lockout/tagout? ........................................................... 2 | OSHA Coverage ........................................................................ 3 | How do I know if the OSHA stand
- `osha_3120_lockout_tagout_c0003` page 3, section `General`, starts_mid=False, ends_mid=True
  - How does the standard apply to general | industry service and maintenance operations? .................... 4 | Requirements of the Standard................................................. 6 | What are OSHA?s requirements? ......................................... 6 | What must an energy-control procedure include? ............... 7 | What must workers do before they | begin service or maintenance activities? ............................. 8 | What must workers do before they | remove their lockout or tagout devi
- Adjacent overlap `osha_3120_lockout_tagout_c0002` -> `osha_3120_lockout_tagout_c0003` page 3 (186 exact chars)
  - left tail: ivities performed | in industries covered by Part 1910? ..................................... 3 | How does the standard apply to general | industry service and maintenance operations? .................... 4 | Requirements of the Standard................................................. 6
  - right head: How does the standard apply to general | industry service and maintenance operations? .................... 4 | Requirements of the Standard................................................. 6 | What are OSHA?s requirements? ......................................... 6 | What must an energy
- Adjacent overlap `osha_3120_lockout_tagout_c0004` -> `osha_3120_lockout_tagout_c0005` page 4 (185 exact chars)
  - left tail: maintenance procedures? .................................. 16 | What if a group performs service | or maintenance activities? .................................................. 16 | What if a shift changes during | machine service or maintenance? ...................................... 16
  - right head: or maintenance activities? .................................................. 16 | What if a shift changes during | machine service or maintenance? ...................................... 16 | How often do I need to review | my lockout/tagout procedures? ..................................

### osha_machine_guarding_checklist

- `osha_machine_guarding_checklist_c0001` page 1, section `General`, starts_mid=False, ends_mid=True
  - Mechanical Hazards | The point of operation:   | 9. Is there a point-of-operation safeguard provided for the machine?   | 10. Does it keep the operator s hands, fingers, body out of the danger area?   | 11. Is there evidence that the safeguards have been tampered with or removed?   | 12. Could you suggest a more practical, effective safeguard?   | 13. Could changes be made on the machine to eliminate the point-of-operation hazard | entirely?   | Power transmission apparatus:   | 14. Are there any unguarded gears,
- `osha_machine_guarding_checklist_c0003` page 2, section `General`, starts_mid=False, ends_mid=True
  - NJ State AFL-CIO Machine Guarding Checklist | Page 2 of 2 | Training | Yes | No | 27. Do operators and maintenance workers have the necessary training in how to use the | safeguards and why? | 28. Have operators and maintenance workers been trained in where the safeguards are | located, how they provide protection, and what hazards they protect against? | 29. Have operators and maintenance workers been trained in how and under what | circumstances guards can be removed? | 30. Have workers been trained in the procedur
- Adjacent overlap `osha_machine_guarding_checklist_c0001` -> `osha_machine_guarding_checklist_c0002` page 1 (147 exact chars)
  - left tail: and stopping controls within easy reach of the operator?   | 18. If there is more than one operator, are separate controls provided?   | Other moving parts:   | 19. Are safeguards provided for all hazardous moving parts of the machine, including | auxiliary parts?   | Nonmechanical Hazards
  - right head: Other moving parts:   | 19. Are safeguards provided for all hazardous moving parts of the machine, including | auxiliary parts?   | Nonmechanical Hazards | 20. Have appropriate measures been taken to safeguard workers against noise hazards?   | 21. Have special guards, enclosures, or perso
- Adjacent overlap `osha_machine_guarding_checklist_c0003` -> `osha_machine_guarding_checklist_c0004` page 2 (187 exact chars)
  - left tail: ? | 32. If protective equipment is required, is it appropriate for the job, in good condition, | kept clean and sanitary, and stored carefully when not in use? | 33. Is the operator dressed safely for the job (i.e., no loose-fitting clothing or jewelry? | Machinery Maintenance and Repair
  - right head: kept clean and sanitary, and stored carefully when not in use? | 33. Is the operator dressed safely for the job (i.e., no loose-fitting clothing or jewelry? | Machinery Maintenance and Repair | 34. Have maintenance workers received up-to-date instruction on the machines they | service? | 3

## Gap Against Section -> Paragraph -> Sentence Chunking

1. Section gap: PDF bookmark TOCs exist for four of the five PDFs, but the ingestion code does not use them. The Markdown header splitter only recognizes `#`, `##`, and `###`, which are not present in plain PDF-extracted text, so all PDF chunks become `General`.
2. Paragraph gap: PyMuPDF `page.get_text("text")` preserves visual line breaks more than semantic paragraphs. The recursive splitter sees many line breaks, so it often splits by visual lines rather than true paragraphs.
3. Sentence gap: `. ` is only the third fallback separator after double-newline and newline. Many chunk boundaries are created by size and overlap, so chunks frequently start or end inside a sentence or repeated paragraph tail.
4. Page gap: The pipeline splits each page independently. A section or paragraph that crosses pages cannot be reconstructed before chunking.
5. Noise gap: Front matter, table-of-contents text, repeated publication headers, page numbers, and checklist table columns are embedded as normal chunks.
6. Traceability gap: Metadata has page and char ranges, but not `section_id`, `section_path` from real PDF structure, `paragraph_index`, `sentence_start`, or `sentence_end`.

## Recommended Fix Order

1. Use PDF TOC/bookmarks as the first section map where available, and fall back to font-size heading detection where no TOC exists.
2. Extract pages into section blocks before chunking, allowing sections to continue across page boundaries while retaining page spans.
3. Normalize PDF text into paragraphs by joining visual line wraps and preserving blank-line or heading breaks.
4. Split paragraphs into sentences, then pack adjacent sentences into chunks under a token budget with small sentence-level overlap.
5. Store richer metadata: `section_title`, `section_path`, `section_level`, `page_start`, `page_end`, `paragraph_index`, `sentence_start`, `sentence_end`, and `chunk_strategy_version`.
6. Rebuild both Chroma and BM25 from the same source manifest, and keep one canonical vector DB path to avoid stale duplicate stores.

## Aggregate Flags

- {'ends_without_terminal_heuristic': 302, 'header_footer_noise_high': 35, 'front_matter_or_boilerplate': 105, 'starts_mid_sentence_heuristic': 176, 'very_short': 10}
