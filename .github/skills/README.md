# GitHub Copilot Agent Skills

Welcome to the RAG Chatbot project's comprehensive agent skills collection. These skills provide specialized guidance for different aspects of the development lifecycle.

## Skills Directory Structure

All skills are organized under `.github/skills/` following [GitHub's Agent Skills specification](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills).

```
.github/skills/
├── backend-development/           # FastAPI, LangChain, vLLM
├── frontend-development/          # React, TypeScript, Next.js
├── testing-automation/            # TDD, pytest, Playwright
├── devops-infrastructure/         # Docker, K8s, CI/CD
├── security-quality/              # OWASP, Accessibility, Performance
├── context-engineering/           # Code organization, refactoring
├── project-planning/              # Feature breakdown, sequencing
└── agent-orchestration/           # Multi-agent coordination
```

## Quick Navigation

### 🔧 Implementation Skills
- **[Backend Development](backend-development/SKILL.md)** - FastAPI, LangChain, vLLM, MCP servers
- **[Frontend Development](frontend-development/SKILL.md)** - React, TypeScript, Next.js, TailwindCSS
- **[Testing Automation](testing-automation/SKILL.md)** - TDD, pytest, Vitest, Playwright

### 🚀 Operations Skills
- **[DevOps & Infrastructure](devops-infrastructure/SKILL.md)** - Docker, Kubernetes, CI/CD, monitoring
- **[Security & Quality](security-quality/SKILL.md)** - OWASP, accessibility, performance

### 📋 Planning & Coordination Skills
- **[Project Planning](project-planning/SKILL.md)** - Feature breakdown, implementation planning
- **[Context Engineering](context-engineering/SKILL.md)** - Code organization, refactoring, dependencies
- **[Agent Orchestration](agent-orchestration/SKILL.md)** - Multi-agent workflows, coordination

## How to Use These Skills

### For Agents
Each skill is loadable by agents and provides domain-specific guidance for their work. Reference skills explicitly when you need specialized guidance:

```
"Use the Backend Development skill for FastAPI endpoint design"
"Refer to Testing Automation skill for TDD workflow"
"Consult DevOps Infrastructure skill for Docker best practices"
```

### For Developers
These skills serve as comprehensive guides for:
- Understanding best practices in different areas
- Following consistent patterns across the project
- Learning domain-specific knowledge
- Troubleshooting common issues

### For Project Lead
Use these skills for agent assignment and task decomposition:
- Assign tasks to agents with relevant skills
- Sequence work based on dependencies (from Project Planning skill)
- Apply quality gates from appropriate skills
- Track progress in PROJECT_STATUS.md

## Key Features

### 📚 Comprehensive Coverage
- Covers full development lifecycle from planning to deployment
- Language-specific guidance (Python, TypeScript, etc.)
- Framework-specific practices (FastAPI, React, Playwright)

### 🔗 Cross-Skill References
- Skills reference each other for related concepts
- Links to external authoritative references
- Consistent terminology and patterns

### 📊 Project-Specific Context
- Customized for RAG chatbot architecture
- References actual tools used in project
- Integrates with PROJECT_STATUS.md

### 🎯 Practical Guidance
- Code examples and templates
- Best practices and anti-patterns
- Common pitfalls and solutions

## Integration with Agent Workflow

### Task Flow with Skills

```
Project Lead
├─ Uses Project Planning skill
│  └─ Decomposes feature into tasks
├─ Assigns to Backend with Backend Development skill
│  └─ API implementation guidance
├─ Assigns to Frontend with Frontend Development skill
│  └─ Component building guidance
├─ Runs through Code Review with Security & Quality skill
├─ Assigns Testing with Testing Automation skill
├─ Deploys with DevOps skill
└─ Documents with project context

All agents coordinate via Agent Orchestration skill
```

### Quality Gates Across Skills
- **Code Review** checks Backend/Frontend Development quality
- **Testing Automation** validates coverage requirements
- **Security & Quality** applies security and accessibility standards
- **DevOps** validates infrastructure requirements

## References & Conventions

### Naming Conventions
- Backend: snake_case for Python, PascalCase for classes
- Frontend: camelCase for functions, PascalCase for components
- Files: kebab-case for file names (except index exports)

### Directory Structure
- Backend: `src/core`, `src/services`, `src/models`, `src/api`
- Frontend: `src/components/`, `src/pages/`, `src/lib/`, `src/types/`
- Tests: `tests/unit/`, `tests/integration/`, `tests/e2e/`

### Configuration
- All configuration in `PROJECT_STATUS.md`
- No separate planning or tracking files
- Decisions logged in PROJECT_STATUS.md

## Getting Started

1. **Read [Agent Orchestration](agent-orchestration/SKILL.md)** - Understand the coordination model
2. **Review [Project Planning](project-planning/SKILL.md)** - Learn task decomposition
3. **Explore domain skills** - For your specific role
4. **Reference [Security & Quality](security-quality/SKILL.md)** - Applies to all work
5. **Check related skills** - Each skill links to related areas

## Contributing

When working with skills:
- Update PROJECT_STATUS.md with your progress
- Reference relevant skills in your commits
- Follow principles from Security & Quality skill
- Update skill docs if you discover improvements

## Quick Links

- [PROJECT_STATUS.md](/PROJECT_STATUS.md) - Single source of truth for project progress
- [Agent Instructions](.github/agents/) - Agent-specific guidance
- [GitHub Documentation](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) - Official spec

---

**Last Updated**: March 9, 2026  
**Skills Version**: 1.0  
**Centered on**: RAG Chatbot Development
