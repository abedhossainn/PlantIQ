# Capstone Project Proposal
## Air-Gapped RAG System for Industrial OT Environments

---

## Section 1: Project Data

### Student Information
- **Student name:** Syed Abed Hossain
- **Contact phone number:** 443 975 0604
- **UMBC email address:** syedabh1@umbc.edu
- **Semester and year of capstone experience:** Spring 2026
- **Expected graduation date:** May 25, 2026

### Capstone Course Information
- **Capstone faculty:** Dr. Mohammad Samarah, Dr. Melissa Sahl
- **Capstone advisor:** Dr. Mohammad Samarah, Dr. Melissa Sahl

### Sponsor Client Information
- **Client contact name:** Randy Holt
- **Client contact title:** Supervisor, LNG Operations
- **Client contact phone number:** 443 771 2023
- **Client contact email address:** randy.holt@bhegts.com
- **Client organization name:** Cove Point - BHE GT&S
- **Client organization other stakeholders with interest in this project and their titles:**
  - [Michael Thorne - Supervisor, LNG Operations]
  - [Virang Parekhji - Superintendent, LNG Operations]
  - [Wesley Evers - LNG Production Coordinator]
  - [Randy Holt - Supervisor, LNG Operations]

---

## Section 2: Project Information

### Project Title
**Air‑Gapped RAG System for Industrial OT Environments**

### Problem Statement
Real-time troubleshooting at LNG export facilities and other industrial OT (Operational Technology) environments is significantly hampered by the inability to quickly access accurate, equipment-specific technical information. Proprietary equipment manuals are not available online, and strict cybersecurity policies prevent the use of public search engines and cloud-based AI tools. Consequently, technicians must manually search through hundreds of pages across multiple vendor manuals during time-sensitive troubleshooting scenarios. This slow, error-prone process increases operational downtime and elevates safety risks in a critical infrastructure environment where rapid response is essential.

The fundamental problem is: **How can industrial facilities provide technicians with instant, accurate access to technical documentation while maintaining strict air-gapped security requirements and protecting proprietary information?**

### Project History and Evolution

#### Original Problem Discovery
This project originated from direct field experience working as an OT Cybersecurity Technician at a BHE GT&S-operated LNG export facility. During routine operations and emergency troubleshooting, a persistent inefficiency became clear: technicians had no fast way to locate precise guidance in proprietary manuals. Standard OT troubleshooting relies on alarms, logs, and vendor manuals, but searching PDFs is limited to Windows file search and physical copies require remembering manual names and locations, often turning urgent fixes into long manual hunts.

#### Existing Practice (No Formal Request)
There was no formal initial request; the site relied on ad hoc search. For PDFs, technicians used Windows search to find likely files and then skimmed manually. For physical manuals, they depended on memory of manual names and storage locations, which is unreliable under time pressure.

#### Scope Evolution
As client needs were analyzed more deeply, the project scope evolved to incorporate modern AI capabilities while addressing the unique constraints of OT environments:

1. **From Simple Search to RAG:** Recognition that Retrieval-Augmented Generation could provide natural language question-answering rather than just document retrieval.

2. **Security Requirements Clarification:** Understanding that the system must operate completely offline (air-gapped) to comply with:
   - IEC 62443 (Industrial Cybersecurity Standards)
   - NERC CIP (Critical Infrastructure Protection)
   - Vendor licensing agreements prohibiting cloud upload of proprietary manuals

3. **Document Complexity Recognition:** Realization that engineering manuals contain complex visual elements (P&ID diagrams, electrical schematics, equipment photos, data tables, mathematical equations) that require Vision-Language Model (VLM) processing rather than simple OCR.

4. **Human-in-the-Loop Quality Assurance:** Addition of structured validation workflows to ensure AI-processed content accurately preserves critical safety information before deployment.

5. **Resource Constraints:** Confirmation that the system must run on locally available hardware with limited GPU resources, ruling out cloud-based solutions and requiring optimization for on-premises deployment.

#### Current Project Definition
The project now encompasses a complete end-to-end system:
- Multi-stage document ingestion pipeline with VLM-powered validation
- Local large language model orchestration with memory optimization
- Human-in-the-loop review workflows for quality assurance
- Production deployment on air-gapped infrastructure
- User interface for natural language query and cited response delivery

This evolution represents a shift from a basic search tool to a sophisticated AI system designed specifically for the security, safety, and operational requirements of critical infrastructure environments.

### Existing Solutions and Differentiation (Market Landscape)

Many teams can already build “chat with your documents” experiences, but the OT/LNG environment in this proposal adds hard requirements: **air‑gapped operation**, proprietary vendor manuals that must not leave the facility, and safety‑critical correctness with traceability and review gates.

The proposed solution is not just a chat UI; it is a governed, offline document transformation + validation workflow that produces an approved and auditable knowledge base before technicians can query it.

#### Local “chat with your documents” products (RAG)

Several established tools support local/self-hosted document Q&A using RAG, including **PrivateGPT**, **AnythingLLM**, and **Open WebUI**.

PrivateGPT positions itself around private document interaction where “no data leaves your execution environment,” providing local document ingestion and question-answering capabilities.

AnythingLLM documents RAG as retrieving only a small amount of semantically relevant context and exposes tuning options such as reranking (e.g., an “Accuracy Optimized” mode).

Open WebUI provides a tutorial workflow for configuring RAG by creating a knowledge base, uploading documentation, connecting it to a model, and querying it for enhanced assistance.

**Why these are not sufficient as-is for this OT use case:** they primarily prove local RAG retrieval and chat experiences are feasible, but this proposal’s biggest risk is upstream of retrieval—engineering manuals with tables, diagrams, and schematics can be extracted incorrectly in subtle ways that are safety-relevant.

This capstone’s differentiator is treating ingestion fidelity + review governance (VLM-backed validation, evidence artifacts, quantitative QA gates, and human approval/version locking) as first-class MVP requirements so only reviewed content enters the RAG index.

#### Enterprise search + documented RAG patterns

Enterprise search vendors document RAG as an architectural pattern that combines retrieval (full-text, vector, or hybrid) with an LLM that answers using retrieved context and can be instructed to cite sources.

For example, Elastic describes a RAG workflow where Elasticsearch retrieves relevant documents and the LLM generates a response grounded in that retrieved context, with benefits including reduced hallucination and the ability to cite authoritative sources.

These platforms are strong for scalable retrieval, but they do not inherently provide an OT-specific ingestion QA pipeline (VLM validation + evidence artifacts + reviewer approval gates) without custom development aligned to the safety and compliance posture described in this proposal.

#### Industrial copilots

Industrial copilots (e.g., Siemens Industrial Copilot) are positioned to support industrial work with generative AI experiences, reflecting demand for faster access to expertise and documentation in industrial settings.

