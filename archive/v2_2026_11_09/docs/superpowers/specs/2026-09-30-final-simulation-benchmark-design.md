# Final simulation benchmark for hierarchical UAV recovery

Date: 2026-09-30  
Status: Design recorded before implementation. Completed execution and evidence limits are reported in [the results report](../../FINAL_BENCHMARK_RESULTS_2026_09_30.md). This document preserves the design rationale; the executed counts and configurations are recorded separately.  
Target: The active September 30 manuscript, executed in resumable batches on the user's laptop.

## 1. Decision and intended evidence

Use one benchmark system with three complementary studies:

1. **Controlled cases:** establish the operational meaning and certificate requirements of every outcome, including genuine Level 4 and infeasibility.
2. **Boundary maps:** measure how forecast changes and mission margins move the boundary of local sufficiency.
3. **Randomized and scaled missions:** measure outcome frequencies, propagation, actual intervention, and the cost of finding and certifying repairs across independent missions.

The central response is the minimum sufficient intervention, together with its evidence. A usable repair, a certified minimum, and a proof of impossibility are distinct results.

The main allowance is **b = 1**, a benchmark policy parameter limiting partial reassignment to at most one additional, initially unaffected UAV. It is the smallest positive helper allowance, so it provides a simple partial-coordination setting and can separate partial from full release when more than one outside UAV remains. It is not a universal definition of hierarchical replanning, an empirically optimal allowance, or a guarantee that Levels 3 and 4 differ on every instance. The formulation admits any declared integer b >= 0. Fix b=1 for comparability throughout the main experiment; report b with every outcome and vary it only in a separately labeled supplementary sensitivity. Larger missions use bounded searches; unresolved outcomes remain in the results.

### Main-paper focus

Study 3 answers four questions:

1. How often is each intervention level required?
2. How different is propagation from actual plan change?
3. How many plans remain unchanged when a local repair suffices?
4. What computational work is required to obtain a repair and certify its minimum scope?

The main results use one frozen primary population and one primary representation. Library/geometry sensitivity, execution-state and commitment sensitivity, allowance sensitivity, structural-collapse analysis, minimum-participation optimization and timing repeats belong in the supplement. They do not each require a main-paper result or a new primary experimental axis. Correctness checks for commitments, shared constraints and evidence labels remain mandatory.

Detected experiment axes: optimization; baseline, robustness, complexity, statistical and reproducibility evidence; risks of overclaiming and missing condition tests; planning stage.  
Paper-reading axes: replication; full active manuscript and relevant supplement; algorithmic formulation; equations, evidence and limitations; deep review.

### Why this design

Three possible designs were considered:

| Approach | What it establishes | Main limitation |
|---|---|---|
| Six examples and small exact sweeps | Mechanisms and trustworthy labels | Does not establish typical behavior or scaling |
| Large numerical simulation alone | Many candidate repairs and timings | Cannot reliably establish minimum levels or impossibility |
| **Exact controlled/core experiments plus bounded scaled experiments** | Mechanisms, empirical regions, population estimates and computational limits | Requires explicit uncertainty and representation labels |

Use the third approach. It fits the contribution and a laptop without promising exhaustive certification at fleet scale.

## 2. Authoritative formulation and current implementation gap

The active formulation is in `manuscript/sections/hierarchical_decision.tex`, `escalation_properties.tex`, `system_model.tex`, and `recovery_details.tex`. The alignment record explicitly says that the existing production simulator and saved September 28 benchmark implement the earlier hierarchy.

| Contract | Active manuscript | Existing implementation to change |
|---|---|---|
| Level 1 | Paths of initially affected UAVs only | `release_sets` currently releases fleet-wide paths |
| Level 2 | Sequences, paths and loading/delivery quantity decisions of initially affected UAVs; task-to-UAV assignments fixed | Currently releases fleet-wide sequences and loading/delivery quantities |
| Level 3 | Union of all patches containing U0 and at most b additional UAVs | Currently uses a task coupling closure to release assignments |
| Shared constraints | Enforced at patch boundaries with outside plans fixed | Coupling reachability must cease to define permission to change the fleet |
| Forecast | Wind, flight admissibility, explicit retained tail estimates and missing coverage | Current wind-only, full-coverage schema needs an extension |
| Evidence | Witnesses, exclusions and unresolved outcomes under the new scopes | Existing machinery is useful, but saved certificates do not transfer to new scopes |

Do not combine old and new outcomes in a paper table. Freeze a new formulation identifier and new result directory. Preserve existing fixtures and reports as historical evidence.

**Level 2 terminology.** The component L contains loading amounts y and delivery amounts x. Use **loading/delivery quantity decisions** in prose, legends and tables. Level 2 may change how much the same responsible UAV loads or delivers at each visit, its visit order and its depot sorties. It cannot move a task's responsibility to another UAV. Task reassignment first becomes permitted at Level 3, within an eligible patch. Existing internal field names may retain `L` or legacy quantity names, but their displayed meaning must be explicit.

Source fingerprints at design time (SHA-256):

| Source section | Hash |
|---|---|
| hierarchical_decision.tex | `03B0188E36CED0A2A7808D793C62F8E2ABCEB0CF63B0C6F53892E695F3598CE0` |
| escalation_properties.tex | `B6F47C3D5285C8EC36D3DE17ED8312D24F44A7960B53AD1C94239D57E8F08EE0` |
| system_model.tex | `837125A123DF4B6342C8FAD681CC55EB0A5BD13ED03763B04768E9D5D5CCCC7E` |
| recovery_details.tex | `20FB6705E114752E3F47CB088C53B4DA272D39F6BF5D7BE53C3E38108B37F617` |

### Invariants for every admitted instance

- Validate the incumbent under the previous forecast, from exactly the same observed state and commitments used after the update. Exact reference instances require an exact previous-feasibility check.
- Change only the declared forecast atoms within a previous/updated pair. A margin experiment creates a new reference mission; it does not change margins between the pair's two projections.
- Derive U0 from directed dependencies of the fixed incumbent evaluations, using the union of previous and updated query supports. A shared constraint's incident UAVs are not automatically affected UAVs; the separate constraint-incidence graph must not become an undirected propagation path. Numerical reporting tolerances do not prune U0. Store an auditable root-to-record dependency trace for each included UAV and log both |U0| and |U0|/M in every experiment.
- Freeze U0, b, commitments, slot bounds, path libraries and the operation protocol before comparing levels or methods for that update.
- At Level 3, preserve every outside UAV's sequence, paths and loading/delivery quantities, and all assignments excluded by V(U). Include previously unassigned optional tasks according to the manuscript's structural rules.
- Keep stock, bay occupancy, deadlines, payload, battery, terminal return and reserve constraints in the complete candidate check.
- A reserve path is an auxiliary feasibility witness, not a plan coordinate. A different reserve witness may establish Level 0.
- Keep the absence of a waiting decision and implicit depot queues. Retain repeated visits, continuous divisible quantities, returned payload and intermediate replenishment.
- Never convert missing forecast coverage, arithmetic uncertainty, an incomplete patch search or a timeout into infeasibility.

