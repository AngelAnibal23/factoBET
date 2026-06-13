# HELPBETOR — AI CONTEXT DOCUMENT
# Version: 2.1 | Generated: 2026-06-08
# Purpose: Full project context for LLM continuation. Read entirely before responding.
# Changelog v2.0: Added sections 11 (UX communication design), 12 (full DB schema), 13 (API contract)
# Changelog v2.1: Updated section 10 — API-Football confirmed, Liga 1 confirmed, planning complete

---

## 1. PROJECT IDENTITY

**Project name:** Helpbetor
**Owner:** Angel Anibal Mamani Casilla — 5th semester, Ingeniería de Sistemas, UNJBG, Tacna, Perú
**Technical level:** Intermediate. Has built frontend + backend projects with AI and databases. No prior ML/statistical modeling experience.
**Goal:** A parlay analysis assistant. User uploads a screenshot of their parlay → system extracts the bets → performs serious statistical analysis → returns a brutally honest report on viability.
**Target market:** Fútbol sudamericano, primary focus Liga 1 Peruana. Secondary: Libertadores, Sudamericana, major European leagues.
**Philosophy:** Not a prediction oracle. An honest statistical auditor. The system never claims to predict the future — it quantifies probabilities and communicates uncertainty explicitly.

---

## 2. CORE ARCHITECTURE (Agreed Design)

### Pipeline (sequential, each stage validates before passing to next)

```
[USER INPUT] Screenshot of parlay
        ↓
[STAGE 1] Vision OCR — Gemini 1.5 Flash
  Extract: equipo_local, equipo_visitante, mercado, seleccion, cuota
  Output: structured JSON
        ↓
[STAGE 2] Validation layer (syntactic + semantic + range)
  Fail loudly, never silently
        ↓
[STAGE 3] Data layer — fetch real stats per team/match
  Primary: API-Football | Fallback: Sofascore scraping | Fallback: own DB
        ↓
[STAGE 4] Statistical engine — Dixon-Coles + xG-informed lambdas
  Output: prob_real per selection, edge vs implied prob, parlay total prob
        ↓
[STAGE 5] Correlation & heterogeneity detector
  Flags: same-match correlations, cross-sport, uncovered leagues
        ↓
[STAGE 6] LLM narrative report — Groq + Llama 3.1 (free tier)
  Input: pre-computed numbers ONLY. LLM explains, never calculates.
        ↓
[USER OUTPUT] Full analysis report with confidence indicators
```

### Tech Stack (100% free tier unless noted)

| Component | Technology | Notes |
|---|---|---|
| Vision OCR | Gemini 1.5 Flash API | Free with limits |
| Statistical engine | Python + scipy + numpy | Local, free |
| Data source primary | API-Football free tier | 100 req/day limit |
| Data source secondary | Sofascore scraping | Fragile, needs robust selectors |
| Vector/history DB | Supabase | Angel already uses this (gutStudy) |
| LLM narrative | Groq + Llama 3.1 70B | Angel already uses this (gutStudy) |
| Backend | FastAPI (Python) | |
| Frontend | React + Vite | |

---

## 3. STATISTICAL MODEL — DECISIONS & RATIONALE

### Chosen model: Dixon-Coles (1997) with time-weighting

**Why not plain Poisson:** Dixon-Coles outperforms plain Poisson by ~15% in predictive accuracy (documented in academic literature for Premier League 2018-19). It corrects two known failures of plain Poisson:
1. Underestimation of draws (especially 0-0, 1-1)
2. Ignores recency — old matches weighted equally as recent ones

**Core formulation:**
- Goals home team: X ~ Poisson(λ_home)
- Goals away team: Y ~ Poisson(λ_away)
- log(λ_home) = μ + α_i + β_j + γ (home advantage)
- log(λ_away) = μ + α_j + β_i
- Where α = attack strength, β = defense strength, γ = home advantage factor
- Correction parameter ρ adjusts joint probability for {0-0, 1-0, 0-1, 1-1} outcomes

**Time-weighting:** Matches are weighted by w(t) = exp(-ξ * t) where t = days since match. Parameter ξ controls decay rate. For Liga 1 Peruana, ξ must be calibrated differently than European leagues due to Apertura/Clausura format (shorter tournaments, fewer matches per team per season).

**Versioning strategy (mandatory — never skip versions):**
- v0.1: Plain Poisson, basic data. Establishes baseline Brier Score.
- v0.2: Dixon-Coles + time-weighting. Must beat v0.1 Brier Score or investigate why.
- v0.3: Local calibration for Liga 1 (home advantage parameter, ξ). Must beat v0.2.
- v1.0: Production. Only deploys when v0.3 is validated on historical holdout set.

**Primary metric:** Brier Score (NOT accuracy). Target: below 0.25 for 1X2 markets.
**Calibration check:** Group predictions by probability range (50-60%, 60-70%, etc.) and verify actual occurrence rates match. Systematic overestimation in 70-80% range = model overfitting.

### xG integration (Phase 2, not v1.0)

xG (Expected Goals) is the preferred input for λ estimation over raw goals, because raw goals have high variance. However, xG data for Liga 1 Peruana is nearly nonexistent in free sources. Strategy:
- v1.0: Use raw goals per game (home/away, last N matches) to estimate λ
- v2.0: Integrate xG from Sofascore/Fbref where available, fall back to raw goals

### Kelly Criterion — Fractional, not Full

**Formula:** f* = (b*p - q) / b where b = decimal_odds - 1, p = true probability, q = 1-p
**Critical finding from literature (Springer 2026, 17,403 matches):** Full Kelly generates >80% drawdown. Fractional Kelly at 15% delivers best risk-adjusted returns (+10.5% ROI). System must ALWAYS recommend Fractional Kelly (15-25%), never Full Kelly.
**Negative Kelly = no edge = do not bet.** This must be shown explicitly.

---

## 4. DATA STRATEGY

### Liga 1 Peruana — Data Reality Assessment

