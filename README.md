# PlantIQ - Air-Gapped RAG System Frontend Prototype

High-fidelity interactive prototype for the Air-Gapped RAG System for Industrial OT Environments (Capstone Project).

## Features

### Document Ingestion Pipeline (Requirement Set 1)
- **Upload**: Add vendor manuals with metadata
- **Validation**: VLM-powered extraction quality report
- **Review**: Web-based interface to edit and validate sections
- **Approval**: Lock reviewed versions for RAG ingestion

### Query Interface (Requirement Set 2)
- **Chat**: Ask natural language questions
- **Citations**: Answers include source page references
- **Multi-turn**: Follow-up questions with context preservation
- **Bookmarks**: Save answers for future reference

### Admin & Security (Requirement Set 3)
- **Authentication**: Login with mock credentials
- **RBAC**: User, Reviewer, Admin roles
- **Audit Logs**: Track all actions
- **User Management**: Assign roles and permissions

## User Stories Implemented

All 13 user stories are fully interactive:

| ID | User Story | Route |
|----|----|---|
| US-1.1 | Upload document | `/admin/upload` |
| US-1.2 | VLM validation report | `/admin/validation-report` |
| US-1.3 | Review interface | `/admin/review` |
| US-1.4 | Approve document | `/admin/approval` |
| US-1.5 | Version history | `/admin/versions` |
| US-1.6 | QA metrics | `/admin/qa-metrics` |
| US-2.1 | Ask questions | `/chat` |
| US-2.2 | View citations | `/chat` |
| US-2.3 | Open source section | `/chat/citation-detail` |
| US-2.4 | Multi-turn conversation | `/chat` |
| US-2.5 | Bookmark answers | `/chat/bookmarks` |
| US-3.1 | Active Directory login | `/login` |
| US-3.2 | RBAC user management | `/admin/users` |

## Testing the Prototype

1. **Test Login (US-3.1):**
   - Visit `/login`
   - Use any email/password (mock authentication)

2. **Test Document Flow (US-1.1 - US-1.6):**
   - Login as Admin
   - `/admin/upload` → Upload a test PDF
   - `/admin/validation-report` → Review extraction issues
   - `/admin/review` → Edit sections with inline evidence images
   - `/admin/approval` → Approve document
   - `/admin/qa-metrics` → See QA metrics

3. **Test Query Flow (US-2.1 - US-2.5):**
   - Login as User
   - `/chat` → Ask "How do I troubleshoot the pump?"
   - See response with citations (US-2.2)
   - Click citation to open source (US-2.3)
   - Ask follow-up questions (US-2.4)
   - Bookmark the answer (US-2.5)

4. **Test Admin (US-3.2):**
   - Login as Admin
   - `/admin/users` → Add user and assign role
   - `/admin/audit-logs` → View action history

## Technologies

- **Framework**: Next.js 16 with TypeScript
- **Styling**: Tailwind CSS + shadcn/ui
- **State Management**: React Context API + Mock Data
- **Form Handling**: React Hook Form
- **Components**: Radix UI + Tailwind

## GitHub Pages Deployment

The repository includes a GitHub Actions workflow (`.github/workflows/deploy.yml`) that:

1. Builds the Next.js app as static HTML/JS
2. Uploads the build artifact
3. Deploys to GitHub Pages on every push to `main`

**Live prototype:** https://abedhossainn.github.io/PlantIQ/

## Notes

- **Mock Data**: The prototype uses React state and mock data (no backend needed)
- **Static Export**: Built with `output: "export"` in Next.js config for GitHub Pages compatibility
- **Responsive**: Works on desktop, tablet, and mobile devices

