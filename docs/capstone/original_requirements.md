# Project: LLM RAG Chatbot with AnythingLLM, vLLM, and RAG Middleware

## Current Project Status
**Last Updated:** January 30, 2026  
**Phase:** Document Processing Pipeline (Stages 1-2 Complete/In-Progress)

### ✅ Completed
- RAG markdown guidelines research and best practices documentation
- Qwen2.5-32B and Qwen2.5-VL-32B model downloads and setup
- Three-stage subprocess-based pipeline architecture
- Stage 1: VLM comparison (validates markdown against PDF) - **WORKING**
- Stage 2: Text reformatter (applies RAG guidelines) - **OPTIMIZED**
- System prompt with 20-point validation checklist and source citation framework

### 🔄 In Progress
- Stage 2: Full document reformatting with Qwen2.5-32B
- Pydantic schema design for output validation

### 📋 Pending
- Step 2.7: vLLM server integration
- Step 2.8: End-to-end testing with vector store

## 1. Project Overview
This project implements a robust, enterprise-grade Retrieval-Augmented Generation (RAG) chatbot system designed for querying technical documentation. It leverages high-performance local LLM inference and a modern web interface.

**Goal:** Enable users to ask natural language questions about technical manuals and receive accurate, context-aware answers cited from the source documents.

**Current Focus:** Build a production-ready RAG document processing pipeline that transforms PDFs → Markdown (via Docling) → RAG-optimized chunks with source citations using locally-hosted models.

## 2. System Architecture & Components

### A. Frontend: AnythingLLM
- **Repository:** [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm)
- **Role:** User interface for chat interactions.
- **Configuration:**
  - Connects to the RAG Middleware via an OpenAI-compatible API.
  - Environment variables: `OPENAI_API_HOST`, `OPENAI_API_KEY`.

### B. Middleware: RAG API Server
- **Framework:** Python (FastAPI) + LangChain or LlamaIndex.
- **Role:** Orchestrates the RAG flow.
  - **Ingestion:** Loads, chunks, and embeds documents.
  - **Retrieval:** Queries the Vector Database for relevant context.
  - **Generation:** Constructs the prompt with context and forwards it to vLLM.
- **API:** Exposes endpoints compatible with OpenAI's `/v1/chat/completions`.

