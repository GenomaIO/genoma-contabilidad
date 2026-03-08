/**
 * CierreAnual.jsx — Panel de Cierre Anual del Ejercicio Fiscal
 *
 * Flujo contable NIIF / Ley Renta CR:
 *  1. Verifica que todos los 12 meses estén CLOSED
 *  2. Ejecuta los 3 asientos CIERRE_ANUAL automáticamente
 *  3. Bloquea el año (LOCKED) — irreversible
 *  4. Genera la apertura del año siguiente (botón separado)
 *
 * El "Cierre Anual" existe ADEMÁS del "Cierre de Período" mensual.
 * Solo aparece disponible cuando todos los meses del año están cerrados.
 */
import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../context/AppContext'

const MESES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

const STATUS_BADGE = {
    OPEN: { color: '#3b82f6', bg: '#3b82f620', icon: '🔓', label: 'Abierto' },
    CLOSING: { color: '#f59e0b', bg: '#f59e0b20', icon: '⏳', label: 'En cierre' },
    CLOSED: { color: '#10b981', bg: '#10b98120', icon: '🔒', label: 'Cerrado' },
    LOCKED: { color: '#7c3aed', bg: '#7c3aed20', icon: '🔐', label: 'LOCKED' },
}

export default function CierreAnual() {
    const { state } = useApp()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const isAdmin = role === 'admin'

    // Año a trabajar
    const currentYear = new Date().getFullYear()
    const [year, setYear] = useState(String(currentYear))
    const yearOptions = Array.from({ length: 6 }, (_, i) => String(currentYear - 2 + i))

    // Estado del año fiscal
    const [fiscalYears, setFiscalYears] = useState([])
    const [fiscalYear, setFiscalYear] = useState(null)   // el FY del año seleccionado
    const [loadingFY, setLoadingFY] = useState(false)

    // Estado de los 12 períodos del año
    const [periods, setPeriods] = useState([])     // [{ym, status}]
    const [loadingPeriods, setLoadingPeriods] = useState(false)

    // Acciones
    const [loadingClose, setLoadingClose] = useState(false)
    const [loadingOpen, setLoadingOpen] = useState(false)
    const [msg, setMsg] = useState(null)
    const [err, setErr] = useState(null)
    const [confirmClose, setConfirmClose] = useState(false)

    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

    // ── Cargar lista de ejercicios fiscales ──────────────────
    const loadFiscalYears = useCallback(async () => {
        if (!token) return
        setLoadingFY(true)
        try {
            const r = await fetch(`${apiUrl}/ledger/fiscal-years`, { headers: { Authorization: `Bearer ${token}` } })
            if (r.ok) {
                const d = await r.json()
                setFiscalYears(d.fiscal_years || [])
            }
        } catch { /* net */ }
        finally { setLoadingFY(false) }
    }, [apiUrl, token])

    // ── Cargar períodos del año seleccionado ─────────────────
    const loadPeriods = useCallback(async () => {
        if (!token || !year) return
        setLoadingPeriods(true)
        try {
            const months = Array.from({ length: 12 }, (_, i) =>
                `${year}-${String(i + 1).padStart(2, '0')}`)
            const results = await Promise.all(months.map(ym =>
                fetch(`${apiUrl}/ledger/period/${ym}/status`, {
                    headers: { Authorization: `Bearer ${token}` }
                })
                    .then(r => r.ok ? r.json() : { year_month: ym, status: 'OPEN' })
                    .catch(() => ({ year_month: ym, status: 'OPEN' }))
            ))
            setPeriods(results)
        } catch { /* net */ }
        finally { setLoadingPeriods(false) }
    }, [apiUrl, token, year])

    useEffect(() => {
        loadFiscalYears()
    }, [])

    useEffect(() => {
        loadPeriods()
        setMsg(null); setErr(null); setConfirmClose(false)
    }, [year, token])

    useEffect(() => {
        const fy = fiscalYears.find(f => f.year === year)
        setFiscalYear(fy || null)
    }, [fiscalYears, year])

    // ── Métricas ──────────────────────────────────────────────
    const closedCount = periods.filter(p => p.status === 'CLOSED').length
    const allClosed = closedCount === 12
    const fyStatus = fiscalYear?.status || 'OPEN'
    const isLocked = fyStatus === 'LOCKED'
    const hasOpening = !!fiscalYear?.opening_entry_id

    // ── Ejecutar cierre anual ─────────────────────────────────
    async function doAnnualClose() {
        setLoadingClose(true); setMsg(null); setErr(null)
        setConfirmClose(false)
        try {
            const r = await fetch(`${apiUrl}/ledger/annual-close?year=${year}`, {
                method: 'POST', headers
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error en cierre anual')
            setMsg(`✅ Cierre anual ${year} completado. ${d.result_label}: ₡${Math.abs(d.net_income).toLocaleString()}. Año LOCKED.`)
            await loadFiscalYears()
            await loadPeriods()
        } catch (e) { setErr(e.message) }
        finally { setLoadingClose(false) }
    }

    // ── Generar apertura del año siguiente ───────────────────
    async function doGenerateOpening() {
        const nextYear = String(parseInt(year) + 1)
        setLoadingOpen(true); setMsg(null); setErr(null)
        try {
            const r = await fetch(`${apiUrl}/ledger/generate-opening?next_year=${nextYear}`, {
                method: 'POST', headers
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error generando apertura')
            setMsg(`✅ Apertura ${nextYear} generada: ${d.lines_count} cuentas trasladadas desde ${year}.`)
            await loadFiscalYears()
        } catch (e) { setErr(e.message) }
        finally { setLoadingOpen(false) }
    }

    const fyBadgeInfo = STATUS_BADGE[fyStatus] || STATUS_BADGE.OPEN

    return (
        <div style={{ maxWidth: 820, margin: '0 auto', padding: '28px 20px' }}>

            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: '1.6rem' }}>📆</span>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                            Cierre Anual del Ejercicio
                        </h2>
                        <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                            NIIF · Art. 51 Ley Renta CR · 3 asientos automáticos + apertura
                        </p>
                    </div>
                </div>
                {/* Badge estado año */}
                <div style={{
                    padding: '5px 14px', borderRadius: 20,
                    background: fyBadgeInfo.bg, border: `1px solid ${fyBadgeInfo.color}40`,
                    color: fyBadgeInfo.color, fontWeight: 700, fontSize: '0.82rem',
                    display: 'flex', alignItems: 'center', gap: 6
                }}>
                    {fyBadgeInfo.icon} {fyBadgeInfo.label} {year}
                </div>
            </div>

            {/* Selector de año */}
            <div style={{ marginBottom: 24 }}>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    Ejercicio fiscal
                </label>
                <select
                    id="cierre-anual-year"
                    value={year}
                    onChange={e => setYear(e.target.value)}
                    style={{
                        padding: '8px 12px', borderRadius: 7,
                        border: '1px solid var(--border-color)',
                        background: 'var(--bg-card)', color: 'var(--text-primary)',
                        fontSize: '0.9rem', minWidth: 140, cursor: 'pointer'
                    }}
                >
                    {yearOptions.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
            </div>

            {/* Checklist de 12 meses */}
            <div style={{
                background: 'var(--bg-card)', borderRadius: 12,
                border: '1px solid var(--border-color)', marginBottom: 20, overflow: 'hidden'
            }}>
                <div style={{
                    padding: '12px 18px', borderBottom: '1px solid var(--border-color)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                }}>
                    <span style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        Prerequisito: Todos los períodos del año cerrados
                    </span>
                    <span style={{
                        fontSize: '0.78rem', fontWeight: 700,
                        color: allClosed ? '#10b981' : '#f59e0b'
                    }}>
                        {loadingPeriods ? '...' : `${closedCount}/12 CLOSED`}
                    </span>
                </div>

                {/* Grid de 12 meses */}
                <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)',
                    gap: 1, padding: '2px', background: 'var(--border-color)'
                }}>
                    {periods.map((p, idx) => {
                        const m = idx + 1
                        const isClosed = p.status === 'CLOSED'
                        return (
                            <div key={p.year_month} style={{
                                background: isClosed ? 'rgba(16,185,129,0.06)' : 'var(--bg-card)',
                                padding: '8px 4px', textAlign: 'center'
                            }}>
                                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                                    {MESES[m]}
                                </div>
                                <div style={{
                                    fontSize: '1rem',
                                    color: isClosed ? '#10b981' : p.status === 'CLOSING' ? '#f59e0b' : '#6b7280'
                                }}>
                                    {isClosed ? '✓' : p.status === 'CLOSING' ? '⏳' : '○'}
                                </div>
                            </div>
                        )
                    })}
                </div>

                {!allClosed && (
                    <div style={{
                        padding: '10px 18px', borderTop: '1px solid var(--border-color)',
                        fontSize: '0.78rem', color: '#f59e0b'
                    }}>
                        ⚠️ Faltan {12 - closedCount} período(s) por cerrar. Use "Cierre de Período" para cada mes.
                    </div>
                )}
            </div>

            {/* Panel de asientos generados (si ya está LOCKED) */}
            {isLocked && fiscalYear?.closing_entries?.length > 0 && (
                <div style={{
                    background: 'rgba(124,58,237,0.06)', borderRadius: 10,
                    border: '1px solid rgba(124,58,237,0.2)', padding: '14px 18px',
                    marginBottom: 20
                }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#7c3aed', marginBottom: 8 }}>
                        🔐 Asientos de cierre (CIERRE_ANUAL) generados
                    </div>
                    {fiscalYear.closing_entries.map((id, i) => (
                        <div key={id} style={{
                            fontSize: '0.75rem', color: 'var(--text-muted)',
                            fontFamily: 'monospace', marginBottom: 2
                        }}>
                            {['A — Cierre Ingresos', 'B — Cierre Gastos', 'C — Traspaso Patrimonio'][i] || `Asiento ${i + 1}`}: {id}
                        </div>
                    ))}
                    {fiscalYear.net_income !== null && (
                        <div style={{
                            marginTop: 10, padding: '8px 12px', borderRadius: 8,
                            background: fiscalYear.net_income >= 0
                                ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                            color: fiscalYear.net_income >= 0 ? '#10b981' : '#ef4444',
                            fontSize: '0.85rem', fontWeight: 700
                        }}>
                            {fiscalYear.net_income >= 0 ? '📈 UTILIDAD' : '📉 PÉRDIDA'} del ejercicio:{' '}
                            ₡{Math.abs(fiscalYear.net_income).toLocaleString()}
                        </div>
                    )}
                </div>
            )}

            {/* Mensajes */}
            {msg && (
                <div style={{
                    padding: '10px 14px', borderRadius: 8, marginBottom: 16,
                    background: 'rgba(16,185,129,0.1)', border: '1px solid #10b981',
                    color: '#10b981', fontSize: '0.85rem'
                }}>
                    {msg}
                </div>
            )}
            {err && (
                <div style={{
                    padding: '10px 14px', borderRadius: 8, marginBottom: 16,
                    background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444',
                    color: '#ef4444', fontSize: '0.85rem'
                }}>
                    ⚠️ {err}
                </div>
            )}

            {/* Acciones */}
            {!isAdmin ? (
                <div style={{
                    padding: 14, borderRadius: 8, fontSize: '0.82rem',
                    background: 'rgba(239,68,68,0.08)', color: '#ef4444',
                    border: '1px solid rgba(239,68,68,0.3)'
                }}>
                    Solo el administrador puede ejecutar el cierre anual.
                </div>
            ) : !isLocked ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {/* Botón cierre anual */}
                    {!confirmClose ? (
                        <button
                            id="btn-cierre-anual"
                            onClick={() => setConfirmClose(true)}
                            disabled={!allClosed || loadingClose}
                            title={!allClosed ? 'Cierra los 12 meses primero' : 'Ejecutar cierre anual'}
                            style={{
                                padding: '12px 22px',
                                background: allClosed ? '#7c3aed' : 'var(--bg-card)',
                                border: 'none', borderRadius: 8,
                                color: allClosed ? 'white' : 'var(--text-muted)',
                                fontWeight: 700, cursor: allClosed ? 'pointer' : 'not-allowed',
                                fontSize: '0.9rem'
                            }}
                        >
                            {loadingClose ? '⏳ Ejecutando cierre...' : `📆 Ejecutar Cierre Anual ${year}`}
                        </button>
                    ) : (
                        <div style={{
                            padding: '16px 18px', borderRadius: 10,
                            background: 'rgba(239,68,68,0.08)',
                            border: '2px solid #ef4444'
                        }}>
                            <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 6, fontSize: '0.9rem' }}>
                                ⚠️ ¿Confirmar cierre del ejercicio {year}?
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                                Se generarán 3 asientos CIERRE_ANUAL. El año quedará <strong>LOCKED</strong> (irreversible).
                                Los libros digitales de {year} estarán disponibles.
                            </div>
                            <div style={{ display: 'flex', gap: 10 }}>
                                <button
                                    onClick={() => setConfirmClose(false)}
                                    style={{
                                        padding: '8px 18px', background: 'var(--bg-card)',
                                        border: '1px solid var(--border-color)', borderRadius: 7,
                                        color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 600
                                    }}
                                >
                                    Cancelar
                                </button>
                                <button
                                    id="btn-cierre-anual-confirmar"
                                    onClick={doAnnualClose}
                                    disabled={loadingClose}
                                    style={{
                                        padding: '8px 22px', background: '#ef4444',
                                        border: 'none', borderRadius: 7, color: 'white',
                                        cursor: 'pointer', fontWeight: 700
                                    }}
                                >
                                    {loadingClose ? '⏳ Ejecutando...' : `🔐 Sí, cerrar ${year} definitivamente`}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                /* Año LOCKED — mostrar botón apertura */
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div style={{
                        padding: '14px 18px', borderRadius: 10,
                        background: 'rgba(16,185,129,0.08)', border: '1px solid #10b981'
                    }}>
                        <div style={{ fontSize: '1.1rem', marginBottom: 4 }}>🔐</div>
                        <div style={{ fontWeight: 700, color: '#10b981', marginBottom: 4 }}>
                            Ejercicio {year} — Cerrado y Bloqueado
                        </div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            Los libros son inalterables (Art. 51 Ley Renta CR).
                        </div>
                    </div>
                    {/* Apertura del año siguiente */}
                    {!hasOpening && (
                        <button
                            id="btn-generar-apertura"
                            onClick={doGenerateOpening}
                            disabled={loadingOpen}
                            style={{
                                padding: '11px 22px', background: '#2563eb',
                                border: 'none', borderRadius: 8, color: 'white',
                                fontWeight: 700, cursor: 'pointer', fontSize: '0.88rem'
                            }}
                        >
                            {loadingOpen
                                ? '⏳ Generando apertura...'
                                : `📂 Generar Apertura ${parseInt(year) + 1} automáticamente`}
                        </button>
                    )}
                    {hasOpening && (
                        <div style={{
                            padding: '10px 14px', borderRadius: 8,
                            background: 'rgba(37,99,235,0.08)', border: '1px solid #2563eb',
                            fontSize: '0.82rem', color: '#2563eb'
                        }}>
                            ✅ Asiento de apertura {parseInt(year) + 1} generado (ID: {fiscalYear.opening_entry_id?.slice(0, 8)}…)
                        </div>
                    )}
                </div>
            )}

            {/* Info contable */}
            <div style={{
                marginTop: 24, padding: '12px 16px', borderRadius: 8,
                background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)',
                fontSize: '0.76rem', color: 'var(--text-secondary)'
            }}>
                <strong style={{ color: '#8b5cf6' }}>📖 Flujo contable NIIF:</strong>{' '}
                <strong>A</strong>) Ingresos → 3304 · <strong>B</strong>) Gastos → 3304 ·{' '}
                <strong>C</strong>) 3304 → 3303 Utilidad (o 3302 Pérdida) ·
                Apertura: saldos de ACTIVO/PASIVO/PATRIMONIO se trasladan al año siguiente.
            </div>
        </div>
    )
}