**What exists:**
- Liga 1 2026: in progress (~153 matches so far as of June 2026)
- Liga 1 2025: 332 matches (complete)
- Liga 1 2024: ~330 matches (complete)
- Liga 1 2023: 336 matches (complete)
- Liga 1 2022: 346 matches (complete)
- Liga 1 2021: 237 matches (complete, COVID-shortened)
- Total available: ~1,500-1,800 matches across 5 usable seasons

**What does NOT exist:**
- xG data for Liga 1 in any free API
- Shot location data for Liga 1
- Player-level event data for Liga 1
- Reliable historical odds for Liga 1 in football-data.co.uk (it does NOT cover Peru)

**Data layer architecture (fallback chain):**
```
Layer 1: API-Football (structured, 100 req/day free)
    ↓ if insufficient data
Layer 2: Sofascore scraping (more complete, fragile)
    ↓ if scraping fails
Layer 3: Own accumulated DB (grows with usage)
    ↓ if nothing available
Layer 4: Graceful degradation — show implied prob only, warn user explicitly
```

**First task before any modeling:** Run data audit script. Must answer:
1. How many Liga 1 matches does API-Football have per season?
2. Which fields are complete (goals, lineups, stats)?
3. Do API-Football and Sofascore results agree for overlapping matches?
Until this audit runs, no model should be designed — data quality determines model feasibility.

### Continuous Learning — Data Flywheel

Every analyzed parlay is stored in Supabase with:
```json
{
  "partido_id": "uuid",
  "equipo_local": "string",
  "equipo_visitante": "string",
  "liga": "string",
  "mercado": "string",
  "seleccion_usuario": "string",
  "cuota": "float",
  "prob_implicita": "float",
  "prob_modelo": "float",
  "lambda_home": "float",
  "lambda_away": "float",
  "edge_calculado": "float",
  "features_snapshot": "jsonb",
  "resultado_real": "string | null",
  "acierto": "boolean | null",
  "confianza_modelo": "ALTA | MEDIA | BAJA",
  "created_at": "timestamp",
  "resolved_at": "timestamp | null"
}
```

Nightly job: query API-Football for results of pending matches → update resultado_real and acierto. This converts each analyzed parlay into a labeled training example. Target: 2,000+ records before first model retrain on own data.

---

## 5. HETEROGENEITY & KNOWN FAILURE MODES

### 5.1 Heterogeneous Parlays — Classification

**Type A: Multi-league (same sport)**
Strategy: Each league has a declared coverage level. Model parameters are league-specific. Never apply Liga 1 parameters to a Premier League match.

```python
LEAGUE_COVERAGE = {
    "Liga 1 Peru":     {"level": "MEDIUM", "seasons": 5,  "model": "dixon_coles_local"},
    "Premier League":  {"level": "HIGH",   "seasons": 10, "model": "dixon_coles_europa"},
    "La Liga":         {"level": "HIGH",   "seasons": 10, "model": "dixon_coles_europa"},
    "Bundesliga":      {"level": "HIGH",   "seasons": 10, "model": "dixon_coles_europa"},
    "Ligue 1":         {"level": "HIGH",   "seasons": 10, "model": "dixon_coles_europa"},
    "Serie A":         {"level": "HIGH",   "seasons": 10, "model": "dixon_coles_europa"},
    "Libertadores":    {"level": "LOW",    "seasons": 3,  "model": "poisson_simple"},
    "Sudamericana":    {"level": "LOW",    "seasons": 3,  "model": "poisson_simple"},
    "Liga MX":         {"level": "MEDIUM", "seasons": 5,  "model": "dixon_coles_local"},
    "UNCOVERED":       {"level": "NONE",   "seasons": 0,  "model": None}
}
```

For UNCOVERED leagues: show implied probability only. Never fabricate statistical analysis.

**Type B: Multi-sport (football + NBA + tennis etc.)**
v1.0 scope: Football only. For non-football sports, system calculates implied probability and parlay math only. Explicit warning displayed.
Future versions: modular sport handlers (NBA uses different distribution entirely — not Poisson).

**Type C: Correlated selections within same match**
This is the most statistically dangerous case. Bookmakers price same-match combinations as if independent — they are not.

Known correlation table (hardcoded, must be in system from day 1):
```python
KNOWN_CORRELATIONS = [
    {"m1": "home_win",      "m2": "over_2.5",      "correlation": "HIGH_POSITIVE",  "note": "High-scoring home wins pull both"},
    {"m1": "btts",          "m2": "over_2.5",       "correlation": "VERY_HIGH_POS",  "note": "BTTS requires 2+ goals, over 2.5 requires 3+"},
    {"m1": "draw",          "m2": "under_2.5",      "correlation": "HIGH_POSITIVE",  "note": "Draws tend to be low-scoring"},
    {"m1": "home_win",      "m2": "btts",           "correlation": "MEDIUM",         "note": "Depends on team attacking profile"},
    {"m1": "handicap_-1.5","m2": "over_2.5",        "correlation": "HIGH_POSITIVE",  "note": "Win by 2+ usually means open game"},
    {"m1": "away_win",      "m2": "under_2.5",      "correlation": "MEDIUM_POSITIVE","note": "Away wins often by narrow margins"},
]
```

Detection function groups selections by match. If >1 selection per match → check correlation table → flag in report.

**Mathematical impact explanation for LLM to communicate:**
P(A and B assuming independence) = P(A) * P(B) → WRONG for correlated events
P(A and B with correlation) = P(A) * P(B|A) → different, sometimes significantly so
The bookmaker prices the combination as independent. The real probability is different. This is either an advantage or disadvantage depending on correlation direction.

### 5.2 OCR Failure Modes

Failure sources:
- Compressed/low-quality screenshot (JPEG artifacts)
- Inconsistent team name abbreviations across bookmakers
- Mixed odds formats (decimal vs American vs fractional)
- Notifications/UI elements overlapping the parlay
- Cropped screenshots missing context

Validation pipeline (all three must pass before analysis proceeds):

**Syntactic:** Does returned JSON have all required fields? Are types correct?

