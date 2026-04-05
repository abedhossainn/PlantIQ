#!/usr/bin/env python3
"""
Import Structure Validator
Validates that all Python files have correct import paths after restructure
Uses AST parsing to check imports without executing code
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple, Set

def extract_imports(file_path: Path) -> Tuple[List[str], List[str]]:
    """
    Extract all import statements from a Python file
    Returns (absolute_imports, relative_imports)
    """
    try:
        with open(file_path, 'r') as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError as e:
        return [f"SYNTAX_ERROR: {e}"], []
    
    absolute_imports = []
    relative_imports = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                absolute_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            if level > 0:  # Relative import
                relative_imports.append(f"{'.' * level}{module}")
            else:  # Absolute import
                absolute_imports.append(module)
    
    return absolute_imports, relative_imports

def validate_module(file_path: Path, repo_root: Path) -> Tuple[bool, List[str]]:
    """
    Validate that a module's imports are correct
    Returns (is_valid, issues)
    """
    issues = []
    
    abs_imports, rel_imports = extract_imports(file_path)
    
    if any(item.startswith("SYNTAX_ERROR") for item in abs_imports):
        return False, abs_imports
    
    # Check for old-style imports that should be updated
    old_prefixes = ["rag_", "vlm_", "progress_", "table_figure_", "docling_convert"]
    
    for imp in abs_imports:
        for prefix in old_prefixes:
            if imp.startswith(prefix):
                issues.append(f"Found old-style import: {imp} (should use relative import)")
    
    # For modules in src/, they should use relative imports for internal dependencies
    if "src/" in str(file_path):
        # Check that they're using relative imports
        module_dir = file_path.parent.name  # e.g., "validation", "utils", "cli"
        
        # Expected internal imports based on module location
        if module_dir == "validation":
            # Should import from ..utils
            if any("vlm_" in imp or "progress_" in imp for imp in abs_imports):
                issues.append("validation module should use relative imports from ..utils")
        
        elif module_dir == "cli":
            # Should import from ../validation ../review ../qa ../lineage ../utils
            if any(prefix in imp for prefix in ["rag_", "vlm_", "progress_", "table_"] for imp in abs_imports):
                issues.append("CLI module should use relative imports from ../validation ../review ../qa ../lineage ../utils")
    
    return len(issues) == 0, issues

def main():
    print("🔍 Validating import structure after restructure...\n")
    
    repo_root = Path(__file__).parent.parent.parent
    pipeline_src = repo_root / "pipeline" / "src"
    
    if not pipeline_src.exists():
        print(f"❌ Pipeline src directory not found: {pipeline_src}")
        return False
    
    # Find all Python files
    python_files = list(pipeline_src.rglob("*.py"))
    python_files = [f for f in python_files if "__pycache__" not in str(f) and f.name != "__init__.py"]
    
    results = []
    for py_file in sorted(python_files):
        rel_path = py_file.relative_to(repo_root)
        is_valid, issues = validate_module(py_file, repo_root)
        results.append((rel_path, is_valid, issues))
    
    # Print results
    print("="*70)
    print("IMPORT STRUCTURE VALIDATION")
    print("="*70 + "\n")
    
    passed = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    
    if passed:
        print(f"✅ VALID STRUCTURE ({len(passed)}):\n")
        for path, _, _ in passed:
            print(f"  ✅ {path}")
    
    if failed:
        print(f"\n❌ ISSUES FOUND ({len(failed)}):\n")
        for path, _, issues in failed:
            print(f"  ❌ {path}")
            for issue in issues:
                print(f"     - {issue}")
    
    # Print import summary for each module
    print("\n" + "="*70)
    print("IMPORT SUMMARY")
    print("="*70 + "\n")
    
    for py_file in sorted(python_files):
        abs_imports, rel_imports = extract_imports(py_file)
        
        # Filter to show only internal imports
        internal_abs = [imp for imp in abs_imports if any(p in imp for p in ["rag_", "vlm_", "progress_", "table_"])]
        
        if internal_abs or rel_imports:
            rel_path = py_file.relative_to(repo_root)
            print(f"\n{rel_path}:")
            if internal_abs:
                print(f"  Old-style imports: {', '.join(internal_abs)}")
            if rel_imports:
                print(f"  Relative imports: {', '.join(rel_imports)}")
    
    print("\n" + "="*70)
    print(f"Summary: {len(passed)} valid, {len(failed)} with issues")
    print("="*70)
    
    return len(failed) == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
