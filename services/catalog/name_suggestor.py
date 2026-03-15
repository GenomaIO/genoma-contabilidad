"""
name_suggestor.py — Vocabulario Semántico para Smart Catalog Builder
Genoma Contabilidad · NIIF PYMES CR (CCPA 2025)

Principio: el sistema sugiere nombres de hijos basándose en el
nombre del PADRE INMEDIATO, no en el abuelo ni en la clase raíz.

Algoritmo:
  1. Normalizar nombre del padre (minúsculas, sin tildes, sin puntuación)
  2. Buscar la keyword MÁS LARGA que aparezca en el nombre normalizado
  3. Retornar las sugerencias asociadas, excluyendo nombres ya usados
  4. Fallback: nombres genéricos "Subcuenta 01, 02, 03"
"""
import unicodedata
import re
from typing import Optional


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, sin puntuación extra."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", sin_tildes.lower()).strip()


# ─── Vocabulario semántico ────────────────────────────────────────────────────
# Clave: keyword normalizada (sin tildes, minúsculas)
# Valor: lista de nombres sugeridos para los HIJOS de una cuenta cuyo nombre
#        contiene esa keyword.
# Orden de evaluación: de clave más larga a más corta (más específica primero).
#
# REGLA DE DISEÑO:
#   - Las keywords deben ser lo suficientemente específicas para no generar
#     falsos positivos. Ej: usar "banco nacional" en lugar de solo "banco".
#   - Los nombres sugeridos usan la misma terminología del Plan General CR.
# ─────────────────────────────────────────────────────────────────────────────

