# CodeGraph AI authentication and repository privacy

## Setup

1. Copy `.env.example` to `.env` (do not commit `.env`).
2. Generate a fresh signing secret from the repository root:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Put the generated value in `.env` as `AUTH_SECRET_KEY=...`. Use a unique value per environment. `AUTH_TOKEN_EXPIRY_HOURS` defaults to 12.
4. Start the backend and frontend as usual. Register at `/register`, then sign in at `/login`.

## What changed

- Registration and login endpoints: `POST /api/v1/auth/register` and `POST /api/v1/auth/login`. Passwords are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations) and a unique random salt. Plaintext passwords are never stored.
- Signed bearer tokens expire after the configured lifetime. The browser keeps the token in `sessionStorage`, so it is cleared when the browser tab session ends or the user signs out.
- Backend middleware requires authentication for API routes other than health checks and authentication endpoints. Every route containing a repository ID is checked against the repository's `owner_id`, covering graph, retrieval, query, indexing, impact, analysis, and deletion endpoints. Unknown and non-owned repositories return the same 404 response.
- New repository records are associated with the authenticated user. Chroma collections and graph data continue to use the existing globally unique repository ID, and requests can reach them only after the server verifies repository ownership.
- Existing databases receive an `owner_id` column automatically. Existing repository rows are intentionally left ownerless and are hidden from all users until an administrator explicitly reviews and assigns them. Do not automatically assign legacy repositories to the first account. Back up the database before deploying.

## Security notes

- Configure HTTPS in any shared or production deployment. Do not use the example signing secret.
- The token is stored in `sessionStorage`; protect the frontend against XSS and do not add unsafe HTML rendering. A server-side revocable session store and rate limiting are recommended before public deployment.
- CORS remains limited to the configured `CORS_ALLOWED_ORIGINS`. Do not add wildcard origins for a credentialed deployment.
- Repository privacy is enforced in the API middleware, not just by hiding frontend links. The repository UUID is not treated as authorization.

## Smoke-test checklist

1. Register account A and upload a ZIP repository.
2. Confirm the dashboard and graph/query/impact features work as before.
3. Sign out and register account B in a separate browser session. Account B should see no repositories from A.
4. While signed in as B, call an A repository endpoint using A's repository ID. It should return 404. Try graph, query, analysis, index, and DELETE routes.
5. Test duplicate email, wrong password, weak password, and expired token behavior.
6. Back up any existing database before using the updated application.
