# Security & Code Quality Skill

This skill provides comprehensive guidance on security best practices, OWASP compliance, accessibility standards, and code quality optimization for the RAG chatbot.

## Operating Guardrails

- **Root-Cause First**: Focus on underlying security, reliability, accessibility, and maintainability issues rather than cosmetic fixes.
- **Clean Code Focus**: Enforce clear naming, focused units, low duplication, separation of concerns, and maintainable design.
- **Development-First Execution**: Validate changes in local, development, or staging environments by default; do not move work into production without explicit user confirmation.
- **Core Functionality First**: Address issues that affect required behavior and critical paths before optional improvements.
- **Plan Discipline**: Follow a deliberate remediation plan and revise it only when evidence shows it is incomplete or wrong.
- **Confirm Before Expanding Scope**: Verify with the user before adding new tools, dependencies, policies, or remediation work outside the request.

## Overview

The Security & Code Quality skill encompasses:
- **Security**: OWASP Top 10, threat modeling, secure design
- **Accessibility**: WCAG 2.1 standards for inclusive design
- **Performance**: Optimization strategies and bottleneck identification
- **Code Quality**: Clean code principles and maintainability
- **Vulnerability**: Dependency scanning and secure coding

## Security Domains

### Authentication & Authorization
- Secure credential storage (never hardcode)
- JWT token validation and expiration
- Role-based access control (RBAC)
- API key rotation

### Data Protection
- Encryption in transit (TLS/HTTPS)
- Encryption at rest (database)
- Secure deletion of sensitive data
- PII data handling

### Application Security
- Input validation and sanitization
- SQL injection prevention (use parameterized queries)
- XSS prevention (escape output)
- CSRF protection (state verification)

### Dependency Management
- Regular security updates
- Vulnerability scanning (npm audit, pip check)
- License compliance (OWASP Dependency-Check)
- Pinned versions for controlled environments

## Accessibility (WCAG 2.1)

### Perceivable
- Sufficient color contrast (4.5:1 for normal text)
- Text alternatives for images
- Distinguishable foreground/background

### Operable
- Keyboard navigation (all functionality keyboard accessible)
- No content that flashes more than 3x per second
- Focus indicators visible

### Understandable
- Clear language and simple sentences
- Consistent navigation
- Error messages with recovery suggestions

### Robust
- Valid HTML and semantic structure
- ARIA labels where needed
- Screen reader compatibility

## Performance Optimization

### Backend Performance
- Database query optimization (avoid N+1 queries)
- Caching strategies (Redis, in-memory)
- Async processing for long-running tasks
- Connection pooling

### Frontend Performance
- Code splitting and lazy loading
- Image optimization and WebP format
- CSS and JavaScript minification
- Critical rendering path optimization

### Monitoring Metrics
- Response time < 200ms for APIs
- Largest Contentful Paint (LCP) < 2.5s
- First Input Delay (FID) < 100ms
- Cumulative Layout Shift (CLS) < 0.1

## Code Quality Standards

### Clean Code Principles
1. **Clarity**: Code that tells a story
2. **Simplicity**: Use KISS, avoid over-engineering
3. **DRY**: Don't Repeat Yourself
4. **SOLID**: Design patterns and principles
5. **Comments**: Explain "why" not "what"

### Code Review Focus Areas
- Security vulnerabilities
- Performance bottlenecks
- Test coverage gaps
- Maintainability concerns
- Compliance issues

## How to Use This Skill

1. **Security Audit**: Use when reviewing code for vulnerabilities
2. **Accessibility Testing**: Apply when adding UI features
3. **Performance Profiling**: Reference when investigating slow operations
4. **Dependency Security**: Use for managing and updating packages
5. **Code Review**: Consult for quality standards
6. **Incident Response**: Reference for security incident handling

## Related Skills
- [Backend Development](../backend-development/SKILL.md) - For secure API design
- [Frontend Development](../frontend-development/SKILL.md) - For secure client-side handling
- [DevOps Infrastructure](../devops-infrastructure/SKILL.md) - For infrastructure security
- [Testing Automation](../testing-automation/SKILL.md) - For security testing

## Best Practices

### Secure Coding
```python
# SQL: Use parameterized queries
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# API: Validate all inputs
from pydantic import BaseModel, validator
class UserInput(BaseModel):
    email: str
    @validator('email')
    def email_valid(cls, v):
        # validation logic
```

### Accessibility
```jsx
// Use semantic HTML
<a href="/docs" aria-label="Read documentation">Docs</a>

// Proper ARIA labels
<button aria-label="Close modal" onClick={handleClose}>×</button>
```

## References
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- WCAG 2.1: https://www.w3.org/WAI/WCAG21/quickref/
- NIST Cybersecurity: https://csrc.nist.gov/projects/cybersecurity-framework
- Core Web Vitals: https://web.dev/vitals/
