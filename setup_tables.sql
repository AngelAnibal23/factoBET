-- HELPBETOR Phase 1 — Table setup
-- Run this in Supabase SQL Editor

-- ── 1. ligas ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ligas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id INTEGER UNIQUE,
    nombre          TEXT NOT NULL,
    pais            TEXT,
    nivel_cobertura TEXT CHECK (nivel_cobertura IN ('ALTA','MEDIA','BAJA','NULA')),
    modelo          TEXT,
    temporadas_disponibles INTEGER,
    deporte         TEXT DEFAULT 'futbol',
    activa          BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE ligas DISABLE ROW LEVEL SECURITY;

-- ── 2. equipos ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS equipos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id INTEGER UNIQUE,
    nombre_oficial  TEXT NOT NULL,
    aliases         TEXT[],
    liga_id         UUID REFERENCES ligas(id),
    pais            TEXT,
    ciudad          TEXT,
    estadio         TEXT,
    altitud_msnm    INTEGER,
    activo          BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE equipos DISABLE ROW LEVEL SECURITY;

-- ── 3. partidos ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS partidos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_football_id     INTEGER UNIQUE,
    liga_id             UUID REFERENCES ligas(id),
    equipo_local_id     UUID REFERENCES equipos(id),
    equipo_visitante_id UUID REFERENCES equipos(id),
    fecha               TIMESTAMPTZ NOT NULL,
    temporada           TEXT,
    jornada             TEXT,
    estado              TEXT CHECK (estado IN ('SCHEDULED','LIVE','FINISHED','POSTPONED','CANCELLED','SUSPENDED')),
    goles_local         INTEGER,
    goles_visitante     INTEGER,
    resultado           TEXT CHECK (resultado IN ('HOME','DRAW','AWAY')),
    -- Halftime
    goles_ht_local      INTEGER,
    goles_ht_visitante  INTEGER,
    -- Raw stats (populated later from /fixtures/statistics)
    tiros_local         INTEGER,
    tiros_puerta_local  INTEGER,
    tiros_visitante     INTEGER,
    tiros_puerta_vis    INTEGER,
    posesion_local      NUMERIC(5,2),
    -- xG (NULL for v1.0 — Liga 1 not available)
    xg_local            NUMERIC(5,3),
    xg_visitante        NUMERIC(5,3),
    -- Venue
    estadio_nombre      TEXT,
    arbitro             TEXT,
    -- Metadata
    datos_completos     BOOLEAN DEFAULT false,
    fuente              TEXT DEFAULT 'api_football',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE partidos DISABLE ROW LEVEL SECURITY;

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_partidos_liga_fecha
    ON partidos(liga_id, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_partidos_equipo_local
    ON partidos(equipo_local_id, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_partidos_equipo_vis
    ON partidos(equipo_visitante_id, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_partidos_temporada
    ON partidos(temporada);
