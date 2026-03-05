/**
 * AsientosPendientes.jsx — Bandeja de Aprobación del Libro Diario
 *
 * Asistente: ve todos los DRAFT, puede crear asientos manuales.
 * Contador/Admin: puede aprobar (POSTED) o anular (VOIDED).
 * Todo con audit trail — Reglas de Oro.
 */
import { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'

const STATUS_CONFIG = {
    DRAFT: { label: 'Borrador', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
    POSTED: { label: 'Aprobado', color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
    VOIDED: { label: 'Anulado', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
}

const SOURCE_ICON = {
    MANUAL: '✍️', FE: '📄', TE: '🧾', NC: '↩️', ND: '➕',
    FEC: '🛒', REP: '💰', RECIBIDO: '📥', CIERRE: '🔒',
}

const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function getCurrentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function AsientosPendientes() {
    const { state } = useApp()
    const [entries, setEntries] = useState([])
    const [loading, setLoading] = useState(true)
    const [period, setPeriod] = useState(getCurrentPeriod())
    const [statusFilter, setStatus] = useState('DRAFT')
    const [expanded, setExpanded] = useState({})
    const [acting, setActing] = useState(null)
    const [voidReason, setVoidReason] = useState('')
    const [voidTarget, setVoidTarget] = useState(null)
    const [error, setError] = useState(null)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const canApprove = role === 'admin' || role === 'contador'

    useEffect(() => { fetchEntries() }, [period, statusFilter])

    async function fetchEntries() {
        setLoading(true); setError(null)
        try {
            const params = new URLSearchParams({ ...(statusFilter ? { status: statusFilter } : {}) })
            const res = await fetch(`${apiUrl}/ledger/entries?period=${period}&${params}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) throw new Error('Error al cargar asientos')
            setEntries(await res.json())
        } catch (e) { setError(e.message) }
        finally { setLoading(false) }
    }

    async function handleApprove(entryId) {
        setActing(entryId)
        try {
            const res = await fetch(`${apiUrl}/ledger/entries/${entryId}/approve`, {
                method: 'PATCH',
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) { const e = await res.json(); alert(e.detail || 'Error') }
            else fetchEntries()
        } finally { setActing(null) }
    }

    async function handleVoid(entryId) {
        if (!voidReason.trim()) { alert('Debe indicar el motivo de anulación'); return }
        setActing(entryId)
        try {
            const res = await fetch(
                `${apiUrl}/ledger/entries/${entryId}/void?reason=${encodeURIComponent(voidReason)}`,
                { method: 'PATCH', headers: { Authorization: `Bearer ${token}` } }
            )
            if (!res.ok) { const e = await res.json(); alert(e.detail || 'Error') }
            else { setVoidTarget(null); setVoidReason(''); fetchEntries() }
        } finally { setActing(null) }
    }

    // ─── Generar opciones de período (24 meses atrás)
    const periodOptions = []
    const base = new Date()
    for (let i = 0; i < 24; i++) {
        const d = new Date(base.getFullYear(), base.getMonth() - i, 1)
        const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        periodOptions.push({ val, label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` })
    }

    const selStyle = {
        padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)',
        background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.85rem'
    }

    return (
        <div style={{ padding: '24px', maxWidth: 960, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        📒 Libro Diario
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        {entries.length} asiento{entries.length !== 1 ? 's' : ''} · {statusFilter || 'Todos'}
                    </p>
                </div>
                {/* Filtros */}
                <div style={{ display: 'flex', gap: 10 }}>
                    <select id="period-select" value={period} onChange={e => setPeriod(e.target.value)} style={selStyle}>
                        {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                    </select>
                    <select id="status-select" value={statusFilter} onChange={e => setStatus(e.target.value)} style={selStyle}>
                        <option value="">Todos</option>
                        <option value="DRAFT">Borrador</option>
                        <option value="POSTED">Aprobados</option>
                        <option value="VOIDED">Anulados</option>
                    </select>
                </div>
            </div>

            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-secondary)' }}>⏳ Cargando asientos...</div>}

            {/* Lista de asientos */}
            {!loading && entries.map(entry => {
                const sc = STATUS_CONFIG[entry.status] || STATUS_CONFIG.DRAFT
                const ico = SOURCE_ICON[entry.source] || '📋'
                const isExpanded = expanded[entry.id]

                const totalDR = entry.lines?.reduce((s, l) => s + (l.debit || 0), 0) || 0
                const totalCR = entry.lines?.reduce((s, l) => s + (l.credit || 0), 0) || 0
                const balanced = Math.abs(totalDR - totalCR) < 0.01

                return (
                    <div key={entry.id} id={`entry-${entry.id}`}
                        style={{
                            border: `1px solid ${sc.color}40`,
                            borderRadius: 10, marginBottom: 12,
                            background: sc.bg, overflow: 'hidden'
                        }}
                    >
                        {/* Cabecera del asiento */}
                        <div
                            onClick={() => setExpanded(e => ({ ...e, [entry.id]: !e[entry.id] }))}
                            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', cursor: 'pointer' }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1 }}>
                                <span style={{ fontSize: '1.2rem' }}>{ico}</span>
                                <div>
                                    <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', fontWeight: 600 }}>
                                        {entry.description?.slice(0, 80)}{entry.description?.length > 80 ? '...' : ''}
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                        {entry.date} · {entry.source}
                                        {entry.source_ref && <span style={{ marginLeft: 6, fontFamily: 'monospace', fontSize: '0.7rem' }}>{entry.source_ref.slice(0, 12)}...</span>}
                                    </div>
                                </div>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                {/* Balance */}
                                <span style={{ fontSize: '0.75rem', color: balanced ? '#10b981' : '#ef4444' }}>
                                    {balanced ? '⚖️' : '⚠️'} ¢{totalDR.toLocaleString('es-CR', { minimumFractionDigits: 2 })}
                                </span>
                                {/* Estado */}
                                <span style={{ fontSize: '0.75rem', padding: '3px 10px', background: sc.color + '22', color: sc.color, borderRadius: 12, fontWeight: 600 }}>
                                    {sc.label}
                                </span>
                                {/* Acciones — solo contador/admin */}
                                {canApprove && entry.status === 'DRAFT' && (
                                    <div style={{ display: 'flex', gap: 6 }} onClick={e => e.stopPropagation()}>
                                        <button
                                            id={`approve-${entry.id}`}
                                            onClick={() => handleApprove(entry.id)}
                                            disabled={acting === entry.id}
                                            style={{ padding: '4px 12px', background: '#10b981', border: 'none', borderRadius: 6, color: 'white', fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer' }}
                                        >
                                            {acting === entry.id ? '...' : '✓ Aprobar'}
                                        </button>
                                        <button
                                            id={`void-${entry.id}`}
                                            onClick={() => setVoidTarget(entry.id)}
                                            style={{ padding: '4px 10px', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, color: '#ef4444', fontSize: '0.75rem', cursor: 'pointer' }}
                                        >
                                            Anular
                                        </button>
                                    </div>
                                )}
                                <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{isExpanded ? '▲' : '▼'}</span>
                            </div>
                        </div>

                        {/* Líneas del asiento */}
                        {isExpanded && entry.lines?.length > 0 && (
                            <div style={{ borderTop: `1px solid ${sc.color}30` }}>
                                {/* Encabezado tabla */}
                                <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 100px 100px 80px', gap: 8, padding: '6px 16px', fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700, background: 'rgba(0,0,0,0.05)' }}>
                                    <span>CUENTA</span><span>DESCRIPCIÓN</span>
                                    <span style={{ textAlign: 'right' }}>DÉBITO</span>
                                    <span style={{ textAlign: 'right' }}>CRÉDITO</span>
                                    <span>FISCAL</span>
                                </div>
                                {entry.lines.map((line, i) => (
                                    <div key={line.id} style={{ display: 'grid', gridTemplateColumns: '100px 1fr 100px 100px 80px', gap: 8, padding: '7px 16px', fontSize: '0.8rem', borderTop: '1px solid rgba(255,255,255,0.04)', background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.04)' }}>
                                        <span style={{ fontFamily: 'monospace', color: '#7c3aed', fontWeight: 700 }}>{line.account_code}</span>
                                        <span style={{ color: 'var(--text-secondary)' }}>{line.description || '—'}</span>
                                        <span style={{ textAlign: 'right', color: line.debit > 0 ? '#3b82f6' : 'var(--text-muted)' }}>
                                            {line.debit > 0 ? `¢${Number(line.debit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                                        </span>
                                        <span style={{ textAlign: 'right', color: line.credit > 0 ? '#10b981' : 'var(--text-muted)' }}>
                                            {line.credit > 0 ? `¢${Number(line.credit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                                        </span>
                                        <span style={{ fontSize: '0.68rem', color: line.deductible_status === 'DEDUCTIBLE' ? '#10b981' : line.deductible_status === 'EXEMPT' ? '#6b7280' : '#f59e0b' }}>
                                            {line.deductible_status?.slice(0, 6) || '—'}
                                        </span>
                                    </div>
                                ))}
                                {/* Totales */}
                                <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 100px 100px 80px', gap: 8, padding: '8px 16px', borderTop: `1px solid ${sc.color}40`, fontWeight: 700, fontSize: '0.8rem', background: 'rgba(0,0,0,0.06)' }}>
                                    <span colSpan={2} style={{ color: 'var(--text-secondary)' }}>TOTAL</span>
                                    <span></span>
                                    <span style={{ textAlign: 'right', color: '#3b82f6' }}>¢{totalDR.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                                    <span style={{ textAlign: 'right', color: '#10b981' }}>¢{totalCR.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                                    <span></span>
                                </div>
                            </div>
                        )}
                    </div>
                )
            })}

            {/* Estado vacío */}
            {!loading && entries.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📭</div>
                    <p>No hay asientos {statusFilter === 'DRAFT' ? 'pendientes' : statusFilter?.toLowerCase() || ''} en {period}.</p>
                </div>
            )}

            {/* Modal de anulación */}
            {voidTarget && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div style={{ background: 'var(--bg-secondary)', borderRadius: 14, padding: 28, maxWidth: 440, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
                        <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: '#ef4444' }}>⚠️ Anular asiento</h2>
                        <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            Se generará un asiento de reversión automático. Esta acción no puede deshacerse.
                        </p>
                        <textarea
                            id="void-reason-input"
                            placeholder="Motivo de anulación *"
                            value={voidReason}
                            onChange={e => setVoidReason(e.target.value)}
                            style={{ width: '100%', padding: '10px 12px', border: '1px solid var(--border-color)', borderRadius: 7, background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', resize: 'vertical', minHeight: 80, boxSizing: 'border-box', marginBottom: 16 }}
                        />
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={() => { setVoidTarget(null); setVoidReason('') }} style={{ padding: '8px 16px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer' }}>Cancelar</button>
                            <button id="confirm-void-btn" onClick={() => handleVoid(voidTarget)} disabled={acting === voidTarget} style={{ padding: '8px 20px', background: '#ef4444', border: 'none', borderRadius: 7, color: 'white', fontWeight: 700, cursor: 'pointer' }}>
                                {acting === voidTarget ? 'Anulando...' : 'Confirmar anulación'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
