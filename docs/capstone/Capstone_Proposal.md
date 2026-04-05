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
- **Client contact name:** Randy Halt
- **Client contact title:** Supervisor, LNG Operations
- **Client contact phone number:** 443 771 2023
- **Client contact email address:** randy.holt@bhegts.com
- **Client organization name:** Cove Point - BHE GT&S
- **Client organization other stakeholders with interest in this project and their titles:**
  - [TO BE FILLED - OT Cybersecurity Manager/Lead]
  - [TO BE FILLED - Operations Manager]
  - [TO BE FILLED - Safety & Compliance Officer]
  - [TO BE FILLED - IT/OT Infrastructure Lead]

---

## Section 2: Project Information

### Project Title
**Air‑Gapped RAG Knowledgebase for Industrial OT Operations**

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

---

## Section 3: Project Background

### Description of Client and Organization

#### Organizational Overview
**BHE GT&S (Berkshire Hathaway Energy Gas Transmission & Storage)** is a subsidiary of Berkshire Hathaway Energy, one of North America's largest integrated energy infrastructure companies. BHE GT&S operates critical natural gas infrastructure including:
- Interstate natural gas pipelines spanning multiple states
- Natural gas storage facilities
- LNG (Liquefied Natural Gas) export terminals
- Compression and processing facilities

The specific client site is an **LNG export facility** that liquefies natural gas for international shipping. This facility represents critical energy infrastructure requiring 24/7 operations and strict safety/security protocols.