**Semantic:** Does each team name fuzzy-match against known Liga 1 teams with similarity ≥ 85%? If 70-85% → request user confirmation. If <70% → reject and ask user to re-upload.

**Range validation:**
```python
VALID_ODDS_RANGES = {
    "1X2":        (1.10, 20.0),
    "over_under": (1.15, 6.0),
    "btts":       (1.25, 4.5),
    "handicap":   (1.10, 10.0),
    "exact_score":(3.0,  150.0),
    "default":    (1.05, 200.0)
}
```
Any extracted odd outside range → flag as probable OCR error → do not proceed.

### 5.3 Data Quality Failures

**Team with insufficient history (< 10 matches in DB):**
- Do not suppress analysis
- Run model with available data
- Set confidence = LOW
- Display explicit warning: "Solo N partidos disponibles. Margen de error elevado."

**Match with no head-to-head data:**
- Do not use H2H as model feature when N < 5
- Mention absence in report but do not fabricate patterns

**Partido suspendido / postergado in parlay:**
- Nightly job must handle these edge cases from API
- Status codes to watch: TBD, SUSP, PST, CANC
- These must NOT be treated as losses or wins in training data

**API-Football rate limit hit (100 req/day):**
- Queue requests, fall to Sofascore scraper
- If both unavailable → use cached data from own DB
- Log every fallback occurrence for debugging

### 5.4 Liga 1 Structural Issues

**Apertura/Clausura format:**
- Season ≠ continuous 38-match run
- Each tournament is ~18 matches per team
- Time-decay parameter ξ must bridge across tournament boundaries
- Matches from previous Clausura are still recent-form indicators for next Apertura
- Calibration of ξ must account for this — use longer half-life than European default

**Home advantage in Peru:**
- Literature confirms bookmakers systematically underestimate home advantage in less-covered leagues
- Liga 1 home advantage is likely higher than European default (~0.3 goals)
- Altitude effects: Binacional (Juliaca, 3,825m), Sport Huancayo (3,259m) — genuine performance impact
- γ parameter must be calibrated per-stadium if data allows, or at minimum flagged for altitude matches

**Team continuity issues:**
- Relegated teams disappear from Liga 1 → their parameters cannot carry over
- Promoted teams have no Liga 1 history → treated as expansion teams, parameters initialized at league average
- Loan players and mid-season transfers affect team strength → cannot be modeled in v1.0

**Inter-tournament competitions:**
- Teams in Libertadores/Sudamericana rotate squads for Liga 1
- Double fixture weeks create fatigue effects
- v1.0: flag these matches explicitly, acknowledge model cannot account for rotation
- v2.0: incorporate competition load as feature

### 5.5 Live Match Detection

User may upload parlay where some matches have already started or finished.
```python
def classify_match_timing(match_datetime, current_datetime):
    delta = match_datetime - current_datetime
    if delta > timedelta(hours=2):
        return "PRE_MATCH"        # Normal analysis
    elif delta > timedelta(0):
        return "IMMINENT"         # Warn: odds may have moved
    elif delta > timedelta(hours=-2):
        return "IN_PLAY"          # Analysis irrelevant, state this
    else:
        return "FINISHED"         # Result known, retrieve it
```

For FINISHED matches: retrieve actual result from API, show whether selection won or lost. Do not run probability model — it's retrospective and misleading.

### 5.6 Multi-bookmaker Margin Inconsistency

User may construct a "mental parlay" combining odds from different bookmakers (Betano, Inkabet, Codere, Betsafe). Each has different overround (margin).
- Betano Peru: ~5-7% margin
- Inkabet: ~7-9% margin
- Codere: ~6-8% margin

When bookmaker cannot be detected from image: assume 7% average margin, document assumption in report.

Margin removal formula for true implied probability:
```python
def remove_margin(odds_list):
    raw_probs = [1/o for o in odds_list]
    total = sum(raw_probs)
    return [p/total for p in raw_probs]  # normalized to sum to 1
```

Always show both: raw implied probability AND margin-adjusted probability.

### 5.7 Exotic Markets (First Scorer, Exact Score, Corners, Cards)

v1.0 scope: Do not model these with statistical engine. For any exotic market:
- Calculate implied probability from odds
- State explicitly: "No tenemos modelo estadístico para este mercado."
- Calculate its impact on parlay total probability (its implied prob contributes to the product)
- Flag it as the "weakest link" in the analysis since it cannot be validated

---

## 6. USER COMMUNICATION STANDARDS

### Confidence Levels (mandatory on every analysis)

```
ALTA:
  ✓ Liga cubierta con nivel ALTO
  ✓ Ambos equipos con 15+ partidos en DB
  ✓ Datos completos últimas 6 fechas
  ✓ No exotic markets
  ✓ No same-match correlations

MEDIA:
  ⚠ Liga con cobertura MEDIA o baja
  ⚠ Al menos un equipo con 10-14 partidos
  ⚠ Algunos campos incompletos en datos recientes
  ⚠ 1 mercado exótico presente

BAJA:
  ⚠ Liga no cubierta o cobertura mínima
  ⚠ Algún equipo con <10 partidos históricos
  ⚠ Múltiples mercados exóticos
  ⚠ Correlaciones detectadas no cuantificables
  ⚠ Partido inmediato (odds may have moved)
```

### What the LLM narrative MUST always include

1. Probability of each individual selection (model vs implied)
2. Edge per selection (positive = value, negative = no value)
3. Combined parlay probability (real, not just implied product)
4. Identification of weakest selection in parlay
5. Correlation alerts if any detected
6. Confidence level with explicit reasons
7. Fractional Kelly recommendation (only if positive edge exists)
8. Explicit disclaimer that this is statistical analysis, not prediction

### What the LLM narrative MUST NEVER do

- Claim certainty about outcomes
- Recommend a specific bet amount in monetary terms (only % of bankroll via Kelly)
- Ignore correlation flags to make the analysis "cleaner"
- Present analysis for uncovered markets as if it has statistical backing
- Suppress low-confidence warnings to seem more impressive

