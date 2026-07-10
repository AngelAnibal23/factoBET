# ADR-0002: Uso de opencode por agotamiento del plan Pro en Claude Code

**Fecha:** 2026-06-27
**Contexto:** El plan Pro de Claude Code se agotó, por lo que se migró temporalmente a opencode como herramienta de planificación y ejecución.

**Decisión:** opencode se utilizó para planificar y redactar el plan piloto de cierre del SoT por jugador (`opencode-plan-cerrar-sot-por-jugador.md`), aprovechando su modo solo lectura (plan) y modo build para generar el documento.

**Consecuencias:**
- El plan fue diseñado por opencode pero será ejecutado por otro agente.
- El plan será auditado por un tercer agente.
- Se establece un precedente de uso de opencode como herramienta de planificación cuando Claude Code no está disponible.

**Archivo generado:** `opencode-plan-cerrar-sot-por-jugador.md`

---

**Adéndum (2026-07-09):** El plan generado fue descartado por Angel (era un
ejercicio de prueba de opencode, no un plan vinculante) y el archivo se
eliminó del working tree. La operación de cierre del SoT por-jugador siguió
el plan original del repo (`docs/superpowers/plans/2026-06-25-tiros-al-arco-por-jugador.md`).
Este ADR se conserva como registro del precedente: opencode como herramienta
de respaldo cuando Claude Code no está disponible.
