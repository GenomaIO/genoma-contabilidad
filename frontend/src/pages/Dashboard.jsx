/**
 * Dashboard.jsx — Resumen Contable · Datos en vivo
 *
 * Lógica de períodos (clase mundial):
 *   · lastClosedPeriod = último mes con status CLOSED   → fuente de KPIs y últimos asientos
 *   · activePeriod     = mes siguiente al cerrado       → fuente de "Estado del Período"
 *
 * Conecta:
 *   · GET /ledger/period/{ym}/status               → descubrir lastClosedPeriod
 *   · GET /ledger/trial-balance?period=CLOSED      → KPIs (Activos/Pasivos/Patrimonio/Resultado)
 *   · GET /ledger/entries?period=CLOSED            → Últimos 5 asientos del mes cerrado
 *   · GET /ledger/entries?period=ACTIVE&status=DRAFT → conteo DRAFTs del mes activo
 *   · GET /ledger/opening-entry                    → ¿hay apertura?
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

const MONTHS_FULL = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const MONTHS_SHORT = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function ymLabel(ym, full = false) {
    if (!ym) return '—'
    const [y, m] = ym.split('-')
    return `${(full ? MONTHS_FULL : MONTHS_SHORT)[parseInt(m) - 1]} ${y}`
}

function nextYm(ym) {
    if (!ym) return null
    const [y, m] = ym.split('-').map(Number)
    return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`
}

function fmt(n) {
    if (n === null || n === undefined || isNaN(n)) return '—'
    return `¢${Math.abs(n).toLocaleString('es-CR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

const PERIOD_COLORS = { OPEN: '#3b82f6', CLOSING: '#f59e0b', CLOSED: '#10b981' }
const PERIOD_LABELS = { OPEN: '🔓 Abierto', CLOSING: '⏳ En cierre', CLOSED: '🔒 Cerrado' }

export default function Dashboard() {
    const { state } = useApp()
    const navigate = useNavigate()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    // ── Períodos calculados automáticamente ─────────────────────
    const [lastClosedPeriod, setLastClosedPeriod] = useState(null)  // '2026-01'
    const [activePeriod, setActivePeriod] = useState(null)          // '2026-02'
    const [discovering, setDiscovering] = useState(true)

    // ── Datos ──────────────────────────────────────────────────
    const [kpis, setKpis] = useState({ activos: null, pasivos: null, patrimonio: null, resultado: null })
    const [recentEntries, setRecentEntries] = useState([])
    const [draftCount, setDraftCount] = useState(null)
    const [hasApertura, setHasApertura] = useState(null)
    const [activePeriodStatus, setActivePeriodStatus] = useState(null)
    const [loading, setLoading] = useState(true)

    const h = { Authorization: `Bearer ${token}` }

    // ── Paso 1: Descubrir el último período cerrado ─────────────
    useEffect(() => {
        if (!token) return
        setDiscovering(true)
        const now = new Date()
        const checks = []
        for (let i = 0; i < 13; i++) {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
            checks.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
        }
        Promise.all(checks.map(ym =>
            fetch(`${apiUrl}/ledger/period/${ym}/status`, { headers: h })
                .then(r => r.ok ? r.json() : { year_month: ym, status: 'OPEN' })
                .catch(() => ({ year_month: ym, status: 'OPEN' }))
        )).then(results => {
            const closed = results.find(r => r.status === 'CLOSED')
            if (closed) {
                const lcp = closed.year_month
                setLastClosedPeriod(lcp)
                setActivePeriod(nextYm(lcp))
            } else {
                // Sin períodos cerrados: el período activo es el mes actual
                const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
                setActivePeriod(cur)
            }
        }).finally(() => setDiscovering(false))
    }, [token])

    // ── Paso 2: Apertura (una sola vez) ─────────────────────────
    useEffect(() => {
        if (!token) return
        fetch(`${apiUrl}/ledger/opening-entry`, { headers: h })
            .then(r => r.ok ? r.json() : null)
            .then(data => setHasApertura(!!data))
            .catch(() => setHasApertura(false))
    }, [token])

    // ── Paso 3: Datos cuando se conocen los períodos ────────────
    useEffect(() => {
        if (!token || discovering) return
        if (!activePeriod) return

        setLoading(true)
        const kpiPeriod = lastClosedPeriod || activePeriod

        Promise.allSettled([
            // 1. Trial balance del ÚLTIMO CERRADO → KPIs
            fetch(`${apiUrl}/ledger/trial-balance?period=${kpiPeriod}&acumulado=true`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 2. Últimos asientos del MES CERRADO
            fetch(`${apiUrl}/ledger/entries?period=${kpiPeriod}`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 3. DRAFTs del MES ACTIVO (a trabajar)
            fetch(`${apiUrl}/ledger/entries?period=${activePeriod}&status=DRAFT`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 4. Estado del MES ACTIVO
            fetch(`${apiUrl}/ledger/period/${activePeriod}/status`, { headers: h })
                .then(r => r.ok ? r.json() : null),
        ]).then(([tbRes, entriesRes, draftRes, statusRes]) => {
            // KPIs — trial_balance devuelve { period, lines:[...], ... } (no un array)
            const tbRaw = tbRes.status === 'fulfilled' ? tbRes.value : null
            const tb = Array.isArray(tbRaw) ? tbRaw : (tbRaw?.lines || [])
            if (tb.length > 0) {
                const sum = (type, sign) => {
                    const rows = tb.filter(r => r.account_type === type)
                    return rows.reduce((acc, r) => {
                        // API devuelve total_debit / total_credit (no debit / credit)
                        const td = r.total_debit ?? r.debit ?? 0
                        const tc = r.total_credit ?? r.credit ?? 0
                        const net = td - tc
                        return acc + (sign === 'debit' ? net : -net)
                    }, 0)
                }
                const ingresos = Math.abs(sum('INGRESO', 'credit'))
                const gastos = Math.abs(sum('GASTO', 'debit'))
                setKpis({
                    activos: sum('ACTIVO', 'debit'),      // Dep.Acum (CR > DR) resta automáticamente
                    pasivos: Math.abs(sum('PASIVO', 'credit')),
                    patrimonio: Math.abs(sum('PATRIMONIO', 'credit')),
                    resultado: ingresos - gastos,
                })
            }
            // Asientos del mes cerrado
            const allEntries = entriesRes.status === 'fulfilled' ? (entriesRes.value || []) : []
            setRecentEntries(allEntries.slice(-5).reverse())

            // DRAFTs
            const drafts = draftRes.status === 'fulfilled' ? (draftRes.value || []) : []
            setDraftCount(drafts.length)

            // Estado del mes activo
            const pst = statusRes.status === 'fulfilled' ? statusRes.value : null
            setActivePeriodStatus(pst?.status || 'OPEN')
        }).finally(() => setLoading(false))
    }, [lastClosedPeriod, activePeriod, discovering, token])

    // ── Tareas del mes activo ────────────────────────────────────
    const tasks = [
        {
            label: 'Apertura del ejercicio creada',
            done: hasApertura === true,
            pending: hasApertura === null,
            action: () => navigate('/configuracion/apertura'),
            actionLabel: 'Crear apertura',
        },
        {
            label: draftCount === 0
                ? 'Sin borradores pendientes ✓'
                : draftCount === null
                    ? 'Verificando borradores...'
                    : `${draftCount} asiento(s) BORRADOR pendiente(s)`,
            done: draftCount === 0,
            pending: draftCount === null,
            action: () => navigate('/diario'),
            actionLabel: 'Ver Diario',
        },
        {
            label: activePeriodStatus === 'CLOSED'
                ? `Período ${activePeriod} cerrado ✓`
                : `Período ${activePeriod}: ${PERIOD_LABELS[activePeriodStatus] || '—'}`,
            done: activePeriodStatus === 'CLOSED',
            pending: activePeriodStatus === null,
            action: () => navigate('/cierre'),
            actionLabel: 'Ir a Cierre',
        },
    ]
    const pendingCount = tasks.filter(t => !t.done && !t.pending).length

    // ── KPI Cards ────────────────────────────────────────────────
    const cards = [
        {
            label: 'Activos', value: fmt(kpis.activos), icon: '🏦',
            color: '#3b82f6', bg: 'rgba(59,130,246,0.12)',
        },
        {
            label: 'Pasivos', value: fmt(kpis.pasivos), icon: '📋',
            color: '#ef4444', bg: 'rgba(239,68,68,0.10)',
        },
        {
            label: 'Patrimonio', value: fmt(kpis.patrimonio), icon: '💎',
            color: '#8b5cf6', bg: 'rgba(139,92,246,0.12)',
        },
        {
            label: 'Resultado',
            value: kpis.resultado !== null
                ? (kpis.resultado >= 0 ? `▲ ${fmt(kpis.resultado)}` : `▼ ${fmt(kpis.resultado)}`)
                : '—',
            icon: (kpis.resultado || 0) >= 0 ? '📈' : '📉',
            color: (kpis.resultado || 0) >= 0 ? '#10b981' : '#ef4444',
            bg: (kpis.resultado || 0) >= 0 ? 'rgba(16,185,129,0.10)' : 'rgba(239,68,68,0.10)',
        },
    ]

    const activeStatusColor = PERIOD_COLORS[activePeriodStatus] || '#6b7280'

    return (
        <div style={{ padding: '20px 0', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ── */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
                <div>
                    <h2 style={{ fontSize: '1.3rem', fontWeight: 700, margin: 0 }}>Resumen Contable</h2>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 3 }}>
                        {lastClosedPeriod
                            ? <>Balanza de comprobación al cierre de <strong>{ymLabel(lastClosedPeriod, true)}</strong></>
                            : 'Sin períodos cerrados aún'}
                    </p>
                </div>
                {/* Badge estado activo */}
                {activePeriod && (
                    <span style={{
                        padding: '4px 12px', borderRadius: 20,
                        fontSize: '0.75rem', fontWeight: 600,
                        background: `${activeStatusColor}22`, color: activeStatusColor,
                        border: `1px solid ${activeStatusColor}44`,
                        alignSelf: 'center',
                    }}>
                        {ymLabel(activePeriod)} · {PERIOD_LABELS[activePeriodStatus] || '—'}
                    </span>
                )}
            </div>

            {/* ── KPI Cards — datos del último período CLOSED ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 4 }}>
                {cards.map(card => (
                    <div key={card.label} style={{
                        background: 'var(--bg-card)', borderRadius: 14,
                        padding: '16px 18px', border: '1px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', gap: 14,
                        position: 'relative', overflow: 'hidden',
                    }}>
                        <div style={{
                            position: 'absolute', top: 0, right: 0,
                            width: 80, height: 80, borderRadius: '0 14px 0 80px',
                            background: card.bg, pointerEvents: 'none',
                        }} />
                        <div style={{
                            width: 42, height: 42, borderRadius: 10,
                            background: card.bg,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: '1.3rem', flexShrink: 0,
                        }}>
                            {card.icon}
                        </div>
                        <div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                {card.label}
                            </div>
                            <div style={{
                                fontSize: '1.05rem', fontWeight: 700, marginTop: 3,
                                color: loading || discovering ? 'var(--text-muted)' : card.color,
                                fontVariantNumeric: 'tabular-nums',
                            }}>
                                {loading || discovering ? <span style={{ opacity: 0.4 }}>—</span> : card.value}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
            {/* Fuente de los KPIs */}
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 18, paddingLeft: 2 }}>
                {lastClosedPeriod
                    ? `📊 Datos acumulados al cierre de ${ymLabel(lastClosedPeriod, true)}`
                    : '📊 Sin período cerrado — mostrando período en curso'}
            </div>

            {/* ── Últimos Asientos + Estado del Período ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>

                {/* Últimos Asientos — del MES CERRADO */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 14, padding: 18, border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <div>
                            <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>📒 Últimos Asientos</span>
                            {lastClosedPeriod && (
                                <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginLeft: 8 }}>
                                    {ymLabel(lastClosedPeriod, true)}
                                </span>
                            )}
                        </div>
                        <button
                            onClick={() => navigate('/diario')}
                            style={{
                                background: 'none', border: 'none', color: 'var(--accent)',
                                fontSize: '0.78rem', cursor: 'pointer', padding: '2px 6px', borderRadius: 5,
                            }}
                        >
                            Ver todos →
                        </button>
                    </div>

                    {loading || discovering ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center', padding: '20px 0', opacity: 0.6 }}>
                            ⏳ Cargando...
                        </div>
                    ) : recentEntries.length === 0 ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center', padding: '24px 0' }}>
                            {lastClosedPeriod
                                ? `Sin asientos en ${ymLabel(lastClosedPeriod, true)}`
                                : 'Aún no hay períodos cerrados'}
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {recentEntries.map(e => {
                                const sc = e.status === 'POSTED' ? '#10b981' : e.status === 'DRAFT' ? '#f59e0b' : '#ef4444'
                                return (
                                    <div key={e.id} style={{
                                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                        padding: '8px 10px', borderRadius: 8,
                                        background: 'rgba(255,255,255,0.03)',
                                        border: '1px solid var(--border-color)',
                                    }}>
                                        <div style={{ overflow: 'hidden' }}>
                                            <div style={{ fontSize: '0.82rem', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 210 }}>
                                                {e.description}
                                            </div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 1 }}>
                                                {e.date}
                                            </div>
                                        </div>
                                        <span style={{
                                            fontSize: '0.68rem', fontWeight: 700, padding: '2px 7px',
                                            borderRadius: 10, background: `${sc}22`, color: sc, flexShrink: 0,
                                        }}>
                                            {e.status}
                                        </span>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>

                {/* Estado del Período — del MES ACTIVO (siguiente al cerrado) */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 14, padding: 18, border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <div>
                            <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>✅ Estado del Período</span>
                            {activePeriod && (
                                <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginLeft: 8 }}>
                                    {ymLabel(activePeriod, true)}
                                </span>
                            )}
                        </div>
                        {pendingCount > 0 && (
                            <span style={{
                                padding: '2px 9px', borderRadius: 20,
                                fontSize: '0.72rem', fontWeight: 700,
                                background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                            }}>
                                {pendingCount} pendiente{pendingCount !== 1 ? 's' : ''}
                            </span>
                        )}
                        {pendingCount === 0 && !loading && !discovering && (
                            <span style={{
                                padding: '2px 9px', borderRadius: 20,
                                fontSize: '0.72rem', fontWeight: 700,
                                background: 'rgba(16,185,129,0.15)', color: '#10b981',
                            }}>
                                Todo al día ✓
                            </span>
                        )}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {tasks.map((task, i) => (
                            <div key={i} style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                padding: '10px 12px', borderRadius: 9,
                                background: task.done
                                    ? 'rgba(16,185,129,0.06)'
                                    : task.pending ? 'rgba(255,255,255,0.02)' : 'rgba(239,68,68,0.06)',
                                border: `1px solid ${task.done ? 'rgba(16,185,129,0.2)' : task.pending ? 'var(--border-color)' : 'rgba(239,68,68,0.2)'}`,
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                                    <span style={{ fontSize: '1rem' }}>
                                        {task.pending ? '⏳' : task.done ? '✅' : '⚠️'}
                                    </span>
                                    <span style={{
                                        fontSize: '0.8rem',
                                        color: task.done ? '#10b981' : task.pending ? 'var(--text-muted)' : 'var(--text-primary)',
                                        fontWeight: task.done ? 400 : 500,
                                    }}>
                                        {task.label}
                                    </span>
                                </div>
                                {!task.done && !task.pending && (
                                    <button
                                        onClick={task.action}
                                        style={{
                                            padding: '3px 9px', borderRadius: 6, border: 'none',
                                            background: 'var(--accent)', color: '#fff',
                                            fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer',
                                            whiteSpace: 'nowrap', flexShrink: 0,
                                        }}
                                    >
                                        {task.actionLabel}
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Acceso directo a Cierre y Libros */}
                    <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                        <button
                            onClick={() => navigate('/cierre')}
                            style={{
                                flex: 1, padding: '8px 0', borderRadius: 8,
                                border: '1px solid var(--border-color)', background: 'transparent',
                                color: 'var(--text-secondary)', fontSize: '0.78rem', cursor: 'pointer',
                                fontWeight: 600,
                            }}
                        >
                            📆 Ir a Cierre
                        </button>
                        <button
                            onClick={() => navigate('/libros-digitales')}
                            style={{
                                flex: 1, padding: '8px 0', borderRadius: 8,
                                border: '1px solid var(--border-color)', background: 'transparent',
                                color: 'var(--text-secondary)', fontSize: '0.78rem', cursor: 'pointer',
                                fontWeight: 600,
                            }}
                        >
                            📚 Libros Digitales
                        </button>
                    </div>
                </div>
            </div>
            {/* Barra API eliminada — ya existe en el footer del Sidebar */}
        </div>
    )
}