## 3. Questions, claims and evidence

| Claim or question | Required evidence | Present evidence | New experiment | Review risk if omitted |
|---|---|---|---|---|
| Each intervention level has a distinct meaning | Feasible witness at each finite level and exclusions below it | Revised manuscript has an analytic 0/3/4 cascade | Study 1, all six outcomes | Critical |
| Local repair ceases to suffice under identifiable conditions | Certified membership/nonmembership in D<=2, and recovery at larger levels | Mathematical definitions and cascade thresholds | Study 2, coupled factor maps | Critical |
| Global release sometimes is necessary | F3 empty over every eligible patch, F4 nonempty | Analytic three-UAV cascade | Study 1 plus randomized occurrences or bounds | Critical |
| Propagation and coupling do not imply necessary intervention | Closure, affected UAVs, actual changes and participation evidence on the same inputs | Formulation distinguishes these objects | Studies 2–3, paired records | Major |
| Findings extend beyond examples | Prespecified independent mission generator and retained unsuccessful searches | Older pilot uses a different hierarchy and constructed families | Study 3 | Critical |
| Certification has a measurable computational cost | Separate time to witness and time to minimum proof | Small earlier reference search | Studies 2–3, equal-budget comparisons | Major |
| Level 3 can coincide with Level 4 | Verified equality of release spaces, with b and commitments recorded | Sufficient equality condition in the manuscript | Supplementary structural-collapse and allowance analysis | Major |
| Smaller intervention is operationally useful | Preserved plans, changed assignments and additional participants; certified minima where available | No new-hierarchy population evidence | Study 3 locality analysis | Major |

These experiments support synthetic, forecast-conditioned conclusions. Field performance, forecast prediction accuracy, recursive feasibility and real-time operation are outside this benchmark's claims.

## 4. What the reported level means

Let R denote the declared finite nominal and reserve-path libraries. The general computational response is **k_R^F**, the represented minimum. The manuscript establishes

    k^F <= k_R^F.

A feasible represented witness is also a witness for the manuscript domain. An exclusion of a finite library generally does not exclude arbitrary admissible paths. Labels for Study 1 may be upgraded to k^F when an independent physical argument excludes the unrestricted smaller spaces.

Every result stores lower and upper represented bounds, witness evidence, excluded levels, and unresolved reasons. Report these categories:

| Outcome | Required evidence |
|---|---|
| Certified minimum k_R^F = k | Validated exact witness and exclusion of every lower level |
| Witness with a gap | Exact feasible upper bound; some smaller level remains unresolved |
| No represented continuation | Sound complete exclusion of represented Level 4 |
| Numerical witness | Original evaluator accepts the candidate, but exact/validated arithmetic has not certified it |
| Unresolved without a witness | Incomplete search, coverage, arithmetic or other unresolved evidence |

Store `no_represented_continuation` explicitly; do not overload JSON null with infinity. A numerical bound is stored separately and never mixed into certified bounds. Conflicting witness/exclusion evidence is an audit failure.

### Required evidence-domain contract

Every saved record must explicitly contain `evidence_domain` (`represented` or `full_domain`), the represented library hash when applicable, `evidence_status`, and the witness/exclusion references supporting each bound. A full-domain claim additionally records the independently verified justification for lifting it beyond R. Keep represented and full-domain evidence as separate records when both exist. In particular:

| Displayed claim | Allowed source of evidence |
|---|---|
| Represented minimum k_R^F=k | Represented witness and complete exclusions below k in the same R |
| Full-domain minimum k^F=k | Validated feasible witness and sound full-domain exclusions below k; no lower exclusion is needed for k=0 |
| No represented continuation, k_R^F=infinity | Complete exclusion of represented Level 4 only |
| Full-domain impossibility, k^F=infinity | Independent physical or other verified exclusion covering the unrestricted Level-4 domain |
| Unresolved | Missing coverage, incomplete search, unsupported arithmetic or another undecided obligation; retain any valid bounds and their domains |

The serializer, validator and figure/table builder must reject a full-domain exclusion backed only by a finite-library search. Every table column, map legend, axis label or caption must identify its evidence domain, and unresolved samples must have an explicit category. Do not merge the two infinity categories or silently relabel represented Level 4 as necessary in the unrestricted model. Add rejection checks for these exact labeling errors before publishing results. A represented exclusion and a full-domain unresolved status can coexist for the same update.

For population frequencies, let S_j be the set of levels still compatible with result j, including infinity when appropriate. For outcome k, report the finite-sample identification interval

    count(S_j = {k}) / n <= frequency(k) <= count(k in S_j) / n.

For a numerical-only result without certified exclusions, S_j remains the full outcome set. Show sampling uncertainty separately from this identification uncertainty. Never calculate the headline distribution using only solved cases.

## 5. Study 1 — Controlled operational mechanisms

### 5.1 Six explicit primary instances

All cases below use consistent normalized units, epoch zero, T = 20, empty mass = commodity unit mass = energy coefficient = 1, battery capacity/initial charge = 100, reserve = 1, payload capacity = 2, and residual stock equal to total mandatory demand. All demand is mandatory, all future coordinates are mutable, and each UAV has three stop slots. Service/preparation duration and ground energy are zero in these analytic primary examples. Flights remain admissible. The previous wind is zero. Take b = 1 and validate the previous incumbent separately.

Unless stated otherwise, use the region [-2,3] x [-1,3], depot (0,0), eastern wind (-alpha,0) on x > 0, and zero wind on x <= 0, throughout the horizon. This is a proper local spatial update. Idle helper UAVs retain zero-slot depot routes.

