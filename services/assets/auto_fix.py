"""
services/assets/auto_fix.py
═══════════════════════════════════════════════════════════════════════
Auto-corrección de cuentas contables en Activos Fijos
═══════════════════════════════════════════════════════════════════════

Se ejecuta al arrancar el servidor, ANTES de startup_depreciation_recovery.
Flujo en cada arranque (idempotente):

  1. Para cada par de corrección conocido:
     - Busca activos con (dep_gasto_code=old_gasto, dep_acum_code=old_acum)
     - Voidea todos sus DRAFTs de depreciación incorrectos
     - Actualiza los códigos a los valores correctos

  2. startup_depreciation_recovery() se encarga de regenerar los DRAFTs
     con los nuevos códigos correctos.

─────────────────────────────────────────────────────────────────────
CÓMO AGREGAR CORRECCIONES FUTURAS:

  Agrega una tupla a KNOWN_BAD_ACCOUNT_PAIRS:
  (old_dep_gasto, old_dep_acum, new_dep_gasto, new_dep_acum, descripcion)
─────────────────────────────────────────────────────────────────────

NOTA SOBRE FORMATO DE CÓDIGOS:
  El catálogo y la BD almacenan los códigos en formato NO-DOTTED:
    1202.03 = Dep. Acum. Vehículos   (display: 1.2.2.03)
    5210.03 = Gasto Dep. Vehículos   (display: 5.2.10.03)
  Los valores de este archivo DEBEN usar el formato no-dotted.
─────────────────────────────────────────────────────────────────────
"""

import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("genoma.assets.auto_fix")


# ── Correcciones conocidas ────────────────────────────────────────────
#
# Formato: (old_dep_gasto, old_dep_acum, new_dep_gasto, new_dep_acum, label)
#
# Usa siempre el formato NO-DOTTED (como el catálogo: 1202.03, 5210.03).
# El display dotted (1.2.2.03, 5.2.10.03) es solo visual.
#
KNOWN_BAD_ACCOUNT_PAIRS: list[tuple] = [
    (
        "5301.01",  # ← Gasto incorrecto (no es cuenta de depreciación)
        "1202.04",  # ← Dep. Acum. Mobiliario (incorrecto para Vehículos)
        "5210.03",  # → Gasto Dep. — Vehículos y Medios de Transporte (no-dotted)
        "1202.03",  # → Dep. Acum. — Vehículos y Medios de Transporte (no-dotted)
        "Vehículos: 5301.01/1202.04 → 5210.03/1202.03",
    ),
    # ── Agrega aquí nuevas correcciones si se descubren más casos ────
    # ("old_gasto", "old_acum", "new_gasto", "new_acum", "descripcion"),
]


# ── Función principal ─────────────────────────────────────────────────

def fix_bad_depreciation_accounts(db: Session) -> dict:
    """
    Detecta y corrige automáticamente activos con cuentas de depreciación
    semánticamente incorrectas según KNOWN_BAD_ACCOUNT_PAIRS.

    Devuelve resumen: {fixed_assets, voided_drafts, corrections}
    """
    total_fixed   = 0
    total_voided  = 0
    corrections   = []

    for (old_gasto, old_acum, new_gasto, new_acum, label) in KNOWN_BAD_ACCOUNT_PAIRS:

        # ── Buscar activos afectados (multi-tenant) ───────────────────
        affected = db.execute(text("""
            SELECT id, tenant_id, nombre, dep_gasto_code, dep_acum_code
            FROM fixed_assets
            WHERE dep_gasto_code = :old_g
              AND dep_acum_code  = :old_a
        """), {"old_g": old_gasto, "old_a": old_acum}).fetchall()

        if not affected:
            logger.debug(f"AutoFix: sin activos con {label} — OK")
            continue

        logger.warning(
            f"⚠️  AutoFix: {len(affected)} activo(s) con cuentas incorrectas: {label}"
        )

        for row in affected:
            asset_id  = row.id
            tenant_id = row.tenant_id
            nombre    = row.nombre

            # ── Void DRAFTs incorrectos de este activo ────────────────
            draft_result = db.execute(text("""
                UPDATE journal_entries
                SET status = 'VOIDED'
                WHERE tenant_id = :tid
                  AND source     = 'DEPRECIACION'
                  AND status     = 'DRAFT'
                  AND id IN (
                    SELECT DISTINCT entry_id
                    FROM journal_lines
                    WHERE tenant_id   = :tid
                      AND account_code = :old_g
                  )
            """), {"tid": tenant_id, "old_g": old_gasto})

            voided_count = draft_result.rowcount or 0
            total_voided += voided_count

            # ── Actualizar cuentas en fixed_assets ────────────────────
            db.execute(text("""
                UPDATE fixed_assets
                SET dep_gasto_code = :new_g,
                    dep_acum_code  = :new_a
                WHERE id        = :aid
                  AND tenant_id = :tid
            """), {
                "new_g": new_gasto, "new_a": new_acum,
                "aid": asset_id, "tid": tenant_id,
            })

            total_fixed += 1
            logger.info(
                f"✅ AutoFix [{tenant_id[:8]}] '{nombre}': "
                f"{old_gasto}/{old_acum} → {new_gasto}/{new_acum} "
                f"| {voided_count} DRAFT(s) anulado(s)"
            )
            corrections.append({
                "asset_id":  asset_id,
                "nombre":    nombre,
                "tenant_id": tenant_id,
                "old":       f"{old_gasto}/{old_acum}",
                "new":       f"{new_gasto}/{new_acum}",
                "voided":    voided_count,
            })

    if total_fixed > 0:
        db.commit()
        logger.info(
            f"✅ AutoFix completo: {total_fixed} activo(s) corregido(s), "
            f"{total_voided} DRAFT(s) anulado(s). "
            f"startup_depreciation_recovery regenerará los DRAFTs correctos."
        )
    else:
        logger.info("✅ AutoFix: sin activos con cuentas incorrectas conocidas")

    return {
        "fixed_assets":  total_fixed,
        "voided_drafts": total_voided,
        "corrections":   corrections,
    }
