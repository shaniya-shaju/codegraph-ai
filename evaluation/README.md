# Evaluation

Working area for executing [EVALUATION_PLAN.md](../EVALUATION_PLAN.md).
Nothing here is implemented yet — this scaffolding exists so evaluation
artifacts have a fixed home once M1+ milestones (see
[PROJECT_PLAN.md](../PROJECT_PLAN.md)) land.

- [datasets/](datasets/) — labeled QA sets and hand-derived ground-truth
  impact sets for the fixture repositories (see EVALUATION_PLAN.md §2, §3).
- [metrics/](metrics/) — scripts/notebooks that compute hit@k, precision/
  recall, and citation-groundedness against a dataset + a running backend.
- [reports/](reports/) — dated output of running the metrics above, kept
  so accuracy numbers are traceable across milestones rather than only
  quoted from memory.