| ID | Expected full-domain k^F | Instance and changed plan | Certificate mechanism |
|---|---:|---|---|
| C0 | 0 | Manuscript cascade at alpha = 1/20; keep all routes | All incumbent predicates remain feasible |
| C1 | 1 | One task (2,0), deadline 3/4; three UAVs of speed 5, only UAV 1 assigned; use the bypass below | Fixed incumbent delivery is late; path-only witness is feasible |
| C2 | 2 | UAV 1 serves B=(1,0), then A=(1/2,0); deadlines B=17/10, A=8/5; all three speeds 1; alpha=1/5; change order to A,B | Any path retaining B,A misses A; new sequence meets both deadlines |
| C3 | 3 | Manuscript cascade at alpha = 3/10; exchange C and E between UAVs 1 and 2 | UAV 1 cannot serve C by its deadline under any path/sequence; one helper suffices |
| C4 | 4 | Manuscript cascade at alpha = 4/5; UAV 3 takes C, UAV 2 visits E,D, UAV 1 stays at depot | Every patch with at most one helper fails; both outside plans must change |
| Cinf | infinity | One task C=(1,0), deadline 11/10; three UAVs all of speed 1; alpha=1/5 | Every UAV needs at least 5/4 to reach C; no allowed path or reassignment can satisfy its deadline |

**Cascade data for C0/C3/C4.** Speeds are (1,3/2,5/2). Incumbent assignments are C to UAV 1, E to UAV 2 and D to UAV 3, with direct return sorties. Task positions/deadlines are C: (1,0), 11/10; E: (-1/5,0), 3/10; D: (-1,0), 4/5. Each task requires one unit. These are the active manuscript's construction.

**C1 geometry.** Only the lower eastern region x >= 0, y <= 1/4 receives wind (-3,0); the western and upper cells remain calm. Declare the lower eastern cell the owner on its shared vertical edge, and use one consistent edge-ownership rule in both evaluators. The incumbent flies directly to (2,0), delivers one unit, and returns. Its previous delivery time is 2/5; the updated time is 1 > 3/4. The outbound bypass is

    (0,0) -> (0,1/2) -> (2,1/2) -> (2,0).

Crosswind ground speed on the two exposed vertical quarters is sqrt(25-9)=4. The bypass delivery time is

    (1/4)/4 + (1/4)/5 + 2/5 + (1/4)/5 + (1/4)/4 = 5/8 < 3/4.

Return directly in 1/4 time. Flight energy is 15/2 in total for that UAV, well below its capacity less reserve. Assignment, stop order and loading/delivery quantities stay fixed. A nominal deadline violation rules out Level 0 independently of alternative reserve paths.

**C2 unrestricted exclusion.** The previous B,A deliveries occur at 1 and 3/2. After the update, any route with the same order needs at least

    1/(1-1/5) + (1/2)/(1+1/5) = 5/3 > 8/5

to reach A. The displacement bounds apply to detours as well as direct paths. Thus Level 1 is excluded. Ordering A,B gives delivery times 5/8 and 5/4, and return time 25/12. Flight energy is 95/24. Direct reserve returns at both service states are feasible.

**C3/C4 exclusion.** The active manuscript proves the thresholds 1/11 and 13/22 using physical arrival bounds and exclusion of every one-helper patch. Reproduce those arguments and all patches in the new simulator. At alpha=3/10, the exchange delivers E at 1/5 and C at 5/6. At alpha=4/5, the global witness delivers E at 2/15, D at 2/3 and C at 10/17; it changes both initially unaffected UAV plans.

**Cinf exclusion.** All UAVs start at the depot. Each must gain one unit of eastern displacement at speed at most 4/5. The lower bound 5/4 exceeds 11/10, whereas the previous incumbent delivers at time 1. This establishes full-domain impossibility, independently of the finite library.

The delivery/return/energy fractions above were checked with rational arithmetic during design. They are not production-simulator results. Implemented fixtures must still pass the complete independent mission and scope validators.

### 5.2 Companions and boundary checks

- Add a companion for each primary case with preparation and service durations 1/100 and service energy 1/100. Preserve the labels only after validation. These selected points have positive timing margins; the analytic zero-duration threshold formulas do not transfer to these companions.
- Check alpha = a-epsilon, a, a+epsilon for a in {1/11,13/22}, epsilon = 1/2200, on the original cascade. Check equality exactly.
- Use eight guard families: irrelevant update; structural reachability without a numerical change; alternate reserve witness at Level 0; nearest helper fails but another eligible helper works; shared stock/bay conflict against an unchanged outside plan; newly inadmissible nominal/reserve passages; absent versus explicitly retained forecast tail; and a two-UAV b=1 structural collapse control.
- A guard family tests a contract, so it need not have a target escalation label. Missing coverage must retain its unresolved status, with any independently established violations recorded separately.

### 5.3 Required outputs

One compact six-case table and route/timeline panels. For each case show U0, eligible patches, witness, changed assignments/UAVs/coordinates, binding constraints, lower-level exclusion reasons, certificate domain and audit result. For C4, show all eligible partial patches, not only the successful global route. These constructed cases establish mechanisms, not population frequencies.

## 6. Study 2 — Escalation boundaries and mission margins

### 6.1 What is held fixed

The reference datum z includes observed state, incumbent, requirements, commitments, previous forecast and b. Wind severity and duration vary the disturbance delta within z. Changing deadline or battery slack creates another z. Label plots accordingly:

- **Disturbance-region maps:** severity versus duration for a fixed mission and margin setting.
- **Margin maps:** deadline versus battery slack at a specified disturbance, comparing a family of reference missions.

Do not label a sweep across different deadlines as one D<=k(z). All paired projections within a point still share identical non-forecast data.

### 6.2 Pilot-adjustable grid

Use three independent mechanism templates: the bypass, the resequencing case and the reassignment cascade. Each template has its own fixed incumbent and libraries.

One candidate allocation for each template is:

1. Two deadline-margin settings and two battery-margin settings give four reference missions.
2. For each reference mission, evaluate nine severities and six durations: 54 points.
3. At one prespecified nonzero disturbance, evaluate a 9 x 9 deadline/battery margin map.

This candidate totals 891 labeled points before refinement. That is a planning estimate, not a required sample count. Select the initial grid density and refinement budget after the development pilot, then freeze the grid and adaptive selection rule. Prioritize sufficient resolution near observed transitions, explicit fixed/reference quantities and trustworthy labels. Reduce grid density before weakening the certification checks. Identical serialized inputs are solved once and linked to every corresponding panel; they are not independent observations.

Parameter definitions:

