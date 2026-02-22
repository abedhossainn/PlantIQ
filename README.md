# PlantIQ - Air-Gapped RAG System Frontend Prototype

High-fidelity interactive prototype for the **PlantIQ Air-Gapped RAG System** in industrial OT environments (Capstone Project).

This prototype demonstrates all major workflows and aligned to the three requirement sets from the capstone proposal.

1. **Document Ingestion & Processing (US-1.x)**
   - Upload with metadata
   - VLM validation report
   - Section review with checklist/evidence UX
   - QA gate metrics and recommendation
   - Final approve/reject decision and lock behavior

2. **Natural Language Query Interface (US-2.x)**
   - Plain-language troubleshooting chat
   - Citation-aware responses
   - Multi-turn interactions
   - Bookmarking useful answers

3. **Security, Access Control & Operations (US-3.x, MVP baseline)**
   - Login flow (prototype uses mock/demo identities)
   - Role-based UI behavior (User, Reviewer, Admin)
   - User management interface for role assignment

## Routes

### Core
- `/` (entry/redirect)
- `/login`
- `/chat`
- `/chat/bookmarks`

### Admin
- `/admin/documents`
- `/admin/documents/upload`
- `/admin/documents/[id]/validation`
- `/admin/documents/[id]/review`
- `/admin/documents/[id]/qa-gates`
- `/admin/documents/[id]/approve`
- `/admin/users`

## User Stories Coverage

All 13 proposal user stories are represented in the prototype experience (with mock data + local state simulation where backend integrations are out of scope for static hosting).

| ID | User Story Area | Primary Prototype Route(s) |
|---|---|---|
| US-1.1 | Upload document with metadata | `/admin/documents/upload` |
| US-1.2 | VLM validation report | `/admin/documents/[id]/validation` |
| US-1.3 | Section review + checklist + evidence UX | `/admin/documents/[id]/review` |
| US-1.4 | Final approval/rejection | `/admin/documents/[id]/approve` |
| US-1.5 | Current vs last-approved version behavior | `/admin/documents/[id]/review` |
| US-1.6 | QA gate metrics/recommendation | `/admin/documents/[id]/qa-gates` |
| US-2.1 | Ask troubleshooting questions | `/chat` |
| US-2.2 | Citation display in responses | `/chat` |
| US-2.3 | Open source context from citation | `/chat` (in-chat source context UX) |
| US-2.4 | Multi-turn conversation | `/chat` |
| US-2.5 | Bookmark useful answers | `/chat/bookmarks` |
| US-3.1 | Login/authentication flow | `/login` |
| US-3.2 | RBAC + user management | `/admin/users` |

## Demo Access

Prototype is deployed at:

**https://abedhossainn.github.io/PlantIQ/**

Demo identities (as described in proposal artifacts):
- Field User: `jdoe` / `demo`
- Reviewer: `mchen` / `demo`
- Admin: `rholt` / `demo`

> Note: In production design, identity is AD/LDAP-integrated. In this static prototype, authentication/authorization behavior is simulated with mock data and local state.

## How to Test End-to-End

1. **Login & role routing**
   - Visit `/login`
   - Use one of the demo identities above

2. **Document workflow (US-1.x)**
   - Go to `/admin/documents`
   - Upload: `/admin/documents/upload`
   - Validate: `/admin/documents/doc-1/validation`
   - Review: `/admin/documents/doc-1/review`
   - QA gates: `/admin/documents/doc-1/qa-gates`
   - Final approval: `/admin/documents/doc-1/approve`

3. **Query workflow (US-2.x)**
   - Go to `/chat`
   - Ask a troubleshooting question
   - Verify citations/source context UX
   - Save an answer and review it in `/chat/bookmarks`

4. **Admin workflow (US-3.2)**
   - Go to `/admin/users`
   - Change roles/status in the prototype UI

## Technology Stack

- **Framework:** Next.js 16 + TypeScript
- **UI:** Tailwind CSS + shadcn/ui + Radix primitives
- **State:** React Context + hooks + localStorage
- **Content Rendering:** React Markdown
- **Deployment:** GitHub Pages via GitHub Actions static export

## Deployment Notes

The workflow `.github/workflows/deploy.yml`:
1. Builds `frontend/` as static export (`output: "export"`)
2. Uploads `frontend/out` as Pages artifact
3. Deploys to GitHub Pages on push to `main` (frontend/deploy workflow changes)

The Next.js config uses project-site base path support for:
- `https://abedhossainn.github.io/PlantIQ/`

## Prototype Constraints (Expected)

- Uses mock data and local persistence; no live backend services on Pages
- Intended to validate UX/flow and capstone feasibility, not production security controls
- Backend pipeline, model serving, and full air-gapped operations are represented conceptually and in companion project documents/scripts