However, the value proposition of this proposal is a facility-controlled, air‑gapped system centered on proprietary vendor manuals and safety-oriented validation/approval workflows, which are core requirements in this project definition.

#### Differentiation: why this project is needed

This proposal is differentiated by combining four requirements into one coherent, end-to-end system scoped as an MVP deliverable:

- Air‑gapped, proprietary‑data‑safe architecture by design (offline processing and serving).
- High‑fidelity ingestion for engineering documents (VLM validation + evidence artifacts + quantitative QA gates).
- Human approval workflow before operational use (review/edit/approve, version locking, audit trail).
- Operationally verifiable answers (citations and traceability back to source sections/pages).

| Product | What it provides | Strength for this project | Gap vs this proposal’s OT requirements |
|---|---|---|---|
| PrivateGPT | Private document Q&A; positioned so “no data leaves your execution environment.” | Demonstrates viable local/private doc chat patterns. | Does not inherently implement OT-specific VLM validation, evidence artifacts, QA gates, and formal reviewer approval/version locking workflow. |
| AnythingLLM | Document chat using attachments or RAG; documents RAG retrieval of small relevant context; includes tuning like reranking (“Accuracy Optimized”). | Practical local RAG with adjustable retrieval behavior. | Not purpose-built for engineering-manual fidelity validation (tables/schematics) with safety-focused HITL approval gates as a required pipeline stage. |
| Open WebUI (RAG knowledge base) | Knowledge base upload + connect to a model + query via RAG (documented workflow). | Helpful reference UX pattern for knowledge-base chat. | Provides a RAG workflow, but not the proposal’s governed ingestion QA + reviewer approval pipeline needed for safety-critical OT content. |
| Elastic (RAG with Elasticsearch) | Documented RAG pattern: retrieve via full-text/vector/hybrid, then generate grounded responses; can be instructed to cite sources. | Strong retrieval architecture option for enterprise-scale indexing. | Not an OT-specific “manual ingestion fidelity + reviewer approval” solution; still requires custom build to meet air‑gapped and safety validation workflow requirements. |
| Danswer | Open-source enterprise search + chat assistant for private/enterprise knowledge. | Representative of “self-hosted enterprise knowledge assistant” category. | General-purpose; does not inherently enforce the proposal’s VLM validation + evidence artifacts + formal reviewer approval gates tuned to engineering manuals. |
| Siemens Industrial Copilot | Industrial copilot positioned for industrial generative-AI assistance. | Demonstrates market pull for copilots in industry. | Proposal prioritizes air‑gapped handling of proprietary manuals and safety-driven validation/approval governance as the core differentiator. |


---

## Section 3: Project Background

### Description of Client and Organization

#### Organizational Overview
**BHE GT&S (Berkshire Hathaway Energy Gas Transmission & Storage)** is a subsidiary of Berkshire Hathaway Energy, one of North America's largest integrated energy infrastructure companies. BHE GT&S operates critical natural gas infrastructure including:
- Interstate natural gas pipelines spanning multiple states
- Natural gas storage facilities
- LNG (Liquefied Natural Gas) export terminals
- Compression and processing facilities.

The specific client site - Cove Point LNG at Lusby, MD, is an **LNG export facility** that liquefies natural gas for international shipping. This facility represents critical energy infrastructure requiring 24/7 operations and strict safety/security protocols.

#### Organizational Structure (Simplified)
```
Cove Point LNG Export Facility
│
├── Operation
│   ├── Power Block
│   ├── Pre Treatment
│   ├── Liquefaction
│   └── OSBL (Outside Battery Limits)
│
├── Maintenance
│   ├── Instrumentation
│   ├── DCS
│   ├── Electrical
│   └── Mechanical
│
├── Human Resources
│
└── Finance
```

### Stakeholders and Expectations

#### Primary Stakeholders

**1. Operations Technicians (Primary End Users)**
- **Expectation:** Immediate access to accurate troubleshooting guidance without leaving the control room or field location
- **Success Criteria:** Reduce manual search time from 30+ minutes to under 60 seconds for common queries
- **Concern:** System must be as reliable as physical manuals; incorrect information could compromise safety

**2. OT Cybersecurity Team**
- **Expectation:** Complete air-gapped deployment with no external network connectivity
- **Success Criteria:** System passes security audit and maintains compliance with IEC 62443, NERC CIP
- **Concern:** No proprietary vendor data can leave the facility network; all AI processing must be local

**3. Operations Management**
- **Expectation:** Measurable reduction in troubleshooting time and operational downtime
- **Success Criteria:** Demonstrate ROI through reduced mean-time-to-repair (MTTR) metrics
- **Concern:** System must not introduce new operational risks or dependencies

**4. Engineering Team**
- **Expectation:** System maintains technical accuracy for complex diagrams, tables, and specifications
- **Success Criteria:** VLM processing preserves critical technical details from original documents
- **Concern:** AI-generated responses must cite source documents for verification

**5. Safety & Compliance Officers**
- **Expectation:** System enhances safety by providing faster access to safety procedures
- **Success Criteria:** No safety-critical information is misrepresented during document processing
- **Concern:** Human validation required before system goes live with safety-related content

#### Shareholders
As a Berkshire Hathaway Energy subsidiary, ultimate shareholders include Berkshire Hathaway Inc. and public utility customers. Their indirect expectation is operational excellence, safety, and efficiency in critical infrastructure operations.

### Required Resources

#### Hardware Resources
| Resource | Specification | Source |
|----------|--------------|--------|
| Development Workstation | 32GB RAM, NVIDIA RTX 4050 (6GB VRAM) | Student-owned |
| Deployment Server | 64GB RAM, NVIDIA RTX A6000 (24GB VRAM) | Client facility (Provisioned) |
| Air-gapped Network | Isolated OT network segment | Client facility (existing) |
| Storage | 1TB NVMe SSD for models and vector database | Client facility (Provisioned) |

#### Software Resources
| Resource | License | Source |
|----------|---------|--------|
| Python 3.10+ | Open Source | Public repository |
| LangChain | MIT License | Public repository |
| FastAPI | MIT License | Public repository |
| vLLM | Apache 2.0 | Public repository |
| Docling | Apache 2.0 | Public repository |
| pdfplumber or PyMuPDF | MIT License | Public repository |
| Qwen2.5-VL | Apache 2.0 | HuggingFace (local deployment) |
| Llama 3.1 (70B/405B) | Meta License | HuggingFace (local deployment) |
| PostgreSQL | PostgreSQL License | Public repository |
| Qdrant or ChromaDB | Apache 2.0 | Public repository |
| React + TypeScript | MIT License | Public repository |
| Next.js | MIT License | Public repository |
| Tailwind CSS + shadcn/ui | MIT License | Public repository |
| Docker | Apache 2.0 | Public repository |

