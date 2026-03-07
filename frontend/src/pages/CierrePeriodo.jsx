/**
 * CierrePeriodo.jsx — Cierre Contable de Período (5 Pasos)
 *
 * Flujo legal (Art. 51 Ley Renta CR — inalterabilidad):
 *  Paso 1: Asientos del mes completados (DRAFT = 0)
 *  Paso 2: Ajustes aplicados (depreciación, devengados)
 *  Paso 3: Asiento de cierre I/E generado (POSTED)
 *  Paso 4: Balance cuadrado (DR = CR)
 *  Paso 5: Admin bloquea → CLOSED (libros digitales disponibles)
 *
 * Estados: OPEN → CLOSING → CLOSED
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

const MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

// Genera opciones desde fromYm hasta el mes siguiente al actual
function periodOptions(fromYm) {
    if (!fromYm) return []
    const opts = []
    const now = new Date()
    const [fy, fm] = fromYm.split('-').map(Number)
    const fromDate = new Date(fy, fm - 1, 1)
    // Incluir hasta el mes siguiente al actual (para el período activo)
    let d = new Date(now.getFullYear(), now.getMonth() + 1, 1)
    while (d >= fromDate) {
        const y = d.getFullYear(), m = d.getMonth() + 1
        const ym = `${y}-${String(m).padStart(2, '0')}`
        opts.push({ ym, label: `${MESES[m]} ${y} (${ym})` })
        d = new Date(y, d.getMonth() - 1, 1)
    }
    return opts
}

const STATUS_COLOR = { OPEN: '#3b82f6', CLOSING: '#f59e0b', CLOSED: '#10b981' }
const STATUS_ICON = { OPEN: '🔓', CLOSING: '⏳', CLOSED: '🔒' }
const STATUS_LABEL = { OPEN: 'Abierto', CLOSING: 'En cierre', CLOSED: 'Cerrado' }

export default function CierrePeriodo() {
    const { state } = useApp()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const isAdmin = role === 'admin'
    const isContador = role === 'contador' || isAdmin
    const navigate = useNavigate()

    const [openingMonth, setOpeningMonth] = useState(null)   // primer mes de apertura
    const [lastClosedPeriod, setLastClosedPeriod] = useState(null)  // último CLOSED
    const [period, setPeriod] = useState(null)                // mes a trabajar (auto)

    // opts dinámicos — solo desde openingMonth hasta hoy+1
    const opts = periodOptions(openingMonth)

    // Estado del período
    const [status, setStatus] = useState('OPEN')
    const [statusInfo, setStatusInfo] = useState(null)
    const [loadingStatus, setLoadingStatus] = useState(false)

    // Checks automáticos
    const [draftCount, setDraftCount] = useState(null)
    const [hasCierre, setHasCierre] = useState(false)
    const [balanced, setBalanced] = useState(false)
    const [loadingChecks, setLoadingChecks] = useState(false)

    // Acciones
    const [loadingAction, setLoadingAction] = useState(false)
    const [actionMsg, setActionMsg] = useState(null)
    const [actionErr, setActionErr] = useState(null)
    const [closing, setClosing] = useState(false)
    const [confirmLock, setConfirmLock] = useState(false)

    // ── Descubrir openingMonth y último período CLOSED ──────────
    useEffect(() => {
        if (!token) return
        const h = { Authorization: `Bearer ${token}` }
        fetch(`${apiUrl}/ledger/opening-entry`, { headers: h })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                const now = new Date()
                const curYm = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
                const fromYm = data?.date?.slice(0, 7) || curYm
                setOpeningMonth(fromYm)
                // Buscar el último período CLOSED desde la apertura hacia atrás
                const [fy, fm] = fromYm.split('-').map(Number)
                const months = []
                let d = new Date(now.getFullYear(), now.getMonth(), 1)
                const fromDate = new Date(fy, fm - 1, 1)
                while (d >= fromDate) {
                    const y = d.getFullYear(), m = d.getMonth() + 1
                    months.push(`${y}-${String(m).padStart(2, '0')}`)
                    d = new Date(y, d.getMonth() - 1, 1)
                }
                Promise.all(months.map(ym =>
                    fetch(`${apiUrl}/ledger/period/${ym}/status`, { headers: h })
                        .then(r => r.ok ? r.json() : { year_month: ym, status: 'OPEN' })
                        .catch(() => ({ year_month: ym, status: 'OPEN' }))
                )).then(results => {
                    const closed = results.find(r => r.status === 'CLOSED')
                    if (closed) {
                        setLastClosedPeriod(closed.year_month)
                        const [cy, cm] = closed.year_month.split('-').map(Number)
                        const nxt = cm === 12 ? `${cy + 1}-01` : `${cy}-${String(cm + 1).padStart(2, '0')}`
                        setPeriod(nxt)
                    } else {
                        // Sin cierres: default al mes de apertura
                        setPeriod(fromYm)
                    }
                })
            })
            .catch(() => {
                const now = new Date()
                const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
                setPeriod(cur)
            })
    }, [token])

    // ── Cargar estado del período ─────────────────────────────────
    const loadStatus = useCallback(async () => {
        if (!token || !period) return
        setLoadingStatus(true)
        try {
            const r = await fetch(`${apiUrl}/ledger/period/${period}/status`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) {
                const d = await r.json()
                setStatus(d.status)
                setStatusInfo(d)
            }
        } catch { /* red */ }
        finally { setLoadingStatus(false) }
    }, [apiUrl, token, period])

    // ── Cargar checks automáticos ────────────────────────────────
    const loadChecks = useCallback(async () => {
        if (!token || !period) return
        setLoadingChecks(true)
        try {
            // Check 1: DRAFTs pendientes
            const rDraft = await fetch(`${apiUrl}/ledger/entries?period=${period}&status=DRAFT`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (rDraft.ok) {
                const d = await rDraft.json()
                setDraftCount(Array.isArray(d) ? d.length : (d.total || 0))
            }
            // Check 3: Asiento de cierre (source=CIERRE, POSTED)
            const rCierre = await fetch(`${apiUrl}/ledger/entries?period=${period}&source=CIERRE&status=POSTED`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (rCierre.ok) {
                const d = await rCierre.json()
                setHasCierre(Array.isArray(d) ? d.length > 0 : (d.total || 0) > 0)
            }
            // Check 4: Balance cuadrado — via trial-balance endpoint
            const rBal = await fetch(`${apiUrl}/ledger/trial-balance?period=${period}&acumulado=false`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (rBal.ok) {
                const d = await rBal.json()
                setBalanced(d.balanced === true)
            }
        } catch { /* net error */ }
        finally { setLoadingChecks(false) }
    }, [apiUrl, token, period])

    useEffect(() => {
        loadStatus()
        loadChecks()
    }, [period, token])

    // ── Generar asiento de cierre I/E (DRAFT) ───────────────────
    async function generateCierre() {
        setClosing(true); setActionMsg(null); setActionErr(null)
        try {
            const r = await fetch(`${apiUrl}/ledger/close-period`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ period })
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error al generar cierre')
            setActionMsg('✅ Asiento de cierre I/E generado como DRAFT. Revísalo y apruébalo en el Diario.')
            await loadChecks()
        } catch (e) { setActionErr(e.message) }
        finally { setClosing(false) }
    }

    // ── Solicitar cierre OPEN → CLOSING ────────────────────────
    async function requestClose() {
        setLoadingAction(true); setActionMsg(null); setActionErr(null)
        try {
            const r = await fetch(`${apiUrl}/ledger/period/${period}/close-request`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error')
            setActionMsg('✅ Período en CLOSING. El administrador puede ahora bloquearlo.')
            await loadStatus()
        } catch (e) { setActionErr(e.message) }
        finally { setLoadingAction(false) }
    }

    // ── Bloquear CLOSING → CLOSED ───────────────────────────────
    async function lockPeriod() {
        setLoadingAction(true); setActionMsg(null); setActionErr(null)
        setConfirmLock(false)
        try {
            const r = await fetch(`${apiUrl}/ledger/period/${period}/lock`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || 'Error')
            setActionMsg('🔒 Período CERRADO. Libros digitales disponibles en "Libros Digitales".')
            await loadStatus()
        } catch (e) { setActionErr(e.message) }
        finally { setLoadingAction(false) }
    }

    // ── Pasos del stepper ────────────────────────────────────────
    const step1OK = draftCount === 0
    const step2OK = true  // manual por ahora — sin activos fijos requeridos
    const step3OK = hasCierre
    const step4OK = balanced
    const allChecksOK = step1OK && step3OK && step4OK

    const steps = [
        { n: 1, label: 'Asientos del mes', desc: draftCount === null ? 'Verificando...' : draftCount === 0 ? '0 borradoes pendientes ✓' : `${draftCount} DRAFT pendiente(s) — aprueba en el Diario`, ok: step1OK },
        { n: 2, label: 'Ajustes aplicados', desc: 'Depreciación, devengados. Verificación manual.', ok: step2OK, manual: true },
        { n: 3, label: 'Asiento de cierre I/E', desc: hasCierre ? 'Asiento de cierre POSTED ✓' : 'Pendiente — genera el asiento de cierre abajo', ok: step3OK },
        { n: 4, label: 'Balance cuadrado', desc: loadingChecks ? 'Verificando...' : balanced ? 'DR = CR ✓' : 'Débitos ≠ Créditos — revisa asientos', ok: step4OK },
        { n: 5, label: 'Bloquear período', desc: status === 'CLOSED' ? '🔒 Período bloqueado — libros digitales listos' : 'Admin bloquea → CLOSED', ok: status === 'CLOSED' },
    ]

    return (
        <div style={{ maxWidth: 780, margin: '0 auto', padding: '32px 20px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, gap: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: '1.5rem' }}>📅</span>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>Cierre de Período</h2>
                        <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            Art. 51 Ley Renta CR · Flujo OPEN → CLOSING → CLOSED
                        </p>
                    </div>
                </div>
                {/* Estado badge */}
                {!loadingStatus && (
                    <div style={{
                        display: 'flex', alignItems: 'center', gap: 6, padding: '5px 14px',
                        borderRadius: 20, background: STATUS_COLOR[status] + '20',
                        border: `1px solid ${STATUS_COLOR[status]}40`, fontSize: '0.82rem',
                        fontWeight: 700, color: STATUS_COLOR[status]
                    }}>
                        {STATUS_ICON[status]} {STATUS_LABEL[status]}
                    </div>
                )}
            </div>

            {/* Selector de período */}
            <div style={{ marginBottom: 24 }}>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Período a cerrar</label>
                <select
                    id="cierre-period-select"
                    value={period}
                    onChange={e => { setPeriod(e.target.value); setActionMsg(null); setActionErr(null) }}
                    style={{
                        padding: '8px 12px', borderRadius: 7, border: '1px solid var(--border-color)',
                        background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.9rem',
                        minWidth: 240, cursor: 'pointer'
                    }}
                >
                    {opts.map(o => (
                        <option key={o.ym} value={o.ym}>{o.label} ({o.ym})</option>
                    ))}
                </select>
            </div>

            {/* Stepper */}
            <div style={{
                background: 'var(--bg-card)', borderRadius: 12, border: '1px solid var(--border-color)',
                overflow: 'hidden', marginBottom: 24
            }}>
                {steps.map((s, idx) => (
                    <div key={s.n} style={{
                        display: 'flex', alignItems: 'flex-start', gap: 14, padding: '14px 18px',
                        borderBottom: idx < steps.length - 1 ? '1px solid var(--border-color)' : 'none',
                        background: s.ok ? 'rgba(16,185,129,0.04)' : 'transparent'
                    }}>
                        {/* Número / check */}
                        <div style={{
                            width: 32, height: 32, borderRadius: '50%', display: 'flex', alignItems: 'center',
                            justifyContent: 'center', flexShrink: 0, fontSize: '0.82rem', fontWeight: 700,
                            background: s.ok ? '#10b981' : s.manual ? '#f59e0b20' : 'var(--bg-header)',
                            color: s.ok ? 'white' : s.manual ? '#f59e0b' : 'var(--text-muted)',
                            border: s.ok ? 'none' : s.manual ? '1px solid #f59e0b40' : '1px solid var(--border-color)'
                        }}>
                            {s.ok ? '✓' : s.n}
                        </div>
                        {/* Texto */}
                        <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '0.88rem', fontWeight: 600, color: s.ok ? '#10b981' : 'var(--text-primary)' }}>
                                {s.label}
                                {s.manual && <span style={{ marginLeft: 6, fontSize: '0.68rem', background: '#f59e0b20', color: '#f59e0b', borderRadius: 4, padding: '1px 5px' }}>manual</span>}
                            </div>
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 2 }}>{s.desc}</div>
                        </div>
                    </div>
                ))}
            </div>

            {/* Mensajes */}
            {actionMsg && (
                <div style={{
                    padding: '10px 14px', borderRadius: 8, background: 'rgba(16,185,129,0.1)',
                    border: '1px solid #10b981', color: '#10b981', fontSize: '0.85rem', marginBottom: 16
                }}>
                    {actionMsg}
                </div>
            )}
            {actionErr && (
                <div style={{
                    padding: '10px 14px', borderRadius: 8, background: 'rgba(239,68,68,0.1)',
                    border: '1px solid #ef4444', color: '#ef4444', fontSize: '0.85rem', marginBottom: 16
                }}>
                    ⚠️ {actionErr}
                </div>
            )}

            {/* Botones de acción */}
            {status !== 'CLOSED' && isContador && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

                    {/* Botón 1: Generar asiento cierre I/E */}
                    {!step3OK && status === 'OPEN' && (
                        <button
                            id="btn-generar-cierre"
                            onClick={generateCierre}
                            disabled={closing || !step1OK}
                            style={{
                                padding: '10px 22px', background: step1OK ? '#7c3aed' : 'var(--bg-card)',
                                border: 'none', borderRadius: 8, color: step1OK ? 'white' : 'var(--text-muted)',
                                fontWeight: 700, cursor: step1OK ? 'pointer' : 'not-allowed', fontSize: '0.88rem'
                            }}
                        >
                            {closing ? '⏳ Generando...' : '📋 Generar asiento de cierre I/E (DRAFT)'}
                        </button>
                    )}

                    {/* Botón 2: Solicitar cierre (OPEN → CLOSING) */}
                    {status === 'OPEN' && (
                        <button
                            id="btn-solicitar-cierre"
                            onClick={requestClose}
                            disabled={loadingAction || !allChecksOK}
                            title={!allChecksOK ? 'Completa los 4 pasos primero' : 'Solicitar cierre al administrador'}
                            style={{
                                padding: '10px 22px', background: allChecksOK ? '#f59e0b' : 'var(--bg-card)',
                                border: 'none', borderRadius: 8, color: allChecksOK ? 'white' : 'var(--text-muted)',
                                fontWeight: 700, cursor: allChecksOK ? 'pointer' : 'not-allowed', fontSize: '0.88rem'
                            }}
                        >
                            {loadingAction ? '⏳ Procesando...' : '✅ Solicitar cierre del período'}
                        </button>
                    )}

                    {/* Botón 3: Bloquear (CLOSING → CLOSED) — solo admin */}
                    {status === 'CLOSING' && isAdmin && !confirmLock && (
                        <button
                            id="btn-lock-periodo"
                            onClick={() => setConfirmLock(true)}
                            disabled={loadingAction}
                            style={{
                                padding: '12px 22px', background: '#ef4444', border: 'none', borderRadius: 8,
                                color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem'
                            }}
                        >
                            🔒 Bloquear período (IRREVERSIBLE)
                        </button>
                    )}
                    {/* Confirmación inline — reemplaza window.confirm() */}
                    {status === 'CLOSING' && isAdmin && confirmLock && (
                        <div style={{
                            padding: '14px 18px', borderRadius: 10, background: 'rgba(239,68,68,0.1)',
                            border: '2px solid #ef4444'
                        }}>
                            <div style={{ fontWeight: 700, color: '#ef4444', marginBottom: 6, fontSize: '0.9rem' }}>
                                ⚠️ ¿Confirmar bloqueo de {period}?
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 14 }}>
                                Esta acción es <strong>IRREVERSIBLE</strong>. El período quedará cerrado y los libros digitales disponibles.
                            </div>
                            <div style={{ display: 'flex', gap: 10 }}>
                                <button
                                    id="btn-lock-cancelar"
                                    onClick={() => setConfirmLock(false)}
                                    style={{
                                        padding: '8px 18px', background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                        borderRadius: 7, color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem'
                                    }}
                                >
                                    Cancelar
                                </button>
                                <button
                                    id="btn-lock-confirmar"
                                    onClick={lockPeriod}
                                    disabled={loadingAction}
                                    style={{
                                        padding: '8px 18px', background: '#ef4444', border: 'none',
                                        borderRadius: 7, color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: '0.85rem'
                                    }}
                                >
                                    {loadingAction ? '⏳ Bloqueando...' : '🔒 Sí, bloquear definitivamente'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Estado CLOSED — link a Libros */}
            {status === 'CLOSED' && (
                <div style={{
                    padding: '16px 18px', borderRadius: 10, background: 'rgba(16,185,129,0.08)',
                    border: '1px solid #10b981', textAlign: 'center'
                }}>
                    <div style={{ fontSize: '1.4rem', marginBottom: 6 }}>🔒</div>
                    <div style={{ fontWeight: 700, color: '#10b981', marginBottom: 4 }}>Período Cerrado</div>
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 12 }}>
                        Los libros digitales (Diario, Mayor, Inventarios y Balances) están listos.
                    </div>
                    <button
                        onClick={() => navigate('/libros-digitales')}
                        style={{
                            display: 'inline-block', padding: '8px 20px', background: '#7c3aed', color: 'white',
                            borderRadius: 8, fontWeight: 700, fontSize: '0.88rem', border: 'none', cursor: 'pointer'
                        }}
                    >
                        📚 Ir a Libros Digitales →
                    </button>
                </div>
            )}

            {!isContador && (
                <div style={{
                    padding: 14, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
                    borderRadius: 8, color: '#ef4444', fontSize: '0.82rem'
                }}>
                    Solo el contador o administrador puede ejecutar el cierre de período.
                </div>
            )}

            {/* Nota legal */}
            <div style={{
                marginTop: 20, padding: '10px 16px', borderRadius: 8,
                background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)',
                fontSize: '0.77rem', color: 'var(--text-secondary)'
            }}>
                <strong style={{ color: '#8b5cf6' }}>⚖️ Marco legal:</strong>{' '}
                Art. 51 Ley del Impuesto sobre la Renta · Código de Comercio CR · Ley 8454 (Firma Digital).
                Una vez en CLOSED, el período es inalterado y los libros tienen validez legal equivalente a los físicos.
            </div>
        </div>
    )
}
