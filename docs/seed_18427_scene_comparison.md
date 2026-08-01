# Seed 18427 scene comparison

The comparison keeps two incompatible scenario schemas visibly separate:

- **Audit scenario-v2:** the exact six-node, two-UAV-ID package in
  `outputs/seed_18427`. Its separate audit action fixture specifies the service
  visit at six hours but does not specify a continuous UAV flight path.
- **Trained-policy scenario:** the twenty-node, three-UAV environment used by
  the final graph-MAPPO checkpoint. This scene is a historical pre-promotion
  audit: its replay branch is unguided graph-MAPPO and therefore asserts
  exactly `g=0`. The later locked 40-seed benchmark promoted fixed guidance
  (`g=0.5`, `beta=5.591`); this existing scene artifact is not retrospectively
  relabelled as that promoted policy.

The side-by-side animation aligns normalized progress, not mission time. The
left clock runs from zero to eight hours; the right clock runs from zero to one
hour. This presentation must not be described as the trained checkpoint
controlling the audit-v2 scenario.

Run from the repository root:

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python scripts\visualize_seed_18427_comparison.py `
  --audit-scenario outputs\seed_18427\seed_18427.json `
  --audit-actions outputs\seed_18427\audit_actions.json `
  --results results\gate_learning_final `
  --output results\seed_18427_scene_comparison `
  --frames 120 `
  --fps 6 `
  --device cpu
```

Generated artifacts:

- `seed_18427_side_by_side.gif`
- `audit_scenario_v2_scripted.gif`
- `trained_graph_mappo_seed18427.gif`
- `seed_18427_comparison_preview.png`
- `trained_policy_trajectory.csv`
- `trained_policy_decisions.csv`
- `comparison_manifest.json`

The manifest records both input hashes, the production checkpoint hash,
rollout metrics, the schema distinction, and the audit trajectory limitation.
