# Frontend Development Skill

This skill provides comprehensive guidance for building production-ready frontend interfaces for the RAG chatbot using TypeScript, React, and modern web technologies.

## Overview

The Frontend Development skill encompasses:
- **React**: Modern component-based UI architecture
- **TypeScript**: Type-safe JavaScript for maintainability
- **Next.js**: Server-side rendering and optimization
- **TailwindCSS + shadcn/ui**: Component library and styling
- **Accessibility (WCAG)**: Inclusive design standards
- **Performance**: Bundle optimization and lazy loading
- **Clean Code**: Maintainable, readable component architecture

## Key Practices

### Component Architecture
- Feature-based folder structure (not file-type based)
- Presentational vs. Container component separation
- Custom hooks for shared logic
- Composition over inheritance

### State Management
- React Context for application state
- Proper scope and memory management
- Server state vs. UI state separation

### Accessibility
- WCAG 2.1 AA standards compliance
- Keyboard navigation support
- Screen reader compatibility
- Semantic HTML structure

### Performance Optimization
- Code splitting with dynamic imports
- React.memo and useMemo for preventing re-renders
- Image optimization and lazy loading
- Bundle size monitoring

### Testing Strategy
- Unit tests (Vitest for components)
- Integration tests (React Testing Library)
- E2E tests (Playwright)
- Visual regression testing

## How to Use This Skill

1. **For Chat UI**: Use when building the main chatbot interface component
2. **For Document Management**: Reference when creating document upload and library interfaces
3. **For Responsive Design**: Apply when ensuring mobile and desktop compatibility
4. **For Accessibility**: Consult when adding WCAG compliance features
5. **For Performance**: Use for optimization when bundle size becomes a concern

## Related Skills
- [Testing Automation](#) - For E2E tests with Playwright
- [Context Engineering](#) - For refactoring large component trees
- [Security & Quality](#) - For security best practices in frontend

## Best Practices

```typescript
// Component naming
export const ChatMessage: React.FC<ChatMessageProps> = ({ message }) => {
  // Implementation
}

// Custom hooks
export const useDocumentFetch = (documentId: string) => {
  // Implementation
}

// Clear prop types
interface ChatMessageProps {
  message: Message
  onReply?: (messageId: string, text: string) => void
  isLoading?: boolean
}
```

## References
- React: https://react.dev
- Next.js: https://nextjs.org
- TypeScript: https://www.typescriptlang.org
- shadcn/ui: https://ui.shadcn.com
- Accessibility: https://www.w3.org/WAI/WCAG21/quickref/
