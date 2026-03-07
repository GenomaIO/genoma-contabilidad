/**
 * Dashboard.jsx — Resumen Contable · Datos en vivo
 *
 * Conecta:
 *   · GET /ledger/trial-balance?period=YM   → KPIs (Activos/Pasivos/Patrimonio/Resultado)
 *   · GET /ledger/entries?period=YM          → Últimos 5 asientos
 *   · GET /ledger/entries?period=YM&status=DRAFT → conteo DRAFTs
 *   · GET /ledger/opening-entry              → ¿há apertura?
 *   · GET /ledger/period/{ym}/status         → estado del período
 */
import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function getCurrentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
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

    const [period, setPeriod] = useState(getCurrentPeriod())
    const [openingMonth, setOpeningMonth] = useState(null)

    // Datos
    const [kpis, setKpis] = useState({ activos: null, pasivos: null, patrimonio: null, resultado: null })
    const [recentEntries, setRecentEntries] = useState([])
    const [draftCount, setDraftCount] = useState(null)
    const [hasApertura, setHasApertura] = useState(null)
    const [periodStatus, setPeriodStatus] = useState(null)
    const [loading, setLoading] = useState(true)

    // ── Apertura (una sola vez) ─────────────────────────────────
    useEffect(() => {
        if (!token) return
        fetch(`${apiUrl}/ledger/opening-entry`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                setHasApertura(!!data)
                if (data?.date) {
                    const ym = data.date.slice(0, 7)
                    setOpeningMonth(ym)
                    setPeriod(p => p < ym ? ym : p)
                }
            })
            .catch(() => setHasApertura(false))
    }, [token])

    // ── Datos dependientes del período ─────────────────────────
    useEffect(() => {
        if (!token) return
        setLoading(true)

        const h = { Authorization: `Bearer ${token}` }

        Promise.allSettled([
            // 1. Trial balance → KPIs por tipo
            fetch(`${apiUrl}/ledger/trial-balance?period=${period}&acumulado=true`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 2. Últimos 5 asientos del período
            fetch(`${apiUrl}/ledger/entries?period=${period}`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 3. DRAFTs pendientes
            fetch(`${apiUrl}/ledger/entries?period=${period}&status=DRAFT`, { headers: h })
                .then(r => r.ok ? r.json() : []),

            // 4. Estado del período
            fetch(`${apiUrl}/ledger/period/${period}/status`, { headers: h })
                .then(r => r.ok ? r.json() : null),
        ]).then(([tbRes, entriesRes, draftRes, statusRes]) => {
            // KPIs del trial balance
            const tb = tbRes.status === 'fulfilled' ? tbRes.value : []
            if (Array.isArray(tb)) {
                const sum = (type, sign) => {
                    const rows = tb.filter(r => r.account_type === type)
                    return rows.reduce((acc, r) => {
                        const net = (r.debit || 0) - (r.credit || 0)
                        return acc + (sign === 'debit' ? net : -net)
                    }, 0)
                }
                const ingresos = Math.abs(sum('INGRESO', 'credit'))
                const gastos = Math.abs(sum('GASTO', 'debit'))
                setKpis({
                    activos: sum('ACTIVO', 'debit'),
                    pasivos: Math.abs(sum('PASIVO', 'credit')),
                    patrimonio: Math.abs(sum('PATRIMONIO', 'credit')),
                    resultado: ingresos - gastos,
                })
            }

            // Últimos 5 asientos
            const allEntries = entriesRes.status === 'fulfilled' ? (entriesRes.value || []) : []
            setRecentEntries(allEntries.slice(-5).reverse())

            // DRAFTs
            const drafts = draftRes.status === 'fulfilled' ? (draftRes.value || []) : []
            setDraftCount(drafts.length)

            // Estado período
            const pst = statusRes.status === 'fulfilled' ? statusRes.value : null
            setPeriodStatus(pst?.status || 'OPEN')
        }).finally(() => setLoading(false))
    }, [period, token])

    // ── Opciones de período dinámicas ──────────────────────────
    const periodOptions = useMemo(() => {
        const now = new Date()
        const startStr = openingMonth || `${now.getFullYear()}-01`
        const start = new Date(startStr + '-01T00:00:00')
        const end = new Date(now.getFullYear(), now.getMonth() + 3, 1)
        const opts = []
        let d = new Date(end)
        while (d >= start) {
            const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0')
            opts.push({ val: `${y}-${m}`, label: `${MONTHS[d.getMonth()]} ${y}` })
            d = new Date(y, d.getMonth() - 1, 1)
        }
        return opts
    }, [openingMonth])

    // ── Tareas dinámicas ────────────────────────────────────────
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
            label: periodStatus === 'CLOSED'
                ? `Período ${period} cerrado ✓`
                : `Período ${period}: ${PERIOD_LABELS[periodStatus] || '—'}`,
            done: periodStatus === 'CLOSED',
            pending: periodStatus === null,
            action: () => navigate('/cierre'),
            actionLabel: 'Ir a Cierre',
        },
    ]
    const pendingCount = tasks.filter(t => !t.done && !t.pending).length

    // ── KPI Cards ───────────────────────────────────────────────
    const cards = [
        {
            label: 'Activos',
            value: fmt(kpis.activos),
            icon: '🏦',
            color: '#3b82f6',
            bg: 'rgba(59,130,246,0.12)',
            positive: (kpis.activos || 0) > 0,
        },
        {
            label: 'Pasivos',
            value: fmt(kpis.pasivos),
            icon: '📋',
            color: '#ef4444',
            bg: 'rgba(239,68,68,0.10)',
            positive: false,
        },
        {
            label: 'Patrimonio',
            value: fmt(kpis.patrimonio),
            icon: '💎',
            color: '#8b5cf6',
            bg: 'rgba(139,92,246,0.12)',
            positive: (kpis.patrimonio || 0) > 0,
        },
        {
            label: 'Resultado',
            value: kpis.resultado !== null
                ? (kpis.resultado >= 0 ? `▲ ${fmt(kpis.resultado)}` : `▼ ${fmt(kpis.resultado)}`)
                : '—',
            icon: kpis.resultado >= 0 ? '📈' : '📉',
            color: (kpis.resultado || 0) >= 0 ? '#10b981' : '#ef4444',
            bg: (kpis.resultado || 0) >= 0 ? 'rgba(16,185,129,0.10)' : 'rgba(239,68,68,0.10)',
            positive: (kpis.resultado || 0) >= 0,
        },
    ]

    const selStyle = {
        padding: '6px 10px', borderRadius: 7, border: '1px solid var(--border-color)',
        background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.82rem',
        cursor: 'pointer',
    }

    const statusColor = PERIOD_COLORS[periodStatus] || '#6b7280'

    return (
        <div style={{ padding: '20px 0', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ── */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
                <div>
                    <h2 style={{ fontSize: '1.3rem', fontWeight: 700, margin: 0 }}>Resumen Contable</h2>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 3 }}>
                        Vista en tiempo real del período activo
                    </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {/* Período selector */}
                    <select value={period} onChange={e => setPeriod(e.target.value)} style={selStyle}>
                        {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                    </select>
                    {/* Estado del período */}
                    {periodStatus && (
                        <span style={{
                            padding: '4px 10px', borderRadius: 20,
                            fontSize: '0.75rem', fontWeight: 600,
                            background: `${statusColor}22`, color: statusColor,
                            border: `1px solid ${statusColor}44`,
                        }}>
                            {PERIOD_LABELS[periodStatus] || periodStatus}
                        </span>
                    )}
                </div>
            </div>

            {/* ── KPI Cards ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
                {cards.map(card => (
                    <div key={card.label} style={{
                        background: 'var(--bg-card)',
                        borderRadius: 14,
                        padding: '16px 18px',
                        border: '1px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', gap: 14,
                        transition: 'transform 0.15s',
                        cursor: 'default',
                        position: 'relative', overflow: 'hidden',
                    }}>
                        {/* Glow accent */}
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
                                color: loading ? 'var(--text-muted)' : card.color,
                                fontVariantNumeric: 'tabular-nums',
                            }}>
                                {loading ? <span style={{ opacity: 0.4 }}>Cargando...</span> : card.value}
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            {/* ── Últimos Asientos + Tareas ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>

                {/* Últimos Asientos */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 14, padding: 18, border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>📒 Últimos Asientos</span>
                        <button
                            onClick={() => navigate('/diario')}
                            style={{
                                background: 'none', border: 'none', color: 'var(--accent)',
                                fontSize: '0.78rem', cursor: 'pointer', padding: '2px 6px',
                                borderRadius: 5, transition: 'background 0.15s',
                            }}
                        >
                            Ver todos →
                        </button>
                    </div>

                    {loading ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center', padding: '20px 0', opacity: 0.6 }}>
                            ⏳ Cargando...
                        </div>
                    ) : recentEntries.length === 0 ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center', padding: '24px 0' }}>
                            Sin asientos en {MONTHS[parseInt(period.split('-')[1]) - 1]} {period.split('-')[0]}
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {recentEntries.map(e => {
                                const statusColor = e.status === 'POSTED' ? '#10b981' : e.status === 'DRAFT' ? '#f59e0b' : '#ef4444'
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
                                            borderRadius: 10, background: `${statusColor}22`, color: statusColor, flexShrink: 0,
                                        }}>
                                            {e.status}
                                        </span>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>

                {/* Tareas Pendientes */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 14, padding: 18, border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>✅ Estado del Período</span>
                        {pendingCount > 0 && (
                            <span style={{
                                padding: '2px 9px', borderRadius: 20,
                                fontSize: '0.72rem', fontWeight: 700,
                                background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                            }}>
                                {pendingCount} pendiente{pendingCount !== 1 ? 's' : ''}
                            </span>
                        )}
                        {pendingCount === 0 && !loading && (
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
                                    : task.pending
                                        ? 'rgba(255,255,255,0.02)'
                                        : 'rgba(239,68,68,0.06)',
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
                                fontWeight: 600, transition: 'all 0.15s',
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
                                fontWeight: 600, transition: 'all 0.15s',
                            }}
                        >
                            📚 Libros Digitales
                        </button>
                    </div>
                </div>
            </div>

            {/* ── Health Bar ── */}
            <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 16px', borderRadius: 10,
                border: `1px solid ${state.apiStatus === 'ok' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                background: state.apiStatus === 'ok' ? 'rgba(16,185,129,0.06)' : 'rgba(239,68,68,0.06)',
            }}>
                <div style={{
                    width: 7, height: 7, borderRadius: '50%',
                    background: state.apiStatus === 'ok' ? '#10b981' : '#ef4444',
                    boxShadow: state.apiStatus === 'ok' ? '0 0 6px #10b981' : '0 0 6px #ef4444',
                    flexShrink: 0,
                }} />
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {state.apiStatus === 'checking' && '⏳ Verificando conexión...'}
                    {state.apiStatus === 'ok' && '🟢 API y base de datos operativas · Datos actualizados en tiempo real'}
                    {state.apiStatus === 'error' && '🔴 Sin conexión con el servidor — Verificar Render'}
                </span>
            </div>
        </div>
    )
}
