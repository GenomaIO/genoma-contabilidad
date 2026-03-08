/**
 * BalanceComprobacion.jsx — Balance de Comprobación (Trial Balance)
 *
 * Tres modos de presentación:
 *   period  → Solo movimientos del período seleccionado
 *   ytd     → Acumulado desde 01/01 hasta el período (DEFAULT)
 *             BASE de los EEFF · NIIF PYMES Sec. 2.36 y 3.10
 *   running → Saldo histórico completo (todos los períodos)
 *
 * Invariante de cuadratura: Debe = Haber siempre.
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

const MODES = [
    {
        id: 'period',
        label: '📅 Solo Mes',
        shortLabel: 'Solo Mes',
        color: '#6b7280',
        desc: 'Movimientos del período seleccionado',
        warning: true,
    },
    {
        id: 'ytd',
        label: '📊 Acumulado Año',
        shortLabel: 'Acumulado',
        color: '#8b5cf6',
        desc: 'Desde Ene hasta el período seleccionado · Base de los EEFF',
        niif: 'NIIF PYMES Sec. 2.36 (devengo) · Sec. 3.10 (período anual)',
        warning: false,
    },
    {
        id: 'running',
        label: '🏛️ Saldo Corriente',
        shortLabel: 'Histórico',
        color: '#0ea5e9',
        desc: 'Saldo histórico acumulado de todos los años',
        warning: false,
    },
]

function getCurrentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// ── Tooltip/Bombillito NIIF ──────────────────────────────────────
function NiifTip({ text }) {
    const [show, setShow] = useState(false)
    return (
        <span style={{ position: 'relative', display: 'inline-block', marginLeft: 6 }}>
            <button
                onMouseEnter={() => setShow(true)}
                onMouseLeave={() => setShow(false)}
                style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontSize: '0.85rem', color: '#f59e0b', padding: '0 2px',
                }}
                title="Ver referencia NIIF"
            >
                💡
            </button>
            {show && (
                <span style={{
                    position: 'absolute', bottom: '120%', left: '50%', transform: 'translateX(-50%)',
                    background: '#1e1b4b', border: '1px solid #7c3aed', borderRadius: 7,
                    padding: '7px 11px', fontSize: '0.73rem', color: '#c4b5fd',
                    whiteSpace: 'nowrap', zIndex: 100, boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
                    minWidth: 260,
                }}>
                    📖 {text}
                </span>
            )}
        </span>
    )
}

export default function BalanceComprobacion() {
    const { state } = useApp()
    const [period, setPeriod] = useState(getCurrentPeriod())
    const [mode, setMode] = useState('ytd')          // DEFAULT: acumulado año (NIIF correcto)
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)
    const [presentLevel, setPresentLevel] = useState(4)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    useEffect(() => { fetchBalance() }, [period, mode])

    async function fetchBalance() {
        if (!token) return
        setLoading(true); setError(null); setData(null)
        try {
            const res = await fetch(`${apiUrl}/ledger/trial-balance?period=${period}&mode=${mode}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) throw new Error('Error al cargar el balance')
            setData(await res.json())
        } catch (e) { setError(e.message) }
        finally { setLoading(false) }
    }

    // Generar opciones de período (24 meses atrás)
    const periodOptions = []
    const base = new Date()
    for (let i = 0; i < 24; i++) {
        const d = new Date(base.getFullYear(), base.getMonth() - i, 1)
        const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        periodOptions.push({ val, label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` })
    }

    // Nivel de desglose: 1000→N1, 1100→N2, 1101→N3, 1101.01→N4
    function getLevel(code) {
        const parts = code.split('.')
        const base = parts[0]
        const suffixCount = parts.length - 1
        let baseLevel
        if (base.slice(1) === '000') baseLevel = 1
        else if (base.slice(2) === '00') baseLevel = 2
        else baseLevel = 3
        return baseLevel + suffixCount
    }

    // Roll-up: acumula cuentas hija en su padre según nivel de presentación
    function rollUpAccounts(rawAccounts, level) {
        const accumulated = {}
        const metaMap = {}
        for (const acc of rawAccounts) {
            const code = acc.account_code
            const lvl = getLevel(code)
            let targetCode = code
            if (lvl > level) {
                const parts = code.split('.')
                while (parts.length > 0 && getLevel(parts.join('.')) > level) parts.pop()
                targetCode = parts.join('.') || code
            }
            if (!accumulated[targetCode]) {
                accumulated[targetCode] = { debit: 0, credit: 0 }
                metaMap[targetCode] = acc
            }
            accumulated[targetCode].debit += acc.total_debit || 0
            accumulated[targetCode].credit += acc.total_credit || 0
        }
        return Object.entries(accumulated)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([code, sums]) => ({
                ...metaMap[code],
                account_code: code,
                total_debit: sums.debit,
                total_credit: sums.credit,
            }))
    }

    const rawAccounts = data?.lines || []
    const accounts = rollUpAccounts(rawAccounts, presentLevel)
    const totalDebit = accounts.reduce((s, a) => s + (a.total_debit || 0), 0)
    const totalCredit = accounts.reduce((s, a) => s + (a.total_credit || 0), 0)
    const balanced = Math.abs(totalDebit - totalCredit) < 0.01
    const currentMode = MODES.find(m => m.id === mode) || MODES[1]

    const fmt = n => `¢${Math.abs(n).toLocaleString('es-CR', { minimumFractionDigits: 2 })}`
    const gridCols = '90px 1fr 75px 120px 120px'

    return (
        <div style={{ padding: '24px', maxWidth: 1000, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ─────────────────────────────────────────────────── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        ⚖️ Balance de Comprobación
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                        Solo asientos POSTED · {accounts.length} cuentas
                        {data && (
                            <span style={{ marginLeft: 10, color: balanced ? '#10b981' : '#ef4444', fontWeight: 700 }}>
                                {balanced ? '✅ Balanceado' : '⚠️ Desbalanceado — revisar asientos'}
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
                            padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)',
                            background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.85rem', cursor: 'pointer',
                        }}
                    >
                        {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                    </select>

                    {/* Selector nivel N4/N5 */}
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Ver hasta:</span>
                    {[4, 5].map(lvl => (
                        <button
                            key={lvl}
                            id={`btn-nivel-${lvl}`}
                            onClick={() => setPresentLevel(lvl)}
                            style={{
                                padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: '0.8rem',
                                border: '1px solid var(--border-color)',
                                background: presentLevel === lvl ? '#7c3aed' : 'var(--bg-card)',
                                color: presentLevel === lvl ? 'white' : 'var(--text-secondary)',
                                fontWeight: presentLevel === lvl ? 700 : 400,
                            }}
                        >N{lvl}</button>
                    ))}
                </div>
            </div>

            {/* ── Toggle de 3 modos ────────────────────────────────────────── */}
            <div style={{
                display: 'flex', gap: 8, marginBottom: 12, padding: '10px 14px',
                background: 'var(--bg-card)', borderRadius: 10, border: '1px solid var(--border-color)',
                alignItems: 'flex-start', flexWrap: 'wrap',
            }}>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {MODES.map(m => (
                        <button
                            key={m.id}
                            id={`btn-mode-${m.id}`}
                            onClick={() => setMode(m.id)}
                            style={{
                                padding: '6px 12px', borderRadius: 7, cursor: 'pointer', fontSize: '0.8rem',
                                border: `1px solid ${mode === m.id ? m.color : 'var(--border-color)'}`,
                                background: mode === m.id ? `${m.color}22` : 'transparent',
                                color: mode === m.id ? m.color : 'var(--text-muted)',
                                fontWeight: mode === m.id ? 700 : 400,
                                transition: 'all 0.15s',
                            }}
                        >
                            {m.label}
                        </button>
                    ))}
                </div>
                {/* Descripción del modo activo */}
                <div style={{ fontSize: '0.77rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', marginLeft: 4 }}>
                    <span style={{ color: currentMode.color }}>{currentMode.desc}</span>
                    {currentMode.niif && (
                        <NiifTip text={currentMode.niif} />
                    )}
                </div>
            </div>

            {/* ── Banner advertencia modo "period" ─────────────────────────── */}
            {mode === 'period' && data && (
                <div style={{
                    background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.35)',
                    borderRadius: 8, padding: '9px 14px', marginBottom: 14,
                    fontSize: '0.8rem', color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 8,
                }}>
                    <span>⚠️</span>
                    <span>
                        Estás viendo <strong>solo los movimientos de {period}</strong>.
                        Este balance no es la base de los EEFF.
                        Para el balance que alimenta los Estados Financieros usá{' '}
                        <button
                            onClick={() => setMode('ytd')}
                            style={{ background: 'none', border: 'none', color: '#8b5cf6', fontWeight: 700, cursor: 'pointer', fontSize: '0.8rem', textDecoration: 'underline' }}
                        >
                            📊 Acumulado Año
                        </button>
                        .
                        <NiifTip text="NIIF PYMES Sec. 3.10: los EEFF anuales acumulan todos los períodos del año." />
                    </span>
                </div>
            )}

            {/* ── Indicador de rango YTD ───────────────────────────────────── */}
            {(mode === 'ytd' || mode === 'running') && data && (
                <div style={{
                    background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)',
                    borderRadius: 8, padding: '7px 14px', marginBottom: 14,
                    fontSize: '0.78rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6,
                }}>
                    <span style={{ color: '#8b5cf6' }}>📆</span>
                    {mode === 'ytd'
                        ? <span>Acumula desde <strong>{data.year_start?.replace('-', ' mes ')}</strong> hasta <strong>{period}</strong> · Base de los EEFF</span>
                        : <span>Saldo histórico completo hasta <strong>{period}</strong></span>
                    }
                    {mode === 'ytd' && <NiifTip text="NIIF PYMES Sec. 2.36: Base de acumulación (devengo). Sec. 3.10: Período anual." />}
                </div>
            )}

            {/* ── Error ───────────────────────────────────────────────────── */}
            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {loading && <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>⏳ Calculando balance...</div>}

            {/* ── Tabla ───────────────────────────────────────────────────── */}
            {!loading && data && accounts.length > 0 && (
                <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden' }}>
                    {/* Cabecera */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: gridCols,
                        gap: 8, padding: '10px 16px',
                        background: 'rgba(124,58,237,0.1)', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)',
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
                                    gap: 8, padding: '9px 16px', borderTop: '1px solid var(--border-color)',
                                    fontSize: '0.82rem', background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)',
                                    cursor: 'pointer', transition: 'background 0.1s',
                                }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)'}
                                onClick={() => window.location.href = `/mayor?code=${acc.account_code}`}
                                title={`Ver Mayor de ${acc.account_code} →`}
                            >
                                <span style={{ fontFamily: 'monospace', color, fontWeight: 700 }}>{acc.account_code}</span>
                                <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {acc.account_name || acc.account_code}
                                </span>
                                <span style={{ fontSize: '0.72rem', color }}>{acc.account_type}</span>
                                <span style={{ textAlign: 'right', color: '#3b82f6', fontFamily: 'monospace' }}>
                                    {acc.total_debit > 0 ? fmt(acc.total_debit) : '—'}
                                </span>
                                <span style={{ textAlign: 'right', color: '#10b981', fontFamily: 'monospace' }}>
                                    {acc.total_credit > 0 ? fmt(acc.total_credit) : '—'}
                                </span>
                            </div>
                        )
                    })}

                    {/* Fila de totales */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: gridCols,
                        gap: 8, padding: '12px 16px', borderTop: '2px solid var(--border-color)',
                        fontWeight: 700, fontSize: '0.85rem', background: 'rgba(0,0,0,0.05)',
                    }}>
                        <span /><span style={{ color: 'var(--text-primary)' }}>TOTAL</span><span />
                        <span style={{ textAlign: 'right', color: '#3b82f6' }}>
                            ¢{totalDebit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}
                        </span>
                        <span style={{ textAlign: 'right', color: '#10b981' }}>
                            ¢{totalCredit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}
                        </span>
                    </div>
                </div>
            )}

            {/* Estado vacío */}
            {!loading && data && accounts.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📭</div>
                    <p>No hay asientos POSTED en este período.<br />
                        <span style={{ fontSize: '0.82rem' }}>Los asientos en borrador (DRAFT) no afectan el balance.</span>
                    </p>
                </div>
            )}
        </div>
    )
}