| Factor | Definition and initial values |
|---|---|
| Severity r | Updated wind magnitude divided by the minimum airspeed; use r(q)=2q/(1+q^2), q=j/16, j=0,...,8. This spans 0 to 0.8 and preserves rational crosswind speeds for the common-speed rectilinear template. Label axes by r. |
| Duration | d/tau* in {0,1/4,1/2,1,2,4}, where tau* is the maximum previous first-positive-delivery time of active UAVs. All chosen templates have 4 tau* <= T. |
| Deadline margin | Write the template's previous completion time as c_i^- and original deadline as d_i^ref. Use d_i(lambda_D)=c_i^-+lambda_D(d_i^ref-c_i^-), initially lambda_D in {1,2}. The margin map uses 1+j/8, j=0,...,8. |
| Battery margin | Compute the least full-charge capacity B_req,u^- needed by the fixed previous routes and chosen reserve witnesses. Set B_u=B_req,u^-+sigma_B E*,u, where E*,u is previous maximum sortie consumption (a declared positive reference for idle UAVs). Use sigma_B in {1/20,1/2}; the margin map uses 1/20+9j/160, j=0,...,8. |
| Margin-map disturbance | q=5/16, d/tau*=2, with the template's fixed adverse direction and spatial support. |

Battery variants change capacity and the corresponding observed initial charge consistently, and are distinct reference missions. Neither changes inside a paired wind evaluation. All primary map templates depart from the depot. Revalidate the previous mission at every point, including deadline <= T and reserve constraints.

Build one master time partition per template containing the requested duration endpoints and both rounds of possible duration refinements before evaluation. Nominal and reserve libraries remain fixed. A refinement uses rational q midpoints, rather than arithmetic midpoints of r, when exact crosswind arithmetic is required.

### 6.3 Refinement and interpretation

- Start with the coarse grids. Mark feasible-at-level, excluded-at-level and unresolved evidence separately.
- Freeze a bounded refinement allocation after the pilot; the initial planning allowance is 144 extra evaluations and two rounds. Allocate it in deterministic round-robin order to adjacent points with different certified labels. Spend a declared continuation budget on unknown points when useful, and leave them unresolved if that budget is exhausted. Unknowns are never evidence of a boundary.
- Keep unresolved points hatched and display the sampled resolution. Do not interpolate categorical level labels into unmeasured points or paint a smooth contour as a certified boundary. Report adjacent certified samples as transition brackets; only an independent analytic argument can certify the intervening region.
- Report transitions where F2 becomes empty while F3 or F4 remains feasible. These are the observed boundaries where paths, sequences and sorties on affected UAVs cease to suffice.
- Also distinguish transition to no represented continuation and loss of forecast coverage.
- Record which exclusion reasons recur near a transition: deadlines, energy/reserve, payload, stock, bay occupancy, commitment or flight admissibility. Do not assign a unique causal explanation when multiple constraints jointly exclude the space.

Pointwise D<=0 through D<=4 must be nested. Increasing generic wind severity or duration need not increase k: direction, time-bin changes and the affected set can change the result. Do not apply bisection or smooth monotone contours without a proof for the chosen family.

Use the original cascade, with battery capacity 100 and its original deadlines, as an analytic threshold check. Also assess its sufficient retention bound: on alpha in [0,1/4], the C deadline residual has slope at most 16/9 and slack 1/10, giving the sufficient radius 9/160. Other incumbent resource/return constraints remain safely feasible throughout that neighborhood. Compare this conservative radius with the exact retention boundary 1/11. Recompute all required residual bounds before applying this analysis to a different margin setting. Report coverage/conservatism, not a fitted sensitivity estimate described as a theorem.

### 6.4 Bounded robustness panels

Use a fixed, seed-selected subset of 24 map points for alternative cardinal wind directions, spatial footprints and b in {0,1,2}. Include the admissibility and forecast-coverage guard families from Study 1. These are sensitivity panels with their own reference data; they do not alter the primary grids or their denominators.

## 7. Study 3 — Randomized missions and scaling

### 7.1 Development-only pilot and freeze

Run a small pilot with disjoint development seeds before freezing the randomized generator. The initial workload suggestion is 24 update cases. Inspect evidence-qualified outcome proportions, the rate of actual forecast-query exposure, the distributions of |U0| and |U0|/M, and arithmetic/search/audit costs. Inspect the two exposure strata separately.

Investigate distributions such as roughly 95% certified Level 0, almost no exposed missions, almost all updates certified infeasible, or U0 almost always equal to the full fleet. These are diagnostic flags, not quotas that the final distribution must avoid. A predominantly unresolved pilot does not establish predominant infeasibility. Determine whether a flag reflects the intended population, uninformative forecast placement, unrealistic margins, or a dependency-construction error.

For every included UAV, retain a trace from a changed forecast root to its own nominal or diagnostic reserve record. Distinguish direct queries, downstream entering-state effects and conservative support for unavailable suffixes. Check record ownership against the manuscript's N_u definition. A shared stock or bay vertex must not label all incident UAVs as affected merely because they contribute to that constraint. Audit agreement of fixed-incumbent records outside the closure between the paired evaluations.

U0 is a conservative set of potential dependencies; it need not equal the set of UAVs with numerically changed outputs. Sound structural inclusions remain even when their numerical effects cancel. A genuinely broad U0 is a result to report. Never impose a size cap, drop guard dependencies, or prune by numerical tolerance to make locality appear stronger.

Before freezing, generator changes may address a documented modeling or coverage problem exposed by the pilot. Save the reason and pilot versions, and use fresh held-out seeds for the main study. Do not target a balanced histogram or require every level to occur in the random sample; Study 1 establishes distinct mechanisms. Freeze the generator, scenario counts, representations, U0 construction, sensitivity subsets and search/refinement budgets together. After freezing, retain all admitted instances and do not tune the generator to improve observed frequencies. A necessary correctness fix requires a versioned rerun and audit.

### 7.2 Candidate size and replication plan

The following is a planning allocation, subject to the pilot. Choose the final number of missions for the four main questions and laptop certification coverage; supplementary analyses do not require multiplying the primary sample into a factorial experiment.

| Panel | Sizes (N tasks, M UAVs) | Spatial families | Independent seeds per size/family | Base missions | Updates per mission |
|---|---|---:|---:|---:|---:|
| Small certification core | (3,3), (4,3), (6,4) | 2 | 10 | 60 | 2 |
| Scaled benchmark | N in {6,12,24} crossed with M in {3,4,6} | 2 | 10 | 180 | 2 |
| **Total** | | | | **240** | **480 update cases** |

Core and scaled seeds are disjoint, including overlapping sizes. The two updates are separate counterfactual updates of the same feasible incumbent, not a rolling mission simulation. The base mission is the independent sampling unit. Per-size estimates will be less precise than aggregate estimates and must show their intervals. Spatial, assignment and resource variation characterize the declared population; they are not separate main-paper competitions. Report detailed subgroup analyses in the supplement.

