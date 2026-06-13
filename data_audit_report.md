# HELPBETOR — DATA AUDIT REPORT
**Date:** 2026-06-10 18:09
**League:** Liga 1 Peruana (API-Football ID: 281)
**API requests remaining after audit:** 92

## 1. Matches Available Per Season

| Season | Total | Finished | Pending |
|--------|-------|----------|---------|
| 2022 | 346 | 346 | 0 |
| 2023 | 344 | 344 | 0 |
| 2024 | 306 | 306 | 0 |
| **TOTAL** | | **996** | |

## 2. Field Completeness (Finished Matches)

### Season 2022 (346 matches)
| Field | Completeness |
|-------|-------------|
| goals_home | 100.0% |
| goals_away | 100.0% |
| date | 100.0% |
| venue | 100.0% |
| referee | 100.0% |
| halftime_score | 100.0% |
| score_fulltime | 100.0% |

### Season 2023 (344 matches)
| Field | Completeness |
|-------|-------------|
| goals_home | 100.0% |
| goals_away | 100.0% |
| date | 100.0% |
| venue | 100.0% |
| referee | 99.7% |
| halftime_score | 97.7% |
| score_fulltime | 100.0% |

### Season 2024 (306 matches)
| Field | Completeness |
|-------|-------------|
| goals_home | 100.0% |
| goals_away | 100.0% |
| date | 100.0% |
| venue | 100.0% |
| referee | 100.0% |
| halftime_score | 100.0% |
| score_fulltime | 100.0% |

## 3. Stats Availability (Sample Matches)

| Match | Score | Has Stats | xG Available | Shots on Goal | Possession |
|-------|-------|-----------|--------------|---------------|------------|
| UTC Cajamarca vs Deportivo Garcilaso | 1-0 | YES | NO | 4 | 65% |
| FBC Melgar vs Cusco | 2-3 | YES | NO | 4 | 27% |
| Sporting Cristal vs ADT | 6-2 | YES | NO | 5 | 58% |

## 4. Key Findings & Feasibility

- **Data volume:** 996 finished matches. MARGINAL — proceed with v0.1 Poisson first.
- **xG data:** NOT AVAILABLE in API-Football for Liga 1. Confirmed: use raw goals for v1.0 lambdas.
- **Match stats:** Available in 3/3 sampled matches. Shots/possession data present.

## 5. Next Steps

- [ ] Phase 1: Build OCR module (Gemini Vision → JSON)
- [ ] Phase 1: Implement validation layer
- [ ] Phase 1: Statistical engine v0.1 (Plain Poisson baseline)
- [ ] Phase 1: Supabase schema setup
- [ ] Phase 2: Dixon-Coles v0.2 once v0.1 Brier Score is established