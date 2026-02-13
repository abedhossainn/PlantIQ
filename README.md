# LLM RAG Chatbot - Enhanced HITL Pipeline

**Production-ready RAG document optimization pipeline with Human-In-The-Loop validation**

## 🎯 Project Overview

This project implements a comprehensive document optimization system for RAG (Retrieval-Augmented Generation) applications. It processes PDF documents through a multi-stage pipeline with manual validation gates, VLM-powered quality assurance, and systematic audit trails.

### Key Features

- ✅ **VLM-Powered Validation** - Qwen2.5-VL-32B for visual comparison and image description
- ✅ **Human Review Workflow** - Section-based review with structured checklists
- ✅ **QA Gates & Metrics** - Objective acceptance criteria and quality metrics
- ✅ **Complete Audit Trail** - Lineage tracking from PDF pages to RAG chunks
- ✅ **Table/Figure Handling** - Advanced extraction and serialization
- ✅ **Production-Ready Infrastructure** - VLMOptions, progress tracking, robust parsing

## 📁 Project Structure

```
.
├── Core Pipeline Modules
│   ├── rag_hitl_pipeline.py           # Main orchestrator (10-stage workflow)
│   ├── rag_validation_enhanced.py     # Per-page validation with evidence
│   ├── rag_section_review.py          # Section-based review workflow
│   ├── rag_qa_gates.py                # QA gates and metrics
│   ├── rag_lineage.py                 # Audit trail and versioning
│   └── rag_table_figure_handler.py    # Table/figure extraction
│
├── VLM Modules
│   ├── rag_vlm_comparison.py          # VLM validation (Stage 2a)
│   ├── rag_vlm_image_describer.py     # Image description generation
│   ├── rag_text_reformatter.py        # RAG optimization (Stage 10)
│   └── docling_convert_with_qwen.py   # PDF to Markdown conversion
│
├── VLM Infrastructure
│   ├── vlm_options.py                 # Centralized VLM configuration
│   ├── vlm_response_parser.py         # Robust JSON parsing with Pydantic
│   ├── progress_tracker.py            # Multi-level progress tracking
│   └── vlm_config_project.yaml        # Production VLM configuration
│
├── Testing & Verification
│   ├── test_vlm_integration.py        # Integration test suite (5/5 passing)
│   └── verify_hitl_setup.py           # Setup verification
│
├── Documentation
│   ├── PROJECT_STATUS.md              # Current project status
│   ├── RAG_Chatbot_Architecture.md    # System architecture
│   └── instructions.md                # Original requirements
│
├── Working Directories
│   ├── hitl_workspace/                # Review workspace
│   ├── validation_evidence/           # Validation snapshots
│   └── InjestDocs/                    # Source documents
│
└── Configuration
    ├── docker-compose.yml             # Docker setup
    └── docling.env                    # Environment variables
```

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Python 3.10+
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Verify setup
python3 verify_hitl_setup.py
```

### 2. Run Pipeline

```bash
# Full HITL pipeline
python3 rag_hitl_pipeline.py run \
  --pdf input.pdf \
  --markdown output.md \
  --reviewer "Your Name"

# Check review status
python3 rag_hitl_pipeline.py status --doc-name "input"

# Post-approval reformatting
python3 rag_hitl_pipeline.py reformat --doc-name "input"
```

### 3. Review Workflow

1. Pipeline generates sections in `hitl_workspace/[document]_review/`
2. Review each section using provided checklists
3. Address QA issues flagged by validation
4. Approve document when ready
5. Run reformatting for vector DB ingestion

## 📊 Pipeline Stages

| Stage | Module | Duration | Description |
|-------|--------|----------|-------------|
| 1 | Lineage | ~1s | Create document manifest |
| 2a | VLM Validation | ~70-80min | Visual comparison (optional) |
| 2b | Image Descriptions | ~47min/page | VLM image analysis (if needed) |
| 3 | Enhanced Validation | ~5s | Per-page validation with evidence |
| 4 | Section Review | ~2s | Extract reviewable sections |
| 5 | Versioning | ~1s | Create initial version |
| 6 | Table/Figure Handling | ~3s | Extract and serialize tables |
| 7 | QA Gates | ~1s | Compute metrics and decision |
| 8 | Review Workspace | ~1s | Generate review checklist |
| 9 | Audit Report | ~1s | Create audit trail |
| 10 | Reformatting | ~40-60min | RAG optimization (post-approval) |

## 🎛️ VLM Configuration

Edit `vlm_config_project.yaml` to customize VLM behavior:

```yaml
# Choose preset: balanced, fast, quality, low_memory
preset: balanced

# Or customize individual settings
temperature: 0.1
max_new_tokens: 2048
batch_size: 1
image_dpi: 100
```

## 🧪 Testing

```bash
# Integration tests (5 test suites)
python3 test_vlm_integration.py

# Verify all modules
python3 verify_hitl_setup.py
```

## 📈 Current Status

- **Phase:** Enhanced HITL Pipeline + VLM Infrastructure - COMPLETE
- **Test Results:** 5/5 integration tests passing
- **Production Ready:** Yes
- **Last Updated:** January 31, 2026

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed status.

## 🏗️ Architecture

See [RAG_Chatbot_Architecture.md](RAG_Chatbot_Architecture.md) for complete system architecture, component diagrams, and design decisions.

## 📝 License

[Add your license here]

## 🤝 Contributing

[Add contribution guidelines here]
