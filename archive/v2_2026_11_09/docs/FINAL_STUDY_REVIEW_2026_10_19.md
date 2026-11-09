# Review of the latest final-study results

Reviewed on 19 October 2026. Scope: the run `final_study_2026_10_17`, completed on 18 October, and its report regenerated on 19 October. This is an audit of the experimental results and reporting, not a full manuscript or mathematical-proof review.

**Assessment:** The results provide substantial evidence for minimum-level certification and reduced disruption compared with global replanning. The report needs several corrections and qualifications before its headline numbers are reused in the manuscript. The evidence does not establish general superiority over PH, or consistently fast Level-4 certification.

Audit axes: optimization; baseline, statistical and reproducibility evidence; risks of overclaiming and inconsistent comparison metrics; audit stage.

## Priority findings

### 1. Major: the primary table and anytime plots use different denominators

At 10 seconds, the reported CMI value of 85.1% is **1,125 / 1,322**, conditional on a known reference minimum in Levels 0–4. It is not the share of all 1,440 FS variants. The excluded variants are 102 certified unrecoverable cases and 16 unresolved cases. The full report explains this condition in its comparison-section introduction, but the primary-endpoint table and short results document do not carry the denominator.

The plot function divides by all instances. Consequently, its 10-second endpoint is 78.1% for CMI, while the table says 85.1%, under essentially the same metric name. The protocol describes Q1 as the share of FS variants and explicitly retains unresolved variants in the population.

| Method | Verified minimum-level plans | Among 1,322 known recoverable minima | Among all 1,440 FS variants |
|---|---:|---:|---:|
| CMI | 1,125 | 85.1% | 78.1% |
| PH | 1,171 | 88.6% | 81.3% |
| LR | 1,029 | 77.8% | 71.5% |
| GR-c | 586 | 44.3% | 40.7% |
| GR | 136 | 10.3% | 9.4% |

**Action:** retain the conditional metric with an explicit denominator, and also report the all-population share of verified minimum-level plans. Use consistent denominators in tables and figures. Describe any departure from the protocol's primary endpoint. An unresolved minimum means success is not verified, rather than proving that the returned plan is nonminimal. This reporting correction does not reverse the 10-second PH/CMI ordering.

Evidence: [scoring](<D:/Post-disaster Logistics/code/src/final_study/analysis.py:430>), [anytime calculation](<D:/Post-disaster Logistics/code/src/final_study/analysis.py:511>), [primary endpoint protocol](<D:/Post-disaster Logistics/code/docs/COMPARISON_PROTOCOL_2026_10_14.md:226>), and [short results table](<D:/Post-disaster Logistics/code/docs/FINAL_STUDY_RESULTS_2026_10_18.md:99>).

### 2. Major: the 60-second advantage over PH is not statistically established

At 10 seconds, PH outperforms CMI on the conditional minimum-level endpoint: 88.6% versus 85.1%. The existing paired interval for CMI minus PH is −5.5 to −1.6 percentage points. The report correctly marks that part of H1 unsupported.

At 60 seconds, CMI obtains 412/417 minimum-level plans and PH 403/417: 98.8% versus 96.6%. Of these 417 instances, both succeed on 400, only CMI on 12, only PH on 3, and neither on 2. A fresh paired bootstrap over the 53 missions gives **+2.16 percentage points, approximate 95% interval [−0.94, +6.24]**. Thus, the point estimate favors CMI, but the interval includes zero.

This additional interval uses 5,000 mission-cluster resamples, Python `random.Random(1)`, retaining all eligible variants of each sampled mission and computing the pooled paired difference. It is an exploratory audit calculation, not an additional preregistered test.

**Action:** describe the 60-second comparison as an observed advantage, and add its paired interval. Do not use it to claim that CMI reliably outperforms PH in plan finding. For the effect of increasing CMI's budget, use the same 477-instance subset: certification rises from **368/477 (77.1%) at 10 seconds to 456/477 (95.6%) at 60 seconds**. Comparing 81.0% on all FS with 95.6% on the subset also changes the cohort.

### 3. Moderate: “baselines cannot certify” omits the Level-0 exception

The saved records mark PH, LR and GR-c certified on 249 FS instances each, all at Level 0; GR has 40 such instances. An accepted Level-0 plan establishes the minimum without excluding a lower level. The scaling table already counts these outcomes: PH, LR and GR-c each show 13/40 certified, while the FS table uses “cannot certify.”

**Action:** consistently distinguish Level-0 verification from certificates requiring exclusion of lower levels. The substantive advantage is that CMI can certify positive intervention minima and no continuation. Also replace “false implied claims” for baseline plans with “plans above the reference minimum”: these baselines do not themselves assert optimality.

Evidence: [saved FS outcomes](<D:/Post-disaster Logistics/code/results/final_study_2026_10_17/analysis/arena_fs_10s.csv>), [saved scaling outcomes](<D:/Post-disaster Logistics/code/results/final_study_2026_10_17/analysis/arena_scaling_60s.csv>), and [report wording](<D:/Post-disaster Logistics/code/src/final_study/analysis.py:789>).

### 4. Moderate: zero post-plan delay does not mean zero proof cost

The reported “proof overhead” subtracts the time of the first plan at the certified level from the certificate time. Proof work completed before that plan is excluded from this difference, so its zero median and p90 do not measure total proof computation or the incremental cost of enabling proofs.

The more useful comparison is the reported 1.13× ratio of median CMI certificate time to median PH first-plan time on the same 1,122 instances. Keep its conditioning visible: CMI did not certify 273 of all 1,440 variants, and PH had no plan on 252. Successful-instance latency does not characterize the timeouts.

