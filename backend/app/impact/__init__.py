"""Deterministic change-impact-analysis engine.

Given a validated target symbol (function, method, class, or API
endpoint), bounded graph traversal determines everything that is
structurally affected by (or that the target itself depends on) — see
this package's ``analyzer.py``. The deterministic graph decides which
symbols are affected; an LLM may only explain an already-computed result
(``explanation.py``), never add to it — see the impact-analysis task's
"IMPORTANT: The deterministic graph must determine impact."

See ARCHITECTURE.md "Change-impact-analysis design".
"""