### C. Backend: LLM Inference (vLLM)
- **Engine:** [vLLM](https://vllm.readthedocs.io/)
- **Role:** High-throughput LLM serving.
- **Hardware Optimization:**
  - **GPU:** NVIDIA RTX A4000 (24GB VRAM) - Requires sequential model loading.
  - **CPU:** Intel Xeon (AVX-512 support).
  - **Strategy:** Models loaded separately via subprocess isolation for complete GPU memory cleanup.
- **Models Currently Deployed:**
  - **Qwen2.5-VL-32B-Instruct:** Vision-Language model for PDF validation and image understanding (64 GB).
  - **Qwen2.5-32B-Instruct:** Text model for markdown reformatting and RAG optimization (62 GB).
  - Primary: `Gaia-Petro-LLM` (for production RAG queries). https://huggingface.co/my2000cup/Gaia-Petro-LLM
  - Future: `Granite-Docling` for document conversion. https://huggingface.co/ibm-granite/granite-docling-258M

### D. Data Layer: Vector Database
- **Technology:** ChromaDB, FAISS, or Milvus (Dockerized).
- **Role:** Stores vector embeddings of the technical documentation for semantic search.

## 3. Document Processing Pipeline (Stages 1-2)

This is the currently active implementation for preparing PDFs for RAG ingestion.

### Architecture: Three-Stage Subprocess Pipeline
The pipeline uses subprocess isolation to handle the 24GB GPU VRAM constraint. Each stage runs in a separate Python process, ensuring complete GPU memory cleanup between stages.

**Why subprocess-based?**
- Both Qwen2.5-VL (64GB) and Qwen2.5-32B (62GB) are too large to load simultaneously
- Same-process model swapping causes GPU memory fragmentation
- Subprocess isolation forces complete model unloading and GPU memory release to OS

### Stage 1: VLM Comparison (PDF Validation)
**File:** [rag_vlm_comparison.py](rag_vlm_comparison.py)  
**Model:** Qwen2.5-VL-32B-Instruct  
**Purpose:** Validate markdown output from Docling by comparing with original PDF pages  
**Runtime:** ~70-80 minutes for standard documents  
**Process:**
1. Loads PDF and markdown
2. Compares markdown excerpt with each PDF page using VLM
3. Generates validation report: format issues, missing content, improvement suggestions
4. Saves: `output_rag_optimized_validation.json`
5. Exits completely (GPU memory fully released)

**Output Example:**
```json
{
  "format_issues": ["Images need proper Markdown syntax", "Table formatting incorrect", ...],
  "missing_content": ["No detailed LNG characteristics content", ...],
  "improvement_suggestions": ["Embed images with Markdown", ...]
}
```

### Stage 2: Text Reformatter (RAG Optimization)
**File:** [rag_text_reformatter.py](rag_text_reformatter.py)  
**Model:** Qwen2.5-32B-Instruct  
**Purpose:** Reformat markdown using validation feedback + RAG guidelines  
**System Prompt:** [rag_markdown_reformatter_prompt.md](rag_markdown_reformatter_prompt.md)  
**Runtime:** ~40-60 minutes for standard documents  
**Process:**
1. Loads full markdown and validation report
2. Applies system prompt with 20-point validation checklist
3. Generates RAG-optimized chunks with:
   - Source citations (PDF page numbers)
   - Reformatted headings as questions
   - Normalized table formatting
   - Embedded figure descriptions
4. Outputs structured JSON:
   - `output_rag_optimized.json` (structured chunks, source URLs, confidence scores)
   - `output_rag_optimized.md` (readable markdown format)
5. Exits completely (GPU memory fully released)

### Stage 3: Orchestrator
**File:** [rag_pipeline_main.py](rag_pipeline_main.py)  
**Purpose:** Coordinates Stage 1 → Stage 2 execution  
**Usage:**
```bash
python3 rag_pipeline_main.py <pdf_path> \
  --markdown <markdown_file> \
  --output <output_prefix>
```

**Example:**
```bash
python3 rag_pipeline_main.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
  --markdown output.md \
  --output output_rag_optimized
```

**Output:**
- `output_rag_optimized.json` - Structured chunks with metadata
- `output_rag_optimized.md` - Formatted markdown
- `output_rag_optimized_validation.json` - Validation report
- `rag_pipeline.log` - Execution log

### System Prompt: RAG Markdown Reformatter
**File:** [rag_markdown_reformatter_prompt.md](rag_markdown_reformatter_prompt.md)  
**Key Sections:**
- Section 0: One Concept Per Section (FUNDAMENTAL rule)
- Section 7: Source Citations (tracks original PDF pages)
- 20-point Critical Validation Checklist
- 12 Success Criteria
- JSON output schema with `source_url` field

**Features:**
- Converts headings to questions (improves semantic search matching)
- Normalizes table formatting for consistency
- Embeds figure descriptions with sources
- Adds confidence scores for RAG retrieval validation
- Tracks source page numbers for end-user verification

## 3a. Legacy Workflow (For Reference)

### Phase 1: Document Ingestion (Admin)
1. **Upload:** Admin places documents (PDF, MD, JSON) into a watched directory or uploads via API.
2. **Processing:**
   - **Loader:** `Docling` or `Unstructured` to parse complex layouts.
   - **Chunking:** Recursive character splitting (e.g., 512-1024 tokens with overlap).
   - **Embedding:** Generate vectors using a high-quality embedding model (e.g., `bge-m3` or `openai-text-embedding-3-small` equivalent).
3. **Indexing:** Vectors and metadata are stored in the Vector Database.

### Phase 2: User Interaction (RAG Loop)
1. **Query:** User asks: "How do I disable NetBIOS?"
2. **Retrieval:** Middleware embeds the query and performs a similarity search in the Vector DB (Top-K results).
3. **Prompt Construction:**
   ```text
   System: You are a helpful technical assistant. Use the following context to answer the user's question.
   Context: {retrieved_chunks}
   User: How do I disable NetBIOS?
   ```
4. **Inference:** Prompt is sent to vLLM.
5. **Response:** vLLM generates the answer, which is streamed back to AnythingLLM.

## 4. Implementation Plan

### Current Work: Step 2 - Document Processing Pipeline
**Status:** 90% complete

#### Step 2.1: PDF to Markdown Conversion ✅
- **Status:** COMPLETE (uses Docling + Qwen2.5-VL)
- **Output:** [output.md](output.md) (59 KB, 863 lines)
- **How:** External tool (Docling), provides structured markdown from PDF

#### Step 2.2: Markdown Validation with VLM ✅
- **Status:** COMPLETE
- **Script:** [rag_vlm_comparison.py](rag_vlm_comparison.py)
- **Output:** [output_rag_optimized_validation.json](output_rag_optimized_validation.json)
- **Execution:**
  ```bash
  python3 rag_vlm_comparison.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
    --markdown output.md \
    --output output_rag_optimized_validation
  ```
- **Duration:** ~70-80 minutes
- **Result:** Detailed validation report with format issues, missing content, improvement suggestions

#### Step 2.3: RAG Optimization with Text Model 🔄
- **Status:** IN PROGRESS (optimized for full document)
- **Script:** [rag_text_reformatter.py](rag_text_reformatter.py)
- **Input:** Full markdown (59 KB) + validation report
- **Execution:**
  ```bash
  python3 rag_text_reformatter.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
    --markdown output.md \
    --validation output_rag_optimized_validation.json \
    --output output_rag_optimized
  ```
- **Expected Duration:** ~40-60 minutes
- **Output:** Structured RAG chunks with source citations, confidence scores, reformatted headings

#### Step 2.4: Full Pipeline Orchestration 🟢
- **Status:** READY TO RUN
- **Script:** [rag_pipeline_main.py](rag_pipeline_main.py)
- **Execution:**
  ```bash
  cd /home/abed/Project/llm-rag-chatbot
  python3 rag_pipeline_main.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
    --markdown output.md \
    --output output_rag_optimized
  ```
- **Total Runtime:** ~120-150 minutes (both stages)
- **Logs:** [rag_pipeline.log](rag_pipeline.log)

#### Step 2.5: Output Validation ⏳
- **Pending:** Verify output quality
- **Checklist:**
  - [ ] JSON structure is valid and complete
  - [ ] Source citations are present and accurate
  - [ ] Chunks are self-contained and semantic
  - [ ] Confidence scores are calculated
  - [ ] No missing content from original document

#### Step 2.6: Pydantic Schema Design ⏸
- **Purpose:** Formalize RAG chunk output structure
- **Scope:** Create dataclasses for:
  - `ValidationReport`
  - `ChunkMetadata`
  - `RAGChunk`
  - `RAGDocument`
- **Status:** Not started

#### Step 2.7: vLLM Server Integration ⏸
- **Purpose:** Integrate reformatter with vLLM server for production use
- **Scope:** Create FastAPI endpoint for RAG reformatting
- **Status:** Not started

#### Step 2.8: End-to-End Testing ⏸
- **Purpose:** Full pipeline validation with sample PDFs
- **Scope:** Test suite for document processing pipeline
- **Status:** Not started

### Next Step: Step 3 - RAG Middleware Development
- Create FastAPI app with `/v1/chat/completions` endpoint
- Implement LangChain retrieval chain
- Integrate vector database (ChromaDB/FAISS)
- Connect to vLLM for inference

### Step 1: Infrastructure Setup
- [ ] **Directory Structure:**
  ```
  /home/abed/Project/llm-rag-chatbot/
  ├── anythingllm/      # Frontend submodule
  ├── rag-middleware/   # Python FastAPI app
  ├── vllm-server/      # Docker config for vLLM
  ├── data/             # Raw documents and Vector DB persistence
  ├── rag_pipeline_main.py        # Stage orchestrator
  ├── rag_vlm_comparison.py       # Stage 1: VLM validation
  ├── rag_text_reformatter.py     # Stage 2: RAG optimization
  ├── rag_markdown_reformatter_prompt.md  # System prompt
  └── docker-compose.yml
  ```
- [x] Document processing pipeline structure established

### Step 2: vLLM Deployment
- [ ] Configure vLLM to serve the target HuggingFace model.
- [ ] Ensure GPU passthrough (`--gpus all`) is working.
- [ ] Test OpenAI compatibility: `curl http://localhost:8000/v1/models`.

### Step 3: RAG Middleware Development
- [ ] Create FastAPI app.
- [ ] Implement `/v1/chat/completions` endpoint.
- [ ] Integrate `LangChain` for the retrieval chain.
- [ ] Implement document ingestion script (`ingest.py`).

### Step 4: Frontend Integration
- [ ] Configure AnythingLLM to point to the Middleware URL.
- [ ] Customize UI branding (optional).

## 5. Technical Requirements & Constraints

### Hardware Configuration
- **GPU:** NVIDIA RTX A4000 (24GB VRAM)
- **CPU:** Intel Xeon (AVX-512 support)
- **Memory Strategy:**
  - **Single Model Limit:** ~11-13 GB per model after loading overhead
  - **Subprocess Isolation:** Forces complete GPU memory release between stages
  - **Max Concurrent Models:** 1 (sequential processing only)

### GPU Memory Management
1. **Per-Stage Limits:**
   - Stage 1 (Qwen2.5-VL): 11 GB GPU + 100 GB CPU offload
   - Stage 2 (Qwen2.5-32B): 11 GB GPU + 100 GB CPU offload
2. **Subprocess Behavior:**
   - Each subprocess fully unloads its model on exit
   - Python garbage collection + `torch.cuda.empty_cache()` called before new stage
   - GPU memory verified between stages
3. **Offloading Strategy:**
   - `device_map="auto"` with aggressive CPU offloading
   - `max_memory={0: "11GiB", "cpu": "100GiB"}`
   - Float16 precision to reduce memory footprint

### Model Specifications
| Model | Size | VRAM | CPU | Type | Status |
|-------|------|------|-----|------|--------|
| Qwen2.5-VL-32B | 64 GB | 11 GB | 100 GB | Vision-Language | ✅ Ready |
| Qwen2.5-32B | 62 GB | 11 GB | 100 GB | Text | ✅ Ready |
| Gaia-Petro-LLM | ~13 GB | ~6 GB | ~50 GB | Domain-Specific | ⏸ Pending |

### Model Locations
```
~/.cache/huggingface/hub/
├── models--Qwen--Qwen2.5-VL-32B-Instruct/
├── models--Qwen--Qwen2.5-32B-Instruct/
└── models--my2000cup--Gaia-Petro-LLM/
```

### Security & Scalability
- **Security:**
  - Middleware must validate API keys if exposed.
  - Run containers with non-root users where possible.
  - Sanitize user inputs for prompt injection prevention.
- **Scalability:** The architecture allows swapping the LLM or Vector DB without rewriting the frontend.

## 6. How to Run the Pipeline

### Full Pipeline (Recommended)
Runs both Stage 1 and Stage 2 with automatic GPU memory management:

```bash
cd /home/abed/Project/llm-rag-chatbot

# Full pipeline: Validation + Reformatting
python3 rag_pipeline_main.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
  --markdown output.md \
  --output output_rag_optimized

# Expected output:
# ✅ output_rag_optimized.json      (structured chunks, 200+ lines)
# ✅ output_rag_optimized.md         (formatted markdown)
# ✅ output_rag_optimized_validation.json  (validation report)
```

**Total Runtime:** ~120-150 minutes  
**Monitor Progress:**
```bash
tail -f rag_pipeline.log
```

### Stage 1 Only (VLM Comparison)
If you only want to validate the markdown:

```bash
python3 rag_vlm_comparison.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
  --markdown output.md \
  --output output_rag_optimized_validation

# Output: output_rag_optimized_validation.json (validation report)
```

**Runtime:** ~70-80 minutes

### Stage 2 Only (Text Reformatter)
If you already have a validation report:

```bash
python3 rag_text_reformatter.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" \
  --markdown output.md \
  --validation output_rag_optimized_validation.json \
  --output output_rag_optimized

# Output:
# ✅ output_rag_optimized.json
# ✅ output_rag_optimized.md
```

**Runtime:** ~40-60 minutes

### Verify GPU Memory Between Stages
```bash
# Before running pipeline
nvidia-smi

# After each stage completes
nvidia-smi

# Expected: GPU memory drops to <500MB between stages
```

### Check Output Quality
```bash
# View structured chunks
python3 -m json.tool output_rag_optimized.json | head -100

# Check for source citations
grep -c '"source_url"' output_rag_optimized.json

# Expected: Each chunk should have source_url field

# View formatted markdown
head -100 output_rag_optimized.md
```

## 7. Project Artifacts & Files

### Core Pipeline Scripts
- [rag_pipeline_main.py](rag_pipeline_main.py) - Orchestrator/Main entry point
- [rag_vlm_comparison.py](rag_vlm_comparison.py) - Stage 1: VLM validation
- [rag_text_reformatter.py](rag_text_reformatter.py) - Stage 2: RAG optimization

### System Prompts & Guidelines
- [rag_markdown_reformatter_prompt.md](rag_markdown_reformatter_prompt.md) - System prompt for Stage 2
- [rag_markdown_guidelines.md](rag_markdown_guidelines.md) - RAG best practices reference
- [MODEL_SETUP.md](MODEL_SETUP.md) - Model configuration documentation

### Input/Output Files
- [output.md](output.md) - Markdown from Docling (59 KB input)
- [output_rag_optimized.json](output_rag_optimized.json) - Structured RAG chunks (output)
- [output_rag_optimized.md](output_rag_optimized.md) - Formatted markdown (output)
- [output_rag_optimized_validation.json](output_rag_optimized_validation.json) - Validation report (intermediate)

### Logs & Documentation
- [rag_pipeline.log](rag_pipeline.log) - Pipeline execution log
- [PIPELINE_CORRECTED.md](PIPELINE_CORRECTED.md) - Architecture documentation

## 6. References
## 6. References
- **AnythingLLM:** https://github.com/Mintplex-Labs/anything-llm
- **vLLM:** https://vllm.readthedocs.io/en/latest/
- **LangChain:** https://python.langchain.com/docs/
- **Docling:** https://github.com/DS4SD/docling (for PDF parsing)
- **Qwen Models:** https://huggingface.co/Qwen
- **HuggingFace:** https://huggingface.co/ (Model source)

## 7. Troubleshooting

### GPU Out of Memory (OOM)
**Symptom:** `CUDA out of memory. Tried to allocate X GiB`

**Solutions:**
1. Verify subprocess completely exited (check `nvidia-smi`)
2. Manually clear cache:
   ```bash
   python3 -c "import torch; torch.cuda.empty_cache(); torch.cuda.synchronize()"
   ```
3. Check system memory:
   ```bash
   free -h
   ```

### Stage Timeout
**Symptom:** Process hangs for >2 hours

**Solutions:**
1. Check GPU utilization: `nvidia-smi -l 1`
2. If stuck: Press Ctrl+C, clear cache, retry
3. Reduce document size for testing

### JSON Parsing Error in Stage 2
**Symptom:** `JSON parsing failed` or invalid JSON in output

**Causes:**
- Model response not properly formatted
- Validation report incompatible

**Solutions:**
1. Check model output in logs
2. Verify validation report is valid JSON
3. Retry with verbose logging

---
*This file serves as the master plan and execution guide for the RAG pipeline project. All code generation should align with the architectural decisions outlined here.*