SEMANTIC_VOCAB: dict[str, list[str]] = {

    # ── CLASE 1: ACTIVO ────────────────────────────────────────────────────────

    # Nivel C → DD (Efectivo y equivalentes)
    "efectivo y equivalentes":  ["Caja", "Bancos", "Inversiones Temporales ≤90 días"],
    "efectivo":                 ["Caja", "Bancos", "Inversiones Temporales ≤90 días"],

    # Nivel DD → EE (Caja)
    "caja":                     ["Caja General", "Caja Chica", "Fondo Fijo de Caja",
                                  "Caja en Dólares", "Caja en Euros"],

    # Nivel DD → EE (Bancos) — sugiere bancos CR reales
    "bancos":                   ["Banco Nacional de CR", "Banco de Costa Rica",
                                  "BAC Credomatic", "Scotiabank", "Davivienda",
                                  "Banco Promerica", "Banco BCT"],

    # Nivel EE → FF (cuando el padre es un banco específico)
    "banco nacional":           ["Cta. Corriente CRC", "Cta. de Ahorros CRC",
                                  "Depósito a Plazo CRC", "Cta. Corriente USD"],
    "banco de costa rica":      ["Cta. Corriente CRC", "Cta. de Ahorros CRC",
                                  "Cta. Corriente USD"],
    "bac credomatic":           ["Cta. Corriente CRC", "Cta. Corriente USD", "Cta. de Ahorros"],
    "scotiabank":               ["Cta. Corriente CRC", "Cta. Corriente USD"],
    "davivienda":               ["Cta. Corriente CRC", "Cta. Corriente USD"],
    "promerica":                ["Cta. Corriente CRC", "Cta. Corriente USD"],
    "bct":                      ["Cta. Corriente CRC", "Cta. Corriente USD"],

    # Nivel FF → G (cuando el padre es un tipo de cuenta bancaria)
    "cta corriente":            ["Moneda Nacional CRC", "Moneda Extranjera USD"],
    "cuenta corriente":         ["Moneda Nacional CRC", "Moneda Extranjera USD"],
    "deposito a plazo":         ["DPT CRC ≤90 días", "DPT USD ≤90 días", "DPT CRC >90 días"],

    # Inversiones temporales
    "inversiones temporales":   ["Depósitos a Plazo CRC", "Depósitos a Plazo USD",
                                  "Bonos del Gobierno", "Operaciones en Bolsa CNBV"],

    # Cuentas por cobrar
    "cuentas por cobrar":       ["Documentos Comerciales por Cobrar", "Clientes",
                                  "Funcionarios y Empleados", "Anticipo a Proveedores",
                                  "Otras Cuentas por Cobrar"],
    "clientes":                 ["Clientes Nacionales", "Clientes Extranjeros",
                                  "Clientes Gobierno", "Clientes Relacionados"],
    "documentos por cobrar":    ["Pagarés Vigentes", "Letras de Cambio", "Cheques Posfechados"],
    "anticipos proveedores":    ["Anticipos Nacionales", "Anticipos Extranjeros"],

    # Inventarios
    "inventarios":              ["Inventario de Mercancías", "Materia Prima",
                                  "Productos en Proceso", "Productos Terminados",
                                  "Materiales y Suministros"],
    "inventario":               ["Inventario de Mercancías", "Materia Prima",
                                  "Productos en Proceso", "Productos Terminados"],
    "mercaderias":              ["Mercadería Nacional", "Mercadería Importada",
                                  "Mercadería en Tránsito"],

    # Propiedades, planta y equipo
    "propiedades planta":       ["Terrenos", "Edificaciones", "Equipo de Cómputo",
                                  "Vehículos", "Equipo de Oficina", "Maquinaria"],
    "terrenos":                 ["Terreno Sede Central", "Terreno Bodega",
                                  "Terreno en Desarrollo"],
    "edificaciones":            ["Edificio Oficinas", "Bodega Industrial",
                                  "Local Comercial", "Casa Habitación Empresa"],
    "equipo de computo":        ["Laptops y PC", "Servidores", "Periféricos",
                                  "Equipos de Comunicación"],
    "vehiculos":                ["Vehículo Administrativo", "Vehículo de Reparto",
                                  "Vehículo de Ventas"],
    "maquinaria":               ["Maquinaria de Producción", "Equipo Industrial",
                                  "Equipo de Laboratorio"],

    # Depreciación acumulada
    "depreciacion acumulada":   ["Dep. Acum. Edificaciones", "Dep. Acum. Equipo Cómputo",
                                  "Dep. Acum. Vehículos", "Dep. Acum. Maquinaria"],

    # ── CLASE 2: PASIVO ────────────────────────────────────────────────────────

    # Cuentas por pagar
    "cuentas por pagar":        ["Proveedores", "Documentos por Pagar",
                                  "Anticipos de Clientes", "Otras CxP"],
    "proveedores":              ["Proveedores Nacionales", "Proveedores Extranjeros",
                                  "Proveedores Gobierno"],
    "proveedores nacionales":   ["Proveedores Bienes", "Proveedores Servicios",
                                  "Proveedores Importación"],
    "documentos por pagar":     ["Pagarés", "Letras de Cambio",
                                  "Obligaciones Negociables"],

    # Gastos acumulados
    "gastos acumulados":        ["Salarios por Pagar", "Cargas Sociales por Pagar",
                                  "IVA Débito Fiscal", "Vacaciones por Pagar",
                                  "Aguinaldo por Pagar"],
    "salarios por pagar":       ["Salarios Ordinarios", "Horas Extra",
                                  "Aguinaldo por Pagar", "Vacaciones por Pagar"],
    "cargas sociales por pagar": ["CCSS Patronal (26.33%)", "CCSS Obrero (retenido)",
                                   "INS Riesgos del Trabajo", "FCL Banco Popular",
                                   "ANDE", "JUPEMA"],

    # IVA
    "iva debito":               ["IVA Débito Contado", "IVA Débito Crédito",
                                  "IVA Diferido Por Cobrar"],
    "iva":                      ["IVA Débito Contado", "IVA Débito Crédito",
                                  "IVA Diferido Por Cobrar"],

    # Préstamos bancarios
    "prestamos bancarios":      ["Banco Nacional de CR", "Banco de Costa Rica",
                                  "BAC Credomatic", "Scotiabank", "Banco Externo"],
    "prestamo":                 ["Préstamo Hipotecario", "Préstamo Prendario",
                                  "Arrendamiento Financiero", "Sobregiro Autorizado"],

    # ── CLASE 3: PATRIMONIO ────────────────────────────────────────────────────

    "capital social":           ["Capital Suscrito y Pagado", "Capital Autorizado no Suscrito",
                                  "Capital Adicional Pagado"],
    "capital suscrito":         ["Acciones Ordinarias", "Acciones Preferentes",
                                  "Cuotas de Capital"],
    "capital adicional":        ["Prima sobre Acciones", "Donaciones de Capital",
                                  "Aportes de Socios"],
    "reservas":                 ["Reserva Legal (5%)", "Reserva Estatutaria",
                                  "Reserva Voluntaria para Expansión"],
    "resultados":               ["Utilidades del Ejercicio", "Utilidades Retenidas",
                                  "Déficit Acumulado (-)"],
    "utilidades retenidas":     ["Utilidad Ejercicio Actual", "Utilidades Ejercicios Anteriores"],

    # ── CLASE 4: INGRESOS ─────────────────────────────────────────────────────

    "ingresos por ventas":      ["Ventas Brutas", "Devoluciones y Descuentos (-)"],
    "ventas brutas":            ["Ventas de Mercancías", "Ventas de Servicios",
                                  "Ventas de Activos"],
    "ventas de mercancias":     ["Ventas Gravadas 13%", "Ventas Gravadas 4%",
                                  "Ventas Exentas", "Ventas Exportación"],
    "ventas de servicios":      ["Servicios Profesionales", "Servicios Técnicos",
                                  "Consultoría", "Mantenimiento y Soporte"],
    "ventas gravadas":          ["Producto A", "Producto B", "Producto C"],
    "devoluciones":             ["Devoluciones en Ventas", "Descuentos Comerciales",
                                  "Rebajas sobre Ventas"],
    "otros ingresos":           ["Intereses Ganados", "Alquileres Ganados",
                                  "Utilidad en Venta de Activos",
                                  "Diferencial Cambiario Ganado", "Dividendos Recibidos"],
    "intereses ganados":        ["Intereses Depósitos CRC", "Intereses Depósitos USD",
                                  "Intereses Préstamos Otorgados"],

    # ── CLASE 5: COSTOS Y GASTOS ──────────────────────────────────────────────

    # Costo de ventas
    "costo de ventas":          ["Inventario Inicial", "Compras Brutas",
                                  "Fletes sobre Compras", "Seguros sobre Compras",
                                  "Devoluciones en Compras (-)", "Inventario Final (-)"],
    "compras brutas":           ["Compras Gravadas 13%", "Compras Gravadas 4%",
                                  "Compras Exentas", "Compras Importación"],

    # Gastos de personal
    "gastos de personal":       ["Salarios y Sueldos", "Cargas Sociales",
                                  "Capacitación y Desarrollo", "Alimentación y Transporte"],
    "salarios y sueldos":       ["Salarios Ordinarios", "Horas Extra",
                                  "Aguinaldo", "Vacaciones", "Impuesto Renta Retenido"],
    "salarios ordinarios":      ["Salarios Administrativos", "Salarios Operativos",
                                  "Salarios Ventas"],
    "cargas sociales":          ["CCSS Patronal (26.33%)", "INS Riesgos del Trabajo",
                                  "FCL Banco Popular", "ANDE", "JUPEMA"],

    # Gastos generales / administrativos
    "gastos generales":         ["Alquileres", "Servicios Públicos", "Telecomunicaciones",
                                  "Materiales de Oficina", "Depreciaciones", "Seguros",
                                  "Honorarios Profesionales"],
    "alquileres":               ["Alquiler Oficina Sede Central", "Alquiler Bodega",
                                  "Alquiler Equipo", "Arrendamiento Local"],
    "servicios publicos":       ["Energía Eléctrica (ICE)", "Agua Potable (AyA)",
                                  "Recolección Basura"],
    "telecomunicaciones":       ["Internet Empresarial", "Telefonía Fija",
                                  "Telefonía Móvil Corporativa", "Correo y Mensajería Digital"],
    "depreciaciones":           ["Dep. Edificaciones (50 años)", "Dep. Equipo Cómputo (5 años)",
                                  "Dep. Vehículos (10 años)", "Dep. Maquinaria (10 años)",
                                  "Dep. Mejoras Locales Arrendados"],
    "seguros":                  ["Seguro de Edificio", "Seguro de Vehículos",
                                  "Seguro de Equipo", "Seguro de Responsabilidad Civil"],
    "honorarios":               ["Honorarios Contables", "Honorarios Legales",
                                  "Honorarios Consultoría", "Auditoría Externa"],

    # Gastos de ventas
    "gastos de ventas":         ["Gastos de Personal Ventas", "Publicidad y Mercadeo",
                                  "Distribución y Logística", "Comisiones"],
    "publicidad":               ["Publicidad Digital", "Publicidad Impresa",
                                  "Redes Sociales y Marketing", "Ferias y Eventos",
                                  "Material POP"],
    "distribucion":             ["Fletes sobre Ventas", "Empaques y Embalajes",
                                  "Combustible Vehículos Reparto"],

    # Gastos financieros
    "gastos financieros":       ["Intereses Bancarios", "Comisiones Bancarias",
                                  "Diferencial Cambiario Perdido", "Multas y Recargos"],
    "intereses bancarios":      ["Intereses Préstamos CRC", "Intereses Préstamos USD",
                                  "Intereses Tarjetas"],
}

