"""
Carga de alias ES->EN para las selecciones nacionales (liga Internacional).

El dataset martj42 usa nombres en INGLES ("Germany", "United States",
"South Korea"...). El OCR de boletos peruanos los entrega en ESPAÑOL
("Alemania", "Estados Unidos", "Corea del Sur"...). El validator ya soporta
matchear por `aliases`; este script solo CARGA esos alias en `equipos`.

Updater idempotente: para cada seleccion hace MERGE de los alias nuevos con los
existentes (sin duplicar, sin borrar). Re-ejecutarlo es seguro.

Cobertura: las ~48 del Mundial 2026 + potencias habituales cuyo nombre español
difiere del inglés.

Uso:
    python set_intl_aliases.py
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

LIGA_INTERNACIONAL_ID = "cc1ffe11-7ba1-4a86-9d35-e6eedbe2ec38"

# Clave = nombre_oficial EXACTO del dataset (martj42, inglés).
# Valor  = lista de alias en español tal como pueden venir del OCR.
ALIAS_ES = {
    # ── Anfitriones 2026 ──
    "United States": ["Estados Unidos", "EEUU", "EE.UU.", "USA"],
    "Mexico": ["México"],
    "Canada": ["Canadá"],
    # ── UEFA / potencias europeas ──
    "France": ["Francia"],
    "Germany": ["Alemania"],
    "Spain": ["España"],
    "England": ["Inglaterra"],
    "Italy": ["Italia"],
    "Netherlands": ["Países Bajos", "Holanda"],
    "Belgium": ["Bélgica"],
    "Portugal": ["Portugal"],
    "Croatia": ["Croacia"],
    "Switzerland": ["Suiza"],
    "Denmark": ["Dinamarca"],
    "Poland": ["Polonia"],
    "Sweden": ["Suecia"],
    "Austria": ["Austria"],
    "Serbia": ["Serbia"],
    "Wales": ["Gales"],
    "Scotland": ["Escocia"],
    "Norway": ["Noruega"],
    "Czech Republic": ["República Checa", "Chequia"],
    "Turkey": ["Turquía", "Turkiye", "Türkiye"],
    "Greece": ["Grecia"],
    "Ukraine": ["Ucrania"],
    "Hungary": ["Hungría"],
    "Romania": ["Rumania", "Rumanía"],
    "Republic of Ireland": ["Irlanda", "República de Irlanda"],
    "Northern Ireland": ["Irlanda del Norte"],
    "Slovakia": ["Eslovaquia"],
    "Slovenia": ["Eslovenia"],
    "Finland": ["Finlandia"],
    "Russia": ["Rusia"],
    # ── CONMEBOL ──
    "Brazil": ["Brasil"],
    "Argentina": ["Argentina"],
    "Uruguay": ["Uruguay"],
    "Colombia": ["Colombia"],
    "Chile": ["Chile"],
    "Peru": ["Perú"],
    "Ecuador": ["Ecuador"],
    "Paraguay": ["Paraguay"],
    "Bolivia": ["Bolivia"],
    "Venezuela": ["Venezuela"],
    # ── CONCACAF ──
    "Costa Rica": ["Costa Rica"],
    "Panama": ["Panamá"],
    "Honduras": ["Honduras"],
    "Jamaica": ["Jamaica"],
    "Haiti": ["Haití"],
    "El Salvador": ["El Salvador"],
    "Trinidad and Tobago": ["Trinidad y Tobago"],
    "Curaçao": ["Curazao", "Curacao"],
    # ── AFC ──
    "Japan": ["Japón"],
    "South Korea": ["Corea del Sur", "Corea"],
    "North Korea": ["Corea del Norte"],
    "Saudi Arabia": ["Arabia Saudita", "Arabia Saudí"],
    "Iran": ["Irán"],
    "Australia": ["Australia"],
    "Qatar": ["Catar", "Qatar"],
    "Iraq": ["Irak"],
    "United Arab Emirates": ["Emiratos Árabes Unidos", "Emiratos"],
    "Uzbekistan": ["Uzbekistán"],
    "Jordan": ["Jordania"],
    "China": ["China", "China PR"],
    # ── CAF ──
    "Morocco": ["Marruecos"],
    "Senegal": ["Senegal"],
    "Tunisia": ["Túnez"],
    "Egypt": ["Egipto"],
    "Algeria": ["Argelia"],
    "Nigeria": ["Nigeria"],
    "Ghana": ["Ghana"],
    "Cameroon": ["Camerún"],
    "Ivory Coast": ["Costa de Marfil"],
    "South Africa": ["Sudáfrica"],
    "Mali": ["Malí"],
    "Cape Verde": ["Cabo Verde"],
    "DR Congo": ["RD Congo", "República Democrática del Congo", "Congo"],
    # ── OFC ──
    "New Zealand": ["Nueva Zelanda", "Nueva Zelandia"],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n" + "=" * 60)
    print("HELPBETOR — CARGA DE ALIAS ES->EN (liga Internacional)")
    print("=" * 60)

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    equipos = (
        sb.table("equipos")
        .select("id, nombre_oficial, aliases")
        .eq("liga_id", LIGA_INTERNACIONAL_ID)
        .execute()
        .data
    )
    by_name = {e["nombre_oficial"]: e for e in equipos}
    print(f"\nSelecciones en la liga Internacional: {len(equipos)}")

    actualizados = 0
    sin_cambio = 0
    no_encontrados = []

    for nombre, nuevos in ALIAS_ES.items():
        e = by_name.get(nombre)
        if e is None:
            no_encontrados.append(nombre)
            continue

        existentes = e.get("aliases") or []
        # merge sin duplicar (case-insensitive), preservando los existentes
        vistos = {a.lower() for a in existentes}
        merged = list(existentes)
        for a in nuevos:
            if a.lower() not in vistos:
                merged.append(a)
                vistos.add(a.lower())

        if merged == existentes:
            sin_cambio += 1
            continue

        sb.table("equipos").update({"aliases": merged}).eq("id", e["id"]).execute()
        actualizados += 1

    print(f"\n  Actualizados   : {actualizados}")
    print(f"  Sin cambio     : {sin_cambio} (ya tenían los alias)")
    if no_encontrados:
        print(f"  No encontrados : {len(no_encontrados)} (no están en el dataset)")
        print(f"    {', '.join(no_encontrados)}")
    print("\n✅ Alias cargados.")
    print("=" * 60)


if __name__ == "__main__":
    main()
