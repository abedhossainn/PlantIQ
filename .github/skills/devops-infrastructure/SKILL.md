# DevOps & Infrastructure Skill

This skill provides comprehensive guidance for containerization, deployment automation, CI/CD pipelines, and infrastructure management for the RAG chatbot.

## Operating Guardrails

- **Root-Cause First**: Investigate the true cause of environment, build, or deployment failures before changing infrastructure.
- **Clean Infrastructure Focus**: Favor simple, readable, modular infrastructure code and automation.
- **Development-First Execution**: Default to local, development, and staging workflows. Treat production rollout as a separate step that requires explicit user confirmation.
- **Core Functionality First**: Stabilize the core development and delivery path before adding operational extras or advanced optimization.
- **Plan Discipline**: Define the deployment or remediation plan and stick to it unless evidence justifies a change.
- **Confirm Before Expanding Scope**: Verify with the user before introducing new infrastructure, services, dependencies, or operational workflows.

## Overview

The DevOps & Infrastructure skill encompasses:
- **Docker**: Containerization and multi-stage builds
- **Docker Compose**: Local development environment
- **Kubernetes**: Production orchestration and scaling
- **GitHub Actions**: CI/CD pipeline automation
- **Infrastructure as Code**: Terraform, Bicep for Azure
- **Security**: Secret management and access control
- **Monitoring**: Health checks, logging, metrics

## Container Architecture

### Multi-Stage Dockerfile
```dockerfile
# Build stage - minimize final image size
FROM python:3.11 as builder

# Runtime stage - small, secure runtime image
FROM python:3.11-slim
```

### Docker Compose for Development
- Backend service (FastAPI)
- Frontend service (Next.js)
- Vector database (Qdrant/Pinecone)
- Optional: LLM service

## CI/CD Pipeline Stages

1. **Code Quality**
   - Linting (ruff, ESLint)
   - Type checking (mypy, TypeScript)
   - Security scanning

2. **Testing**
   - Unit tests (pytest, Vitest)
   - Integration tests
   - E2E tests (Playwright)

3. **Build**
   - Docker image creation
   - Frontend bundle optimization
   - Artifact storage

4. **Deploy**
   - Blue-green deployment
   - Health checks
   - Automated rollback

## Environment Management

### Environment Variables
- `.env.example`: Template with safe defaults
- GitHub Secrets: protected environment credentials
- `.env.local`: Development overrides (gitignored)
- Never commit `.env` files

### Secrets Management
- GitHub Secrets for protected environments
- .env for local development
- Encrypted vaults for enterprise

## Infrastructure Patterns

### High Availability
- Multiple replicas of services
- Load balancing
- Graceful degradation

### Security
- Private networks and subnets
- API key rotation
- Rate limiting and DDoS protection

### Monitoring & Observability
- Health check endpoints
- Structured logging (JSON)
- Metrics collection (Prometheus)
- Tracing (distributed spans)

## Deployment Strategies

### Blue-Green
- Two identical production environments
- Instant traffic switching
- Zero downtime deployments

### Rolling Updates
- Gradual instance replacement
- Health checks ensure readiness
- Automatic rollback on failure

## How to Use This Skill

1. **Local Development**: Use Docker Compose for environment setup
2. **CI/CD Pipeline**: Reference for GitHub Actions workflow configuration
3. **Container Security**: Apply when hardening Docker images
4. **Deployment**: Use for blue-green or rolling update strategy
5. **Incident Response**: Reference for rollback procedures
6. **Scaling**: Consult for Kubernetes resource planning

## Related Skills
- [Backend Development](../backend-development/SKILL.md) - For API health endpoints
- [Frontend Development](../frontend-development/SKILL.md) - For frontend build optimization
- [Testing Automation](../testing-automation/SKILL.md) - For CI test execution
- [Security & Quality](../security-quality/SKILL.md) - For security best practices

## Best Practices

### Container Image Size
- Use slim base images: `python:3.11-slim`
- Multi-stage builds for build tools
- Minimal final image footprint

### Health Checks
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s \
  CMD curl -f http://localhost:8000/health || exit 1
```

## References
- Docker: https://docker.com
- Docker Compose: https://docs.docker.com/compose/
- Kubernetes: https://kubernetes.io
- GitHub Actions: https://github.com/features/actions
- Infrastructure as Code: https://www.terraform.io
