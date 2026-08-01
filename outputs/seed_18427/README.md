# Seed 18427 audit package

This directory is a deterministic scenario-v2 package. Canonical internal
units are metres, seconds, watt-hours, kilograms, and standardized demand
units. Medical and water are active; food and shelter slots are retained at
zero for compatibility.

Generate and audit from the `code` directory:

```text
python -m scripts.generate_seed --seed 18427 --config configs/prototype_seed.yaml --output outputs/seed_18427
python -m scripts.audit_seed --scenario outputs/seed_18427/seed_18427.json --audit-actions outputs/seed_18427/audit_actions.json --time-hours 4.2
```

`seed_18427.json` contains the exogenous scenario
only. `audit_actions.json` is a separate scripted audit policy and is never
part of the exogenous event schedule. The four `.npy` files expose the
normalized population, infrastructure, terrain-difficulty, and base composite
risk rasters on the coarse grid. See `risk_layers_metadata.json` for
coordinates, fixed normalization references, dtype, and composite weights.
