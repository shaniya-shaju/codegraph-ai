# demo-python-app

A small, deterministic sample Python application used to demonstrate
CodeGraph AI's parsing, knowledge-graph construction, vector indexing,
hybrid retrieval, grounded question answering, and change-impact analysis.

**This code is never executed by CodeGraph AI, its scripts, or its
tests.** CodeGraph analyzes source statically only — see
`scripts/seed_demo_repository.py` and `scripts/run_demo_checks.py` at the
repository root.

## Architecture

```
POST /login  -> login_endpoint -> AuthService.login
                                     -> UserRepository.find_by_email
                                     -> TokenService.create_access_token

POST /users  -> create_user_endpoint (async) -> UserService.create_user
                                                   -> UserRepository.save
```

- `UserRepository` extends `BaseRepository` (inheritance).
- `AuthService.login` has both a direct caller (`login_endpoint`) and,
  transitively, the `POST /login` API endpoint.
- `app.models.user.format_user_display_name` is an intentionally isolated
  utility function — never called anywhere else in this repository.
- `app.security.tokens.validate_credentials` and
  `app.services.user_service.validate_credentials` intentionally share a
  name across two different modules, to exercise symbol-ambiguity
  handling (an unqualified lookup for "validate_credentials" should
  report both as candidates rather than guessing).
- `tests/test_auth.py` and `tests/test_users.py` call production code
  directly, giving CodeGraph AI's "related tests" signal something real
  to find.