**Action:** call the zero-valued statistic “additional delay after the certified-level plan.” Use the paired PH comparison, coverage, ablations and CPU breakdown to discuss cost. Avoid interpreting 1.13× as a universal per-instance slowdown.

Evidence: [time comparison](<D:/Post-disaster Logistics/code/src/final_study/analysis.py:485>), [overhead calculation](<D:/Post-disaster Logistics/code/src/final_study/analysis.py:795>), and [cost interpretation](<D:/Post-disaster Logistics/code/docs/FINAL_STUDY_RESULTS_2026_10_18.md:132>).

### 5. Moderate: report operation overruns explicitly

The protocol permits the final operation to overrun but requires reporting it. Overruns are present in the CSV and summary data, but absent from the narrative report. Examples: maximum PH overrun is 7.125 seconds in FS at a nominal 60 seconds and 7.891 seconds in LS at 60 seconds. FS CMI's maximum overrun at 10 seconds is 0.938 seconds.

The checked CSVs contain no late CMI certificate in FS, LS, P1 or 60-second scaling, so this does not invalidate those certification rates. One LS GR first plan is timestamped after 10 seconds. Strict-budget recovery comparisons should exclude that event or explicitly identify the allowed-overrun convention.

**Action:** add per-arm overrun frequency and maximum, and make the event cutoff consistent between the final tables and anytime curves. This can be done from stored results.

## Claims supported by the current evidence

| Claim | Required evidence | Current evidence | Remaining work | Review risk |
|---|---|---|---|---|
| CMI certifies minimum intervention or infeasibility | Replayable evidence and no contradictions | 98.9% reference certification at 600 seconds; recorded replay success throughout | State the model and budget; do not equate reference performance with online performance | Low within the benchmark |
| CMI changes fewer UAVs than global replanning | Paired counts on common solved instances | CMI minus GR: −3.50 UAVs, 95% interval [−3.80, −3.21]; versus GR-c: −0.44 [−0.51, −0.37] | Preserve paired-success conditioning; level minimality does not certify minimum edit count | Low for these implementations |
| CMI beats PH in plan finding | Paired advantage at the stated budget | PH wins at 10 seconds; CMI's observed gain at 60 seconds has an interval crossing zero | Narrow the claim; add the 60-second interval | High if broad superiority is claimed |
| Underlying 10-second certification exceeds 80% | Lower confidence bound above 80% | 81.0%, interval [76.2, 85.7] | Keep “observed target met” separate from population evidence | High if described as established |
| Level 4 can be certified quickly and generally | Representative Level-4 support and adequate short-budget coverage | FS: 13 variants from 6 missions; selected LS: 5/60 certified at 10 seconds, 38/60 at 60 seconds | Present as the difficult class; retain LS selection qualification | High for broad real-time claims |
| Affected-fleet identification and reuse help | Controlled ablations | Certification drops 5.7 points without AF and 10.6 points without ER | Keep the paired intervals and budget attached | Low within FS |
| Larger missions are tractable | Scaling evidence under a fixed budget | 35/40 certified at 60 seconds; 38/40 at 300 seconds | Limit scope to the tested 24–48-task missions | Moderate for broader deployment claims |

The Level-2 mission-count target, Level-4 prevalence/support targets and P1 90% short-budget criterion were missed. These should remain visible. LS fills the intended class quotas, but its selection cannot repair population-frequency claims from FS.

The update-time result deserves emphasis: later updates increase both Level-0 outcomes and no-continuation outcomes. A small aggregate ordinal coefficient should not be paraphrased as “update time does not matter.” The current short report already notes this distributional change. The fitted proportional-odds model's convergence alone is not a check of that modeling assumption.

## Verification performed

- Recounted the exported FS, LS, P1 and scaling results and recomputed the main comparison denominators and timing cutoffs.
- Verified all **114 archived source-file SHA-256 hashes** against the run manifest. Of those files, only live `src/final_study/analysis.py` differs from the archived version.
- Compared the saved original and regenerated summary JSON: only the ordinal-regression and interaction sections differ.
- Validated run and record hashes for **7,666 saved label/arena records**, containing **20,655 arm results and 4,219 reference labels**. All referenced proof files exist; no recorded audit failures were found. This checks the bindings that exist; it does not independently establish that every possible planned unit was generated.
- Freshly replayed one saved FS reference result at each of Levels 0, 1, 2, 3, 4 and no continuation; all six passed. The samples were selected for low recorded runtime within each class.
- Freshly replayed the exclusion evidence for pooled LS instance `LS_L4_m6_0468`; it passed and established lower bound 4. Its saved pooled record reports an exact-checked Level-4 construction witness. The full pooled witness was not independently rechecked in this review.
- Ran the existing focused test for recoverability accounting, H3 pairing and regression interactions: **1 passed, 17 deselected**. The first invocation stopped during unrelated Dash plugin loading because `typing_extensions` was missing; the retry passed with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. No packages were changed. These checks used the current Python 3.13 environment; the original experiment manifest records Python 3.10.21.
- The review did not rerun the full experiment or freshly replay every proof. The reported all-result replay rate is the stored audit result, supported here by record validation and sampled fresh replay.

## Recommended result framing

> Under equal nominal CPU budgets, CMI certified 81.0% of FS variants within 10 seconds and 95.6% of the 60-second subset. It reduced the number of changed UAVs relative to global replanning. PH found minimum-level plans more frequently at 10 seconds; CMI's higher point estimate at 60 seconds was not statistically established in the paired audit. Level-4 certification remained the principal short-budget limitation.

First correct the reporting from the existing records. A full rerun is not justified by the issues found here. Additional experiments are needed only if the intended claim remains broader—for example, consistent superiority over PH or general real-time Level-4 performance.