---

## 7. BIBLIOGRAPHY — FOUNDATIONAL PAPERS

These are the academic sources that ground the statistical decisions. Reference when implementing.

| Paper | Authors | Year | Use in project |
|---|---|---|---|
| Modelling Association Football Scores and Inefficiencies in the Football Betting Market | Dixon & Coles | 1997 | Core statistical model |
| Predicting Football Results With Statistical Modelling: Dixon-Coles and Time-Weighting | dashee87 (blog) | 2018 | Python implementation reference |
| A Machine Learning Approach for Player and Position Adjusted Expected Goals | Hewitt & Karakuş | 2023 | xG methodology (Phase 2) |
| Expected Goals in Football: Improving Model Performance | Mulholland & Ryan | 2023 | xG validation (PLOS ONE, free) |
| Risk Parity vs Kelly Criterion in Football Value Betting | Tshimula et al. | 2026 | Fractional Kelly rationale |
| Efficiency of the Football Betting Market | CBS Research | 2019 | Market efficiency framework |
| Can simple models predict football and beat the odds? | Wilkens | 2026 | xG + market efficiency connection |

**Implementation reference:** dashee87.github.io/football/python/predicting-football-results-with-statistical-modelling-dixon-coles-and-time-weighting/
**Free xG paper:** arxiv.org/pdf/2301.13052
**Free xG paper 2:** ncbi.nlm.nih.gov/pmc/articles/PMC10075453/

---

## 8. BUILD PHASES — SEQUENCING

### Phase 0 — Data Audit (before any model code)
Write audit.py. Query API-Football for Liga 1 2021-2026. Report:
- Matches available per season
- Field completeness % (goals, lineups, stats, odds)
- Cross-reference with Sofascore for 20 random matches
Output: data_audit_report.md with exact numbers. This determines Phase 1 feasibility.

### Phase 1 — MVP (Weeks 1-8)
- OCR module: Gemini Vision → JSON extraction
- Validation layer: syntactic + semantic + range
- Data layer: API-Football + fallback chain
- Statistical engine v0.1: Plain Poisson baseline
- Storage: Supabase schema (all fields from section 5)
- Basic report: table with prob_real vs prob_implicita per selection
- Parlay total probability calculation
- No LLM narrative yet — just numbers

### Phase 2 — Statistical Upgrade (Weeks 9-14)
- Dixon-Coles v0.2 implementation
- Brier Score validation against v0.1
- Time-weighting calibration for Apertura/Clausura
- Home advantage calibration for Liga 1
- Correlation detection module
- Confidence level system

### Phase 3 — Intelligence Layer (Weeks 15-18)
- Groq + Llama 3.1 narrative generation
- All validation gates before LLM
- Heterogeneous parlay handling (multi-league, multi-sport)
- Exotic market flagging
- User-facing confidence indicators

### Phase 4 — Learning Loop (Ongoing)
- Nightly result resolution job
- Monthly Brier Score tracking
- Quarterly model retrain trigger
- Own data growing as training set
- Model versioning system

---

## 9. CRITICAL DESIGN PRINCIPLES (Non-negotiable)

1. **Never fail silently.** Every failure has an explicit user-facing message explaining what failed and why.

2. **Numbers first, LLM second.** The statistical engine runs completely before the LLM is called. The LLM receives pre-computed numbers, never raw data to interpret.

3. **Calibration over accuracy.** A well-calibrated model that says "60% probability" and is right 60% of the time is better than a model with higher accuracy that is systematically miscalibrated.

4. **Version every model change.** No silent model updates. Every change is versioned, tested against historical holdout, documented with before/after Brier Score.

5. **Degrade gracefully, never fabricate.** When data is insufficient, reduce confidence level and say so. Never invent statistical analysis to cover for missing data.

6. **Kelly is a fraction, always.** System never outputs Full Kelly recommendations. Maximum recommendation: 25% of bankroll. Always with explicit risk warning.

7. **Correlation detection is mandatory.** Same-match multi-selection parlays always trigger correlation check. Never suppressed for UX convenience.

8. **The model measures edge, not outcomes.** Success metric is calibration over thousands of predictions, not whether any individual parlay won.

---

## 10. OWNER CONTEXT FOR CONTINUATION

When continuing this project with Angel:
- He communicates in Spanish, informally, often in caps for emphasis
- He learns best through worked examples, not theory
- He has existing Supabase + Groq infrastructure from gutStudy project (same stack)
- He is aware of all documented failure modes — do not re-explain them, reference them
- Current status: Planning COMPLETE. No code written yet. Ready to start Phase 0.
- Next concrete step: Write audit.py and run it against API-Football
- He explicitly does NOT want interactive widgets — plain text or tables only
- He prefers additive changes — never remove existing content when extending documents
- Planning sessions are separate from coding sessions — do not mix them

### API-Football credentials (confirmed working)
- Dashboard: dashboard.api-football.com
- API URL: v3.football.api-sports.io
- Header: x-apisports-key
- Plan: Free, 100 requests/day, Active
- Liga 1 Peruana league ID: 268
- API key: stored by Angel, not written here for security

### Key decisions made late in planning
- **Development target confirmed: Liga 1 Peruana** — not Premier League. Edge is in less-covered markets.
- **Validation strategy:** Pipeline will be validated with Premier League data first (clean data), then calibrated for Liga 1. This is NOT a scope change — Liga 1 remains the primary target.
- **API-Football is direct** (api-sports.io), not via RapidAPI — RapidAPI no longer lists this API.

---

## 11. UX COMMUNICATION DESIGN — HOW TO TALK TO A NON-MATHEMATICAL USER

### The Core Problem

A user who sees "67% probability" will likely interpret it as "almost certain." That misinterpretation is dangerous and the system is responsible for preventing it. The statistical analysis can be perfectly correct and still cause harm if communication is poorly designed.

### Probability Language — Translation Table

The LLM narrative MUST translate every probability into natural language using this scale. Never show a raw percentage without its natural language equivalent.

