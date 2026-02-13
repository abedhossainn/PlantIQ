#!/usr/bin/env python3
"""
Enhanced HITL Pipeline - Verification Script
Checks that all modules are properly installed and functional
"""

import sys
import importlib
from pathlib import Path

def check_module(module_name, description):
    """Check if a module can be imported"""
    try:
        importlib.import_module(module_name)
        print(f"✅ {description}")
        return True
    except Exception as e:
        print(f"❌ {description}: {e}")
        return False

def check_file(file_path, description):
    """Check if a file exists"""
    if Path(file_path).exists():
        print(f"✅ {description}")
        return True
    else:
        print(f"❌ {description}: File not found")
        return False

def main():
    print("=" * 80)
    print("🔍 ENHANCED HITL PIPELINE - VERIFICATION")
    print("=" * 80)
    
    all_checks = []
    
    # Check dependencies
    print("\n📦 Checking Dependencies:")
    all_checks.append(check_module("pdfplumber", "pdfplumber (PDF extraction)"))
    all_checks.append(check_module("PIL", "Pillow (Image processing)"))
    all_checks.append(check_module("json", "json (built-in)"))
    all_checks.append(check_module("dataclasses", "dataclasses (built-in)"))
    
    # Check HITL modules
    print("\n🔧 Checking HITL Modules:")
    modules = [
        ("rag_validation_enhanced", "Enhanced Validation Module"),
        ("rag_section_review", "Section Review Module"),
        ("rag_qa_gates", "QA Gates Module"),
        ("rag_lineage", "Lineage & Audit Trail Module"),
        ("rag_table_figure_handler", "Table/Figure Handler Module"),
        ("rag_hitl_pipeline", "HITL Pipeline Orchestrator")
    ]
    
    for module_name, description in modules:
        all_checks.append(check_module(module_name, description))
    
    # Check documentation
    print("\n📖 Checking Documentation:")
    docs = [
        ("IMPLEMENTATION_SUMMARY.md", "Implementation Summary"),
        ("ENHANCED_HITL_GUIDE.md", "Enhanced HITL Guide"),
        ("REVIEWER_QUICK_REFERENCE.md", "Reviewer Quick Reference"),
        ("HITL_README.md", "HITL README"),
        ("RAG_Chatbot_Architecture.md", "Architecture Documentation"),
        ("PROJECT_STATUS.md", "Project Status")
    ]
    
    for doc_file, description in docs:
        all_checks.append(check_file(doc_file, description))
    
    # Check Python modules
    print("\n🐍 Checking Python Module Files:")
    modules_files = [
        ("rag_validation_enhanced.py", "Validation Module"),
        ("rag_section_review.py", "Section Review Module"),
        ("rag_qa_gates.py", "QA Gates Module"),
        ("rag_lineage.py", "Lineage Module"),
        ("rag_table_figure_handler.py", "Table/Figure Handler"),
        ("rag_hitl_pipeline.py", "Pipeline Orchestrator")
    ]
    
    for module_file, description in modules_files:
        all_checks.append(check_file(module_file, description))
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 80)
    
    passed = sum(all_checks)
    total = len(all_checks)
    
    print(f"\nPassed: {passed}/{total} checks")
    
    if passed == total:
        print("\n✅ All checks passed! Enhanced HITL Pipeline is ready to use.")
        print("\n📋 Next Steps:")
        print("   1. Read HITL_README.md for quick start guide")
        print("   2. Run: python rag_hitl_pipeline.py run --pdf input.pdf --markdown output.md --reviewer 'Your Name'")
        print("   3. Review sections in hitl_workspace/[document]_review/")
        return 0
    else:
        print(f"\n❌ {total - passed} checks failed. Please resolve issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