### 7.3 Primary generator

The exact-compatible core uses rational task coordinates in two dimensions and finite rectilinear nominal/return libraries. Use a 0.1-spaced grid in [-1,1]^2 with depot (0,0). Sample distinct non-depot sites using two declared layouts:

- Uniform sites sampled without replacement.
- Two spatial clusters: sample two non-depot grid centers at least 3/4 distance apart, then sample sites without replacement with rational weight (1+100 min_c ||p-c||^2)^(-2). Save the centers and sampling order.

Assign tasks using an equally weighted seeded mixture of two rules: sort tasks by polar angle around the depot and divide contiguous groups as evenly as possible among UAVs, or randomly permute tasks and assign them round-robin. Keep the realized policy identifier. Within each assigned group, use nearest-next-site order under previous travel time, breaking ties by task ID, and return to the depot. Build the incumbent using previous information only, before sampling its update. Demand, vehicle capacity, battery margin, task deadline margins, resource headroom and commitments vary independently where feasibility permits.

Use one common rational airspeed within each exact-compatible 2D mission. Vary payload capacities and energy coefficients across UAVs. Heterogeneous airspeeds are established by the analytic cascade and tested separately where arithmetic supports them. This restriction must be stated in the paper.

The reason for this choice is technical: rational coordinates alone do not make Euclidean lengths or crosswind square roots rational. The existing exact integrator rejects unsupported irrational expressions. For axis-aligned paths and cardinal wind magnitude v r(q), the orthogonal speed is v(1-q^2)/(1+q^2), which is rational. Use calm previous wind in the primary randomized population; updated entries are drawn from the compatible family. Any nonzero previous-wind sensitivity must also preserve the declared arithmetic requirements or retain an unresolved/numerical label. Do not certify a rounded surrogate as the original model.

Generator defaults to freeze after development-only calibration:

| Ingredient | Proposed distribution or rule |
|---|---|
| Mandatory demand | Rational quantities from {1/2,1,3/2}; full demand mandatory in the primary population |
| Vehicle constants | Common airspeed v=1, empty mass and commodity mass 1, reserve 1; each vehicle's energy coefficient sampled from {4/5,1,6/5}. All units are synthetic and consistent. |
| Deadline slack | Task-specific previous completion plus a sampled margin; tight/moderate/loose regime weights 1/3 each, with normalized increments {1/10,1/4,1/2} times tau*, the maximum previous first-positive-delivery time |
| Battery slack | Relative to previous feasible capacity requirement, sampled from {1/20,1/5,1/2} |
| Payload headroom | Previous maximum required payload multiplied by a factor in {1,5/4,3/2}; use capacity 2 for idle UAVs |
| Shared stock | Previous total planned loading multiplied by a factor in {1,5/4,3/2}; history and carried load remain consistent |
| Ground operations | Preparation and service durations 1/100, service energy 1/100; no preparation energy beyond the prescribed full-charge reset |
| Horizon | Twice the maximum previous complete route duration, including ground operations; check every generated deadline against it |
| Commitments | No additional future commitments in the primary randomized population. Commitment preservation remains mandatory in Study 1; randomized commitment variation is a supplementary sensitivity. |
| Depot bays | Unlimited in the primary all-at-depot population; finite-bay conflicts are tested using feasible staggered execution-state fixtures, because simultaneous positive-duration departures cannot be admitted with fewer bays than departures |
| Slot bound | 2 ceil(N/M)+3 for each UAV, with the actual incumbent validated against it; fixed across levels and methods |
| Wind partition | Fixed 4 x 4 spatial cells and eight time bins over the mission horizon |
| Forecast support | One or four spatial cells, and one, two or four contiguous bins; always a proper local support |
| Wind direction/magnitude | Cardinal direction sampled uniformly; nonzero q from {1/16,...,8/16}; entry values must actually change |
| Update A | Support sampled independently of incumbent route exposure |
| Update B | Support anchored to one sampled incumbent flight query; remaining entries sampled by the same declared rules |
| Allowance | b=1, the declared one-helper benchmark policy, fixed for all primary comparisons |

The population is deliberately synthetic and stratified. Report both exposure strata separately, plus their prespecified equally weighted mixture. Never present that mixture as an estimated real-world weather frequency.

For each base mission, validate a complete feasible previous continuation and its reserve witnesses. Keep generation failures and rejection reasons. Do not reject a mission because its update yields retention, infeasibility, a difficult proof or an unwanted level. Do not tune post-update outcomes to make the histogram balanced.

The primary population starts from settled depot states to keep construction auditable. Broader execution states belong to a supplementary sensitivity. Neither that sensitivity nor minimum-participation optimization is required on every primary instance.

### 7.4 Supplementary sensitivities

Freeze the selected supplementary subsets after the pilot, before observing main-study outcomes. The earlier suggestion of 30 updates per sensitivity is a planning allowance, not a requirement. Run only the supplementary analyses needed to support the stated claims, and identify omitted analyses explicitly. Preserve the structural-collapse summary and allowance check as the supplementary answer to the original Level-3/4 question.

- Primary libraries contain both horizontal-then-vertical and vertical-then-horizontal endpoint paths, with geometric duplicates removed, and every incumbent/committed path and supplied previous reserve witness appended.
- This is a declared restriction: two simple rectilinear paths do not exhaust the manuscript's geometry or all useful loops.
- **Library sensitivity:** on the selected subset, enlarge the nominal and return libraries with two deterministic bypass alternatives and a bounded out-and-back option. Fix all other hierarchy data. An exactly resolved k_R^F must not increase. Unresolved bounds need not become tighter under the same finite search budget.
- **Broader geometry:** on the selected subset, test unconstrained rational 2D site locations, direct/waypoint paths, and wind vectors outside the rational-speed family. Save numerical feasibility and work separately unless the available backend certifies them. Keep exact-compatible geometry for primary certification and broader geometry as numerical sensitivity. A new general continuous-geometry exact backend is outside the required implementation.
- **Execution states and commitments:** derive consistent observed positions, onboard payload, residual operations and leading commitments from feasible previous execution records. Stagger prior depot occupancy before imposing a finite bay count. A commitment variant may freeze the first destination/path and its loading/delivery quantities on ceil(M/4) selected active UAVs, capped by the active count. Derive all values from the valid incumbent.
- **Optional service:** where useful for a stated claim, set mandatory/demand ratio to 1/2 on a selected small-core subset and validate the previous premise again. Keep its denominator separate from the primary full-demand population.
- **Allowance, necessary participation and timing:** use the bounded supplementary analyses below. Their tables remain outside the main four-question narrative.

