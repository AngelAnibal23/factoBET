"""Modelo de conteos (córners/tarjetas/tiros) de la Capa 2.

Multiplicativo ataque/defensa por equipo, estimado por método de momentos con
shrinkage empírico-Bayes (robusto a muestra fina), distribución Negative Binomial
para over/under (Poisson como caso límite d<=1). NO lee red al importar: funciones
puras testeables.
"""

from scipy.stats import poisson, nbinom

METRICAS = ("corners", "cards", "shots", "sot")
COL_A_METRICA = {"corners": "corners", "crd_y": "cards", "sh": "shots", "sot": "sot"}


def estimar_metrica(partidos: list[dict], k: float = 5.0) -> dict:
    """Estima bases de liga y multiplicadores atk/def por equipo para UNA métrica.

    partidos: lista de {home, away, val_home, val_away} (valores de la métrica).
    k: fuerza del prior de shrinkage (nº de "partidos virtuales" en la media de liga).

    Devuelve {base_home, base_away, atk:{equipo:mult}, def:{equipo:mult}}.
    El equipo promedio tiene atk=def=1.0. atk = cuánto GENERA; def = cuánto CONCEDE.
    """
    if not partidos:
        return {"base_home": 0.0, "base_away": 0.0, "atk": {}, "def": {}}

    base_home = sum(p["val_home"] for p in partidos) / len(partidos)
    base_away = sum(p["val_away"] for p in partidos) / len(partidos)
    base_home = max(base_home, 1e-6)
    base_away = max(base_away, 1e-6)

    # Ratios crudos normalizados por sede: cuánto generó/concedió un equipo
    # respecto a la base de la sede en que jugó cada partido.
    gen = {}   # equipo -> [ratios de generación]
    con = {}   # equipo -> [ratios de concesión]
    for p in partidos:
        h, a = p["home"], p["away"]
        gen.setdefault(h, []).append(p["val_home"] / base_home)
        gen.setdefault(a, []).append(p["val_away"] / base_away)
        # concede = lo que generó el rival, normalizado por la sede del rival
        con.setdefault(h, []).append(p["val_away"] / base_away)
        con.setdefault(a, []).append(p["val_home"] / base_home)

    def _shrink(ratios):
        n = len(ratios)
        return (sum(ratios) + k * 1.0) / (n + k)   # media bayesiana hacia 1.0

    atk = {t: _shrink(r) for t, r in gen.items()}
    dfn = {t: _shrink(r) for t, r in con.items()}
    return {"base_home": base_home, "base_away": base_away, "atk": atk, "def": dfn}


class CountsModel:
    """Predictor de conteos con params congelados. params: {metrica: {base_home,
    base_away, factor_neutral, disp, atk:{equipo:mult}, def:{equipo:mult}}}.

    Solo contiene las métricas que pasaron el gate para esta liga; el motor
    consulta `tiene(metrica)` antes de usarla.
    """

    @classmethod
    def from_params(cls, params: dict) -> "CountsModel":
        m = cls()
        m.params = params
        return m

    def tiene(self, metrica: str) -> bool:
        return metrica in self.params

    def lambdas(self, metrica: str, home: str, away: str, neutral: bool) -> tuple[float, float]:
        p = self.params[metrica]
        atk, dfn = p["atk"], p["def"]
        ah = atk.get(home, 1.0)
        aa = atk.get(away, 1.0)
        dh = dfn.get(home, 1.0)
        da = dfn.get(away, 1.0)
        if neutral:
            base = 0.5 * (p["base_home"] + p["base_away"]) * p.get("factor_neutral", 1.0)
            lh = base * ah * da
            la = base * aa * dh
        else:
            lh = p["base_home"] * ah * da
            la = p["base_away"] * aa * dh
        return lh, la

    def prob_over_under(self, metrica: str, scope: str, sel: str, linea: float,
                        home: str, away: str, neutral: bool) -> float:
        """P(over/under) de la métrica en el scope dado. scope: total|home|away.

        Negative Binomial con dispersión `d` por métrica (Poisson si d<=1). Para
        media `lam` y dispersión `d>1`: r=lam/(d-1), p=1/d, X~NegBin(r,p) (media lam).
        """
        lh, la = self.lambdas(metrica, home, away, neutral)
        if scope == "home":
            lam = lh
        elif scope == "away":
            lam = la
        elif scope == "total":
            lam = lh + la
        else:
            raise ValueError(f"scope inválido: {scope!r}")
        d = self.params[metrica].get("disp", 1.0)
        k = int(linea)            # over 9.5 -> P(X>=10) = 1 - cdf(9)
        if d > 1.0 + 1e-9:
            r, p = lam / (d - 1.0), 1.0 / d
            p_over = 1.0 - nbinom.cdf(k, r, p)
        else:
            p_over = 1.0 - poisson.cdf(k, lam)
        return p_over if sel == "over" else (1.0 - p_over)
