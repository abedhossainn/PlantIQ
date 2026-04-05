# Project Background

## Problem Statement & Motivation
I currently work as an OT Cybersecurity Technician at a client site operated by BHE GT&S, an LNG export facility. While working in this environment, I have noticed a recurring operational problem: real-time troubleshooting is difficult because proprietary equipment manuals are not available online, which limits access to accurate, equipment-specific solutions. Strict security policies also prevent the use of public search engines and AI tools.

As a result, technicians must manually search through hundreds of pages across multiple vendor manuals during time-sensitive troubleshooting. This process is slow and increases the risk of mistakes in a safety-critical industrial environment.

## Proposed Solution
I propose building a fully local, air-gapped Retrieval-Augmented Generation (RAG) system that allows staff to ask technical questions in natural language and receive accurate, cited answers directly from vendor manuals. In any high-stakes situation, the difference between a near-instant AI-driven response and a 30-minute manual search through physical or PDF manuals can be the difference between a routine fix and a significant operational delay. The system will run completely offline to meet security requirements and protect proprietary data.

## Technical Scope and Complexity
This project focuses on challenges that make commercial AI tools unsuitable for OT environments:

- **High-Fidelity Document Ingestion:** Engineering manuals contain complex tables, diagrams, and schematics that standard OCR tools often fail to capture correctly. I plan to design a multi-stage ingestion pipeline using local Vision-Language Models (VLMs) to interpret and validate visual content alongside text.

- **Improved Semantic Retrieval:** Following RAG ingestion best practices, restructuring technical documents into concept-based sections with question-style headers can improve retrieval accuracy for troubleshooting.

- **Resource-Constrained Model Orchestration:** For the prototype, the system must support large language models on local hardware with limited VRAM. This requires a custom software architecture, utilizing subprocess isolation and aggressive memory management to orchestrate high-parameter models on localized hardware without causing system instability or GPU fragmentation.

- **Security and Data Control:** Vendor manuals cannot be sent to cloud services without violating license agreements or exposing sensitive operational data. The system will operate fully offline within an air-gapped network.

## Key Engineering Challenges
The project addresses two major technical challenges appropriate for graduate-level work:

- **Resource Optimization:** Running large AI models on limited local hardware without performance failure.
- **Accurate Knowledge Representation:** Preserving the meaning of technical diagrams and structured data during ingestion and retrieval.

## Long-Term Industry Impact
Many industrial sectors, especially energy and critical infrastructure, operate in isolated or high-security environments and have not been able to benefit from modern AI tools. This project demonstrates a practical approach for deploying AI safely in air-gapped OT environments. Over time, systems like this could reduce downtime, improve safety, shorten training time for new technicians, and enable wider AI adoption across industries that are currently excluded due to security and data restrictions.