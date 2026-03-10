# Testing Automation Skill

This skill provides comprehensive guidance for test automation, TDD workflows, and quality assurance for the RAG chatbot project.

## Overview

The Testing Automation skill encompasses:
- **Test-Driven Development (TDD)**: Red-Green-Refactor cycle
- **Unit Testing**: pytest (backend), Vitest (frontend)
- **Integration Testing**: API endpoints, RAG pipeline components
- **End-to-End Testing**: Playwright browser automation
- **Test Coverage**: Logical coverage analysis and gap identification
- **Continuous Testing**: Automated test execution in CI/CD

## Test Types by Framework

### Backend (Python/pytest)
- Unit tests: `test_document_processor.py`
- Integration tests: test RAG pipeline stages
- Mock external services (LLMs, vector stores)
- Test fixtures for consistent data

### Frontend (TypeScript/React)
- Unit tests: Component logic isolation
- Integration tests: Component interaction
- E2E tests: Critical user workflows

### Test Organization
```
tests/
├── unit/           # Fast, isolated tests
├── integration/    # Component boundary tests  
├── e2e/           # User journey tests
├── fixtures/      # Test data and factories
└── conftest.py    # Shared pytest configuration
```

## TDD Workflow

### Red Phase
- Write failing test that describes the desired behavior
- Test fails because feature doesn't exist
- Minimal test setup, clear assertions

### Green Phase
- Write minimal code to make test pass
- Don't optimize yet, just make it work
- All tests should pass

### Refactor Phase
- Clean up code without changing behavior
- Improve naming, reduce duplication
- All tests still pass

## Testing Best Practices

### Test Naming
- Clear intent: `test_upload_rejects_oversized_files()`
- One behavior per test
- Arrange-Act-Assert pattern

### Test Data
- Use fixtures for common setups
- Factory functions for test object creation
- Seed data for consistent results

### Mocking Strategy
- Mock external APIs (LLMs, vector stores)
- Mock file I/O operations
- Keep mocks simple and predictable

### Coverage Goals
- Backend: 80%+ logical coverage
- Frontend: 70%+ component coverage
- Focus on behavior, not line count

## How to Use This Skill

1. **For Unit Tests**: Write before implementation (TDD Red phase)
2. **For Integration**: Test component interactions and API contracts
3. **For E2E Tests**: Cover critical user workflows with Playwright
4. **For Regression**: Add tests when bugs are found
5. **For Coverage**: Identify gaps and add tests for untested paths

## Related Skills
- [Backend Development](#) - For API testing
- [Frontend Development](#) - For component testing
- [DevOps Infrastructure](#) - For CI/CD test automation

## References
- pytest: https://pytest.org
- Vitest: https://vitest.dev
- Playwright: https://playwright.dev
- React Testing Library: https://testing-library.com/react
- Test Driven Development: https://en.wikipedia.org/wiki/Test-driven_development