#### Data Resources
| Resource | Format | Source | Sensitivity |
|----------|--------|--------|-------------|
| Vendor Equipment Manuals | PDF | Client facility (licensed from vendors) | Proprietary/Confidential |
| P&ID Diagrams | PDF/CAD | Client facility | Proprietary/Confidential |
| Standard Operating Procedures | PDF/DOCX | Client facility | Internal Use Only |
| Historical Troubleshooting Cases | Text/Logs | Client facility (anonymized) | Internal Use Only |

**Data Access Note:** All proprietary documents will be processed on client premises or student-owned air-gapped hardware. No proprietary data will be transmitted to cloud services or public networks.

#### Human Resources
| Role | Time Commitment | Source |
|------|----------------|--------|
| Student Developer | 20 hrs/week (Spring 2026) | Student |
| Capstone Faculty Advisor | 2 hrs/week | UMBC |
| Client Technical SME | 2-4 hrs/week | BHE GT&S |
| OT Cybersecurity Reviewer | 1-2 hrs/week | BHE GT&S |
| Test User Group (3-5 technicians) | 2 hrs/month | BHE GT&S |

### Anticipated Challenges, Risks, and Mitigation Strategies

#### Technical Challenges

**Challenge 1: Resource-Constrained Model Orchestration**
- **Description:** Running 70B+ parameter LLMs on limited GPU memory (12GB dev, 24GB production)
- **Risk:** System crashes, GPU OOM errors, poor response times
- **Mitigation:**
  - Implement vLLM with quantization (8-bit/4-bit)
  - Use aggressive memory management and model swapping
  - Subprocess isolation for memory cleanup
  - Benchmark multiple model sizes (7B, 13B, 70B) to find optimal performance/accuracy tradeoff
  - Fall-back architecture using smaller models if memory constraints cannot be overcome

**Challenge 2: Complex Document Ingestion Accuracy**
- **Description:** Engineering manuals contain tables, diagrams, and schematics that standard OCR corrupts
- **Risk:** Critical technical information misrepresented, leading to incorrect troubleshooting guidance
- **Mitigation:**
  - Multi-stage VLM validation pipeline comparing original PDFs to extracted content
  - Human-in-the-loop review for all sections containing tables/figures
  - QA gates with objective acceptance criteria (>95% text accuracy, >90% table structure preservation)
  - Complete audit trail from source PDF to final RAG chunks
  - Iterative refinement based on validation feedback

**Challenge 3: Retrieval Accuracy for Technical Queries**
- **Description:** Standard RAG may fail to retrieve correct context for domain-specific technical questions
- **Risk:** System provides irrelevant or incomplete answers
- **Mitigation:**
  - Implement document restructuring into concept-based sections with question-style headers
  - Hybrid search combining semantic embeddings with keyword filters
  - Test suite with 50+ real-world troubleshooting queries from historical cases
  - Iterative tuning of chunk size, overlap, and retrieval parameters

**Challenge 4: Air-Gapped Deployment Complexity**
- **Description:** No internet connectivity for package downloads, model updates, or remote debugging
- **Risk:** Deployment failures, inability to troubleshoot production issues remotely
- **Mitigation:**
  - Complete offline installation package with all dependencies pre-bundled
  - Docker containerization for reproducible deployment
  - Comprehensive documentation for on-site troubleshooting
  - Staged deployment: development → isolated test environment → production
  - Local model registry with version control

#### Security & Compliance Risks

**Risk 1: Data Leakage Through Model Training**
- **Description:** Concern that proprietary data could be embedded in fine-tuned models
- **Impact:** Vendor license violations, competitive intelligence exposure
- **Mitigation:**
  - Use inference-only approach (no model fine-tuning)
  - RAG architecture keeps proprietary data in vector database, not model weights
  - Regular security audits of data flow
  - Network segmentation verification

**Risk 2: Unauthorized Access to Technical Documentation**
- **Description:** System could enable unauthorized users to access restricted manuals
- **Impact:** Security policy violations, potential safety risks
- **Mitigation:**
  - Role-based access control (RBAC) integrated with facility Active Directory
  - Audit logging of all queries and retrieved documents
  - Physical access controls on server hardware
  - Regular access reviews with security team

**Risk 3: Non-Compliance with Industrial Cybersecurity Standards**
- **Description:** Failure to meet IEC 62443 or NERC CIP requirements
- **Impact:** Regulatory violations, project termination
- **Mitigation:**
  - Early engagement with compliance team for requirements gathering
  - Security architecture review before development begins
  - Compliance checklist validation at each milestone
  - Penetration testing before production deployment

#### Project Management Risks

**Risk 1: Scope Creep**
- **Description:** Stakeholders requesting additional features beyond core RAG functionality
- **Impact:** Timeline delays, incomplete core functionality
- **Mitigation:**
  - Clear requirements documentation with "in-scope" and "future enhancements" sections
  - Regular stakeholder reviews with feature prioritization
  - Minimum Viable Product (MVP) definition for proposal/alpha/beta milestones
  - Defer non-critical features to post-capstone implementation.

  **Risk 2: Client Resource Availability**
- **Description:** Client SMEs may have limited availability due to operational demands
- **Impact:** Delays in requirements validation, testing, and deployment
- **Mitigation:**
  - Establish regular meeting schedule (bi-weekly) early in semester
  - Async communication channels for quick questions
  - Pre-scheduled testing windows for user validation
  - Self-sufficient testing using publicly available equipment manuals during development

**Risk 3: Hardware Provisioning Delays**
- **Description:** Client may delay provisioning production server hardware
- **Impact:** Unable to validate performance at production scale
- **Mitigation:**
  - Develop and test on student-owned hardware (RTX 4050)
  - Use cloud-enabled models during development (later air-gapped for deployment)
  - Document hardware requirements early for client procurement process
  - Design system to be hardware-agnostic (configurable model sizes)

#### Timeline Risks

**Risk: Insufficient Time for Human-in-the-Loop Validation**
- **Description:** Manual review of processed documents may take longer than anticipated
- **Impact:** Cannot validate quality before final deliverable
- **Mitigation:**
  - Prioritize validation of most critical documents first
  - Develop automated QA metrics to pre-filter high-quality sections
  - Involve test user group early (Alpha checkpoint) for parallel validation
  - Scope human review to subset of documents for capstone, with full validation post-graduation

---

## Section 4: Proposed Solution

This section presents the functional and non-functional requirements organized into **three** major requirement sets. Each requirement set addresses a significant system capability essential for delivering a functional prototype of the air-gapped RAG system. The goal of this capstone project is to build a **Minimal Viable Product (MVP)** that demonstrates the feasibility of deploying AI-powered technical documentation retrieval in industrial OT environments, with potential for expansion to production-grade systems if the client chooses to invest further.