## 8. Four main questions and supplementary analyses

### 8.1 Main question 1 — How often is each level required?

Show represented level frequencies by mission size and the declared aggregate mixture, with compatible frequency intervals and unresolved/numerical-only fractions. Label infinity as **no represented continuation**. Place full-domain minima/impossibility in separately labeled results. Exposure-stratum checks remain visible in the reporting context; detailed spatial, assignment and margin subgroup tables belong in the supplement.

### 8.2 Main question 2 — How different is propagation from actual change?

Treat **|U0| and |U0|/M as main diagnostics**, logged for every experiment including retention, infeasibility and unresolved outcomes. Compare their distributions with the actually changed UAV set Delta_U on updates with a validated witness, and state that witness denominator. Show U0 intersect Delta_U, U0 minus Delta_U and Delta_U minus U0: a reassignment can involve initially unaffected UAVs, so Delta_U need not be a subset of U0.

Also save changed forecast atoms, directly exposed records, downstream reachable records, all reachable operational vertices and affected tasks. Exclude isolated changed forecast roots from the operational-closure count. Normalize DAG counts by the corresponding eligible record count and state the DAG version, because raw node counts depend on representation. Keep detailed node-level breakdowns in the supplement.

The constraint-incidence closure is a separate diagnostic. It must not overwrite U0 or define the Level-3 patch. If U0 contains most of the fleet, report that the UAV restriction at Levels 1–2 offers limited locality and that Level 3 may equal full release. Do not attribute small returned changes to a restrictive local mask when the mask already permits almost the whole fleet. Cases with fleet-wide incidence connectivity but a small U0/repair illustrate the difference between coupling and propagation.

### 8.3 Main question 3 — How many plans does locality preserve?

For each returned plan, record:

- Changed assignments and changed coordinates for sequences, paths and loading/delivery quantities separately.
- C_U = number of UAVs whose sequence, path or loading/delivery quantity plan changes.
- m(Pi) = number of those changed UAVs outside U0.
- Preserved fraction 1-C_U/M.
- Released coordinates, actual changed coordinates and the selected patch U, as different fields.

Use canonical paths, canonical padding and exact quantities for certified equality checks. Reporting tolerances may describe numerical witnesses separately. Changing an auxiliary reserve witness does not count as intervention.

Report local sufficiency among invalidated, recoverable updates, using certified k_R^F in {1,2,3} and retaining uncertainty in the conditioning denominator. Pair this with the achieved preserved fraction 1-C_U/M. Show the continuous preservation distribution; an optional descriptive materiality threshold is at least one untouched UAV and at least 25% of the fleet untouched, frozen before the run. For partial versus global distinctions, identify cases with strict X3 subset X4. These are sufficiency and achieved-preservation results; they do not establish a minimum changed set or a causal improvement over G.

### 8.4 Main question 4 — What does certification cost?

Record preprocessing/library time, diagnostic time, time to first validated witness, time to certified minimum or exclusion, independent proof-audit time, total wall time, CPU time and peak memory. Also record unique patches considered/excluded, unique route skeletons, branch attempts, LP proposals, exact checks, pruning reasons and cache hits. Deduplicated work is counted once.

Keep timeouts as censored runs in completion curves. Show the fraction with a witness and the fraction with a certified minimum as functions of budget. Means over completed runs alone do not answer the runtime question.

Track exclusion work performed both before and after the first witness. A zero difference between time to witness and time to certificate does not mean certification was free: smaller levels may already have been excluded before the witness was found. Conversely, post-witness work may include finding a lower-level witness as well as checking exclusions. Use phase/work records to interpret these timings, without claiming an exact causal decomposition from H-minus-G elapsed time.

### 8.5 Supplement — How often Level 3 equals Level 4

Structural equality means X3 = X4 in the stated domain, independently of feasibility. Under the participation characterization, it holds exactly when

    max over Pi in Y of m(Pi) <= b.

The readily checked sufficient condition is b >= M-|U0|. Commitments can make equality occur earlier. Exhaustive structural analysis on the tiny core establishes equality only in its declared representation R. A full-domain equality label requires a structural argument valid throughout Y, such as the sufficient condition above. At scale, use sound equality certificates and report equality as unknown where no decision is established. A structurally valid plan with m(Pi)>b disproves equality, even if that plan is mission-infeasible. Distinguish full-domain equality from equality established only in R.

Report equality frequency, unknown frequency and the sufficient-condition subcount separately in the supplement, retaining the per-update fields in every primary record. Equal feasible outcomes or the same returned witness do not prove equality of spaces. The frequency of global necessity **within R** is a separate quantity: certified k_R^F=4. Full-domain global necessity requires full-domain lower exclusions.

### 8.6 Supplement — Minimum necessary participation

On a prespecified small-core subset, determine m_R* = min over F4^R of m(Pi), using certified cardinality feasibility queries. These auxiliary queries do not change the primary b=1 hierarchy. Validate F3^R nonempty iff m_R*<=b. Report intervals when these queries remain unresolved. Use the unrestricted m* label only for examples with an independent full-domain proof. This supplementary optimization is not required on every randomized mission.

Do not call the changed set of the first feasible witness the minimum changed set. If a claim about minimum total changed UAVs is needed, separately solve min C_U over the declared represented feasible set on this subset and retain its certificate. Minimizing k does not imply minimizing C_U, changed coordinates, energy or duration.

## 9. Computational consequences of seeking minimum intervention

H and G answer partly different questions. G seeks a feasible recovery; H seeks a recovery and, when enough exclusions are available, a minimum-scope certificate. The comparison explains the computational consequences of requesting stronger intervention evidence. It is not the main scientific claim of algorithm superiority.

### Evidence targets

**H — Hierarchical search:** common incumbent screening, then Levels 1,2,3,4; Level 3 covers the entire eligible patch family, with duplicate work shared. A lower-level timeout may be followed by a larger-level search, but the output retains the unresolved minimum.

**G — Immediate full release:** the same incumbent screen, then Level 4 using the same feasibility engine. Evaluate the smallest scope containing its witness afterward. That membership is an upper bound, not a proof that smaller scopes are infeasible. Full release does not force every UAV to change.

Run H on the primary population. Use a prespecified stratified subset for paired G runs supporting the certification-cost question; freeze that subset after the pilot and select it independently of H's outcomes. Report its size and denominator. A larger H/G sweep can be supplementary if needed.

