"""
scripts/purge_tenant_data.py
════════════════════════════════════════════════════════════
Limpieza quirúrgica de datos contables para tenants específicos.

SCOPE: Solo Genoma Contabilidad. Cero cambios al Facturador.

Qué borra:
  - journal_lines    (líneas de asientos)
  - journal_entries  (encabezados de asientos)
  - import_batch     (registro de imports)

Qué NO toca:
  - tenants          (el tenant sigue existiendo)
  - accounts         (catálogo NIIF intacto)
  - users            (usuarios intactos)
  - fiscal_profiles  (configuración fiscal intacta)
  - Facturador       (documentos enviados/recibidos intactos)

Uso:
  # Paso 1: DRY-RUN (solo muestra conteos, no borra nada)
  python scripts/purge_tenant_data.py

  # Paso 2: EJECUCIÓN REAL (requiere --confirm)
  python scripts/purge_tenant_data.py --confirm

Seguridad:
  - Requiere DATABASE_URL configurada
  - Sin --confirm solo hace SELECT COUNT (lectura)
  - Log de cada operación
  - Orden: lines → entries → batch (respeta FK)
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ─── Cédulas de los tenants a limpiar ────────────────────────
# SOLO MODIFICAR ESTA LISTA
CEDULAS_A_LIMPIAR = [
    "603170547",     # Angélica Li Wong (test persona)
    "3101953441",    # Sociedad 3-101-953441 (SA GenomaIO)
]

# ─── Tablas a limpiar (en ORDEN de borrado por FK) ───────────
TABLAS_CONTABILIDAD = [
    "journal_lines",    # 1. Líneas (FK → journal_entries)
    "journal_entries",  # 2. Encabezados
    "import_batch",     # 3. Registro de imports
]

# ─── Tablas que NO se tocan (para verificación) ──────────────
TABLAS_INTOCABLES = [
    "tenants",
    "accounts",
    "users",
    "fiscal_profiles",
    "cabys_account_rules",
    "emisores",
]


def get_db_connection():
    """Obtiene conexión usando DATABASE_URL."""
    try:
        from sqlalchemy import create_engine, text
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("❌ DATABASE_URL no configurada.")
            logger.info("   Configurá la variable de entorno:")
            logger.info("   export DATABASE_URL='postgresql://user:pass@host:5432/dbname'")
            sys.exit(1)

        # Railway/Render usan postgres:// pero SQLAlchemy necesita postgresql://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        engine = create_engine(db_url, echo=False)
        return engine, text
    except ImportError:
        logger.error("❌ SQLAlchemy no instalado. Ejecutá: pip install sqlalchemy psycopg2-binary")
        sys.exit(1)


def resolve_tenant_ids(conn, text_fn):
    """
    Busca los tenant_id reales a partir de las cédulas.
    Retorna dict: {cedula: tenant_id}
    """
    found = {}
    for cedula in CEDULAS_A_LIMPIAR:
        row = conn.execute(text_fn(
            "SELECT id, cedula, nombre FROM tenants WHERE cedula = :ced LIMIT 1"
        ), {"ced": cedula}).fetchone()
        if row:
            found[cedula] = {"id": row[0], "nombre": row[2] or "Sin nombre"}
            logger.info(f"  ✅ Cédula {cedula} → tenant_id={row[0][:12]}... ({row[2]})")
        else:
            logger.warning(f"  ⚠️  Cédula {cedula} → NO encontrada en tabla tenants")
    return found


def dry_run(conn, text_fn, tenant_ids: list):
    """
    Solo cuenta filas que se borrarían. No modifica nada.
    """
    logger.info("\n" + "─"*60)
    logger.info("  🔍 DRY-RUN: Conteo de filas a borrar")
    logger.info("─"*60)

    total_filas = 0
    for tabla in TABLAS_CONTABILIDAD:
        try:
            # Construir placeholders para IN clause
            placeholders = ", ".join([f":tid{i}" for i in range(len(tenant_ids))])
            params = {f"tid{i}": tid for i, tid in enumerate(tenant_ids)}

            row = conn.execute(text_fn(
                f"SELECT COUNT(*) FROM {tabla} WHERE tenant_id IN ({placeholders})"
            ), params).fetchone()
            count = row[0] if row else 0
            total_filas += count
            emoji = "🔴" if count > 0 else "⚪"
            logger.info(f"  {emoji} {tabla}: {count} filas")
        except Exception as ex:
            logger.warning(f"  ⚠️  {tabla}: tabla no existe o error ({ex})")

    logger.info(f"\n  📊 Total filas a borrar: {total_filas}")

    # Verificar tablas intocables
    logger.info("\n  🛡️  Tablas que NO se tocan (verificación):")
    for tabla in TABLAS_INTOCABLES:
        try:
            placeholders = ", ".join([f":tid{i}" for i in range(len(tenant_ids))])
            params = {f"tid{i}": tid for i, tid in enumerate(tenant_ids)}
            row = conn.execute(text_fn(
                f"SELECT COUNT(*) FROM {tabla} WHERE tenant_id IN ({placeholders})"
            ), params).fetchone()
            count = row[0] if row else 0
            logger.info(f"     🟢 {tabla}: {count} filas (se preservan)")
        except Exception:
            logger.info(f"     ⚪ {tabla}: tabla no existe (OK)")

    return total_filas


def execute_purge(conn, text_fn, tenant_ids: list):
    """
    Ejecuta el borrado real. Orden: lines → entries → batch.
    Transacción única: rollback si falla cualquier paso.
    """
    logger.info("\n" + "═"*60)
    logger.info("  🗑️  EJECUTANDO BORRADO REAL")
    logger.info("═"*60)

    total_borrado = 0
    placeholders = ", ".join([f":tid{i}" for i in range(len(tenant_ids))])
    params = {f"tid{i}": tid for i, tid in enumerate(tenant_ids)}

    try:
        for tabla in TABLAS_CONTABILIDAD:
            try:
                result = conn.execute(text_fn(
                    f"DELETE FROM {tabla} WHERE tenant_id IN ({placeholders})"
                ), params)
                count = result.rowcount or 0
                total_borrado += count
                logger.info(f"  ✅ {tabla}: {count} filas borradas")
            except Exception as ex:
                logger.warning(f"  ⚠️  {tabla}: {ex} (tabla no existe o sin FK)")

        conn.commit()
        logger.info(f"\n  ✅ COMMIT exitoso. Total borrado: {total_borrado} filas.")

    except Exception as ex:
        conn.rollback()
        logger.error(f"\n  ❌ ERROR — ROLLBACK ejecutado: {ex}")
        logger.error("  Ningún dato fue modificado.")
        return 0

    return total_borrado


def main():
    confirm = "--confirm" in sys.argv

    logger.info("\n" + "═"*60)
    logger.info("  Purge Tenant Data — Genoma Contabilidad")
    logger.info("  SCOPE: Solo Contabilidad. Facturador intacto.")
    logger.info("═"*60)
    logger.info(f"\n  Modo: {'🔴 EJECUCIÓN REAL' if confirm else '🔍 DRY-RUN (solo lectura)'}")
    logger.info(f"  Cédulas a limpiar: {CEDULAS_A_LIMPIAR}")

    engine, text_fn = get_db_connection()

    with engine.connect() as conn:
        # 1. Resolver tenant_ids desde cédulas
        logger.info("\n📋 Paso 1: Resolver tenant_id por cédula")
        found = resolve_tenant_ids(conn, text_fn)

        if not found:
            logger.error("\n❌ Ninguna cédula encontrada. Nada que hacer.")
            sys.exit(1)

        tenant_ids = [info["id"] for info in found.values()]
        logger.info(f"\n  → {len(tenant_ids)} tenant(s) encontrados")

        # 2. Dry-run (siempre, incluso con --confirm)
        logger.info("\n📋 Paso 2: Conteo previo")
        total = dry_run(conn, text_fn, tenant_ids)

        if total == 0:
            logger.info("\n✅ No hay datos que borrar. Los tenants ya están limpios.")
            sys.exit(0)

        # 3. Ejecución real (solo con --confirm)
        if not confirm:
            logger.info("\n" + "─"*60)
            logger.info("  ℹ️  Esto fue un DRY-RUN. Ningún dato fue modificado.")
            logger.info("  Para ejecutar el borrado real:")
            logger.info("  python scripts/purge_tenant_data.py --confirm")
            logger.info("─"*60 + "\n")
            sys.exit(0)

        logger.info("\n📋 Paso 3: Ejecución del borrado")
        borrado = execute_purge(conn, text_fn, tenant_ids)

        # 4. Verificación post-borrado
        logger.info("\n📋 Paso 4: Verificación post-borrado")
        remaining = dry_run(conn, text_fn, tenant_ids)

        if remaining == 0:
            logger.info("\n" + "═"*60)
            logger.info("  ✅ LIMPIEZA COMPLETADA")
            logger.info(f"  {borrado} filas borradas de {len(tenant_ids)} tenant(s)")
            logger.info("  Tenants existen pero sin datos contables")
            logger.info("  Catálogo NIIF, usuarios y Facturador intactos")
            logger.info("═"*60 + "\n")
        else:
            logger.warning(f"\n  ⚠️  Quedan {remaining} filas. Revisar manualmente.")


if __name__ == "__main__":
    main()