**Project Timeline:** 11 weeks (Spring 2026 semester)

---

### Requirement Set 1: Document Ingestion & Processing Pipeline

#### Overview
Enable technical staff to upload proprietary vendor manuals to **air‑gapped server storage** and have them automatically processed, validated, and optimized for RAG retrieval while maintaining accuracy of complex technical content (tables, diagrams, P&IDs, schematics). The MVP includes a **web‑based review interface** with checklists and **inline evidence images**, a **single reviewer workflow**, and a **limited version history** (current + last approved).

#### Requirements Engineering Methods
- **Stakeholder Interviews:** Structured interviews with operations technicians and engineers to understand manual complexity and content requirements
- **Document Analysis:** Analysis of sample vendor manuals to identify content distribution and extraction challenges
- **Technology Prototyping:** Proof-of-concept development using Vision-Language Models for visual element validation
- **User Testing:** Validation sessions with technical reviewers to refine quality standards

#### Implementation Approach

**Weeks 1-4: Core Pipeline Development**
- Implement PDF ingestion and conversion to structured markdown format
- Build VLM-powered validation pipeline to compare extracted content against original PDF pages
- Develop issue categorization system for extraction quality assessment
- Create validation reporting with per-page confidence scoring and evidence image artifacts

**Weeks 5-7: Human-in-the-Loop Review System**
- Section extraction based on document heading structure
- Web‑based review interface for section editing with inline evidence images
- Single-reviewer workflow (no concurrent editing)
- Checklist-driven review status and progress tracking
- Limited version history stored in the database (current + last approved)

**Weeks 8-11: Quality Assurance and Optimization**
- Development of quantitative QA metrics and acceptance criteria
- Implementation of risk-based sampling policy for large documents
- Post-approval text reformatting for RAG optimization (triggered only after approval)
- Vector embedding generation and database indexing of **approved** versions

#### Technologies
- **Backend:** Python 3.10+, FastAPI
- **VLM Processing:** vLLM inference engine with Vision-Language Models
- **Document Processing:** PDF extraction libraries, Pydantic schema validation
- **Deployment:** Docker containers for offline deployment

#### Data Handling Strategy

**Data Collection:**
- Input: PDF vendor manuals via web interface upload to **air‑gapped server storage** (local filesystem or on‑prem object storage)
- Metadata: document title, version, timestamps, user tracking
- Lineage: cryptographic hashing for integrity verification, page-to-section mapping
- Review data: section content, checklist status, reviewer actions stored in Postgres
- Evidence artifacts: validation snapshots stored in local artifact storage for inline display

**Security:**
- All processing occurs on air-gapped infrastructure
- User authentication via facility identity management system
- Role-based access control
- Basic audit logging for reviewer actions and approvals

**Transformation Pipeline:**
1. PDF to markdown conversion with structure preservation
2. VLM validation comparing extracted content to original pages
3. Human review via the review interface with inline evidence images (single reviewer)
4. RAG optimization with semantic chunking and structured headings (post‑approval)
5. Vector embedding generation
6. Indexing in vector database using **approved** versions and metadata

#### Expected Benefits
- Preserve technical accuracy of complex content during digital transformation
- Reduce manual document preparation time through AI-assisted processing
- Ensure safety-critical information integrity via human validation
- Provide traceable review history suitable for MVP evaluation

---

### Requirement Set 2: Natural Language Query Interface & Response Generation

#### Overview  
Enable operations technicians to ask natural language questions about equipment troubleshooting and receive accurate, cited answers drawn from processed vendor manuals within seconds.

#### Requirements Engineering Methods
- **Observational Studies:** Shadowing technicians during troubleshooting to understand query patterns
- **Historical Analysis:** Analysis of maintenance logs to identify common question types
- **Retrieval Testing:** Evaluation of multiple chunking and retrieval strategies
- **Usability Testing:** Interface testing with end users to optimize interaction patterns

#### Implementation Approach

**Weeks 7-9: RAG Backend Development**
- FastAPI middleware with OpenAI-compatible API endpoints
- LangChain-based RAG pipeline implementation
- Document chunking with optimal size and overlap parameters
- Hybrid retrieval combining semantic search and keyword filtering
- Optional reranking layer for improved relevance
- Context assembly with source citation tracking
- LLM inference integration for answer generation

**Weeks 9-11: Chat Interface Development**
- React + TypeScript frontend application
- Real-time response streaming implementation
- Citation display with source document linking
- Query history management
- Multi-turn conversation support

#### Technologies
- **Backend:** FastAPI, LangChain, vLLM, Vector Database
- **Frontend:** React 18, TypeScript, Modern CSS framework
- **Embeddings:** Open-source embedding model
- **LLM:** Local large language model deployment

#### Data Handling Strategy

**Query Processing Flow:**
1. User submits natural language query
2. Query converted to vector embedding
3. Hybrid retrieval from vector database
4. Optional reranking of retrieved chunks
5. Context assembly with source citations
6. LLM generation with streaming response
7. Citation extraction and formatting
8. Basic query logging for troubleshooting and evaluation

**Security:**
- Complete air-gapped operation
- User authentication and session management
- Basic query logging for troubleshooting and evaluation

**Actionable Insights:**
- Instant answers with verifiable source citations
- Query pattern analysis for knowledge gap identification
- Manual usage statistics for content prioritization

#### Expected Benefits
- Dramatic reduction in troubleshooting information retrieval time
- Cited answers enabling user verification
- Continuous availability without dependency on SME availability
- Searchable knowledge base for institutional knowledge retention

---

### Requirement Set 3: Security, Access Control & Operations (MVP Phase)

#### Overview
For the MVP phase, security, access control, and operations are implemented at a **baseline, practical level** to support air‑gapped use while prioritizing core HITL + RAG functionality. Full compliance reporting, advanced monitoring, and automated backup workflows are **out of scope for the MVP** and deferred to post‑capstone phase if client desides to go move forward with the permanent deployment of the application inside their secured network environment.

#### Requirements Engineering Methods
- **Stakeholder Check‑ins:** Confirm minimum security expectations with OT cybersecurity team
- **Risk Review:** Identify high‑impact risks (unauthorized access, data leakage)
- **Operational Baseline:** Define baseline deployment/ops steps for air‑gapped execution

#### Implementation Approach

**Weeks 4-6: Baseline Identity & Access**
- Active Directory/LDAP login integration
- Role definition and RBAC (User, Reviewer, Admin)
- Basic audit logging for authentication and approvals

**Weeks 7-9: Baseline Operational Readiness**
- Docker Compose‑based deployment for air‑gapped environments
- Environment‑based configuration
- Manual backup/export instructions (no automated backups in MVP)