Report time to a validated witness for both methods against the same target. Separately report H's time/work to a certified minimum, including unresolved cases and independent replay cost. Record any certificate G happens to establish, but label minimum certification as not requested when G does not perform that task. Do not present missing, unrequested G certificates as algorithm failures, or rank G's witness time against H's minimum-certificate time as if they were identical tasks.

Hold inputs, libraries/order, commitments, arithmetic, LP settings, preprocessing access, total time/work/memory limits and any common initial witness construction equal. Do not give H a new total budget at each level or patch. Any strategy-specific prioritization is logged as part of the method.

Timed H/G calls on the paired subset do not exchange witnesses, exclusions or search caches. After they finish, an offline reference record may combine independently verified evidence from available methods and the reference extension. Keep that pooled label distinct from what each method certified within its own budget.

The scientific interpretation is the work and evidence associated with recovery and minimum intervention. Do not prespecify that H must be faster, find more repairs, or change fewer UAVs than G.

### Supplementary comparisons

- Derive the path/sequence-only policy's outcomes from the H prefix through Level 2. Do not pay for a redundant complete run.
- On a prespecified subset, compare complete patch search with a nearest-helper-only candidate policy if needed to support a claim. Failure of that policy remains a heuristic failure; it cannot certify Level 3 exclusion.
- On the designated small-core subset, calculate m_R* and optionally min C_U as an intervention reference. This prevents interpreting arbitrary extra changes by a first-feasible global solver as inherently necessary.
- On the selected allowance subset, reuse fixed inputs for b in {0,1,2,M-|U0|}, removing duplicate allowance values. Each b defines a different benchmark policy; hold it fixed within each comparison. Keep primary b=1 frequencies separate. The last value is a structural-collapse positive control. The extent of this supplementary scan is fixed after the pilot.

No learning baseline is needed for the current formulation claim. A claim of superiority to a particular published routing algorithm would require implementing and fairly comparing that algorithm; this protocol does not make that claim.

## 10. Laptop execution envelope

Observed hardware: AMD Ryzen 7 5800H, 8 physical cores / 16 logical processors, about 15.9 GiB RAM. No GPU is required.

Use one measured solver process at a time with one numerical-library thread. Keep a process memory limit of 4 GiB and a run-level target below 8 GiB, subject to platform enforcement. Unmeasured input construction and audits may use two workers if memory permits. Do not benchmark H and G concurrently on this laptop.

Proposed per-call limits, with final counts selected after the pilot:

| Work | Initial cap | Purpose |
|---|---:|---|
| Development calibration | Initially 24 disjoint update cases, 20 seconds per method | Inspect generator outcomes, exposure, U0 traces/fractions, cost, arithmetic and checkpoint correctness |
| Controlled examples | 60 seconds per case before explicit continuation | All six headline labels must be fully resolved and audited |
| Study 2 | Initially 5 seconds per point; refinement/continuation allowance frozen after pilot | Prioritize certified transitions; reduce grid density before relaxing evidence checks |
| Study 3 primary H | Initially 20 seconds per update | Produce the four primary diagnostics |
| Paired G subset | Same total per-update allowance as H | Explain witness/certificate work with matched inputs and an explicit denominator |
| Small-core reference extension | Initially an additional 40 seconds per core update | Improve label coverage independently of the timed cost comparison |
| Supplementary sensitivities and participation queries | A separately frozen aggregate allowance; 2 hours was the initial planning estimate | Selected supporting analyses with their own denominators |
| Timing variability | A small seed-selected subset, with extra matched repeats only if needed | Supplementary measurement stability; not additional scientific samples |

Compute the search envelope from the frozen numbers of H cases, paired G cases, map evaluations, reference extensions and selected supplementary runs. Add generation, serialization and independent audit costs measured during the pilot. The earlier expanded workload is not a completion requirement. Prefer fewer well-classified samples and a focused paper to a larger catalogue of secondary results. Pilot changes may address documented generator pathologies as well as cost; they must not target attractive level frequencies. Main runs use the frozen design and remain resumable.

Record budget checkpoints from the same primary call at 1,5,20 seconds, rather than rerunning every case for each limit. Pair sequential H/G execution and counterbalance which runs first. Exclude a warm-up pair. Repeats quantify timing variability; they do not increase the scientific sample count.

Also retain shared work ceilings: initially 100,000 generator events and 10,000 branch attempts per primary call, 10,000 elimination operations and 2,000 rows per branch LP. H initially allocates its total time and work in proportions (5%,15%,20%,35%,25%) to Levels 0 through 4, carrying unused allowance forward. Level 3 shares its allocation across all patches; no patch receives a fresh total budget. G receives the same Level-0 allocation and the balance at Level 4. Freeze the scheduling policy after calibration. A wall-clock watchdog applies to the complete call, including diagnosis and witness validation. Independent replay audits are measured separately.

Checkpoint completed cases and completed proof units atomically. Resume with immutable instance, library, formulation and solver hashes. Existing live cursors are not persistent verified checkpoints; durable continuation requires implementation. Stop at a case boundary when the user stops a batch, and retain completed evidence.

## 11. Statistical and reporting protocol

- Freeze development seeds, test seeds, generator distributions, rejection rules, factor values, subsets, representations, branch ordering and caps before the main run.
- Estimate the four primary quantities using the complete declared primary population. Aggregate within base mission and resample whole missions within design strata for 95% bootstrap intervals. Use 2,000 bootstrap replicates for analysis; these are cheap operations on saved results. On the prespecified H/G subset, compute paired differences only for common targets such as time to witness, and report the subset's denominator. Present H's minimum-certification work separately.
- Two wind updates, nearby sweep points and repeated timing runs do not constitute independent mission samples.
- Report paired recovery differences on the H/G subset and H's certification yield separately. Report achieved preservation with its eligible denominator and, for any paired preservation comparison, the joint-recovery subset size. Do not treat these witness-specific changes as minimum changed sets.
- If membership of an analysis denominator is itself unresolved, show its bounds as well. In particular, do not silently discard updates whose recoverability or incumbent invalidity has not been decided.
- Show medians, upper quantiles, completion-versus-budget curves and the full timeout fraction. Performance profiles may supplement these, provided both methods are measured against the same completion target.
- Do not claim the exact population frequency is known when compatible-outcome intervals remain wide. Keep numerical feasibility, identification uncertainty and sampling uncertainty separate.
- Report rejection rate, unsupported arithmetic, proof-audit failures and forecast-coverage failures. Audit failures invalidate the affected result; timeouts do not.
- The primary estimates describe the declared generator. Adversarial fixtures and rare-case enrichment have separate denominators.