#### Organizational Structure (Simplified)
```
BHE GT&S LNG Facility
│
├── Operations Division
│   ├── Operations Manager
│   ├── Shift Supervisors
│   ├── Process Technicians (primary end users)
│   └── Maintenance Technicians (primary end users)
│
├── Engineering Division
│   ├── Process Engineers
│   ├── Electrical Engineers
│   └── Instrumentation Engineers
│
├── IT/OT Infrastructure
│   ├── IT Manager
│   ├── OT Cybersecurity Team (student's current role)
│   └── Network & Systems Administration
│
└── Safety, Security & Compliance
    ├── HSE (Health, Safety, Environment) Manager
    ├── Security Operations
    └── Regulatory Compliance Officers
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
| Development Workstation | 32GB RAM, NVIDIA RTX 4070 (12GB VRAM) | Student-owned |
| Production Server (Phase 1) | 64GB RAM, NVIDIA RTX 4090/A6000 (24GB VRAM) | Client facility (to be provisioned) |
| Air-gapped Network | Isolated OT network segment | Client facility (existing) |
| Storage | 2TB NVMe SSD for models and vector database | Client facility (to be provisioned) |

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
  - Defer non-critical features to post-capstone implementation

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
  - Develop and test on student-owned hardware (RTX 4070)
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

**Security (MVP):**
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

**Security (MVP):**
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
For the MVP phase, security, access control, and operations are implemented at a **baseline, practical level** to support air‑gapped use while prioritizing core HITL + RAG functionality. Full compliance reporting, advanced monitoring, and automated backup workflows are **out of scope for the MVP** and deferred to post‑capstone hardening.

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

### Acceptance Criteria

- **US-1.1**
  - Upload accepts PDF and required metadata fields (title, version, system).
  - Document appears in processing queue with a unique identifier.
  - Metadata is persisted and visible in pipeline artifacts.
- **US-1.2**
  - Validation report lists issues by category with page references.
  - Report includes a severity/priority indicator for each issue.
  - Reviewer can download or open the report from the review interface.
- **US-1.3**
  - Review interface renders section content with an editable markdown view and checklist.
  - Inline evidence images are displayed with page references.
  - Edits are saved with timestamps and reviewer identity.
  - Reviewer can mark a section complete and track progress.
- **US-1.4**
  - Approval action locks the document version from further edits.
  - Only approved versions are eligible for ingestion.
  - Approval is recorded in the audit trail with reviewer and timestamp.
- **US-1.5**
  - The system stores only the **current** and **last approved** section versions.
  - The last approved version is preserved even if the current draft changes.
- **US-1.6**
  - QA gate outputs metric scores and a clear accept/reject status.
  - Thresholds are configurable and documented.
  - Rejected documents include a list of failing criteria.
- **US-2.1**
  - User can submit a plain‑language question in the chat UI.
  - System returns a response within target latency for the pilot.
  - Query is logged for audit and analytics.
- **US-2.2**
  - Each answer includes at least one citation with page number.
  - Citations map to the correct source document/version.
  - Missing citations are flagged to the user.
- **US-2.3**
  - User can open the cited section in a readable view.
  - The view shows surrounding context (e.g., section heading and body).
  - The displayed content matches the cited source version.
- **US-2.4**
  - Follow‑up questions preserve prior conversation context.
  - The system references earlier answers when relevant.
  - User can start a new chat that resets context.
- **US-2.5**
  - User can bookmark an answer from the UI.
  - Bookmarks are retrievable in a “Saved Answers” list.
  - Bookmarks persist across sessions for the same user.
- **US-3.1**
  - Login supports facility AD credentials via configured identity provider.
  - Access is denied for unknown or disabled accounts.
  - Successful logins are recorded in audit logs.
- **US-3.2**
  - Admin can assign roles to users through an admin interface or config.
  - Role changes take effect immediately for access control.
  - Users cannot access features outside their assigned role.

---

## UI/UX Prototype Plan

### Prototype Development Strategy
To demonstrate the feasibility of the system and validate user requirements, the project will deliver prototypes at three fidelity levels:

**Low-Fidelity Wireframes (Weeks 3-4)**
- Basic layout and navigation structure
- Core user interaction patterns
- Information architecture validation

**High-Fidelity Interactive Prototypes (Weeks 7-8)**
- Detailed visual design
- Interactive navigation and state transitions
- User testing validation

**Functional MVP Implementation (Weeks 9-11)**
- Working React application
- Integration with backend services
- End-to-end user flow demonstration

### Key User Flows

**Flow 1: Technician Query**  
Login → Chat Interface → Submit Question → View Cited Answer → Examine Sources → Follow-up Questions

**Flow 2: Document Processing**  
Login (Admin) → Upload PDF → Review Validation Report → Edit Sections → Approve Document → Deployment

**Flow 3: System Administration**  
Login (Admin) → Manage Users/Roles → Review Audit Logs → Export Review Data

### Design Principles
- Industrial-grade simplicity and reliability
- High-contrast accessibility for various environments
- Limited dependencies on external resources
- Responsive layout for workstation and tablet access

All prototype artifacts will be maintained in the project Git repository under `/docs/ui-prototypes/`.

---

## Section 5: Git Repository Link

**Official Project Repository:**
- **URL:** [https://github.com/[username]/LLL-Rag-Chatbot](https://github.com/[username]/LLL-Rag-Chatbot) [TO BE UPDATED WITH ACTUAL URL]

**Repository Structure:**
- `/backend/` - FastAPI middleware and RAG pipeline implementation
- `/frontend/` - React + TypeScript chat interface
- `/pipeline/` - Document ingestion and processing modules
- `/deployment/` - Docker Compose orchestration and deployment scripts
- `/docs/` - Technical documentation, architecture diagrams, UI prototypes
- `/tests/` - Unit tests, integration tests, end-to-end tests
- `/config/` - Configuration templates and examples

**Milestone Deliverables:**
- **Proposal (Week 3):** Complete proposal document, initial UI wireframes, project plan
- **Alpha (Week 6):** Document processing MVP, authentication system, low-fidelity prototypes, progress report
- **Beta (Week 9):** RAG query system, high-fidelity prototypes, testing report
- **Final (Week 11):** Integrated MVP system, deployment bundle, final presentation

---

*Document Version: 2.0*  
*Last Updated: February 15, 2026*  
*Status: Complete - Ready for Submission*