# Ordenamos de más larga a más corta para que el match sea siempre el más específico
_VOCAB_SORTED = sorted(SEMANTIC_VOCAB.keys(), key=len, reverse=True)


def suggest_child_names(
    parent_name: str,
    existing_child_names: Optional[list[str]] = None,
    max_suggestions: int = 6,
) -> list[str]:
    """
    Sugiere nombres para los hijos de una cuenta dado el nombre del padre.

    Args:
        parent_name:          Nombre del padre inmediato (ej: "Bancos")
        existing_child_names: Nombres ya existentes como hijos (se excluyen)
        max_suggestions:      Máximo de sugerencias a retornar

    Returns:
        Lista de nombres sugeridos (sin los ya existentes)
    """
    norm = _normalizar(parent_name)
    excluded = set(_normalizar(n) for n in (existing_child_names or []))

    for keyword in _VOCAB_SORTED:
        if keyword in norm:
            raw = SEMANTIC_VOCAB[keyword]
            filtered = [
                name for name in raw
                if _normalizar(name) not in excluded
            ]
            return filtered[:max_suggestions]

    # Fallback genérico
    fallback = [f"Subcuenta {str(i+1).zfill(2)}" for i in range(max_suggestions)
                if _normalizar(f"Subcuenta {str(i+1).zfill(2)}") not in excluded]
    return fallback[:max_suggestions]


