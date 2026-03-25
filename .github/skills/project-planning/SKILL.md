# Project Planning Skill

This skill provides comprehensive guidance for software project planning, feature breakdown, epic management, and implementation planning for the RAG chatbot.

## Operating Guardrails

- **Root-Cause First**: Build plans around the real problem to solve, not around superficial symptoms or assumed fixes.
- **Clean Code Alignment**: Ensure planned work encourages maintainable, modular, low-duplication implementation.
- **Development-First Execution**: Default plans to local, development, and staging execution; treat production rollout as requiring explicit user confirmation.
- **Core Functionality First**: Prioritize the critical path and must-have requirements before enhancements or polish.
- **Plan Discipline**: Create a clear plan and keep work aligned to it; only revise the plan when evidence justifies a change.
- **Confirm Before Expanding Scope**: Verify with the user before adding new features, workstreams, dependencies, or deliverables beyond the request.

## Overview

The Project Planning skill encompasses:
- **Feature Breakdown**: Decomposing large features into manageable tasks
- **Epic Management**: Organizing work at different levels of scope
- **Implementation Planning**: Creating detailed execution roadmaps
- **Specification Driven Workflows**: Using specifications to guide implementation
- **Task Research**: Investigating unknowns before implementation

## Planning Hierarchy

### Epic
- Large business capability (3-6 months)
- Example: "RAG Pipeline Implementation"
- Broken down into features

### Feature  
- Specific functionality (1-3 weeks)
- Example: "Document Upload with Vector Processing"
- Broken down into tasks

### Task
- Implementation unit (1-3 days)
- Example: "Implement FastAPI /upload endpoint"
- Can be assigned to single developer

### Story
- User-centric description
- Each task has acceptance criteria
- Verifiable completion

## Planning Process

### 1. Feature Breakdown
- Identify all requirements
- Break into independent work streams
- Sequence dependencies
- Estimate complexity

### 2. Specification
- Write detailed requirements
- Define acceptance criteria
- Create architectural diagrams
- Document data models

### 3. Implementation Planning
- Break spec into tasks
- Identify dependencies
- Create GitHub issues
- Assign to team members

### 4. Execution
- Follow TDD workflow (Red-Green-Refactor)
- Update PROJECT_STATUS.md as you work
- Run tests frequently
- Refactor for quality

### 5. Validation
- Code review by peers
- Test coverage validation
- Acceptance criteria verification
- Performance testing

## Technical Spike Process

### Problem Statement
- What don't we know?
- What's the risk?
- What's the question?

### Research Phase
- Explore technology options
- Create proof-of-concept
- Document findings
- Propose solution

### Output
- Decision documented in PROJECT_STATUS.md
- Proof-of-concept code (may be discarded)
- Clear rationale for choice

## How to Use This Skill

1. **For Feature Planning**: Use to break down large features
2. **For Task Creation**: Reference when creating GitHub issues
3. **For Estimation**: Apply when estimating complexity and effort
4. **For Dependencies**: Use for sequencing work streams
5. **For Unknowns**: Run technical spike when facing uncertainty
6. **For Tracking**: Update PROJECT_STATUS.md throughout

## Related Skills
- [Backend Development](../backend-development/SKILL.md) - For implementation
- [Frontend Development](../frontend-development/SKILL.md) - For UI implementation
- [Testing Automation](../testing-automation/SKILL.md) - For test planning
- [Code Review Agent](../../agents/review.agent.md) - For quality gates

## Planning Templates

### Feature Breakdown Template
```markdown
## Feature: [Name]

### Summary
Brief description of what this feature does

### User Stories
- As a [role], I want [action] so that [benefit]
- ...

### Technical Tasks
- [ ] Task 1: [Specific, implementable work]
- [ ] Task 2: [Specific, implementable work]
- ...

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- ...

### Dependencies
- Feature/Task X must be completed first
- ...

### Estimate
- Backend: X story points
- Frontend: Y story points  
- Total: X+Y story points
```

### Implementation Plan Template
```markdown
## Implementation: [Feature Name]

### Overview
Goals: What will be delivered

### Phases
1. Phase 1: [Scope] - Week 1-2
2. Phase 2: [Scope] - Week 3-4

### Detailed Tasks
- [Backend] Task X - Owner: [Name] - 3 days
- [Frontend] Task Y - Owner: [Name] - 2 days
- ...

### Testing Strategy
- Unit tests for [component]
- Integration tests for [workflow]
- E2E tests for [user journey]

### Risks & Mitigation
- Risk: [Description]
  Mitigation: [Plan]
- ...
```

## References
- Agile Planning: https://www.agilealliance.org/
- User Stories: https://en.wikipedia.org/wiki/User_story
- Estimation: https://www.mountaingoatsoftware.com/agile/planning-poker
- Epic Management: https://www.atlassian.com/agile/project-management/epics