| Probability range | Natural language (Spanish) | Color signal |
|---|---|---|
| < 35% | "Poco probable — menos de 1 de cada 3 veces" | 🔴 |
| 35–50% | "Bajo — menos probable que improbable" | 🟠 |
| 50–60% | "Ligeramente favorable — cara o cruz con leve ventaja" | 🟡 |
| 60–70% | "Moderado — ocurre 6 de cada 10 veces en el largo plazo" | 🟡 |
| 70–80% | "Alto — pero falla 2-3 de cada 10 veces" | 🟢 |
| > 80% | "Muy alto — pero nunca es certeza en fútbol" | 🟢 |

**Critical rule:** Never omit the failure rate. If something has 70% probability, the system must always state "falla el 30% de las veces" in the same sentence. This is non-negotiable.

### Parlay Compound Probability — Always Show the Math Visually

Users do not intuitively understand that multiplying probabilities collapses combined probability fast. The report must always show the step-by-step multiplication explicitly:

```
Selección 1: Alianza Lima gana      → 58% (0.58)
Selección 2: Over 2.5 en La Liga   → 61% (0.61)
Selección 3: Ambos anotan PSG      → 54% (0.54)

Probabilidad combinada real:
0.58 × 0.61 × 0.54 = 19.1%

Esto significa: este parlay sale aproximadamente 1 de cada 5 veces.
La cuota total implica: 22.4% → la casa no está pagando valor real aquí.
```

The "1 de cada N veces" framing is mandatory for the combined probability. It is the most intuitive format for non-mathematical users.

### Edge Communication — What It Means in Plain Language

Edge is the most important metric the system produces. Users will not understand "edge = +6.2%" without context.

Translation rules for edge:
```
edge > +5%  → "Esta selección tiene valor estadístico real. La cuota paga más de lo que el riesgo justifica."
edge 0-5%   → "Valor marginal. Dentro del margen de error del modelo."
edge 0       → "Sin valor. La cuota refleja exactamente la probabilidad estimada."
edge negativo → "Sin valor. La casa tiene ventaja estadística en esta selección."
edge < -5%  → "La casa tiene ventaja clara aquí. Esta selección perjudica el parlay."
```

### What NOT to Communicate

- Never use the word "seguro" or "garantizado" in any context
- Never say "el modelo recomienda apostar" — it says "el modelo detecta valor estadístico"
- Never omit the confidence level warning even if it makes the report look less clean
- Never present the analysis as a substitute for the user's own judgment
- Never imply that positive edge = winning bet. Edge is a long-run concept, not a single-game guarantee.

### Mandatory Disclaimer (always at end of every report)

```
⚠ Este análisis es estadístico, no predictivo. El fútbol tiene alta varianza
irreducible — el equipo con 80% de probabilidad pierde el 20% de las veces.
El valor estadístico solo se realiza en el largo plazo con disciplina de
bankroll. Este sistema no garantiza resultados individuales.
```

### Handling User Frustration (when model was "wrong")

When a user returns after a parlay with positive edge that lost, the system context must acknowledge the variance without undermining the model's validity. The LLM should be primed with this framing:

"Un resultado individual no valida ni invalida el modelo. Si el modelo dijo 65% y perdió, eso es completamente consistente con un modelo correcto — ocurre el 35% de las veces. La calibración se mide en cientos de predicciones, no en una."

---

## 12. FULL DATABASE SCHEMA (Supabase / PostgreSQL)

### Design principles
- All tables use UUID primary keys (Supabase default)
- Timestamps always UTC
- Soft deletes only (deleted_at field) — never hard delete training data
- JSONB for snapshot fields — preserves full state at time of analysis without schema migrations

### Table 1: `equipos`
Master table of all known teams. Populated from API-Football + manual entries.

```sql
CREATE TABLE equipos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id INTEGER UNIQUE,          -- API-Football team ID
    nombre_oficial  TEXT NOT NULL,           -- Official name
    aliases         TEXT[],                  -- Array of known abbreviations/variants
    liga_id         UUID REFERENCES ligas(id),
    pais            TEXT,
    ciudad          TEXT,
    estadio         TEXT,
    altitud_msnm    INTEGER,                 -- Critical for Liga 1 altitude teams
    capacidad       INTEGER,
    activo          BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Table 2: `ligas`
Master table of covered leagues with their model coverage level.

```sql
CREATE TABLE ligas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id INTEGER UNIQUE,
    nombre          TEXT NOT NULL,
    pais            TEXT,
    nivel_cobertura TEXT CHECK (nivel_cobertura IN ('ALTA','MEDIA','BAJA','NULA')),
    modelo          TEXT,                    -- 'dixon_coles_local', 'dixon_coles_europa', 'poisson_simple', NULL
    temporadas_disponibles INTEGER,
    deporte         TEXT DEFAULT 'futbol',
    activa          BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Table 3: `partidos`
Historical and upcoming matches. Core training data source.