The rationale for retaining solver failures in runtime summaries is consistent with Dolan and More, [Benchmarking Optimization Software with Performance Profiles](https://optimization-online.org/wp-content/uploads/2001/03/300.pdf). Here, time to witness and time to minimum certification are different completion targets and need separate curves.

## 12. Figures, tables and reproducible artifacts

### Main-paper package

1. **Table: benchmark contract and factors.** Formulation, b, libraries, mission sizes, counts, hardware, caps and certificate scope.
2. **Figure/table: six controlled mechanisms.** Incumbent, repair, changed UAVs and minimum-level evidence.
3. **Figure: boundary atlas.** Represented k_R^F severity/duration panels for deadline/battery regimes, with unresolved hatching and sampled transition brackets. Mark any full-domain analytic overlay separately.
4. **Figure: randomized represented escalation distribution.** Stacked k_R^F outcomes by size, showing unresolved mass and compatible frequency ranges; label represented infinity explicitly.
5. **Figure: propagation and preservation.** Main panels show |U0|, |U0|/M, actual changed UAVs and preserved-plan fractions. State witness coverage and show where U0 itself is broad.
6. **Figure: cost of stronger evidence.** Separate witness and minimum-certificate completion targets, exclusion work and unresolved runs. Use the paired G subset as computational context, without a winner ranking.

Items 4–6 cover only the four main Study 3 questions; combine panels where that improves clarity. Use the supplement for additional margin maps, guard details, exact exclusions, library/geometry sensitivity, commitment/execution-state sensitivity, b sensitivity, Level-3/4 structural collapse, minimum-participation calculations, timing repeats, detailed subgroup statistics and solver settings. Correctness checks are required even when their presentation is supplementary. Every figure/table preserves represented versus full-domain evidence and unresolved outcomes. Do not draw empirical heatmaps before results exist.

### Per-update record

Persist at least:

    formulation_id, source_hashes, protocol_hash, generator_version,
    mission_seed, update_seed, stratum, N, M, b, slot_bounds,
    scenario_hash, representation_hash, previous_feasibility,
    forecast_support, wind_direction, severity, duration, margin_values,
    coverage_and_tail_provenance, admissibility_changes, commitments,
    changed_atoms, direct_support, downstream_support, closure, U0,
    u0_count, u0_fraction, u0_dependency_traces, conservative_support_reasons,
    patch_family_definition, patch_coverage, outside_constraint_checks,
    released_coordinates, changed_coordinates_by_component, C_U, m,
    evidence_domain, evidence_status, full_domain_justification,
    witness_and_reserve_paths, exclusions, lower_bound, upper_bound,
    numerical_upper_bound, compatible_outcomes, unresolved_reasons,
    collapse_domain, collapse_status, collapse_evidence,
    requested_evidence_target, timing_breakdown, work_counts, peak_memory, audit_status.

Use immutable scenario/library JSON, append-only run records, certificate files, a source snapshot, an environment lock, an audit manifest and scripts that regenerate every figure/table from records. Save representative witnesses by a prespecified rule, not by visual attractiveness.

## 13. Implementation order and completion criteria

This is a research design, not an executed implementation plan. Implementation should follow these dependencies:

1. **Align the contract.** Extend the schema, affected-UAV diagnostic, masks, patch union and scope validator. Add wind admissibility and forecast-tail provenance/coverage.
2. **Align evidence.** Update enumeration, exact membership, all-patch exclusion, bounded scheduling and independent proof replay. Keep reserve choice available at every level.
3. **Establish controlled correctness.** Implement Study 1 and verify every example and guard family, including unrestricted analytic exclusions.
4. **Add durable experiment records.** Freeze/replay inputs, checkpoint evidence, record change sets and work, and audit outputs independently.
5. **Pilot on disjoint missions.** Inspect generator pathologies and U0 membership traces alongside laptop cost. Resolve documented design/implementation problems, choose the primary workload and supporting subsets, then freeze the final manifest.
6. **Execute the three studies and audits.** Complete the four main randomized-study questions before adding secondary analyses. Run the selected supplementary checks under their frozen plan. Retain all failures and unresolved cases; generate paper artifacts only from audited records.

Likely code touchpoints are `src/env/intervention_scope.py`, `wind_dependency.py`, `wind.py`, `route_evaluator.py`, `scenario.py`, `recovery_validation.py`, `schemas/`, `src/recovery/`, and `src/experiments/`. Preserve the old benchmark entry point; create a distinctly versioned new runner. No changes to manuscript files are part of this design task.

Completion gates:

- All six controlled labels are established, including strict 3/4 separation and full-domain Cinf impossibility.
- Outside coordinates and all commitments are preserved exactly; every eligible Level-3 patch is covered before exclusion.
- The main b=1 policy is explicit in records and captions; supplementary b values are separate comparisons. Level 2 changes loading/delivery quantities and never task responsibility.
- Every experiment logs |U0| and |U0|/M, with auditable membership traces. Shared-constraint incidence does not inflate U0 by itself, and conservative support is not pruned to improve locality statistics.
- Reserve alternatives, closed passages, shared resources and missing tail coverage pass their guard checks.
- Every claimed witness and exclusion passes independent replay; tampered evidence and wrong-scope witnesses are rejected.
- A represented Level-4 exclusion cannot be serialized, aggregated or plotted as full-domain impossibility. Full-domain minimum/exclusion labels require their own verified justification; unresolved labels retain their domains and any valid bounds.
- Every plotted point/sample is traceable to immutable input and evidence. Sampled membership respects level nesting; library and allowance sensitivity checks obey the applicable mathematical implications.
- The small certification core targets complete resolution. Any shortfall is visible in the frequency intervals; it prevents claiming an exact six-outcome distribution for that core.
- The scaled panel reports its certification frontier. If most scaled results are unresolved, it answers computational limits but cannot support a strong typical-minimum-level claim; improve the solver or narrow that claim before calling the paper's empirical validation complete.
- Main text reports measured outcomes, including unfavorable comparisons and rare or absent levels. It does not inherit numerical findings from the old hierarchy.
- Study 3's main text answers the four stated questions. H/G results describe evidence targets and computational work, with no comparison of unrequested certification as a solver failure. Supplementary breadth is not a condition for declaring those four analyses complete.

The final benchmark succeeds when it can explain **what intervention is sufficient, what evidence makes escalation necessary, where that boundary moves, and how much can be established on the available computer**.