#### Technologies
- **Authentication:** LDAP/Active Directory
- **Authorization:** Basic RBAC in FastAPI
- **Deployment:** Docker Compose (offline)
- **Logging:** Structured logs for authentication and approvals

#### Data Handling Strategy

**Security Measures (MVP):**
- Air‑gapped deployment with local storage only
- Role‑based access control enforced in API
- Audit logs for login and approval actions

**Operational Data (MVP):**
- Manual export of review data and approved outputs
- No automated monitoring/alerting in MVP

#### Expected Benefits
- Satisfies baseline access control needs for MVP
- Maintains air‑gapped data handling
- Leaves room for future compliance, monitoring, and backup automation

---

## User Stories

The following user stories detail the specific functional requirements for the prototype system. Each story follows the standard format: "As a [user type], I want [capability], so that [benefit]."

| Req. ID | Requirement stated as a user story | Expected Completion | Complexity | Risk |
|--------:|-----------------------------------|:-------------------:|:----------:|:----:|
| US-1.1 | As a **Document Administrator**, I want to upload a vendor manual PDF with basic metadata (title, version, system), so that the document is traceable throughout the pipeline. | Week 3 | Low | Low |
| US-1.2 | As a **Technical Reviewer**, I want to receive a VLM validation report with categorized issues (missing text, table fidelity, image loss), so that I can prioritize critical fixes. | Week 4 | Medium | Medium |
| US-1.3 | As a **Technical Reviewer**, I want to review and edit document sections in a **web‑based review interface** with checklists and **inline evidence images**, so that corrections are consistent and auditable. | Week 6 | High | Medium |
| US-1.4 | As a **Document Administrator**, I want to approve and lock a reviewed document version, so that only validated content is ingested for RAG. | Week 8 | Medium | Medium |
| US-1.5 | As a **Document Administrator**, I want the system to store only the **current** and **last approved** section versions, so that review history is limited but traceable. | Week 7 | Medium | Low |
| US-1.6 | As a **QA Reviewer**, I want to see objective QA gate metrics and an accept/reject recommendation, so that go‑live decisions are defensible. | Week 8 | Medium | Medium |
| US-2.1 | As an **Operations Technician**, I want to ask troubleshooting questions in plain English, so that I can find answers without manual PDF searching. | Week 8 | Low | Low |
| US-2.2 | As an **Operations Technician**, I want answers with citations and page numbers, so that I can verify guidance against the source manual. | Week 9 | High | High |
| US-2.3 | As an **Operations Technician**, I want to open the cited source section in context, so that I can confirm related steps and safety notes. | Week 9 | Medium | Medium |
| US-2.4 | As an **Operations Technician**, I want to ask follow‑up questions in the same chat session, so that the system maintains context and avoids repetition. | Week 10 | Medium | Medium |
| US-2.5 | As an **Operations Technician**, I want to bookmark useful answers for future reference, so that I can quickly reuse proven solutions. | Week 10 | Low | Low |
| US-3.1 | As an **Operations Technician**, I want to log in using facility Active Directory credentials, so that access is consistent with OT security policy. | Week 5 | Medium | High |
| US-3.2 | As a **System Administrator**, I want to assign users to roles (User, Reviewer, Admin), so that each user only has access to appropriate functions. | Week 6 | High | High |

### High-Fidelity UI Prototype

A fully functional high-fidelity interactive prototype has been developed to demonstrate the feasibility and usability of the PlantIQ air-gapped RAG system. The prototype, deployed on GitHub Pages for evaluation, serves as a cohesive, start-to-finish experience that showcases the integration of all 13 user stories across the three requirement sets defined in this proposal. The prototype is designed to be visually polished and functionally representative of the final system, with realistic data and interactions that reflect the intended user experience for operations technicians, technical reviewers, and system administrators.

#### Technical Implementation

The prototype is built using the follwoing technologies:
- **Frontend:** React 18 with TypeScript, providing type safety and maintainability
- **Styling:** Tailwind CSS with shadcn/ui component library for professional, accessible UI
- **State Management:** React hooks and Context API for session state and authentication
- **Data Persistence:** Browser localStorage for cross-session data retention and audit simulation
- **Deployment:** GitHub Pages (static hosting) for accessibility and evaluation is structured to reflect real-world application architecture, with clear separation of concerns between components, services, and data management. The prototype includes mock data that simulates the document ingestion, validation, review, and RAG retrieval processes, allowing stakeholders to experience the full workflow from document upload to natural language querying with citations. The frontend is designed to be easily adaptable for integration with a backend API and vector database in future development phases, ensuring that the prototype serves as a solid foundation for the eventual production system.

#### User Experience Validation

The prototype supports evaluation across three user personas:
1. **Operations Technicians** (end users) can experience the chat workflow, citation verification, and bookmark management
2. **Technical Reviewers** can experience document upload, VLM validation reviews, section editing, checklist completion, and approval workflows
3. **System Administrators** can experience user management, role assignment, and access control demonstration

#### Access and Deployment

The prototype is deployed at the following public URL for stakeholder evaluation:

**[https://abedhossainn.github.io/PlantIQ/](https://abedhossainn.github.io/PlantIQ/)**

**Demo Credentials:**
- Field User: `jdoe` / `demo` (Operations Technician access)
- Reviewer: `mchen` / `demo` (Technical Reviewer access)
- Admin: `rholt` / `demo` (System Administrator access)

The prototype source code is maintained in the project Git repository under `/frontend/` and is version-controlled.

#### Document Ingestion & Processing Pipeline (US-1.x)

**US-1.1: Document Upload with Metadata Capture**

*Prototype Flow:*
1. Document Administrator logs in with AD credentials and navigates to `/admin/documents`
2. Clicks **"Upload Document"** button to access the upload form at `/admin/documents/upload`
3. Provides required metadata in a structured form:
   - **File Selection**: Drag-and-drop or click-to-select PDF files (up to 100MB)
   - **Document Title**: Auto-populated from filename, editable
   - **Version**: Semantic version (e.g., 1.0, 2.1)
   - **System**: Dropdown selection (e.g., "Cryogenic Pump System", "LNG Characteristics")
   - **Document Type**: Classification (e.g., "Operating Manual", "Service Guide")
4. On submission, the system:
   - Generates a unique document ID (e.g., `JOB-202602191234-A7C9`)
   - Displays a multi-stage progress pipeline showing: File Upload → Docling Conversion → VLM Validation → Chunking & Embedding → RAG Indexing
   - Each stage animates through active/complete states with timestamps
   - Document appears in the Document Pipeline list with "Uploaded" status

*Acceptance Criteria:*
- Metadata fields (title, version, system) are captured in a form with validation
- Document receives a unique identifier shown in the upload completion screen
- Metadata persists in mock data and is visible in the Document Pipeline table
- Progress tracking shows the document moving through ingestion stages

---

**US-1.2: VLM Validation Report with Issue Categorization**

*Prototype Flow:*
1. After upload completes, document status becomes "Validation Complete" in the pipeline
2. Admin clicks the document row and selects "Start Review" (navigation to `/admin/documents/{id}/validation`)
3. The **VLM Validation Report** page displays:
   - **Summary Statistics**: 5 cards showing Total Issues, Critical (red), High (orange), Medium (amber), Low (blue), and Overall Confidence Score
   - **Issues Table** with columns:
     - Page Number (e.g., 12, 15, 21)
     - Category: Table Fidelity, Image Loss, Missing Text, Formatting, OCR Error
     - Severity: Color-coded badge (Critical/High/Medium/Low)
     - Description: AI-identified issue (e.g., "Table cell alignment lost in conversion")
     - Context: Excerpt or reference
     - Actions: View evidence button
4. Issues are sorted by severity (critical first) for prioritization
5. Admin can download the full report as a reference artifact

*Acceptance Criteria:*
- Validation report lists 5+ issues organized by category (table-fidelity, image-loss, missing-text, formatting, ocr-error)
- Each issue displays severity level with visual indicators (color-coded badges)
- Report page is accessible and downloadable from the review interface
- Page references provide traceability to original source

---

**US-1.3: Section Review Interface with Checklists & Inline Evidence**

*Prototype Flow:*
1. From the validation report, Admin proceeds to **Document Engineering Review** at `/admin/documents/{id}/review`
2. The review interface displays:
   - **Left Sidebar**: List of all document sections with status indicators (Pending → In Review → Complete)
   - **Progress Bar**: Visual progress showing "X of Y sections reviewed"
   - **Main Content Area**: 
     - Section heading and editable markdown content
     - **Review Checklist** with 5 items:
       ☐ Text accuracy confirmed
       ☐ Tables verified  
       ☐ Images described
       ☐ Formatting correct
       ☐ Technical terms accurate
     - **Edit Mode**: Reviewer can click "Edit" to enter markdown editing mode, make corrections, and click "Save"
     - **Evidence Images**: Inline comparison images showing original PDF vs. converted markdown (when applicable)
3. As reviewer checks off items, the section status changes from Pending → In Review → Complete
4. Edit history is tracked with timestamps and reviewer name (e.g., "Chen, Michelle · Feb 19, 10:45 AM")
5. Last approved version is compared with current draft when applicable

*Acceptance Criteria:*
- Review interface renders section markdown content with editable textarea
- Inline evidence images display with original PDF reference
- Checklist items track review progress (checkboxes persist per section)
- Edits are timestamped with reviewer identity in localStorage
- Section status transitions are visible in the left sidebar

---

**US-1.4: Document Approval & Version Lock**

*Prototype Flow:*
1. After all sections are marked complete in the review workflow, Admin navigates to the next gate
2. On `/admin/documents/{id}/qa-gates`, QA metrics are displayed and evaluated
3. If metrics pass or reviewer overrides with approval, Admin proceeds to `/admin/documents/{id}/approve`
4. The **Final Approval** page displays:
   - Document summary card with metadata (title, version, system, page count)
   - Uploaded by / date information
   - QA Score (if available) with color-coded status
   - QA Recommendation (Accept / Reject)
   - **Decision Panel**:
     - Radio buttons: **Approve** or **Reject**
     - Text field for optional approval notes
     - **Lock Document** button (visible after decision)
5. Admin selects **Approve** and clicks the button
6. The system:
   - Records the approval decision with timestamp and reviewer identity
   - Persists approval in localStorage (simulating database storage)
   - Updates document status to **"Approved"** in the pipeline
   - Prevents further edits to the approved version
   - Preserves the current version for future reference

*Acceptance Criteria:*
- Approval action (button click) records decision with timestamp and reviewer identity
- Document status changes to "Approved" in the Document Pipeline
- Approved versions are locked from further review edits
- Approval decision is persisted in localStorage (audit trail simulation)

---

**US-1.5: Version History (Current + Last Approved)**

*Prototype Flow:*
1. In the **Review Client**, the system maintains two versions:
   - **Current Draft**: The reviewer's working edits stored in `sectionContent` state
   - **Last Approved**: The previous approved version referenced in the mockedSections data
2. When a reviewer makes edits and saves:
   - Changes update the "Current" version in state
   - Previous state is pushed to a version history structure
   - localStorage stores the revision with `review-saves-{docId}` key
3. If the document is re-ingested after new updates:
   - The "Last Approved" version remains intact
   - The new section updates become the "Current" version
4. The interface optionally shows a **"View History"** button to compare versions

*Acceptance Criteria:*
- System stores current draft version and last approved version separately
- Version history is persisted in localStorage as `review-saves-{docId}`
- Approved versions are never overwritten by draft changes
- Reviewers can differentiate between current and last approved state

---

**US-1.6: QA Gate Metrics & Accept/Reject Recommendation**

*Prototype Flow:*
1. After review is complete, Admin navigates to `/admin/documents/{id}/qa-gates`
2. The **QA Gate Metrics** page displays:
   - **Recommendation Banner** with color-coded status:
     - **Green (ACCEPT)**: All metrics pass threshold
     - **Red (REJECT)**: One or more critical failures
     - **Amber (MANUAL REVIEW)**: Warnings present, needs evaluation
   - **QA Metric Cards** (grid layout, up to 4 metrics):
     - Text Accuracy (e.g., 94/100 → PASS)
     - Table Structure Preservation (e.g., 87/100 → WARNING)
     - Image Description Coverage (e.g., 91/100 → PASS)
     - Overall Quality Score (e.g., 91/100 → PASS)
   - Each card shows:
     - Metric name with icon
     - Score with "/100" denominator
     - Progress bar (color-coded: green/amber/red)
     - Threshold comparison (e.g., "Threshold: 85")
3. Failed criteria are listed if recommendation is REJECT
4. Admin uses the recommendation to decide whether to proceed with approval

*Acceptance Criteria:*
- QA gates output metric scores with pass/warning/fail status
- Clear accept/manual review/reject recommendation is displayed
- Thresholds are configurable and shown on each metric card
- Failed metrics are highlighted for easy identification

---

#### Natural Language Query Interface (US-2.x)

**US-2.1: Ask Troubleshooting Questions in Plain English**

*Prototype Flow:*
1. Operations Technician logs in with facility AD credentials
2. System redirects (based on role) to `/chat` for non-admin roles
3. **Chat Interface** displays:
   - Header: "PlantIQ" with facility branding
   - Conversation area (empty on first load)
   - Bottom input section:
     - **Textarea**: "Ask a troubleshooting question..." placeholder
     - **Send Button**: Prominent button with send icon
4. Technician types a query: "What is the normal boil-off rate for LNG storage?"
5. On button click or Enter key:
   - Query is submitted to the backend (mock response in proto)
   - Textarea clears
   - A **user message** appears in the conversation
   - System displays loading state
   - Response generates with streaming effect

*Acceptance Criteria:*
- User can type plain-language questions in the textarea
- Submit button sends query to system backend
- Query is logged (visible in mock via message history)
- Response appears within target latency (2-3 seconds in demo)

---

**US-2.2: Answers with Citations & Page Numbers**

*Prototype Flow:*
1. After submitting a query, the chat displays an **Assistant Response** containing:
   - Plain-language answer text (e.g., "Normal boil-off rate for insulated LNG storage is 0.05-0.1% per day...")
   - **Citation Blocks** at the bottom of the response:
     - Citation card showing:
       - Document title: e.g., "COMMON Module 3 Characteristics of LNG"
       - Section heading: e.g., "2.4 Boil-Off Gas Management"
       - **Page Number**: e.g., "Page 8"
       - Relevance score: e.g., "94% relevant"
       - Excerpt preview
   - **"View Source"** button beneath each citation
2. Citations are deterministically selected based on query content (seeded hash)
3. If a citation is missing or incomplete, a warning is shown

*Acceptance Criteria:*
- Each response includes at least one citation with page number
- Citations map to correct document title and section
- Relevance score is displayed for transparency
- Excerpt preview confirms content match
- Missing citations would trigger a visual flag

---

**US-2.3: Open Cited Section in Context**

*Prototype Flow:*
1. In the chat response, technician clicks **"View Source"** button on a citation
2. A **Source Drawer** slides in from the right side of the screen containing:
   - Header: "Source Reference" with document icon and close button
   - **Document Metadata**:
     - Document title (bold, large)
     - Section heading
     - Page reference (e.g., "Page 8 of 45")
   - **Full Section Content**:
     - Markdown-rendered text with proper formatting
     - Tables (if applicable)
     - Related safety notes or context
   - **Related Context**:
     - Links to adjacent sections (e.g., "Previous: 2.3 Pressure Management")
     - Links to next section (e.g., "Next: 2.5 Emergency Procedures")
3. Content displays in a scrollable panel, maintaining citation context
4. Technician can read the complete section, verify guidance, and reference related procedures

*Acceptance Criteria:*
- Cited section opens in a readable side panel
- Full section content with context (heading, body, tables) is displayed
- Content matches the cited source version exactly
- Related sections are accessible for cross-reference

---

**US-2.4: Multi-Turn Conversation with Context Preservation**

*Prototype Flow:*
1. Technician's first query: "How do I cool down a cryogenic pump?" 
   - Response includes steps and citations from "Cryogenic Pump System Operating Manual"
2. Technician asks a follow-up: "What is the maximum cooling rate?"
   - System recognizes this as a follow-up in the same chat session
   - Chat history is preserved in the conversation area
   - New response references earlier answer: "As mentioned in the startup sequence, the maximum cooling rate is 50°C/hr..."
   - New citations are added for the follow-up query
3. Technician can continue asking related questions without losing context
4. **Start New Chat** button (at bottom) allows technician to reset context and begin a new conversation
5. Chat history is stored in browser state (mock equivalent of session memory)

*Acceptance Criteria:*
- Follow-up questions retain prior conversation context
- System references earlier answers when relevant
- Conversation history is visible in chronological order
- User can initiate a new chat at any time (context reset)

---

**US-2.5: Bookmark Answers for Future Reference**

*Prototype Flow:*
1. In the chat interface, after receiving a helpful response, technician sees a **Bookmark Button** (heart/star icon) in the response header
2. Clicking the bookmark button:
   - Button changes state (filled/highlighted)
   - Toast notification confirms: "Answer bookmarked!"
   - Bookmark data is saved to localStorage: `plantiq-bookmarks-{userId}`
   - Bookmark structure includes: `{ id, messageId, query, answer, citations, createdAt }`
3. Technician navigates to `/chat/bookmarks` to view all saved answers
4. **Saved Answers Page** displays:
   - Header: "Saved Answers" with bookmark count badge
   - List of bookmarked responses showing:
     - Original query (highlighted with blue border)
     - Answer text
     - Citation references
     - Date/time saved
     - Delete button to remove bookmark
5. Bookmarks persist across browser sessions (stored in localStorage)
6. Technician can quickly reuse proven solutions

*Acceptance Criteria:*
- User can click a bookmark icon to save responses
- Bookmarks are stored in localStorage and persist across sessions
- Bookmarks page lists all saved answers with full context
- User can delete individual bookmarks
- Quick access to proven troubleshooting solutions

---

#### Security, Access Control & Authentication (US-3.x)

**US-3.1: Login with Facility Active Directory Credentials**

*Prototype Flow:*
1. User navigates to the application (root path `/`)
2. `RootPage` component checks authentication status via `useAuth()` hook
3. If not authenticated, user is redirected to `/login`
4. **Login Page** displays:
   - Application logo and title: "PlantIQ"
   - Facility branding: "BHE GT&S · Cove Point LNG Facility"
   - **Credential Fields**:
     - Username input field
     - Password input field
   - **Submit Button**: "Sign In"
   - **Demo User Quick Buttons** (for prototype testing):
     - "Field User" (jdoe / demo)
     - "Reviewer" (mchen / demo)  
     - "Admin" (rholt / demo)
5. User enters credentials or clicks a demo button
6. `login()` function in AuthContext validates credentials:
   - In production: LDAP/Active Directory integration
   - In prototype: Mock user data from `mockUsers`
7. On success:
   - User token is stored in browser context
   - `isAuthenticated` flag is set
   - User role is determined (admin, reviewer, user)
8. User is redirected to appropriate dashboard:
   - Admin/Reviewer → `/admin/documents` (Document Pipeline)
   - User → `/chat` (Chat Interface)
9. On failure:
   - Error message displayed: "Authentication failed"
   - User remains on login page

*Acceptance Criteria:*
- Login form accepts username and password
- Credentials are validated against mock user database (AD-compatible in production)
- Unknown/disabled accounts are rejected with error message
- Successful logins are recorded (mock in localStorage, audit in production)
- User is redirected to role-appropriate interface

---

**US-3.2: Role-Based Access Control & User Management**

*Prototype Flow:*
1. System Admin logs in with admin credentials
2. After login redirection, admin accesses `/admin/users` for **User Management**
3. **User Management Interface** displays:
   - Header: "User Management" with "Add User" button
   - **Role Distribution Stats**: 4 cards showing:
     - Number of Admins
     - Number of Reviewers
     - Number of Users
     - Total Active accounts
   - **Users Table** organized by role:
     - Admin section (e.g., Randy Holt - rholt)
     - Reviewer section (e.g., Michelle Chen - mchen)
     - User section (e.g., John Doe - jdoe)
   - Each user row contains:
     - Username and full name
     - Email address
     - AD Organization (LDAP)
     - Current Status (Active / Disabled)
     - Role assignment (dropdown)
     - Enable/Disable toggle
     - Last login info
4. Admin can **change a user's role**:
   - Click the role dropdown for a user
   - Select new role (Admin, Reviewer, User)
   - Change is immediately persisted to localStorage
   - User's next session reflects the new role restrictions
5. Admin can **disable/enable users**:
   - Toggle the status switch
   - Change persists in localStorage
   - Disabled users cannot log in
6. **Role-based UI restrictions** enforce access:
   - Users see only `/chat` interface
   - Reviewers see `/admin/documents` and review workflows
   - Admins see admin panel + document pipeline + user management
   - Unauthorized route access redirects to permitted interface

*Acceptance Criteria:*
- Admin can view all users grouped by role
- Admin can assign roles via dropdown (change takes effect immediately)
- Admin can enable/disable users (persisted in localStorage)
- UI/routing enforces role-based access (users cannot access admin routes)
- Role changes are persisted and take effect on next session

---

## End-to-End User Flows in Hi-Fi Prototype

### Flow 1: Technician Query & Citation Verification (US-2.1 → US-2.3)

1. Technician logs in with AD credentials (US-3.1) → redirected to `/chat`
2. Types query: "What is the emergency response for LNG spill?" → clicks Send (US-2.1)
3. System returns answer citing "Cryogenic Pump System Operating Manual, Section 3.1, Page 15" (US-2.2)
4. Technician clicks "View Source" to verify procedure in full context (US-2.3)
5. Reads complete emergency protocol with surrounding safety notes

### Flow 2: Document Approval Workflow (US-1.1 → US-1.6)

1. Document Admin uploads PDF with metadata at `/admin/documents/upload` (US-1.1)
2. System processes through pipeline stages (Docling, VLM, Chunking, Indexing)
3. Admin reviews VLM Validation Report showing issues by category/severity (US-1.2)
4. Admin proceeds to `/admin/documents/{id}/review` to edit sections using checklist (US-1.3)
5. After review complete, navigation to QA gates shows metrics with recommendation (US-1.6)
6. Admin approves document at `/admin/documents/{id}/approve` (US-1.4)
7. Document locked and version history preserved (US-1.5)
8. Approved content now available for technician queries (US-2.1)

### Flow 3: System Administration (US-3.1 → US-3.2)

1. OT Cybersecurity Manager logs in with admin credentials → redirected to `/admin/documents`
2. Navigates to `/admin/users` to manage account access (US-3.2)
3. Reviews role distribution and updates user assignments
4. Disables contractors / enables new technicians
5. Role changes take effect on next user login (US-3.1)

---

All prototype artifacts will be maintained in the project Git repository under `/frontend/`.

---

## Section 5: Git Repository Link

**Official Project Repository:**
- **URL:** [https://github.com/abedhossainn/PlantIQ](https://github.com/abedhossainn/PlantIQ)

### Proposed Production Repository Structure

To support maintainability, secure air-gapped deployment, and clear separation of responsibilities, the project should follow a monorepo structure with explicit boundaries for application layers, infrastructure, testing, and documentation.

```text
PlantIQ/
├── .github/
│   └── workflows/                    # CI/CD pipelines (lint, test, build, deploy)
│
├── frontend/                         # Next.js/React TypeScript UI (PlantIQ web app)
│   ├── app/                          # Route-based pages (chat, admin, login)
│   ├── components/                   # Shared and feature UI components
│   ├── lib/                          # Client utilities, auth context, API clients
│   ├── public/                       # Static assets (logos, icons)
│   ├── tests/                        # Frontend unit/component/e2e tests
│   ├── package.json
│   └── tsconfig.json
│
├── backend/                          # FastAPI middleware + RAG orchestration APIs
│   ├── app/
│   │   ├── api/                      # API routers (chat, auth, admin, docs)
│   │   ├── core/                     # Config, settings, security, logging
│   │   ├── services/                 # RAG, retrieval, citation, business services
│   │   ├── models/                   # Pydantic/domain models
│   │   └── main.py                   # FastAPI entrypoint
│   ├── tests/                        # Backend unit/integration tests
│   ├── pyproject.toml
│   └── requirements.txt
│
├── pipeline/                         # HITL ingestion + validation workflow modules
│   ├── src/
│   │   ├── ingestion/                # Conversion and parsing stages
│   │   ├── validation/               # VLM validation and evidence generation
│   │   ├── review/                   # Section extraction and reviewer workflow tools
│   │   ├── qa/                       # QA gates, scoring, thresholds
│   │   ├── lineage/                  # Manifest/version/audit generation
│   │   └── cli/                      # Pipeline orchestration commands
│   ├── configs/                      # YAML/JSON pipeline configs
│   ├── tests/                        # Pipeline tests and fixtures
│   └── pyproject.toml
│
├── infra/                            # Deployment and platform assets
│   ├── docker/                       # Service Dockerfiles
│   ├── compose/                      # docker-compose for local/offline deployment
│   ├── k8s/                          # Optional Kubernetes manifests (future scale)
│   ├── scripts/                      # Provisioning, backup, restore, migration scripts
│   └── monitoring/                   # Logging/metrics templates and dashboards
│
├── data/                             # Non-source runtime data (gitignored where required)
│   ├── raw/                          # Original input documents
│   ├── processed/                    # Intermediate transformed artifacts
│   ├── artifacts/                    # Validation evidence, QA outputs, audit reports
│   └── indexes/                      # Vector DB persistence and metadata
│
├── docs/                             # Technical and project documentation
│   ├── architecture/                 # Architecture plans, diagrams, ADRs
│   ├── api/                          # API specifications and examples
│   ├── operations/                   # Runbooks, incident response, DR procedures
│   ├── security/                     # Threat model, controls, compliance mappings
│   └── capstone/                     # Proposal, alpha, beta, final deliverables
│
├── tests/                            # Cross-system and end-to-end test suites
│   ├── integration/
│   ├── e2e/
│   ├── performance/
│   └── fixtures/
│
├── tools/                            # Developer and QA utilities (formatters, generators)
├── .env.example                      # Required environment variables template
├── docker-compose.yml                # Unified local/air-gapped deployment entrypoint
├── Makefile                          # Standardized task shortcuts
├── README.md                         # Top-level setup and project overview
└── PROJECT_STATUS.md                 # Progress and change-log source of truth
```