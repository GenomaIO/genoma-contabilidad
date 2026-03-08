/**
 * BalanceComprobacion.jsx — Balance de Comprobación (Trial Balance)
 *
 * Dos modos:
 *   period → Solo movimientos del mes seleccionado
 *   ytd    → Acumulado desde Ene hasta el período (BASE de los EEFF)
 *            DEFAULT. Garantía: Debe = Haber (partida doble).
 *
 * Solo asientos POSTED. tenant_id resuelto por el backend desde JWT.
 */
import { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'

const TYPE_COLOR = {
    ACTIVO: '#3b82f6',
    PASIVO: '#ef4444',
    PATRIMONIO: '#8b5cf6',
    INGRESO: '#10b981',
    GASTO: '#f59e0b',
}

const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function getCurrentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Redondeo seguro a 2 decimales para evitar acumulación de error float
function r2(n) { return Math.round((n || 0) * 100) / 100 }

export default function BalanceComprobacion() {
    const { state } = useApp()
    const [period, setPeriod] = useState(getCurrentPeriod())
    const [mode, setMode] = useState('ytd')   // DEFAULT: acumulado (base EEFF)
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [presentLevel, setPresentLevel] = useState(4)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    useEffect(() => { fetchBalance() }, [period, mode])

    async function fetchBalance() {
        if (!token) return
        setLoading(true); setError(null); setData(null)
        try {
            const res = await fetch(
                `${apiUrl}/ledger/trial-balance?period=${period}&mode=${mode}`,
                { headers: { Authorization: `Bearer ${token}` } }
            )
            if (!res.ok) throw new Error('Error al cargar el balance')
            setData(await res.json())
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    // Opciones de período: 24 meses hacia atrás
    const periodOptions = []
    const base = new Date()
    for (let i = 0; i < 24; i++) {
        const d = new Date(base.getFullYear(), base.getMonth() - i, 1)
        const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        periodOptions.push({ val, label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` })
    }

    // Nivel real de un código (1000→N1, 1100→N2, 1101→N3, 1101.01→N4)
    function getLevel(code) {
        const parts = code.split('.')
        const base = parts[0]
        const sfx = parts.length - 1
        let lvl = base.slice(1) === '000' ? 1 : base.slice(2) === '00' ? 2 : 3
        return lvl + sfx
    }

    // Roll-up: acumula cuentas hijas en su padre al nivel de presentación
    // Usa r2() en cada suma para evitar error de flotante (el ¢0.01)
    function rollUpAccounts(raw, level) {
        const acc = {}
        const meta = {}
        for (const a of raw) {
            const code = a.account_code
            let target = code
            if (getLevel(code) > level) {
                const parts = code.split('.')
                while (parts.length > 0 && getLevel(parts.join('.')) > level) parts.pop()
                target = parts.join('.') || code
            }
            if (!acc[target]) { acc[target] = { d: 0, c: 0 }; meta[target] = a }
            acc[target].d = r2(acc[target].d + r2(a.total_debit || 0))
            acc[target].c = r2(acc[target].c + r2(a.total_credit || 0))
        }
        return Object.entries(acc)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([code, sums]) => ({
                ...meta[code],
                account_code: code,
                total_debit: sums.d,
                total_credit: sums.c,
            }))
    }

    const raw = data?.lines || []
    const accounts = rollUpAccounts(raw, presentLevel)
    const totalDebit = r2(accounts.reduce((s, a) => r2(s + a.total_debit), 0))
    const totalCredit = r2(accounts.reduce((s, a) => r2(s + a.total_credit), 0))
    const balanced = Math.abs(totalDebit - totalCredit) < 0.02

    const fmt = n => `¢${Math.abs(n).toLocaleString('es-CR', { minimumFractionDigits: 2 })}`
    const gridCols = '90px 1fr 80px 130px 130px'

    // Estilos de botón modo
    const btnStyle = (active) => ({
        padding: '6px 16px', borderRadius: 7, cursor: 'pointer',
        fontSize: '0.83rem', fontWeight: active ? 700 : 400,
        border: `1px solid ${active ? '#7c3aed' : 'var(--border-color)'}`,
        background: active ? '#7c3aed' : 'var(--bg-card)',
        color: active ? '#fff' : 'var(--text-muted)',
        transition: 'all 0.15s',
    })

    return (
        <div style={{ padding: '24px', maxWidth: 1000, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ─────────────────────────────────────────────── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        ⚖️ Balance de Comprobación
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                        Solo asientos POSTED · {accounts.length} cuentas
                        {data && (
                            <span style={{ marginLeft: 10, color: balanced ? '#10b981' : '#ef4444', fontWeight: 700 }}>
                                {balanced ? '✅ Balanceado' : '⚠️ Desbalanceado'}
                            </span>
                        )}
                    </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {/* Selector de período */}
                    <select
                        id="balance-period-select"
                        value={period}
                        onChange={e => setPeriod(e.target.value)}
                        style={{
                            padding: '7px 12px', borderRadius: 7,
                            border: '1px solid var(--border-color)',
                            background: 'var(--bg-card)', color: 'var(--text-primary)',
                            fontSize: '0.85rem', cursor: 'pointer',
                        }}
                    >
                        {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                    </select>

                    {/* Nivel N4/N5 */}
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Ver hasta:</span>
                    {[4, 5].map(lvl => (
                        <button
                            key={lvl}
                            id={`btn-nivel-${lvl}`}
                            onClick={() => setPresentLevel(lvl)}
                            style={{
                                padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                                fontSize: '0.8rem', border: '1px solid var(--border-color)',
                                background: presentLevel === lvl ? '#7c3aed' : 'var(--bg-card)',
                                color: presentLevel === lvl ? 'white' : 'var(--text-secondary)',
                                fontWeight: presentLevel === lvl ? 700 : 400,
                            }}
                        >N{lvl}</button>
                    ))}
                </div>
            </div>

            {/* ── 2 Botones de modo ──────────────────────────────────── */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <button
                    id="btn-mode-period"
                    onClick={() => setMode('period')}
                    style={btnStyle(mode === 'period')}
                >
                    Mes
                </button>
                <button
                    id="btn-mode-ytd"
                    onClick={() => setMode('ytd')}
                    style={btnStyle(mode === 'ytd')}
                >
                    Acumulado
                </button>
            </div>

            {/* ── Error ─────────────────────────────────────────────── */}
            {error && (
                <div style={{
                    background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                    borderRadius: 8, padding: '10px 14px', color: '#ef4444',
                    marginBottom: 16, fontSize: '0.88rem',
                }}>
                    ⚠️ {error}
                </div>
            )}

            {loading && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    ⏳ Calculando balance...
                </div>
            )}

            {/* ── Tabla ─────────────────────────────────────────────── */}
            {!loading && data && accounts.length > 0 && (
                <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden' }}>
                    {/* Cabecera */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: gridCols,
                        gap: 8, padding: '10px 16px',
                        background: 'rgba(124,58,237,0.1)',
                        fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)',
                    }}>
                        <span>CÓDIGO</span>
                        <span>NOMBRE</span>
                        <span>TIPO</span>
                        <span style={{ textAlign: 'right' }}>DÉBITOS</span>
                        <span style={{ textAlign: 'right' }}>CRÉDITOS</span>
                    </div>

                    {accounts.map((acc, i) => {
                        const color = TYPE_COLOR[acc.account_type] || '#9ca3af'
                        return (
                            <div
                                key={acc.account_code}
                                id={`balance-row-${acc.account_code}`}
                                style={{
                                    display: 'grid', gridTemplateColumns: gridCols,
                                    gap: 8, padding: '9px 16px',
                                    borderTop: '1px solid var(--border-color)',
                                    fontSize: '0.82rem',
                                    background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)',
                                    cursor: 'pointer', transition: 'background 0.1s',
                                }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)'}
                                onClick={() => window.location.href = `/mayor?code=${acc.account_code}`}
                                title={`Ver Mayor de ${acc.account_code} →`}
                            >
                                <span style={{ fontFamily: 'monospace', color, fontWeight: 700 }}>
                                    {acc.account_code}
                                </span>
                                <span style={{
                                    color: 'var(--text-primary)',
                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                }}>
                                    {acc.account_name || acc.account_code}
                                </span>
                                <span style={{ fontSize: '0.72rem', color }}>
                                    {acc.account_type}
                                </span>
                                <span style={{ textAlign: 'right', color: '#3b82f6', fontFamily: 'monospace' }}>
                                    {acc.total_debit > 0 ? fmt(acc.total_debit) : '—'}
                                </span>
                                <span style={{ textAlign: 'right', color: '#10b981', fontFamily: 'monospace' }}>
                                    {acc.total_credit > 0 ? fmt(acc.total_credit) : '—'}
                                </span>
                            </div>
                        )
                    })}

                    {/* Totales */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: gridCols,
                        gap: 8, padding: '12px 16px',
                        borderTop: '2px solid var(--border-color)',
                        fontWeight: 700, fontSize: '0.85rem',
                        background: 'rgba(0,0,0,0.05)',
                    }}>
                        <span /><span style={{ color: 'var(--text-primary)' }}>TOTAL</span><span />
                        <span style={{ textAlign: 'right', color: '#3b82f6' }}>
                            {fmt(totalDebit)}
                        </span>
                        <span style={{ textAlign: 'right', color: '#10b981' }}>
                            {fmt(totalCredit)}
                        </span>
                    </div>
                </div>
            )}

            {/* Estado vacío */}
            {!loading && data && accounts.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📭</div>
                    <p>
                        No hay asientos POSTED en {period}.<br />
                        <span style={{ fontSize: '0.82rem' }}>
                            Los asientos en borrador (DRAFT) no afectan el balance.
                        </span>
                    </p>
                </div>
            )}
        </div>
    )
}
