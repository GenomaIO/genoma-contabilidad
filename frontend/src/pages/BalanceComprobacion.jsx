/**
 * BalanceComprobacion.jsx — Balance de Comprobación (Trial Balance)
 *
 * Muestra saldos de todas las cuentas con asientos POSTED en un período.
 * Llama: GET /ledger/trial-balance?period=YYYY-MM
 *
 * Reglas de Oro:
 * - Solo asientos POSTED (DRAFT no afectan saldos)
 * - tenant_id del JWT (el backend lo resuelve)
 * - Solo contador/admin pueden ver el módulo completo
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

export default function BalanceComprobacion() {
    const { state } = useApp()
    const [period, setPeriod] = useState(getCurrentPeriod())
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [presentLevel, setPresentLevel] = useState(4)
    const [acumulado, setAcumulado] = useState(false)  // modo NIIF: saldo inicial + período

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    useEffect(() => { fetchBalance() }, [period, acumulado])

    async function fetchBalance() {
        setLoading(true); setError(null); setData(null)
        try {
            const res = await fetch(`${apiUrl}/ledger/trial-balance?period=${period}&acumulado=${acumulado}`, {
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

    // get_level: nivel real de un código interno
    // 1000→N1, 1100→N2, 1101→N3, 1101.01→N4, 1101.01.01→N5
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

    // Roll-up: agrega cuentas de nivel superior al nivel de presentación
    // El backend devuelve cuentas al nivel que tienen movimientos (puede ser N5).
    // Este proceso acumula N5 en su padre N4 cuando presentLevel=4, evitando doble conteo.
    function rollUpAccounts(rawAccounts, level) {
        const accumulated = {}
        const metaMap = {}
        for (const acc of rawAccounts) {
            const code = acc.account_code
            const lvl = getLevel(code)
            let targetCode = code
            if (lvl > level) {
                // Encontrar el ancestro al nivel deseado
                const parts = code.split('.')
                while (parts.length > 0 && getLevel(parts.join('.')) > level) parts.pop()
                targetCode = parts.join('.') || code
            }
            if (!accumulated[targetCode]) {
                accumulated[targetCode] = { debit: 0, credit: 0 }
                metaMap[targetCode] = acc  // usar meta del primer acc que aporta
            }
            accumulated[targetCode].debit += acc.total_debit || 0
            accumulated[targetCode].credit += acc.total_credit || 0
        }
        return Object.entries(accumulated).sort(([a], [b]) => a.localeCompare(b)).map(([code, sums]) => ({
            ...metaMap[code],
            account_code: code,
            total_debit: sums.debit,
            total_credit: sums.credit,
        }))
    }

    const rawAccounts = data?.lines || data?.accounts || []
    const accounts = rollUpAccounts(rawAccounts, presentLevel)
    const totalDebit = accounts.reduce((s, a) => s + (a.total_debit || 0), 0)
    const totalCredit = accounts.reduce((s, a) => s + (a.total_credit || 0), 0)
    const balanced = Math.abs(totalDebit - totalCredit) < 0.01

    return (
        <div style={{ padding: '24px', maxWidth: 960, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        ⚖️ Balance de Comprobación
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Solo asientos POSTED · {accounts.length} cuentas
                        {data && (
                            <span style={{ marginLeft: 10, color: balanced ? '#10b981' : '#ef4444', fontWeight: 700 }}>
                                {balanced ? '✅ Balanceado' : '⚠️ Desbalanceado'}
                            </span>
                        )}
                    </p>
                </div>
                <select
                    id="balance-period-select"
                    value={period}
                    onChange={e => setPeriod(e.target.value)}
                    style={{ padding: '8px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
                >
                    {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                </select>
                {/* Toggle acumulado + Nivel */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {/* Modo acumulado */}
                    <button
                        id="btn-acumulado"
                        onClick={() => setAcumulado(a => !a)}
                        title={acumulado ? 'Modo NIIF: muestra saldo inicial (apertura) + saldo final' : 'Modo simple: solo movimientos del período'}
                        style={{
                            padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: '0.78rem',
                            border: `1px solid ${acumulado ? '#8b5cf6' : 'var(--border-color)'}`,
                            background: acumulado ? 'rgba(139,92,246,0.15)' : 'var(--bg-card)',
                            color: acumulado ? '#8b5cf6' : 'var(--text-muted)', fontWeight: acumulado ? 700 : 400,
                        }}
                    >
                        {acumulado ? '📊 NIIF acumulado' : '📊 Solo período'}
                    </button>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Ver hasta:</span>
                    {[4, 5].map(lvl => (
                        <button key={lvl}
                            id={`btn-nivel-${lvl}`}
                            onClick={() => setPresentLevel(lvl)}
                            title={lvl === 4 ? 'Nivel 4 (recomendado DGCN)' : 'Nivel 5+ (detalle máximo)'}
                            style={{
                                padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border-color)',
                                background: presentLevel === lvl ? '#7c3aed' : 'var(--bg-card)',
                                color: presentLevel === lvl ? 'white' : 'var(--text-secondary)',
                                fontWeight: presentLevel === lvl ? 700 : 400,
                                cursor: 'pointer', fontSize: '0.8rem',
                            }}
                        >N{lvl}</button>
                    ))}
                </div>
            </div>

            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {loading && <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>⏳ Calculando balance...</div>}

            {/* Tabla */}
            {!loading && data && (
                <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden' }}>
                    {/* Cabecera */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: acumulado ? '90px 1fr 75px 110px 110px 110px 110px' : '90px 1fr 80px 120px 120px 110px',
                        gap: 8, padding: '10px 16px',
                        background: 'rgba(124,58,237,0.1)', fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)',
                    }}>
                        <span>CÓDIGO</span>
                        <span>NOMBRE</span>
                        <span>TIPO</span>
                        {acumulado && <span style={{ textAlign: 'right' }}>SALDO INICIAL</span>}
                        <span style={{ textAlign: 'right' }}>DÉBITOS</span>
                        <span style={{ textAlign: 'right' }}>CRÉDITOS</span>
                        <span style={{ textAlign: 'right' }}>SALDO {acumulado ? 'FINAL' : ''}</span>
                    </div>

                    {accounts.map((acc, i) => {
                        const color = TYPE_COLOR[acc.account_type] || '#9ca3af'
                        const saldo = acumulado ? (acc.saldo || 0) : ((acc.total_debit || 0) - (acc.total_credit || 0))
                        const saldoInicial = acc.saldo_inicial || 0
                        const fmt = n => `¢${Math.abs(n).toLocaleString('es-CR', { minimumFractionDigits: 2 })}`
                        return (
                            <div
                                key={acc.account_code}
                                id={`balance-row-${acc.account_code}`}
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: acumulado ? '90px 1fr 75px 110px 110px 110px 110px' : '90px 1fr 80px 120px 120px 110px',
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
                                <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{acc.account_name || acc.account_code}</span>
                                <span style={{ fontSize: '0.72rem', color }}>{acc.account_type}</span>
                                {acumulado && (
                                    <span style={{ textAlign: 'right', color: saldoInicial !== 0 ? '#8b5cf6' : 'var(--text-muted)', fontFamily: 'monospace' }}>
                                        {saldoInicial !== 0 ? fmt(saldoInicial) : '—'}
                                    </span>
                                )}
                                <span style={{ textAlign: 'right', color: '#3b82f6', fontFamily: 'monospace' }}>
                                    {acc.total_debit > 0 ? fmt(acc.total_debit) : '—'}
                                </span>
                                <span style={{ textAlign: 'right', color: '#10b981', fontFamily: 'monospace' }}>
                                    {acc.total_credit > 0 ? fmt(acc.total_credit) : '—'}
                                </span>
                                <span style={{ textAlign: 'right', color: saldo >= 0 ? '#10b981' : '#ef4444', fontWeight: 600, fontFamily: 'monospace' }}>
                                    {fmt(saldo)}{saldo < 0 && <span style={{ fontSize: '0.7rem', marginLeft: 2 }}>CR</span>}
                                </span>
                            </div>
                        )
                    })}

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: acumulado ? '90px 1fr 75px 110px 110px 110px 110px' : '90px 1fr 80px 120px 120px 110px',
                        gap: 8, padding: '12px 16px', borderTop: '2px solid var(--border-color)',
                        fontWeight: 700, fontSize: '0.85rem', background: 'rgba(0,0,0,0.05)',
                    }}>
                        <span /><span style={{ color: 'var(--text-primary)' }}>TOTAL</span><span />
                        {acumulado && <span />}
                        <span style={{ textAlign: 'right', color: '#3b82f6' }}>¢{totalDebit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                        <span style={{ textAlign: 'right', color: '#10b981' }}>¢{totalCredit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                        <span style={{ textAlign: 'right', color: balanced ? '#10b981' : '#ef4444' }}>
                            {balanced ? '⚖️ OK' : `Δ ¢${Math.abs(totalDebit - totalCredit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}`}
                        </span>
                    </div>
                </div>
            )}

            {/* Estado vacío */}
            {!loading && data && accounts.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📭</div>
                    <p>No hay asientos POSTED en {period}.<br />
                        <span style={{ fontSize: '0.82rem' }}>Los asientos en borrador (DRAFT) no afectan el balance.</span></p>
                </div>
            )}
        </div>
    )
}
