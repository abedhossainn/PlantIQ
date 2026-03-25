# Agent Orchestration Skill

This skill provides comprehensive guidance for coordinating multiple specialized agents to execute complex development tasks in a disciplined, plan-driven way.

## Operating Guardrails

- **Root-Cause First**: Coordinate work so agents investigate and solve the underlying problem before applying fixes.
- **Clean Code Alignment**: Require clean code and clean design principles across all handoffs and work streams.
- **Development-First Execution**: Keep implementation and validation in local, development, or staging environments unless the user explicitly confirms a move to production.
- **Core Functionality First**: Sequence work around the critical path and must-have behavior before enhancements or polish.
- **Plan Discipline**: Create a plan, keep agents aligned to it, and revise it only when evidence shows the plan is incomplete or wrong.
- **Confirm Before Expanding Scope**: Verify with the user before assigning net-new features, dependencies, integrations, files, or workflows outside the original request.

## Overview

The Agent Orchestration skill encompasses:
- **Multi-Agent Orchestration**: Coordinating specialized agents
- **Workflow Design**: Defining task dependencies and sequences
- **DAG-Based Planning**: Directed acyclic graphs for parallel execution
- **Agent Communication**: Passing context between agents
- **State Management**: Tracking project progress across teams
- **Quality Gates**: Validation checkpoints

## Project Agent Team

### Your Specialized Agents

1. **Project Lead**
   - Role: Orchestrator and planner
   - Task: High-level analysis, workflow management
   - Handoff: To specialists based on decomposed plan

2. **Architecture Planning**
   - Role: System designer
   - Task: Create architectural diagrams, technology decisions
   - Handoff: To backend/frontend/devops with design specs

3. **Backend Development**
   - Role: API and service implementation
   - Task: Implement FastAPI, LangChain, RAG pipeline
   - Handoff: To code review with implementation

4. **Frontend Development**
   - Role: UI implementation
   - Task: Build React chatbot interface
   - Handoff: To code review with components

5. **DevOps/Infrastructure**
   - Role: Deployment and infrastructure
   - Task: Docker, CI/CD, deployment pipelines
   - Handoff: To testing with infrastructure

6. **Code Review**
   - Role: Quality assurance
   - Task: Code quality, security, performance review
   - Handoff: To testing with issues or to backend/frontend for fixes

7. **Testing & QA**
   - Role: Test automation
   - Task: Unit, integration, E2E test creation
   - Handoff: To devops or back to development for fixes

8. **Documentation**
   - Role: Knowledge capture
   - Task: README, API docs, architecture documentation
   - Handoff: Final documentation

## Workflow Patterns

### Sequential Workflow
```
Architecture → Backend → Frontend → Code Review → Testing → DevOps → Documentation
```

### Parallel Workflow (Reduced Latency)
```
Architecture
├→ Backend → Code Review →↓
├→ Frontend → Code Review → Testing
├→ DevOps → Testing →↓
└→ Documentation →→→→→→→→→→
```

### Parallel with Synchronization
```
Architecture
├→ Backend ─┐
├→ Frontend ├→ Integration Testing → DevOps → Deployment
├→ DevOps ──┘
└→ Documentation
```

## Communication Protocol

### Input Context
Each agent receives:
- Project status from PROJECT_STATUS.md
- Architectural guidelines
- Assigned tasks with clear scope
- Success criteria

### Output Context
Each agent delivers:
- Implementation/analysis results
- Updated PROJECT_STATUS.md entries
- Decisions logged in Decisions Log
- Handoff information to next agent

### State Management
**Single Source of Truth: PROJECT_STATUS.md**
- All agents log progress here
- No separate communication channels
- Historical record of decisions

## Task Dependencies

### Critical Path Analysis
- Which tasks block other tasks?
- What's the minimum timeline?
- Where can we parallelize?

### Dependency Types
- **Hard Dependency**: Task X must complete before Y
- **Soft Dependency**: Y prefers X done first but can proceed
- **No Dependency**: Can be done in parallel

## Quality Gates

### Before Handoff
- All requirements implemented
- Tests pass (80%+ coverage)
- Code reviewed and approved
- Documentation updated

### Between Phases  
- Integration testing passes
- Performance benchmarks met
- Security scanning passes
- Accessibility checks pass

## How to Use This Skill

1. **Planning Large Features**: Use workflow patterns to sequence work
2. **Team Coordination**: Reference for agent assignment and handoffs
3. **Progress Tracking**: Update PROJECT_STATUS.md continuously
4. **Dependency Resolution**: Identify blocking issues early
5. **Resource Allocation**: Plan parallel work to reduce timeline
6. **Quality Assurance**: Apply quality gates before handoffs

## Related Skills
- [Project Planning](../project-planning/SKILL.md) - For decomposition and sequencing
- [Code Review Agent](../../agents/review.agent.md) - For quality gates
- [Testing Automation](../testing-automation/SKILL.md) - For validation
- [Backend Development](../backend-development/SKILL.md) - For backend implementation
- [Frontend Development](../frontend-development/SKILL.md) - For frontend implementation

## Orchestration Checklist

### Before Starting
- [ ] Clear project goals defined
- [ ] Architecture approved
- [ ] Team roles assigned
- [ ] Success criteria documented

### During Execution
- [ ] PROJECT_STATUS.md updated regularly
- [ ] Blockers identified and escalated
- [ ] Quality gates applied
- [ ] Communication clear between agents

### At Completion
- [ ] All tasks completed
- [ ] Tests passing
- [ ] Documentation current
- [ ] Lessons learned captured

## Best Practices

### Clear Handoff
```markdown
## Handoff: Backend to Code Review

### Deliverables
- FastAPI endpoints implemented ✓
- Unit tests created (84% coverage) ✓
- API documentation in docstrings ✓

### Known Issues
- RAG latency on large documents needs optimization
- Batch processing performance needs tuning

### Next Steps
1. Review code quality and security
2. Identify optimization opportunities
3. Recommend performance tuning

### Success Criteria
- No critical security issues
- Performance within benchmarks
- 80%+ test coverage maintained
```

### Progress Update
```markdown
## In Progress
- [Backend] Implementing RAG pipeline - 60% done, on track
- [Frontend] Chat interface components - waiting for API spec

## Completed Today
- [Architecture] System design diagram approved
- [DevOps] Docker infrastructure setup

## Blockers
- API rate limits from LLM provider affecting testing
- Waiting for vector DB credentials
```

## References
- Directed Acyclic Graphs (DAG): https://en.wikipedia.org/wiki/Directed_acyclic_graph
- Parallel Execution: https://en.wikipedia.org/wiki/Parallel_computing
- Workflow Orchestration: https://www.serverless.com/blog/durable-functions
- Project Management: https://www.pmi.org/
