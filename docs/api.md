# API reference

All non-auth endpoints except `/api/health` require `Authorization: Bearer <access_token>`. Send JSON except uploads, which use multipart form data. Validation failures return 422; unavailable records 404; role violations 403; state conflicts 409. OpenAPI is available locally at `/docs` and `/openapi.json`.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | /api/auth/register | Name, email, password; grants claim_reviewer only |
| POST | /api/auth/login | Email/password; returns access and refresh tokens |
| POST | /api/auth/refresh | Rotates refresh token |
| POST | /api/auth/logout | Revokes supplied refresh token |
| GET | /api/auth/me | Current user without password hash |
| POST | /api/auth/forgot-password | Generic response; demo token only in demo mode |
| POST | /api/auth/reset-password | One-use token and new password |
| GET, POST | /api/claims | Search/filter or create a validated claim |
| GET, PUT | /api/claims/{id} | Detail or edit an eligible claim |
| GET, POST | /api/claims/{id}/documents | List or extract multipart file |
| POST | /api/claims/{id}/investigate | Queue actual graph execution; idempotent while running |
| GET | /api/claims/{id}/investigation | Persisted run, steps, findings, evidence, summary |
| GET | /api/claims/{id}/agents | Alias for investigation progress |
| GET | /api/agents/runs/{id} | Run by identifier |
| GET | /api/reviews/pending | Human attention queue |
| POST | /api/reviews/assign | Admin/senior: claim_id, reviewer_id |
| POST | /api/reviews/{id}/decision | action, reason, evidence chunk/document IDs |
| POST | /api/reviews/{id}/request-information | Same schema; action=request_information |
| POST | /api/reviews/{id}/escalate | Same schema; action=escalate |
| POST | /api/knowledge/upload | Admin/policy specialist: file, category, version |
| GET | /api/knowledge/documents | Versioned source documents |
| GET | /api/knowledge/search?q=... | Source-preserving lexical hybrid retrieval |
| DELETE | /api/knowledge/documents/{id} | Deactivates version, preserves evidence history |
| GET | /api/analytics | Database-derived totals, trend, agent timing, reviewer counts |
| GET | /api/dashboard | Alias for analytics |
| GET | /api/reports/claims.csv | Admin/senior/auditor CSV; formula-injection escaping |
| GET | /api/audit | Admin/senior/auditor append-only records |
| GET | /api/audit/integrity | Admin/auditor checks SHA-256 chain |
| GET | /api/admin/users | Admin/senior user list |
| PATCH | /api/admin/users/{id} | Admin role/activation update; cannot modify self |
| GET | /api/admin/settings | Admin capability configuration; no secrets |
| GET | /api/models | Demonstration model metadata and limitations |

Claim input: reference, patient, provider, policy, service_date (ISO date, not future), diagnosis, procedure, amount (positive, finite), claim_type and description. Decisions: approve, deny, request_information, escalate, medical_review, investigation, return. Final decisions need a completed investigation waiting at the human checkpoint and valid evidence. Denials additionally require a policy citation and senior/admin role.
