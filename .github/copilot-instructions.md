# Agent System

This project uses a specialized multi-agent system for coordinated development. Each agent has a specific role and expertise:

## Available Agents

1. **Project Lead** - Orchestrates work across all agents
   - Use this for: Project analysis, workflow planning, delegating work
   - Does NOT implement code

2. **Architecture Planning** - System design and technical decisions
   - Use this for: Design reviews, technology choices, integration patterns
   - Outputs: Architecture documents, component diagrams

3. **Backend Development** - FastAPI middleware, LangChain, vLLM integration
   - Use this for: Backend implementation, RAG pipeline, API endpoints
   - Hands off to: Code Review, Documentation

4. **Frontend Development** - TypeScript/React Chatbot UI
   - Use this for: UI implementation, components, user interactions
   - Hands off to: Code Review, Documentation

5. **DevOps/Infrastructure** - Docker, deployment, CI/CD
   - Use this for: Containerization, deployment configs, infrastructure setup
   - Hands off to: Documentation, Testing & Validation

6. **Code Review** - Quality, security, performance analysis
   - Use this for: Code quality assessment, security review
   - Hands off to: Testing, Backend Work, Frontend Work

7. **Testing & QA** - Test strategy and implementation
   - Use this for: Test creation, test automation, quality assurance
   - Hands off to: DevOps, Backend Work, Frontend Work

8. **Documentation** - Technical guides, architecture records
   - Use this for: Documentation creation, knowledge base maintenance
   - Outputs: READMEs, API docs, ADRs, setup guides

## Agent Workflow

The standard development workflow follows this sequence:

```
Project Lead (analyze & plan)
  ↓
Architecture Planning (design)
  ├→ Backend Development → Code Review → Testing → DevOps → Documentation
  ├→ Frontend Development → Code Review → Testing → DevOps → Documentation
  └→ DevOps/Infrastructure → Testing & Validation → Documentation
```

## How to Use

**For Full Project Work:** Start with the Project Lead agent
- Say: "Analyze the project and create a plan for [feature]"
- Lead will decompose work and provide handoff buttons to specialized agents

**For Specific Tasks:** Jump directly to the relevant agent
- Backend implementation → Backend Development agent
- Code quality check → Code Review agent
- Testing → Testing & QA agent
- Documentation → Documentation agent

## Handoff Buttons

After each agent completes their work, you'll see handoff buttons showing available next steps. Click the button to delegate to the next agent in the workflow.

# Behavior
- When generating code, ensure it aligns with the "Detailed Workflow" in `instructions.md`.
- If you are unsure about a requirement, ask for clarification based on the `instructions.md` file.
- Prefer using `vLLM` specific optimizations when applicable.
- Use agents for specialized work - don't attempt to handle architecture, implementation, review, testing, and deployment in a single response.
- Always clarify which agent context you're operating in (via handoff buttons or explicit agent selection).
- Always investigate the root cause before proposing or applying a fix; avoid symptom-only patches.
- Apply clean code principles consistently: clear naming, small focused units, low duplication, and separation of concerns.
- Work in local, development, or staging environments by default; do not move work into production until the user explicitly confirms it.
- Focus on core functionality and the critical path before enhancements, optimizations, or polish.
- Create a plan and stick to it; only revise the plan when evidence shows it is incomplete or incorrect, and explain why.
- Verify with the user before adding new scope, features, dependencies, files, or behaviors that were not explicitly requested.

# Context7 MCP Server

**CRITICAL**: Always use Context7 MCP Server before starting any task or troubleshooting issues:

- **For Library Documentation**: Use Context7 to fetch up-to-date code examples and API documentation for FastAPI, LangChain, vLLM, React, TypeScript, and other project dependencies
- **For Package Versions**: Get version-specific documentation to avoid hallucinated APIs or outdated examples
- **For Setup/Configuration**: Retrieve accurate setup instructions for any library or framework
- **For Troubleshooting**: Query Context7 for documented solutions before attempting fixes
- **Usage**: Simply add `use context7` to your prompt or use library IDs like `/mongodb/docs` or `/vercel/next.js`

See [Context7 Documentation](https://github.com/upstash/context7) for more details.
