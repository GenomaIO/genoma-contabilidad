/**
 * LibrosDigitales.jsx — Módulo de Libros Contables Digitales (Hacienda CR)
 *
 * Libros obligatorios (Art. 51 Ley Renta · Código Comercio · CNPT Art. 128):
 *   📋 Libro Diario    — asientos cronológicos
 *   📒 Libro Mayor     — T-account por cuenta
 *   ⚖️ Inventarios y Balances — balance de comprobación
 *
 * Solo disponibles cuando el período está en estado CLOSED.
 * Inalterabilidad: el backend devolverá 423 si el período aún no está cerrado.
 */
import { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'

const MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

function ymToLabel(ym) {
    const [y, m] = ym.split('-')
    return `${MESES[parseInt(m)]} ${y}`
}

function formatMoney(v) {
    return (v || 0).toLocaleString('es-CR', { minimumFractionDigits: 2 })
}

function downloadCSV(filename, headers, rows) {
    const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`
    const csv = [headers.join(','), ...rows.map(r => r.map(esc).join(','))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv' }))
    a.download = filename; a.click()
}

function printBook(title, tenant, ym, bodyHtml) {
    const w = window.open('', '_blank', 'width=900,height=700')
    w.document.write(`<!DOCTYPE html><html><head><title>${title}</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; color: #111; margin: 28px; font-size: 11px; }
        h1 { font-size: 15px; text-align: center; margin-bottom: 2px; }
        h2 { font-size: 12px; text-align: center; color: #555; margin-bottom: 14px; }
        .meta { text-align: center; color: #777; font-size: 10px; margin-bottom 16px; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; }
        th { background: #f3f3f3; padding: 5px 8px; text-align: left; border: 1px solid #ccc; font-size: 10px; }
        td { padding: 4px 8px; border: 1px solid #ddd; font-size: 10px; }
        .num { text-align: right; font-family: monospace; }
        tfoot td { font-weight: bold; background: #f9f9f9; border-top: 2px solid #999; }
    </style></head><body>
    <h1>${tenant || 'Empresa'}</h1>
    <h2>${title}</h2>
    <div class="meta">Período: ${ymToLabel(ym)} (${ym}) &nbsp;|&nbsp; Generado: ${new Date().toLocaleString('es-CR')}</div>
    ${bodyHtml}
    </body></html>`)
    w.document.close()
    setTimeout(() => w.print(), 400)
}

export default function LibrosDigitales() {
    const { state } = useApp()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const tenant = (state.user?.nombre || 'Empresa').toUpperCase()

    const [meses, setMeses] = useState([])
    const [loading, setLoading] = useState(true)
    const [loadingLib, setLoadingLib] = useState({})
    const [error, setError] = useState(null)
    const [expanded, setExpanded] = useState(new Set())

    function toggleMes(ym) {
        setExpanded(prev => {
            const next = new Set(prev)
            if (next.has(ym)) next.delete(ym)
            else next.add(ym)
            return next
        })
    }

    // ── Cargar historial de períodos CLOSED ─────────────────────
    useEffect(() => {
        if (!token) return
        setLoading(true)
        // Intentamos obtener periods CLOSED para los últimos 24 meses
        const now = new Date()
        const checks = []
        for (let i = 0; i <= 23; i++) {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
            const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
            checks.push(ym)
        }
        Promise.all(checks.map(ym =>
            fetch(`${apiUrl}/ledger/period/${ym}/status`, {
                headers: { Authorization: `Bearer ${token}` }
            }).then(r => r.ok ? r.json() : { year_month: ym, status: 'OPEN' })
                .catch(() => ({ year_month: ym, status: 'OPEN' }))
        )).then(results => {
            const closed = results.filter(r => r.status === 'CLOSED').map(r => r.year_month)
            setMeses(closed)
            // Expandir el primero por defecto
            if (closed.length > 0) setExpanded(new Set([closed[0]]))
        }).finally(() => setLoading(false))
    }, [token, apiUrl])

    // ── Obtener datos de un libro ────────────────────────────────
    async function getLibro(ym, tipo) {
        const key = `${ym}-${tipo}`
        setLoadingLib(l => ({ ...l, [key]: true }))
        try {
            const r = await fetch(`${apiUrl}/ledger/libros/${ym}/${tipo}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!r.ok) {
                const d = await r.json()
                throw new Error(d.detail || `Error ${r.status}`)
            }
            return await r.json()
        } finally {
            setLoadingLib(l => ({ ...l, [key]: false }))
        }
    }

    // ── Exportar Diario ──────────────────────────────────────────
    async function exportDiarioPDF(ym) {
        try {
            const d = await getLibro(ym, 'diario')
            const rows = d.lineas.map(l =>
                `<tr><td>${l.fecha}</td><td>${l.ref}</td><td>${l.cuenta}</td>
                 <td>${l.descripcion}</td>
                 <td class="num">${l.debe > 0 ? formatMoney(l.debe) : ''}</td>
                 <td class="num">${l.haber > 0 ? formatMoney(l.haber) : ''}</td></tr>`
            ).join('')
            const totalDR = d.lineas.reduce((s, l) => s + l.debe, 0)
            const totalCR = d.lineas.reduce((s, l) => s + l.haber, 0)
            printBook('LIBRO DIARIO', tenant, ym,
                `<table><thead><tr><th>FECHA</th><th>REF</th><th>CUENTA</th><th>DESCRIPCIÓN</th>
                 <th>DEBE (₡)</th><th>HABER (₡)</th></tr></thead>
                 <tbody>${rows}</tbody>
                 <tfoot><tr><td colspan="4">TOTALES</td>
                 <td class="num">${formatMoney(totalDR)}</td>
                 <td class="num">${formatMoney(totalCR)}</td></tr></tfoot></table>`)
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    async function exportDiarioCSV(ym) {
        try {
            const d = await getLibro(ym, 'diario')
            downloadCSV(`Diario_${ym}.csv`,
                ['FECHA', 'REF', 'CUENTA', 'DESCRIPCIÓN', 'DEBE', 'HABER'],
                d.lineas.map(l => [l.fecha, l.ref, l.cuenta, l.descripcion, l.debe, l.haber]))
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    // ── Exportar Mayor ───────────────────────────────────────────
    async function exportMayorPDF(ym) {
        try {
            const d = await getLibro(ym, 'mayor')
            // Orden contable estándar CR: Activo → Pasivo → Patrimonio → Ingreso → Gasto
            const TIPO_ORDER = ['ACTIVO', 'PASIVO', 'PATRIMONIO', 'EQUITY', 'INGRESO', 'INCOME', 'GASTO', 'EXPENSE']
            const TIPO_LABEL = {
                ACTIVO: 'ACTIVOS', PASIVO: 'PASIVOS', PATRIMONIO: 'PATRIMONIO',
                EQUITY: 'PATRIMONIO', INGRESO: 'INGRESOS', INCOME: 'INGRESOS',
                GASTO: 'GASTOS', EXPENSE: 'GASTOS'
            }
            // Agrupar por tipo normalizado
            const grupos = {}
            TIPO_ORDER.forEach(t => { grupos[t] = [] })
            d.cuentas.forEach(c => {
                const tipoKey = (c.tipo || '').toUpperCase()
                if (grupos[tipoKey]) grupos[tipoKey].push(c)
                else grupos['GASTO'] = [...(grupos['GASTO'] || []), c]
            })
            // Generar filas con encabezados de sección
            let rowsHtml = ''
            const seccionesVistas = new Set()
            TIPO_ORDER.forEach(tipo => {
                const cuentas = grupos[tipo] || []
                if (cuentas.length === 0) return
                const label = TIPO_LABEL[tipo] || tipo
                if (seccionesVistas.has(label)) return
                seccionesVistas.add(label)
                // Encabezado de sección
                rowsHtml += `<tr style="background:#e8e8e8"><td colspan="7" style="font-weight:700;font-size:10px;padding:5px 8px;border-top:2px solid #999">${label}</td></tr>`
                // Filas de la sección ordenadas por código
                const sorted = [...cuentas].sort((a, b) => (a.cuenta || '').localeCompare(b.cuenta || ''))
                sorted.forEach(c => {
                    rowsHtml += `<tr>
                        <td>${c.cuenta}</td><td>${c.nombre || ''}</td><td>${c.tipo || ''}</td>
                        <td class="num">${formatMoney(c.saldo_inicial)}</td>
                        <td class="num">${formatMoney(c.debe)}</td>
                        <td class="num">${formatMoney(c.haber)}</td>
                        <td class="num"><strong>${formatMoney(c.saldo_cierre)}</strong></td>
                    </tr>`
                })
            })
            printBook('LIBRO MAYOR', tenant, ym,
                `<table><thead><tr><th>CUENTA</th><th>NOMBRE</th><th>TIPO</th>
                 <th>SALDO INICIAL</th><th>DEBE</th><th>HABER</th><th>SALDO CIERRE</th></tr></thead>
                 <tbody>${rowsHtml}</tbody></table>`)
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    async function exportMayorCSV(ym) {
        try {
            const d = await getLibro(ym, 'mayor')
            downloadCSV(`Mayor_${ym}.csv`,
                ['CUENTA', 'NOMBRE', 'TIPO', 'SALDO_INICIAL', 'DEBE', 'HABER', 'SALDO_CIERRE'],
                d.cuentas.map(c => [c.cuenta, c.nombre, c.tipo, c.saldo_inicial, c.debe, c.haber, c.saldo_cierre]))
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    // ── Exportar Inventarios y Balances ──────────────────────────
    async function exportBalancePDF(ym) {
        try {
            const d = await getLibro(ym, 'balance')
            const rows = d.cuentas.map(c =>
                `<tr><td>${c.cuenta}</td><td>${c.nombre || ''}</td><td>${c.tipo || ''}</td>
                 <td class="num">${formatMoney(c.debe)}</td>
                 <td class="num">${formatMoney(c.haber)}</td></tr>`
            ).join('')
            const bal = d.balanceado ? '✓ Balanceado' : '⚠ Desbalanceado'
            printBook('INVENTARIOS Y BALANCES', tenant, ym,
                `<table><thead><tr><th>CUENTA</th><th>NOMBRE</th><th>TIPO</th>
                 <th>DEBE (₡)</th><th>HABER (₡)</th></tr></thead>
                 <tbody>${rows}</tbody>
                 <tfoot><tr><td colspan="3">TOTALES — ${bal}</td>
                 <td class="num">${formatMoney(d.total_debe)}</td>
                 <td class="num">${formatMoney(d.total_haber)}</td></tr></tfoot></table>`)
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    async function exportBalanceCSV(ym) {
        try {
            const d = await getLibro(ym, 'balance')
            downloadCSV(`Balance_${ym}.csv`,
                ['CUENTA', 'NOMBRE', 'TIPO', 'DEBE', 'HABER'],
                d.cuentas.map(c => [c.cuenta, c.nombre, c.tipo, c.debe, c.haber]))
        } catch (e) { alert(`Error: ${e.message}`) }
    }

    // ── Render ───────────────────────────────────────────────────
    const libros = [
        {
            key: 'diario', icon: '📋', titulo: 'Libro Diario',
            desc: 'Asientos en orden cronológico',
            onPDF: exportDiarioPDF, onCSV: exportDiarioCSV,
        },
        {
            key: 'mayor', icon: '📒', titulo: 'Libro Mayor',
            desc: 'T-account de cada cuenta activa',
            onPDF: exportMayorPDF, onCSV: exportMayorCSV,
        },
        {
            key: 'balance', icon: '⚖️', titulo: 'Inventarios y Balances',
            desc: 'Balance de comprobación del período',
            onPDF: exportBalancePDF, onCSV: exportBalanceCSV,
        },
    ]

    return (
        <div style={{ maxWidth: 800, margin: '0 auto', padding: '32px 20px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
                <span style={{ fontSize: '1.5rem' }}>📚</span>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>Libros Digitales</h2>
                    <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Art. 51 Ley Renta CR · Solo períodos CERRADOS · Inalterables
                    </p>
                </div>
            </div>

            {/* Note legal */}
            <div style={{
                padding: '10px 14px', borderRadius: 8, background: 'rgba(139,92,246,0.07)',
                border: '1px solid rgba(139,92,246,0.2)', fontSize: '0.78rem',
                color: 'var(--text-secondary)', marginBottom: 24
            }}>
                <strong style={{ color: '#8b5cf6' }}>Obligatorios (Hacienda CR):</strong> Diario · Mayor · Inventarios y Balances.
                Tienen la misma validez legal que los libros físicos (Ley 8454 · Firma Digital).
                Solo están disponibles para períodos con estado <strong>CLOSED</strong>.
            </div>

            {loading && (
                <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                    ⏳ Consultando períodos cerrados...
                </div>
            )}

            {!loading && meses.length === 0 && (
                <div style={{
                    textAlign: 'center', padding: 40, color: 'var(--text-muted)',
                    background: 'var(--bg-card)', borderRadius: 12, border: '1px solid var(--border-color)'
                }}>
                    <div style={{ fontSize: '2rem', marginBottom: 12 }}>📭</div>
                    <div style={{ fontWeight: 600, marginBottom: 6 }}>Sin períodos cerrados</div>
                    <div style={{ fontSize: '0.82rem' }}>
                        Ve a <a href="/cierre-periodo" style={{ color: '#7c3aed', fontWeight: 700 }}>Cierre de Período</a> y
                        completa el flujo de 5 pasos para cerrar un mes.
                    </div>
                </div>
            )}

            {!loading && meses.map(ym => (
                <div key={ym} style={{
                    background: 'var(--bg-card)', borderRadius: 12,
                    border: '1px solid var(--border-color)', marginBottom: 16,
                    overflow: 'hidden'
                }}>
                    {/* Header del mes — clickable para expandir/colapsar */}
                    <div
                        onClick={() => toggleMes(ym)}
                        style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            padding: '12px 18px', borderBottom: expanded.has(ym) ? '1px solid var(--border-color)' : 'none',
                            background: 'rgba(16,185,129,0.06)', cursor: 'pointer',
                            userSelect: 'none',
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: '1.1rem' }}>🔒</span>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                                    {ymToLabel(ym)}
                                </div>
                                <div style={{ fontSize: '0.72rem', color: '#10b981' }}>CERRADO · {ym}</div>
                            </div>
                        </div>
                        <span style={{ fontSize: '1rem', color: 'var(--text-muted)', transition: 'transform 0.2s', display: 'inline-block', transform: expanded.has(ym) ? 'rotate(0deg)' : 'rotate(-90deg)' }}>▾</span>
                    </div>

                    {/* Los 3 libros — solo si expandido */}
                    {expanded.has(ym) && (
                        <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                            {libros.map(lib => {
                                const keyPDF = `${ym}-${lib.key}-pdf`
                                const keyCSV = `${ym}-${lib.key}-csv`
                                return (
                                    <div key={lib.key} style={{
                                        display: 'flex', alignItems: 'center',
                                        justifyContent: 'space-between', padding: '10px 14px',
                                        borderRadius: 8, background: 'var(--bg-header)',
                                        border: '1px solid var(--border-color)'
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                            <span style={{ fontSize: '1.1rem' }}>{lib.icon}</span>
                                            <div>
                                                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                                                    {lib.titulo}
                                                </div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{lib.desc}</div>
                                            </div>
                                        </div>
                                        <div style={{ display: 'flex', gap: 6 }}>
                                            <button
                                                id={`btn-${lib.key}-pdf-${ym}`}
                                                onClick={() => lib.onPDF(ym)}
                                                disabled={loadingLib[`${ym}-${lib.key}`]}
                                                style={{
                                                    padding: '6px 12px', background: '#7c3aed', border: 'none',
                                                    borderRadius: 6, color: 'white', cursor: 'pointer',
                                                    fontSize: '0.78rem', fontWeight: 600
                                                }}>
                                                {loadingLib[`${ym}-${lib.key}`] ? '⏳' : '📥 PDF'}
                                            </button>
                                            <button
                                                id={`btn-${lib.key}-csv-${ym}`}
                                                onClick={() => lib.onCSV(ym)}
                                                disabled={loadingLib[`${ym}-${lib.key}`]}
                                                style={{
                                                    padding: '6px 12px', background: 'transparent',
                                                    border: '1px solid var(--border-color)', borderRadius: 6,
                                                    color: 'var(--text-secondary)', cursor: 'pointer',
                                                    fontSize: '0.78rem'
                                                }}>
                                                📊 CSV
                                            </button>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
}