```sql
CREATE TABLE partidos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id     INTEGER UNIQUE,
    liga_id             UUID REFERENCES ligas(id),
    equipo_local_id     UUID REFERENCES equipos(id),
    equipo_visitante_id UUID REFERENCES equipos(id),
    fecha               TIMESTAMPTZ NOT NULL,
    temporada           TEXT,                -- e.g. '2025', '2025-Apertura'
    jornada             INTEGER,
    estado              TEXT CHECK (estado IN ('SCHEDULED','LIVE','FINISHED','POSTPONED','CANCELLED','SUSPENDED')),
    goles_local         INTEGER,             -- NULL until finished
    goles_visitante     INTEGER,             -- NULL until finished
    resultado           TEXT CHECK (resultado IN ('HOME','DRAW','AWAY', NULL)),
    -- Raw stats (NULL if not available)
    tiros_local         INTEGER,
    tiros_puerta_local  INTEGER,
    tiros_visitante     INTEGER,
    tiros_puerta_vis    INTEGER,
    posesion_local      NUMERIC(5,2),
    -- xG (NULL for Liga 1 in v1.0 — populated in v2.0)
    xg_local            NUMERIC(5,3),
    xg_visitante        NUMERIC(5,3),
    -- Data quality flag
    datos_completos     BOOLEAN DEFAULT false,  -- true only when all core fields populated
    fuente              TEXT DEFAULT 'api_football',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### Table 4: `parametros_modelo`
Stores fitted model parameters per league per version. One row per league per model version.

```sql
CREATE TABLE parametros_modelo (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    liga_id         UUID REFERENCES ligas(id),
    version_modelo  TEXT NOT NULL,           -- 'v0.1', 'v0.2', 'v0.3', 'v1.0'
    temporada_fit   TEXT,                    -- which seasons were used for fitting
    -- Dixon-Coles global parameters
    mu              NUMERIC(10,6),           -- baseline scoring rate
    gamma           NUMERIC(10,6),           -- home advantage
    rho             NUMERIC(10,6),           -- low-score correction
    xi              NUMERIC(10,6),           -- time decay rate
    -- Per-team parameters stored as JSONB
    -- {"Alianza Lima": {"alpha": 0.34, "beta": -0.21}, ...}
    attack_params   JSONB,
    defense_params  JSONB,
    -- Validation metrics
    brier_score     NUMERIC(10,6),
    log_loss        NUMERIC(10,6),
    n_matches_fit   INTEGER,
    n_matches_val   INTEGER,
    is_production   BOOLEAN DEFAULT false,   -- only one row per liga can be true
    fitted_at       TIMESTAMPTZ DEFAULT NOW(),
    notas           TEXT
);
```

### Table 5: `analisis_parlays`
Every parlay submitted by any user. Core flywheel table.

```sql
CREATE TABLE analisis_parlays (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Parlay-level data
    prob_parlay_real    NUMERIC(8,6),        -- product of all prob_modelo
    prob_parlay_implicita NUMERIC(8,6),      -- product of all prob_implicita
    cuota_total         NUMERIC(10,4),
    n_selecciones       INTEGER,
    tiene_correlaciones BOOLEAN DEFAULT false,
    tiene_mercados_exoticos BOOLEAN DEFAULT false,
    nivel_confianza     TEXT CHECK (nivel_confianza IN ('ALTA','MEDIA','BAJA')),
    razon_confianza     TEXT[],              -- array of reasons for confidence level
    -- Outcome
    resultado_parlay    TEXT CHECK (resultado_parlay IN ('GANADO','PERDIDO','PENDIENTE','ANULADO')),
    -- Image metadata
    imagen_hash         TEXT,               -- to detect duplicate submissions
    casa_apuestas       TEXT,               -- detected or assumed bookmaker
    -- Timestamps
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ
);
```

### Table 6: `selecciones_parlay`
Individual selections within each parlay. One row per bet line.

```sql
CREATE TABLE selecciones_parlay (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parlay_id           UUID REFERENCES analisis_parlays(id) ON DELETE CASCADE,
    partido_id          UUID REFERENCES partidos(id),        -- NULL if match not in DB
    -- Raw extracted data
    equipo_local_raw    TEXT,               -- exactly as extracted by OCR
    equipo_visitante_raw TEXT,
    mercado             TEXT,               -- '1X2', 'over_under', 'btts', 'handicap', 'exotic'
    seleccion           TEXT,               -- 'home', 'draw', 'away', 'over', 'under', 'yes', 'no'
    cuota               NUMERIC(10,4),
    -- Computed fields
    prob_implicita      NUMERIC(8,6),       -- 1/cuota
    prob_implicita_adj  NUMERIC(8,6),       -- margin-adjusted
    prob_modelo         NUMERIC(8,6),       -- from statistical engine (NULL if uncovered)
    edge                NUMERIC(8,6),       -- prob_modelo - prob_implicita_adj
    kelly_fraccion      NUMERIC(8,6),       -- fractional kelly (NULL if edge <= 0)
    lambda_home         NUMERIC(8,4),
    lambda_away         NUMERIC(8,4),
    -- Model context snapshot (full state at analysis time)
    features_snapshot   JSONB,
    -- Quality flags
    nivel_cobertura     TEXT CHECK (nivel_cobertura IN ('ALTA','MEDIA','BAJA','NULA')),
    es_mercado_exotico  BOOLEAN DEFAULT false,
    correlaciones_detectadas JSONB,         -- array of correlation alerts
    -- Outcome
    resultado_real      TEXT,               -- actual match result
    acierto             BOOLEAN,            -- did selection win?
    -- Metadata
    version_modelo      TEXT,               -- which model version was used
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ
);
```

### Table 7: `calibracion_historica`
Monthly calibration snapshots. Used to track model drift over time.

```sql
CREATE TABLE calibracion_historica (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    liga_id         UUID REFERENCES ligas(id),
    version_modelo  TEXT,
    periodo         TEXT,                   -- 'YYYY-MM'
    mercado         TEXT,                   -- '1X2', 'over_under', 'btts'
    rango_prob_min  NUMERIC(4,2),           -- e.g. 0.50
    rango_prob_max  NUMERIC(4,2),           -- e.g. 0.60
    n_predicciones  INTEGER,
    tasa_real       NUMERIC(6,4),           -- actual occurrence rate in this range
    brier_score     NUMERIC(10,6),
    registrado_at   TIMESTAMPTZ DEFAULT NOW()
);
```

### Table 8: `alias_equipos`
Fuzzy matching support. Maps OCR variants to canonical team IDs.

```sql
CREATE TABLE alias_equipos (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    equipo_id   UUID REFERENCES equipos(id),
    alias       TEXT NOT NULL UNIQUE,       -- e.g. 'U. Cristal', 'Spo. Cristal', 'CRISTAL'
    fuente      TEXT,                       -- 'betano', 'inkabet', 'manual', 'ocr_detected'
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### Key indexes (performance-critical)

```sql
-- Frequent queries
CREATE INDEX idx_partidos_liga_fecha ON partidos(liga_id, fecha DESC);
CREATE INDEX idx_partidos_equipo_local ON partidos(equipo_local_id, fecha DESC);
CREATE INDEX idx_partidos_equipo_vis ON partidos(equipo_visitante_id, fecha DESC);
CREATE INDEX idx_partidos_estado ON partidos(estado) WHERE estado = 'SCHEDULED';
CREATE INDEX idx_selecciones_pendientes ON selecciones_parlay(acierto) WHERE acierto IS NULL;
CREATE INDEX idx_alias_lower ON alias_equipos(LOWER(alias));  -- case-insensitive lookup
```

---

## 13. INTERNAL API CONTRACT (FastAPI)

### Design principles
- All endpoints return consistent envelope: `{success, data, error, meta}`
- Errors always include a `code` (machine-readable) and `message` (human-readable in Spanish)
- No endpoint proceeds past a failed validation gate
- All analysis endpoints are idempotent on same image hash (deduplication)

### Standard response envelope

```json
{
  "success": true,
  "data": { },
  "error": null,
  "meta": {
    "version_modelo": "v0.2",
    "timestamp": "2026-06-07T14:32:00Z",
    "duracion_ms": 1240
  }
}
```

Error response:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "OCR_EXTRACTION_FAILED",
    "message": "No se pudo extraer información del parlay. Intenta con una imagen más nítida.",
    "detalle": "Cuota fuera de rango válido: 0.5 para mercado 1X2"
  },
  "meta": { "timestamp": "..." }
}
```

### Endpoint 1: POST /api/v1/parlay/analizar

Primary endpoint. Accepts image, returns full analysis.

**Request:**
```
Content-Type: multipart/form-data
Body:
  imagen: File (jpeg/png/webp, max 5MB)
  info_adicional: string (optional) — free text from user e.g. "el goleador está lesionado"
