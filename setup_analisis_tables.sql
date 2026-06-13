-- HELPBETOR Phase 2 — Analisis storage tables
-- Run this in Supabase SQL Editor after setup_tables.sql

-- ── 4. analisis_parlays ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analisis_parlays (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Parlay-level stats
    prob_parlay_real         NUMERIC(8,6),        -- product of prob_modelo (non-exotic)
    prob_parlay_implicita    NUMERIC(8,6),        -- product of prob_implicita_adj
    cuota_total              NUMERIC(10,4),
    n_selecciones            INTEGER,
    tiene_correlaciones      BOOLEAN DEFAULT false,
    tiene_mercados_exoticos  BOOLEAN DEFAULT false,
    nivel_confianza          TEXT CHECK (nivel_confianza IN ('ALTA','MEDIA','BAJA')),
    razon_confianza          TEXT[],              -- array of reasons
    -- Bookmaker
    casa_apuestas            TEXT,
    imagen_hash              TEXT,                -- SHA-256 prefix for dedup detection
    -- Outcome (filled by nightly job)
    resultado_parlay         TEXT CHECK (resultado_parlay IN ('GANADO','PERDIDO','PENDIENTE','ANULADO')) DEFAULT 'PENDIENTE',
    -- Timestamps
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    resolved_at              TIMESTAMPTZ
);

ALTER TABLE analisis_parlays DISABLE ROW LEVEL SECURITY;

-- ── 5. selecciones_parlay ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS selecciones_parlay (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parlay_id                UUID NOT NULL REFERENCES analisis_parlays(id) ON DELETE CASCADE,
    partido_id               UUID REFERENCES partidos(id),  -- NULL in Phase 1
    -- Raw OCR names (exactly as extracted)
    equipo_local_raw         TEXT,
    equipo_visitante_raw     TEXT,
    -- Market data
    mercado                  TEXT,    -- '1X2', 'over_under', 'btts', 'handicap', 'exotic'
    seleccion                TEXT,    -- 'home', 'draw', 'away', 'over', 'under', 'yes', 'no'
    linea                    NUMERIC(6,2),         -- for over_under / handicap (e.g. 2.5, -1.5)
    cuota                    NUMERIC(10,4),
    -- Probability outputs
    prob_implicita           NUMERIC(8,6),         -- 1/cuota
    prob_implicita_adj       NUMERIC(8,6),         -- margin-adjusted
    prob_modelo              NUMERIC(8,6),         -- from Dixon-Coles (NULL if exotic/uncovered)
    edge                     NUMERIC(8,6),         -- prob_modelo - prob_implicita_adj
    kelly_fraccion           NUMERIC(8,6),         -- fractional Kelly at 20% (NULL if edge <= 0)
    lambda_home              NUMERIC(8,4),
    lambda_away              NUMERIC(8,4),
    -- Model context at time of analysis
    features_snapshot        JSONB,               -- n_partidos, equipo_ids, model params used
    -- Quality flags
    nivel_cobertura          TEXT CHECK (nivel_cobertura IN ('ALTA','MEDIA','BAJA','NULA')),
    es_mercado_exotico       BOOLEAN DEFAULT false,
    correlaciones_detectadas JSONB,               -- array of {tipo, nota, otra_seleccion_idx}
    version_modelo           TEXT DEFAULT 'v0.2',
    -- Outcome (filled by nightly job)
    resultado_real           TEXT,                -- actual match result
    acierto                  BOOLEAN,             -- did selection win?
    -- Timestamps
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    resolved_at              TIMESTAMPTZ
);

ALTER TABLE selecciones_parlay DISABLE ROW LEVEL SECURITY;

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_selecciones_parlay_id
    ON selecciones_parlay(parlay_id);

CREATE INDEX IF NOT EXISTS idx_selecciones_pendientes
    ON selecciones_parlay(acierto)
    WHERE acierto IS NULL;

CREATE INDEX IF NOT EXISTS idx_analisis_hash
    ON analisis_parlays(imagen_hash);

CREATE INDEX IF NOT EXISTS idx_analisis_created
    ON analisis_parlays(created_at DESC);
