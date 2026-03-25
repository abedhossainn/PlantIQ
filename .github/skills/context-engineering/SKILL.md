# Context Engineering Skill

This skill provides guidance for maximizing GitHub Copilot effectiveness through better context management, code organization, and refactoring strategies.

## Operating Guardrails

- **Root-Cause First**: Use refactoring and context analysis to address the underlying cause of complexity, duplication, or fragility.
- **Clean Code Focus**: Favor simple, modular, readable structures with explicit boundaries and minimal coupling.
- **Development-First Execution**: Apply structural changes in local, development, or staging workflows before any production rollout.
- **Core Functionality First**: Refactor around the critical path first; avoid broad cleanup that distracts from required behavior.
- **Plan Discipline**: Map dependencies, define the plan, and change it only when evidence requires it.
- **Confirm Before Expanding Scope**: Verify with the user before turning a focused refactor into a broader redesign, file split, or architectural expansion.

## Overview

Context Engineering encompasses:
- **Code Organization**: Structuring code for clarity and context
- **Refactoring**: Planning and executing multi-file changes
- **Dependency Management**: Understanding and visualizing code dependencies
- **Testing Strategy**: Building testable code with clear boundaries

## Core Principles

### Single Responsibility
- Each file: one cohesive concept
- Each function: one clear purpose
- Each class: one reason to change

### Clear Boundaries
- Explicit interfaces between modules
- Minimal cross-cutting concerns
- Dependency direction: inward toward core

### Modularity
- Organize by feature, not by type
- Group related functionality
- Isolate concerns into separate modules

## Refactoring Workflows

### Extract Function
- Identify repetition or complexity
- Pull logic into named, testable function
- Update call sites
- Verify tests still pass

### Extract Module
- Move related functionality to new file
- Update imports and exports
- Maintain clear module interface
- Update documentation

### Consolidate Duplicate Code
- Identify duplicated patterns
- Extract common abstraction
- Remove duplication
- Unify test coverage

## Context Mapping

### Dependency Analysis
- What imports this module?
- What does this module import?
- Is there circular dependency?
- Can we break the dependency?

### Scope of Changes
- Files affected by change
- Functions that need updates
- Tests that require modification
- Documentation updates needed

## How to Use This Skill

1. **Before Large Refactoring**: Map context and dependencies
2. **For Multi-file Changes**: Plan refactoring with clear boundaries
3. **For Code Review**: Verify module organization and dependencies
4. **For Performance**: Identify optimization opportunities
5. **For Maintenance**: Break down complex modules into simpler parts

## Related Skills
- [Backend Development](../backend-development/SKILL.md) - For Python module organization
- [Frontend Development](../frontend-development/SKILL.md) - For React component structure
- [Testing Automation](../testing-automation/SKILL.md) - For testable code design
- [Code Review Agent](../../agents/review.agent.md) - For evaluating code structure

## Best Practices

### Project Structure
```
project/
├── src/
│   ├── core/           # Business logic
│   ├── services/       # Business logic
│   ├── models/         # Data structures
│   ├── utils/          # Utilities
│   └── api/            # API handlers
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
```

### Module Interface
```python
# Clear, focused interface
# __init__.py exports only what's needed
from .processor import DocumentProcessor
from .models import Document, ProcessingResult

__all__ = ["DocumentProcessor", "Document", "ProcessingResult"]
```

### Test Organization
```
doc_processor/
├── __init__.py
├── processor.py        # Implementation
├── models.py          # Data structures
└── tests/
    ├── test_processor.py           # Unit tests
    └── test_integration.py         # Integration tests
```

## References
- Code Smells (Refactoring Guide): https://refactoring.guru
- Clean Architecture: https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
- SOLID Principles: https://en.wikipedia.org/wiki/SOLID
- Export Strategy: https://www.typescriptlang.org/docs/handbook/modules.html