```

**Processing sequence (all must pass before next):**
1. Image hash check → return cached result if duplicate within 2h
2. Gemini Vision OCR → extract selections JSON
3. Syntactic validation → fail if malformed
4. Semantic validation → fuzzy match team names, request confirmation if 70-85% match
5. Range validation → fail if odds out of bounds
6. Match timing classification → flag live/finished matches
7. Data layer fetch → API-Football → Sofascore → own DB → graceful degrade
8. Statistical engine → Poisson/Dixon-Coles per covered league
9. Correlation detector → flag same-match multi-selections
10. Kelly calculator → fractional, only if edge > 0
11. Confidence level assignment
12. LLM narrative generation → Groq, pre-computed numbers only
13. Store in Supabase
14. Return response

**Response data:**
```json
{
  "parlay_id": "uuid",
  "resumen": {
    "prob_real": 0.191,
    "prob_implicita": 0.224,
    "cuota_total": 4.46,
    "n_selecciones": 3,
    "nivel_confianza": "MEDIA",
    "tiene_valor": false,
    "alertas": ["CORRELACION_DETECTADA", "MERCADO_EXOTICO"]
  },
  "selecciones": [
    {
      "equipo_local": "Alianza Lima",
      "equipo_visitante": "Universitario",
      "mercado": "1X2",
      "seleccion": "home",
      "cuota": 2.10,
      "prob_implicita": 0.476,
      "prob_implicita_adj": 0.449,
      "prob_modelo": 0.512,
      "edge": 0.063,
      "kelly_fraccion": 0.058,
      "nivel_cobertura": "MEDIA",
      "alertas": [],
      "datos_utilizados": {
        "n_partidos_local": 14,
        "n_partidos_visitante": 16,
        "temporadas": ["2024", "2025"]
      }
    }
  ],
  "correlaciones": [
    {
      "seleccion_1": "home",
      "seleccion_2": "over_2.5",
      "partido": "PSG vs Lyon",
      "tipo": "CORRELACION_POSITIVA",
      "impacto": "La probabilidad combinada real es mayor que el producto simple. La casa puede estar subpagando esta combinación."
    }
  ],
  "narrativa": "string — full LLM-generated report in Spanish",
  "disclaimer": "string — mandatory disclaimer"
}
```

**Error codes:**
```
OCR_EXTRACTION_FAILED     — Gemini could not extract structured data
VALIDATION_SYNTACTIC      — Missing required fields in OCR output
VALIDATION_SEMANTIC       — Team name match below 70% threshold
VALIDATION_RANGE          — Odds outside valid range
DATA_INSUFFICIENT         — Not enough historical data for any selection
IMAGE_TOO_LARGE           — File exceeds 5MB
DUPLICATE_SUBMISSION      — Same image analyzed within 2h (returns cached)
RATE_LIMIT_EXCEEDED       — API-Football daily limit hit, fallback unavailable
```

---

### Endpoint 2: GET /api/v1/parlay/{parlay_id}

Retrieve a previously analyzed parlay. Used for history view and result resolution display.

**Response:** Same structure as POST /analizar, plus:
```json
{
  "resultado": {
    "estado": "PENDIENTE | GANADO | PERDIDO | ANULADO",
    "selecciones_resultado": [
      {"seleccion_id": "uuid", "acierto": true, "resultado_real": "HOME"}
    ],
    "resolved_at": "timestamp | null"
  }
}
```

---

### Endpoint 3: GET /api/v1/equipos/buscar

Fuzzy search endpoint for team name validation. Used by frontend confirmation modal when OCR match is 70-85%.

**Request:** `?q=U.Cristal&liga=liga1_peru&limit=5`

**Response:**
```json
{
  "resultados": [
    {"equipo_id": "uuid", "nombre": "Sporting Cristal", "similitud": 0.87, "liga": "Liga 1 Peru"},
    {"equipo_id": "uuid", "nombre": "Crystal Palace", "similitud": 0.71, "liga": "Premier League"}
  ]
}
```

---

### Endpoint 4: GET /api/v1/modelo/estado

System health + current model version info. Used for admin monitoring.

**Response:**
```json
{
  "version_activa": "v0.2",
  "ligas_cubiertas": 8,
  "total_partidos_db": 1847,
  "total_analisis": 342,
  "pendientes_resolucion": 47,
  "ultimo_brier_score": {
    "liga1_peru": 0.238,
    "premier_league": 0.211
  },
  "api_football_requests_hoy": 67,
  "api_football_limite_diario": 100
}
```

---

### Endpoint 5: POST /api/v1/admin/resolver-resultados

Nightly job trigger. Queries API-Football for results of pending matches and updates DB.

**Auth:** Internal only (API key header, not user-facing)

**Response:**
```json
{
  "partidos_resueltos": 12,
  "selecciones_actualizadas": 31,
  "parlays_cerrados": 8,
  "errores": []
}
```

---

### Endpoint 6: GET /api/v1/calibracion/{liga_id}

Returns calibration data for a league. Used for internal model monitoring.

**Response:** Calibration table grouped by probability range and market type, with Brier Score trend over last 6 months.

---

## 14. PLANNING STATUS — COMPLETE CHECKLIST

| Area | Status |
|---|---|
| Project identity & philosophy | ✅ Complete |
| Core pipeline architecture | ✅ Complete |
| Tech stack decisions | ✅ Complete |
| Statistical model selection & rationale | ✅ Complete |
| Model versioning strategy | ✅ Complete |
| Kelly Criterion approach | ✅ Complete |
| Data reality assessment (Liga 1) | ✅ Complete |
| Data fallback chain | ✅ Complete |
| Data flywheel (continuous learning) | ✅ Complete |
| Heterogeneous parlay handling | ✅ Complete |
| OCR failure modes & validation | ✅ Complete |
| Liga 1 structural issues (Apertura/Clausura, altitude) | ✅ Complete |
| Live match detection | ✅ Complete |
| Multi-bookmaker margin handling | ✅ Complete |
| Exotic markets handling | ✅ Complete |
| UX communication design | ✅ Complete |
| Probability language translation | ✅ Complete |
| Edge communication standards | ✅ Complete |
| Full database schema (8 tables) | ✅ Complete |
| API contract (6 endpoints) | ✅ Complete |
| Build phases & sequencing | ✅ Complete |
| Critical design principles | ✅ Complete |
| Bibliography | ✅ Complete |
| Owner context for AI continuation | ✅ Complete |

**Planning phase: COMPLETE. Next action: Phase 0 — audit.py**

---

*End of AI Context Document v2.0*
*Next document: HELPBETOR_HUMAN.md (pending — Angel requested this separately)*

---

## 15. BUILD STATUS — LIVE (actualizar en cada sesión)

**Última actualización:** 2026-06-10

### Archivos completados y ejecutados

| Archivo | Descripción | Estado |
|---|---|---|
| `audit.py` | Auditoría API-Football | ✅ Ejecutado (re-confirmado 2026-06-10) |
| `data_audit_report.md` | Resultado auditoría | ✅ Generado |
| `setup_tables.sql` | Schema DB Supabase (ligas, equipos, partidos + índices) | ✅ Ejecutado en Supabase |
| `download_fixtures.py` | Descarga 996 partidos a Supabase | ✅ Ejecutado (re-confirmado 2026-06-10, 0 errores) |
| `verify_db.py` | Verificación de datos en DB | ✅ Ejecutado — 996 partidos confirmados |
| `engine_v01.py` | Motor Plain Poisson | ✅ Ejecutado — Brier Score = 0.2751 |
| `engine_v02.py` | Motor Dixon-Coles + time-weighting | ✅ Ejecutado — Brier Score = 0.2797 |
| `engine_v03.py` | Motor Dixon-Coles + calibración altitud/xi | ✅ Listo para ejecutar |
| `ocr.py` | OCR module — Gemini 1.5 Flash → JSON | ✅ Escrito — PENDIENTE PRUEBA CON IMAGEN REAL |
| `.env` | Credenciales fuera del código | ✅ Creado 2026-06-10 |
| `.gitignore` | Excluye .env del control de versiones | ✅ Creado 2026-06-10 |

### Seguridad — credenciales (migrado 2026-06-10)

Todos los archivos Python tenían credenciales hardcodeadas. Migradas a `.env`:

| Variable | Servicio |
|---|---|
| `API_FOOTBALL_KEY` | API-Football (key original d6840...) |
| `GEMINI_API_KEY` | Google Gemini (para ocr.py) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |

Archivos actualizados: `audit.py`, `find_league.py`, `check_seasons.py`, `download_fixtures.py`, `verify_db.py`, `engine_v01.py`, `engine_v02.py`, `engine_v03.py`

Dependencia instalada: `python-dotenv 1.2.2`

### Estado de la DB (verificado 2026-06-09)

- Liga 1 Peruana (ID 281): 1 fila en tabla `ligas`
- Equipos: 24 equipos en tabla `equipos`
- Partidos: 996 (346/2022 + 344/2023 + 306/2024) en tabla `partidos`
- Distribución: 52.1% HOME / 24.3% DRAW / 23.6% AWAY

### Pendientes inmediatos (Phase 1 MVP)

- [ ] **Ejecutar `engine_v03.py`** — Dixon-Coles + altitud + grid search xi, debe superar Brier 0.2797
- [ ] **Probar `ocr.py` con imagen real de parlay** — GEMINI_API_KEY ya está en .env
  - Comando actualizado: `python ocr.py foto_parlay.jpg` (ya no necesita key como argumento)
  - Verificar primero que ocr.py lee de .env, no de CLI
- [ ] Escribir `validator.py` — validación sintáctica + semántica + rangos de cuotas
- [ ] Escribir `analyzer.py` — conecta validación → engine_v03 → calcula edge y Kelly
- [ ] Escribir `main.py` — endpoint FastAPI `POST /parlay/analizar`

### Próxima sesión — arrancar aquí

1. Ejecutar `engine_v03.py` y ver si supera Brier Score de v0.2
2. Probar `ocr.py` con imagen real de parlay
3. Si pasa → escribir `validator.py`
4. Si falla → debuggear prompt de Gemini en `ocr.py`