def next_child_code(parent_code: str, existing_child_codes: list[str]) -> str:
    """
    Calcula el siguiente código hijo libre dado el padre y los hijos existentes.

    Reglas:
    - Si el padre tiene código dotted (1101.01), los hijos serán 1101.01.01, .02, etc.
    - Si el padre es un entero de 4 dígitos y sus hijos son enteros, incrementa por pasos.
    - Siempre usa formato .NN (dos dígitos con padding) para niveles dotted.
    """
    if not existing_child_codes:
        # Primer hijo
        if "." in parent_code:
            return f"{parent_code}.01"
        base = int(parent_code)
        step = 100 if base % 1000 == 0 else 1
        return str(base + step)

    # Hijos dotted: extraer el último segmento y buscar el máximo
    first_child = existing_child_codes[0]
    if "." in first_child:
        nums = [
            int(c.split(".")[-1])
            for c in existing_child_codes
            if c.split(".")[-1].isdigit()
        ]
        nxt = max(nums) + 1 if nums else 1
        return f"{parent_code}.{str(nxt).zfill(2)}"

    # Hijos enteros
    nums = [int(c) for c in existing_child_codes if c.isdigit()]
    if not nums:
        return str(int(parent_code) + 1)

    all_hundreds = all(n % 100 == 0 for n in nums)
    if all_hundreds:
        base = int(parent_code)
        taken = set(nums)
        candidate = base + 100
        while candidate in taken and candidate < base + 1000:
            candidate += 100
        return str(candidate)

    return str(max(nums) + 1)
