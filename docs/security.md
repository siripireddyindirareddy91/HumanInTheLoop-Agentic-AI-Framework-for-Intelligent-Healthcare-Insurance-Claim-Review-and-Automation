# Security boundaries

Passwords use Argon2. JWTs are signed server-side, access tokens expire in one hour and refresh tokens rotate and are revocable. Logout revokes refresh access; an already-issued access token expires naturally. Password-reset tokens are hashed, expire after 15 minutes and are single-use. Demo token delivery is intentionally only for synthetic demonstration accounts.

Role checks are enforced by FastAPI, including exports, audit, administration, document management and decisions. Human review checks assignment, investigation state, final-state immutability, reason length and evidence ownership. AI identities cannot invoke a final decision as a human. No payment endpoint exists.

Uploads are bounded, extension/signature checked where applicable and extracted without executing source content. DOCX archives have expanded-size limits; PDFs have page limits; images have pixel limits. Uploaded originals are not retained. Documents never become system prompts. The optional LLM adapter treats source text as untrusted and checks citation identifiers.

Audit writes append records linked by SHA-256; there is no API to edit/delete audit records. The chain is tamper-evident at application level, not an independent immutable ledger. Production needs serialized audit writers and external anchoring.

Synthetic data is required in this demonstration. Real protected health information requires durable encrypted storage, tenant/row isolation, retention policy, MFA, rate limits, incident monitoring, independent penetration testing and applicable organizational/legal approval.
