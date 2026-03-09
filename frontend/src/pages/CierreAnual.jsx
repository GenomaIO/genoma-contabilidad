/**
 * CierreAnual.jsx — Panel de Cierre Anual del Ejercicio Fiscal
 *
 * Flujo contable NIIF / Ley Renta CR:
 *  1. Verifica que todos los 12 meses estén CLOSED
 *  2. Ejecuta los 3 asientos CIERRE_ANUAL automáticamente
 *  3. Bloquea el año (LOCKED) — irreversible
 *  4. Genera la apertura del año siguiente (botón separado)
 *
 * También incluye:
 *  - Cierre por Terminación de Actividades (Art. 51 Ley 7092 / NIIF Sec.3.8)
 *  - Reactivación de empresa tras terminación
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
    TERMINATED: { color: '#ef4444', bg: '#ef444420', icon: '🔴', label: 'TERMINADO' },
}

const MOTIVOS_TERMINACION = [
    'Disolución voluntaria (Cód. Comercio Art. 201)',
    'Quiebra / Insolvencia',
    'Fusión con otra empresa',
    'Venta total de activos',
    'Liquidación por acuerdo de socios',
    'Otro',
]

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
    const [fiscalYear, setFiscalYear] = useState(null)
    const [loadingFY, setLoadingFY] = useState(false)

    // Estado de los 12 períodos del año
    const [periods, setPeriods] = useState([])
    const [loadingPeriods, setLoadingPeriods] = useState(false)

    // Acciones cierre anual
    const [loadingClose, setLoadingClose] = useState(false)
    const [loadingOpen, setLoadingOpen] = useState(false)
    const [msg, setMsg] = useState(null)
    const [err, setErr] = useState(null)
    const [confirmClose, setConfirmClose] = useState(false)

    // Terminación de actividades
    const [showTermSection, setShowTermSection] = useState(false)
    const [termDate, setTermDate] = useState(`${year}-12-31`)
    const [termReason, setTermReason] = useState(MOTIVOS_TERMINACION[0])
    const [confirmTerm, setConfirmTerm] = useState(false)
    const [loadingTerm, setLoadingTerm] = useState(false)
    const [termResult, setTermResult] = useState(null)

    // Reactivación
    const [showReactivate, setShowReactivate] = useState(false)
    const [reactDate, setReactDate] = useState('')
    const [reactReason, setReactReason] = useState('')
    const [loadingReact, setLoadingReact] = useState(false)
    const [reactResult, setReactResult] = useState(null)

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

    useEffect(() => { loadFiscalYears() }, [])
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
    const isTerminated = fyStatus === 'TERMINATED'
    const hasOpening = !!fiscalYear?.opening_entry_id

    // Tenant terminado globalmente (de cualquier año)
    const tenantTerminated = state.user?.tenant_status === 'terminated'

    // ── Ejecutar cierre anual normal ─────────────────────────
    async function doAnnualClose() {
        setLoadingClose(true); setMsg(null); setErr(null); setConfirmClose(false)
        try {
            const r = await fetch(`${apiUrl}/ledger/annual-close?year=${year}`, { method: 'POST', headers })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error en cierre anual')
            setMsg(`✅ Cierre anual ${year} completado. ${d.result_label}: ₡${Math.abs(d.net_income).toLocaleString()}. Año LOCKED.`)
            await loadFiscalYears(); await loadPeriods()
        } catch (e) { setErr(e.message) }
        finally { setLoadingClose(false) }
    }

    // ── Generar apertura del año siguiente ───────────────────
    async function doGenerateOpening() {
        const nextYear = String(parseInt(year) + 1)
        setLoadingOpen(true); setMsg(null); setErr(null)
        try {
            const r = await fetch(`${apiUrl}/ledger/generate-opening?next_year=${nextYear}`, { method: 'POST', headers })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error generando apertura')
            setMsg(`✅ Apertura ${nextYear} generada: ${d.lines_count} cuentas trasladadas desde ${year}.`)
            await loadFiscalYears()
        } catch (e) { setErr(e.message) }
        finally { setLoadingOpen(false) }
    }

    // ── Ejecutar cierre por terminación ─────────────────────
    async function doTermination() {
        setLoadingTerm(true); setErr(null); setConfirmTerm(false)
        try {
            const r = await fetch(`${apiUrl}/ledger/close-termination`, {
                method: 'POST', headers,
                body: JSON.stringify({ year, termination_date: termDate, reason: termReason })
            })
            const d = await r.json()
            if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail))
            setTermResult(d)
            await loadFiscalYears(); await loadPeriods()
        } catch (e) { setErr(e.message) }
        finally { setLoadingTerm(false) }
    }

    // ── Reactivar empresa ────────────────────────────────────
    async function doReactivate() {
        setLoadingReact(true); setErr(null)
        try {
            const r = await fetch(`${apiUrl}/ledger/reactivate`, {
                method: 'POST', headers,
                body: JSON.stringify({ reactivation_date: reactDate, reason: reactReason || 'Reactivación de actividades' })
            })
            const d = await r.json()
            if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail))
            setReactResult(d)
            await loadFiscalYears()
        } catch (e) { setErr(e.message) }
        finally { setLoadingReact(false) }
    }

    const fyBadgeInfo = STATUS_BADGE[fyStatus] || STATUS_BADGE.OPEN

    const panelStyle = (color) => ({
        background: `${color}10`, borderRadius: 12,
        border: `1px solid ${color}30`, padding: '16px 18px', marginBottom: 16
    })

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
                    onChange={e => { setYear(e.target.value); setTermDate(`${e.target.value}-12-31`) }}
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
                    <span style={{ fontSize: '0.78rem', fontWeight: 700, color: allClosed ? '#10b981' : '#f59e0b' }}>
                        {loadingPeriods ? '...' : `${closedCount}/12 CLOSED`}
                    </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 1, padding: '2px', background: 'var(--border-color)' }}>
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
                                <div style={{ fontSize: '1rem', color: isClosed ? '#10b981' : p.status === 'CLOSING' ? '#f59e0b' : '#6b7280' }}>
                                    {isClosed ? '✓' : p.status === 'CLOSING' ? '⏳' : '○'}
                                </div>
                            </div>
                        )
                    })}
                </div>
                {!allClosed && (
                    <div style={{ padding: '10px 18px', borderTop: '1px solid var(--border-color)', fontSize: '0.78rem', color: '#f59e0b' }}>
                        ⚠️ Faltan {12 - closedCount} período(s) por cerrar. Use "Cierre de Período" para cada mes.
                    </div>
                )}
            </div>

            {/* Panel asientos generados si LOCKED */}
            {isLocked && fiscalYear?.closing_entries?.length > 0 && (
                <div style={panelStyle('#7c3aed')}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#7c3aed', marginBottom: 8 }}>
                        🔐 Asientos de cierre (CIERRE_ANUAL) generados
                    </div>
                    {fiscalYear.closing_entries.map((id, i) => (
                        <div key={id} style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'monospace', marginBottom: 2 }}>
                            {['A — Cierre Ingresos', 'B — Cierre Gastos', 'C — Traspaso Patrimonio'][i] || `Asiento ${i + 1}`}: {id}
                        </div>
                    ))}
                    {fiscalYear.net_income !== null && (
                        <div style={{
                            marginTop: 10, padding: '8px 12px', borderRadius: 8,
                            background: fiscalYear.net_income >= 0 ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                            color: fiscalYear.net_income >= 0 ? '#10b981' : '#ef4444',
                            fontSize: '0.85rem', fontWeight: 700
                        }}>
                            {fiscalYear.net_income >= 0 ? '📈 UTILIDAD' : '📉 PÉRDIDA'} del ejercicio: ₡{Math.abs(fiscalYear.net_income).toLocaleString()}
                        </div>
                    )}
                </div>
            )}

            {/* TERMINATED — resultado de terminación */}
            {isTerminated && (
                <div style={panelStyle('#ef4444')}>
                    <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 8, fontSize: '0.92rem' }}>
                        🔴 Ejercicio {year} — TERMINADO
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 6 }}>
                        Fecha de cese: <strong>{fiscalYear?.termination_date || '—'}</strong>
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 10 }}>
                        Motivo: {fiscalYear?.termination_reason || '—'}
                    </div>
                    <div style={{ fontSize: '0.78rem', color: '#ef444480', fontStyle: 'italic' }}>
                        NIIF PYMES Sec. 3.8 — Empresa no es empresa en marcha. Libros en SOLO LECTURA.
                    </div>
                </div>
            )}

            {/* Mensajes */}
            {msg && (
                <div style={{ padding: '10px 14px', borderRadius: 8, marginBottom: 16, background: 'rgba(16,185,129,0.1)', border: '1px solid #10b981', color: '#10b981', fontSize: '0.85rem' }}>
                    {msg}
                </div>
            )}
            {err && (
                <div style={{ padding: '10px 14px', borderRadius: 8, marginBottom: 16, background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444', color: '#ef4444', fontSize: '0.85rem' }}>
                    ⚠️ {err}
                </div>
            )}

            {/* Acciones cierre anual normal */}
            {!isAdmin ? (
                <div style={{ padding: 14, borderRadius: 8, fontSize: '0.82rem', background: 'rgba(239,68,68,0.08)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
                    Solo el administrador puede ejecutar el cierre anual.
                </div>
            ) : !isLocked && !isTerminated ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {!confirmClose ? (
                        <button id="btn-cierre-anual" onClick={() => setConfirmClose(true)}
                            disabled={!allClosed || loadingClose} title={!allClosed ? 'Cierra los 12 meses primero' : 'Ejecutar cierre anual'}
                            style={{ padding: '12px 22px', background: allClosed ? '#7c3aed' : 'var(--bg-card)', border: 'none', borderRadius: 8, color: allClosed ? 'white' : 'var(--text-muted)', fontWeight: 700, cursor: allClosed ? 'pointer' : 'not-allowed', fontSize: '0.9rem' }}>
                            {loadingClose ? '⏳ Ejecutando cierre...' : `📆 Ejecutar Cierre Anual ${year}`}
                        </button>
                    ) : (
                        <div style={{ padding: '16px 18px', borderRadius: 10, background: 'rgba(239,68,68,0.08)', border: '2px solid #ef4444' }}>
                            <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 6, fontSize: '0.9rem' }}>
                                ⚠️ ¿Confirmar cierre del ejercicio {year}?
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                                Se generarán 3 asientos CIERRE_ANUAL. El año quedará <strong>LOCKED</strong> (irreversible).
                            </div>
                            <div style={{ display: 'flex', gap: 10 }}>
                                <button onClick={() => setConfirmClose(false)} style={{ padding: '8px 18px', background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 600 }}>Cancelar</button>
                                <button id="btn-cierre-anual-confirmar" onClick={doAnnualClose} disabled={loadingClose}
                                    style={{ padding: '8px 22px', background: '#ef4444', border: 'none', borderRadius: 7, color: 'white', cursor: 'pointer', fontWeight: 700 }}>
                                    {loadingClose ? '⏳ Ejecutando...' : `🔐 Sí, cerrar ${year} definitivamente`}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            ) : isLocked ? (
                /* Año LOCKED — mostrar botón apertura */
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div style={{ padding: '14px 18px', borderRadius: 10, background: 'rgba(16,185,129,0.08)', border: '1px solid #10b981' }}>
                        <div style={{ fontSize: '1.1rem', marginBottom: 4 }}>🔐</div>
                        <div style={{ fontWeight: 700, color: '#10b981', marginBottom: 4 }}>Ejercicio {year} — Cerrado y Bloqueado</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Los libros son inalterables (Art. 51 Ley Renta CR).</div>
                    </div>
                    {!hasOpening && (
                        <button id="btn-generar-apertura" onClick={doGenerateOpening} disabled={loadingOpen}
                            style={{ padding: '11px 22px', background: '#2563eb', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.88rem' }}>
                            {loadingOpen ? '⏳ Generando apertura...' : `📂 Generar Apertura ${parseInt(year) + 1} automáticamente`}
                        </button>
                    )}
                    {hasOpening && (
                        <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(37,99,235,0.08)', border: '1px solid #2563eb', fontSize: '0.82rem', color: '#2563eb' }}>
                            ✅ Asiento de apertura {parseInt(year) + 1} generado (ID: {fiscalYear.opening_entry_id?.slice(0, 8)}…)
                        </div>
                    )}
                </div>
            ) : null}

            {/* ═══════════════════════════════════════════════════════════
                SECCIÓN: TERMINACIÓN DE ACTIVIDADES
            ═══════════════════════════════════════════════════════════ */}
            {isAdmin && !isTerminated && !termResult && (
                <div style={{ marginTop: 32 }}>
                    {/* Toggle */}
                    <button
                        id="btn-toggle-terminacion"
                        onClick={() => setShowTermSection(!showTermSection)}
                        style={{
                            width: '100%', padding: '10px 16px', background: 'transparent',
                            border: '1px dashed #ef444460', borderRadius: 8,
                            color: '#ef4444', cursor: 'pointer', fontWeight: 600,
                            fontSize: '0.84rem', display: 'flex', alignItems: 'center',
                            justifyContent: 'space-between', gap: 8
                        }}
                    >
                        <span>🔴 Cierre por Terminación de Actividades</span>
                        <span style={{ fontSize: '0.7rem', color: '#ef444480' }}>
                            {showTermSection ? '▲ ocultar' : '▼ expandir'}
                        </span>
                    </button>

                    {showTermSection && (
                        <div style={{ marginTop: 12, padding: '18px 20px', borderRadius: 12, background: 'rgba(239,68,68,0.05)', border: '1px solid #ef444430' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                                <strong style={{ color: '#ef4444' }}>NIIF PYMES Sec. 3.8 · Art. 51 Ley 7092 · MH-DGT-RES-0037-2025</strong>
                                <br />Cierra la empresa en una fecha libre. Los libros quedan en modo lectura permanente.
                                No se genera apertura del año siguiente.
                            </div>

                            {/* Fecha de cese */}
                            <div style={{ marginBottom: 12 }}>
                                <label style={{ fontSize: '0.76rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                                    Fecha de cese de operaciones
                                </label>
                                <input type="date" value={termDate}
                                    min={`${year}-01-01`} max={`${year}-12-31`}
                                    onChange={e => setTermDate(e.target.value)}
                                    id="terminacion-fecha"
                                    style={{ padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', width: 170 }}
                                />
                            </div>

                            {/* Motivo */}
                            <div style={{ marginBottom: 16 }}>
                                <label style={{ fontSize: '0.76rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                                    Motivo del cese
                                </label>
                                <select value={termReason} onChange={e => setTermReason(e.target.value)}
                                    id="terminacion-motivo"
                                    style={{ padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', width: '100%', maxWidth: 400 }}>
                                    {MOTIVOS_TERMINACION.map(m => <option key={m} value={m}>{m}</option>)}
                                </select>
                            </div>

                            {/* Botón o confirmación */}
                            {!confirmTerm ? (
                                <button id="btn-iniciar-terminacion"
                                    onClick={() => setConfirmTerm(true)}
                                    disabled={!termDate || loadingTerm}
                                    style={{ padding: '10px 22px', background: '#ef4444', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.88rem' }}>
                                    🔒 Ejecutar Cierre por Terminación
                                </button>
                            ) : (
                                <div style={{ padding: '14px 16px', borderRadius: 10, background: 'rgba(239,68,68,0.12)', border: '2px solid #ef4444' }}>
                                    <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>
                                        ⚠️ ¿Confirmar terminación definitiva de la empresa?
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 12 }}>
                                        Fecha de cese: <strong>{termDate}</strong><br />
                                        Motivo: <strong>{termReason}</strong><br /><br />
                                        Esta acción marcará los libros como <strong>SOLO LECTURA</strong> permanente.
                                        Se generarán 3 asientos de cierre con fecha {termDate}.
                                    </div>
                                    <div style={{ display: 'flex', gap: 10 }}>
                                        <button onClick={() => setConfirmTerm(false)} style={{ padding: '7px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 600 }}>
                                            Cancelar
                                        </button>
                                        <button id="btn-confirmar-terminacion" onClick={doTermination} disabled={loadingTerm}
                                            style={{ padding: '7px 20px', background: '#ef4444', border: 'none', borderRadius: 7, color: 'white', cursor: 'pointer', fontWeight: 700 }}>
                                            {loadingTerm ? '⏳ Ejecutando...' : '🔴 Sí, terminar empresa definitivamente'}
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* TERMINACIÓN resultado + checklist legal */}
            {termResult && (
                <div style={{ marginTop: 20, ...panelStyle('#ef4444') }}>
                    <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 10 }}>
                        🔴 Terminación ejecutada — {termResult.termination_date}
                    </div>
                    <div style={{ fontSize: '0.85rem', color: termResult.net_income >= 0 ? '#10b981' : '#ef4444', fontWeight: 700, marginBottom: 14 }}>
                        {termResult.result_label}: ₡{Math.abs(termResult.net_income).toLocaleString()}
                    </div>
                    <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
                        📋 Pendientes externos con Hacienda:
                    </div>
                    {Object.entries(termResult.legal_reminders || {}).map(([k, v]) => (
                        <div key={k} style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 4, paddingLeft: 12, borderLeft: '2px solid #ef444440' }}>
                            ⏰ {v}
                        </div>
                    ))}
                    <div style={{ marginTop: 10, fontSize: '0.74rem', color: '#ef444480', fontStyle: 'italic' }}>
                        {termResult.niif_note}
                    </div>
                </div>
            )}

            {/* ═══════════════════════════════════════════════════════════
                SECCIÓN: REACTIVAR EMPRESA (solo si está TERMINATED)
            ═══════════════════════════════════════════════════════════ */}
            {isAdmin && (isTerminated || termResult) && !reactResult && (
                <div style={{ marginTop: 20 }}>
                    <button id="btn-toggle-reactivar"
                        onClick={() => setShowReactivate(!showReactivate)}
                        style={{ width: '100%', padding: '10px 16px', background: 'transparent', border: '1px dashed #10b98160', borderRadius: 8, color: '#10b981', cursor: 'pointer', fontWeight: 600, fontSize: '0.84rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span>🟢 Reactivar Empresa</span>
                        <span style={{ fontSize: '0.7rem', color: '#10b98180' }}>{showReactivate ? '▲ ocultar' : '▼ expandir'}</span>
                    </button>
                    {showReactivate && (
                        <div style={{ marginTop: 10, padding: '18px 20px', borderRadius: 12, background: 'rgba(16,185,129,0.05)', border: '1px solid #10b98130' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                                Reactiva la empresa. Se creará un nuevo ejercicio fiscal. Los libros anteriores permanecen inmutables.
                            </div>
                            <div style={{ marginBottom: 10 }}>
                                <label style={{ fontSize: '0.76rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                                    Fecha de nueva inscripción ante Hacienda
                                </label>
                                <input type="date" value={reactDate} onChange={e => setReactDate(e.target.value)}
                                    id="reactivar-fecha"
                                    style={{ padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', width: 170 }} />
                            </div>
                            <div style={{ marginBottom: 14 }}>
                                <label style={{ fontSize: '0.76rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                                    Razón (opcional)
                                </label>
                                <input type="text" value={reactReason} onChange={e => setReactReason(e.target.value)}
                                    placeholder="Ej: Nueva inscripción Hacienda #123456"
                                    style={{ padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', width: '100%', maxWidth: 380 }} />
                            </div>
                            <button id="btn-reactivar-empresa" onClick={doReactivate} disabled={!reactDate || loadingReact}
                                style={{ padding: '9px 22px', background: '#10b981', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: reactDate ? 'pointer' : 'not-allowed', opacity: reactDate ? 1 : 0.5, fontSize: '0.88rem' }}>
                                {loadingReact ? '⏳ Reactivando...' : '🟢 Reactivar y abrir nuevo ejercicio'}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Resultado reactivación */}
            {reactResult && (
                <div style={{ marginTop: 16, ...panelStyle('#10b981') }}>
                    <div style={{ fontWeight: 700, color: '#10b981', marginBottom: 8 }}>
                        🟢 Empresa reactivada — {reactResult.reactivation_date}
                    </div>
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 6 }}>
                        Nuevo ejercicio fiscal <strong>{reactResult.new_fiscal_year}</strong> abierto.
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        📌 {reactResult.next_action}
                    </div>
                </div>
            )}

            {/* Info contable */}
            <div style={{ marginTop: 24, padding: '12px 16px', borderRadius: 8, background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)', fontSize: '0.76rem', color: 'var(--text-secondary)' }}>
                <strong style={{ color: '#8b5cf6' }}>📖 Flujo contable NIIF:</strong>{' '}
                <strong>A</strong>) Ingresos → 3304 · <strong>B</strong>) Gastos → 3304 ·{' '}
                <strong>C</strong>) 3304 → 3303 Utilidad (o 3302 Pérdida) ·
                Apertura: saldos de ACTIVO/PASIVO/PATRIMONIO se trasladan al año siguiente.
            </div>
        </div>
    )
}

