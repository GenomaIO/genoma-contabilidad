/**
 * EstadosFinancieros.jsx
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * Estados Financieros NIIF PYMES 3ª Edición (Feb 2025)
 * 
 * Tabs:
 *   ESF  → Estado de Situación Financiera (Balance General)
 *   ERI  → Estado de Resultado Integral
 *   MAP  → Wizard de Mapeo NIIF (cuentas sin mapear)
 *
 * Flujo:
 *   1. Al montar: POST /reporting/eeff/seed-mapping (idempotente)
 *   2. GET /reporting/eeff/{year} → datos ESF + ERI
 *   3. Drilldown: cada partida expande las cuentas que la componen
 *   4. Warning si hay cuentas sin mapear
 */
import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../context/AppContext'


// ── CSS de impresión ─────────────────────────────────────────────
const PRINT_STYLE = `
@media print {
    body { background: #fff !important; color: #000 !important; font-size: 9pt !important; }
    nav, aside, header, .no-print, button, select,
    [id*="btn"], [id*="toggle"] { display: none !important; }
    #eeff-tab-content { display: block !important; }

    /* NIIF Sección 3.14: presentación comparativa obligatoria */
    /* Forzar visibilidad de la columna N-1 en impresión */
    td[data-prior], th[data-prior] { display: table-cell !important; }
    .niif-prior-col { display: table-cell !important; }
    .niif-print-header { display: block !important; margin-bottom: 12pt; }
    .niif-comparativo-nota { display: block !important; font-size: 7pt; color: #555; }

    /* Tabla de 3 columnas: Descripción | N-1 (Año anterior) | N (Año actual) */
    table { width: 100%; border-collapse: collapse; page-break-inside: avoid; }
    td, th { padding: 3pt 6pt !important; font-size: 8pt !important; }
    tr { page-break-inside: avoid; }

    /* Fondo blanco en bloques de color del dark mode */
    [style*="background"] { background: transparent !important; }
    [style*="color: var"] { color: #000 !important; }
    [style*="border-radius"] { border-radius: 0 !important; }

    @page { margin: 1.5cm; size: A4 portrait; }
    .print-page-break { page-break-before: always; }
}
`

function PrintStyleInjector() {
    useEffect(() => {
        const style = document.createElement('style')
        style.id = 'eeff-print-style'
        style.textContent = PRINT_STYLE
        if (!document.getElementById('eeff-print-style')) {
            document.head.appendChild(style)
        }
        return () => {
            const s = document.getElementById('eeff-print-style')
            if (s) s.remove()
        }
    }, [])
    return null
}

// ── Paleta de colores por tipo de sección ─────────────────────
const COLORS = {
    activo: '#10b981',  // verde
    pasivo: '#f59e0b',  // amarillo
    patrimonio: '#8b5cf6',  // violeta
    ingreso: '#06b6d4',  // cyan
    costo: '#ef4444',  // rojo
    gasto: '#f97316',  // naranja
    isr: '#64748b',  // gris
    total: '#fff',     // blanco
}

const SECTION_COLOR = {
    activo_corriente: COLORS.activo,
    activo_no_corriente: COLORS.activo,
    pasivo_corriente: COLORS.pasivo,
    pasivo_no_corriente: COLORS.pasivo,
    patrimonio: COLORS.patrimonio,
    ingresos: COLORS.ingreso,
    costos: COLORS.costo,
    gastos_operativos: COLORS.gasto,
    gastos_financieros: COLORS.gasto,
    impuesto_renta: COLORS.isr,
    otro_resultado: COLORS.patrimonio,
}

// ── Helpers ────────────────────────────────────────────────────
const fmt = (n) => new Intl.NumberFormat('es-CR', {
    style: 'currency', currency: 'CRC',
    minimumFractionDigits: 0, maximumFractionDigits: 0,
}).format(n || 0)

const fmtNum = (n) => new Intl.NumberFormat('es-CR', {
    minimumFractionDigits: 0, maximumFractionDigits: 0,
}).format(n || 0)

const isNeg = (n) => (n || 0) < 0

// ── Componente: Fila de partida NIIF con drilldown ─────────────
function NiifLine({ label, amount, priorAmount, niifCode, detail = [], color, isTotal = false, indent = false, showCompar = false }) {
    const [open, setOpen] = useState(false)
    const hasDetail = detail.length > 0

    return (
        <>
            <tr
                onClick={hasDetail ? () => setOpen(o => !o) : undefined}
                style={{
                    cursor: hasDetail ? 'pointer' : 'default',
                    background: isTotal ? 'rgba(255,255,255,0.04)' : 'transparent',
                    borderBottom: isTotal ? '1px solid rgba(255,255,255,0.1)' : 'none',
                    transition: 'background 0.15s',
                }}
                onMouseEnter={e => { if (hasDetail) e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
                onMouseLeave={e => { if (!isTotal) e.currentTarget.style.background = 'transparent' }}
            >
                {/* Descripción */}
                <td style={{
                    padding: indent ? '5px 8px 5px 24px' : '6px 8px',
                    fontSize: isTotal ? '0.82rem' : '0.8rem',
                    fontWeight: isTotal ? 700 : 400,
                    color: isTotal ? '#fff' : 'var(--text-secondary)',
                    display: 'flex', alignItems: 'center', gap: 6,
                    borderLeft: !isTotal ? `2px solid ${color}30` : 'none',
                }}>
                    {hasDetail && (
                        <span style={{
                            fontSize: '0.6rem', opacity: 0.5,
                            transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
                            display: 'inline-block', transition: 'transform 0.15s',
                            userSelect: 'none',
                        }}>▶</span>
                    )}
                    {!hasDetail && !isTotal && (
                        <span style={{ width: 10, display: 'inline-block' }} />
                    )}
                    {label}
                    {niifCode && !isTotal && (
                        <span style={{ fontSize: '0.6rem', opacity: 0.35, marginLeft: 2 }}>
                            {niifCode}
                        </span>
                    )}
                </td>
                {/* Monto N-1 (comparativo) — NIIF Sec. 3.14: obligatorio siempre */}
                {showCompar && (
                    <td
                        data-prior="true"
                        className="niif-prior-col"
                        style={{
                            padding: '6px 8px', textAlign: 'right',
                            fontFamily: 'monospace', fontSize: '0.75rem',
                            color: priorAmount ? 'var(--text-muted)' : 'var(--text-muted)',
                            whiteSpace: 'nowrap',
                            borderRight: '1px solid rgba(255,255,255,0.06)',
                            fontStyle: !priorAmount ? 'italic' : 'normal',
                        }}
                    >
                        {priorAmount !== undefined && priorAmount !== null
                            ? fmt(priorAmount)
                            : '¢0'}
                    </td>
                )}
                {/* Monto N */}
                <td style={{
                    padding: '6px 12px 6px 8px',
                    textAlign: 'right',
                    fontFamily: 'monospace',
                    fontSize: isTotal ? '0.85rem' : '0.8rem',
                    fontWeight: isTotal ? 700 : 500,
                    color: isNeg(amount)
                        ? '#ef4444'
                        : (isTotal ? '#fff' : color || 'var(--text-primary)'),
                    whiteSpace: 'nowrap',
                }}>
                    {fmt(amount)}
                </td>
            </tr>

            {/* Drilldown: cuentas que componen esta partida */}
            {open && detail.map((d, i) => (
                <tr key={i} style={{ background: 'rgba(0,0,0,0.25)' }}>
                    <td style={{
                        padding: '3px 8px 3px 44px',
                        fontSize: '0.72rem',
                        color: 'var(--text-muted)',
                        borderLeft: `2px solid ${color}18`,
                    }}>
                        <span style={{ fontFamily: 'monospace', marginRight: 8, color: color, opacity: 0.7 }}>
                            {d.code}
                        </span>
                        {d.name}
                    </td>
                    <td style={{
                        padding: '3px 12px 3px 8px',
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        fontSize: '0.72rem',
                        color: isNeg(d.balance) ? '#ef4444' : 'var(--text-muted)',
                    }}>
                        {fmt(d.balance)}
                    </td>
                </tr>
            ))}
        </>
    )
}

// ── Componente: Sección del ESF/ERI (encabezado + líneas) ──────
function StatementSection({ title, lines = [], total, totalLabel, color, showCompar = false, priorTotal }) {
    if (!lines.length && !total) return null
    return (
        <tbody>
            {/* Encabezado de sección */}
            <tr>
                <td colSpan={showCompar ? 3 : 2} style={{
                    padding: '12px 8px 4px',
                    fontSize: '0.65rem',
                    fontWeight: 800,
                    letterSpacing: '0.1em',
                    color,
                    textTransform: 'uppercase',
                    borderBottom: `1px solid ${color}30`,
                }}>
                    {title}
                </td>
            </tr>
            {/* Líneas */}
            {lines.map((l, i) => (
                <NiifLine
                    key={i}
                    label={l.label}
                    amount={l.amount}
                    priorAmount={l.prior_amount}
                    niifCode={l.code}
                    detail={l.detail || []}
                    color={color}
                    showCompar={showCompar}
                />
            ))}
            {/* Total de sección */}
            {total !== undefined && (
                <NiifLine
                    label={totalLabel}
                    amount={total}
                    priorAmount={priorTotal}
                    color={color}
                    isTotal
                    showCompar={showCompar}
                />
            )}
            <tr><td colSpan={2} style={{ height: 4 }} /></tr>
        </tbody>
    )
}

// ── Componente: Badge de check ESF cuadrado ────────────────────
function BalanceCheck({ balanced, difference }) {
    return (
        <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '4px 12px', borderRadius: 20,
            background: balanced ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
            border: `1px solid ${balanced ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            fontSize: '0.72rem', fontWeight: 700,
            color: balanced ? '#10b981' : '#ef4444',
        }}>
            {balanced ? '✅ ESF cuadrado (A = P + Pat)' : `❌ Diff: ${fmt(difference)}`}
        </div>
    )
}

// ── Componente: Warning de cuentas sin mapear ──────────────────
function UnmappedWarning({ accounts = [] }) {
    const [open, setOpen] = useState(false)
    if (!accounts.length) return null
    return (
        <div style={{
            background: 'rgba(245,158,11,0.08)',
            border: '1px solid rgba(245,158,11,0.3)',
            borderRadius: 10, padding: '10px 14px',
            marginBottom: 16,
        }}>
            <div
                onClick={() => setOpen(o => !o)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
            >
                <span style={{ fontSize: '1rem' }}>⚠️</span>
                <span style={{ fontWeight: 700, color: '#f59e0b', fontSize: '0.8rem' }}>
                    {accounts.length} cuenta{accounts.length > 1 ? 's' : ''} sin mapear NIIF
                </span>
                <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {open ? 'ocultar ▲' : 'ver ▼'}
                </span>
            </div>
            {open && (
                <div style={{ marginTop: 8 }}>
                    {accounts.map((a, i) => (
                        <div key={i} style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '2px 0' }}>
                            <span style={{ fontFamily: 'monospace', color: '#f59e0b' }}>{a}</span>
                        </div>
                    ))}
                    <div style={{ marginTop: 8, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        → Ir a tab <strong>Mapeo NIIF</strong> para asignarles una partida
                    </div>
                </div>
            )}
        </div>
    )
}

// ── TAB: Estado de Situación Financiera ────────────────────────
function TabESF({ esf, year, priorYear, showCompar }) {
    if (!esf) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Sin datos ESF</div>
    const t = esf.totals || {}
    const p = esf.prior_totals || {}
    const cols = showCompar ? 3 : 2

    return (
        <div>
            {/* Sub-header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Al 31 de diciembre de {year}</span>
                <BalanceCheck balanced={t.balanced} difference={t.difference} />
            </div>

            {/* ━━━ Tabla vertical única (Activos → Pasivos → Patrimonio) ━━━ */}
            <div style={{ background: 'var(--bg-card)', borderRadius: 14, overflow: 'hidden', border: '1px solid var(--border)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                    <colgroup>
                        <col style={{ width: showCompar ? '60%' : '75%' }} />
                        {showCompar && <col style={{ width: '20%' }} />}
                        <col style={{ width: showCompar ? '20%' : '25%' }} />
                    </colgroup>
                    <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.04)', borderBottom: '2px solid rgba(255,255,255,0.08)' }}>
                            <th style={{ padding: '11px 16px', textAlign: 'left', fontSize: '0.69rem', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>Partida NIIF</th>
                            {showCompar && (
                                <th data-prior="true" className="niif-prior-col"
                                    style={{ padding: '11px 10px', textAlign: 'right', fontSize: '0.69rem', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
                                    {priorYear || (parseInt(year) - 1)}
                                </th>
                            )}
                            <th style={{ padding: '11px 16px', textAlign: 'right', fontSize: '0.69rem', fontWeight: 900, color: '#fff', letterSpacing: '0.04em' }}>{year}</th>
                        </tr>
                    </thead>

                    {/* ─ ACTIVOS ─────────────────────────────────────────── */}
                    <tbody>
                        <tr style={{ background: `${COLORS.activo}12`, borderTop: `2px solid ${COLORS.activo}50` }}>
                            <td colSpan={cols} style={{ padding: '7px 16px 5px', fontSize: '0.63rem', fontWeight: 900, letterSpacing: '0.15em', color: COLORS.activo, textTransform: 'uppercase' }}>Activos</td>
                        </tr>
                    </tbody>
                    <StatementSection title="Activo Corriente" color={COLORS.activo}
                        lines={esf.activo_corriente} total={t.total_activo_corriente}
                        totalLabel="Total Activo Corriente" showCompar={showCompar} priorTotal={p?.total_activo_corriente} />
                    <StatementSection title="Activo No Corriente" color={COLORS.activo}
                        lines={esf.activo_no_corriente} total={t.total_activo_no_corriente}
                        totalLabel="Total Activo No Corriente" showCompar={showCompar} priorTotal={p?.total_activo_no_corriente} />
                    <tbody>
                        <tr style={{ background: `${COLORS.activo}18`, borderTop: `2px solid ${COLORS.activo}60` }}>
                            <td style={{ padding: '12px 16px', fontWeight: 900, fontSize: '0.83rem', color: COLORS.activo }}>TOTAL ACTIVOS</td>
                            {showCompar && <td data-prior="true" className="niif-prior-col" style={{ padding: '12px 10px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text-muted)' }}>{fmt(p.total_activos)}</td>}
                            <td style={{ padding: '12px 16px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 900, fontSize: '0.9rem', color: COLORS.activo }}>{fmt(t.total_activos)}</td>
                        </tr>
                        <tr><td colSpan={cols} style={{ height: 10, background: 'rgba(0,0,0,0.15)' }} /></tr>
                    </tbody>

                    {/* ─ PASIVOS ─────────────────────────────────────────── */}
                    <tbody>
                        <tr style={{ background: `${COLORS.pasivo}12`, borderTop: `2px solid ${COLORS.pasivo}50` }}>
                            <td colSpan={cols} style={{ padding: '7px 16px 5px', fontSize: '0.63rem', fontWeight: 900, letterSpacing: '0.15em', color: COLORS.pasivo, textTransform: 'uppercase' }}>Pasivos</td>
                        </tr>
                    </tbody>
                    <StatementSection title="Pasivo Corriente" color={COLORS.pasivo}
                        lines={esf.pasivo_corriente} total={t.total_pasivo_corriente}
                        totalLabel="Total Pasivo Corriente" showCompar={showCompar} priorTotal={p?.total_pasivo_corriente} />
                    <StatementSection title="Pasivo No Corriente" color={COLORS.pasivo}
                        lines={esf.pasivo_no_corriente} total={t.total_pasivo_no_corriente}
                        totalLabel="Total Pasivo No Corriente" showCompar={showCompar} priorTotal={p?.total_pasivo_no_corriente} />
                    <tbody>
                        <tr style={{ background: `${COLORS.pasivo}14`, borderTop: `1px solid ${COLORS.pasivo}40` }}>
                            <td style={{ padding: '10px 16px', fontWeight: 800, fontSize: '0.8rem', color: COLORS.pasivo }}>Total Pasivos</td>
                            {showCompar && <td data-prior="true" className="niif-prior-col" style={{ padding: '10px 10px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-muted)' }}>{fmt(p.total_pasivos)}</td>}
                            <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, fontSize: '0.83rem', color: COLORS.pasivo }}>{fmt(t.total_pasivos)}</td>
                        </tr>
                        <tr><td colSpan={cols} style={{ height: 10, background: 'rgba(0,0,0,0.15)' }} /></tr>
                    </tbody>

                    {/* ─ PATRIMONIO ──────────────────────────────────────── */}
                    <tbody>
                        <tr style={{ background: `${COLORS.patrimonio}12`, borderTop: `2px solid ${COLORS.patrimonio}50` }}>
                            <td colSpan={cols} style={{ padding: '7px 16px 5px', fontSize: '0.63rem', fontWeight: 900, letterSpacing: '0.15em', color: COLORS.patrimonio, textTransform: 'uppercase' }}>Patrimonio</td>
                        </tr>
                    </tbody>
                    <StatementSection title="Patrimonio" color={COLORS.patrimonio}
                        lines={esf.patrimonio} showCompar={showCompar} priorTotal={p?.total_patrimonio} />

                    {/* ─ GRAN TOTAL ──────────────────────────────────────── */}
                    <tbody>
                        <tr style={{ background: 'rgba(255,255,255,0.06)', borderTop: '2px solid rgba(255,255,255,0.22)' }}>
                            <td style={{ padding: '13px 16px', fontWeight: 900, fontSize: '0.85rem', color: '#fff' }}>TOTAL PASIVOS + PATRIMONIO</td>
                            {showCompar && (
                                <td data-prior="true" className="niif-prior-col"
                                    style={{ padding: '13px 10px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                                    {fmt((p.total_pasivos ?? 0) + (p.total_patrimonio ?? 0))}
                                </td>
                            )}
                            <td style={{ padding: '13px 16px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 900, fontSize: '0.92rem', color: '#fff' }}>{fmt(t.total_pasivo_patrimonio)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            {/* Nota NIIF */}
            <div className="niif-comparativo-nota" style={{ marginTop: 10, padding: '7px 12px', borderRadius: 8, background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                <span>📖 NIIF PYMES 3ª Ed. (Feb 2025) · Sec. 4 · Clasificación Corriente/No Corriente</span>
                {showCompar && !priorYear && (
                    <span style={{ color: '#f59e0b', fontStyle: 'italic' }}>· ⚠️ Primer año · columna {parseInt(year) - 1} en cero (Sec. 3.14)</span>
                )}
            </div>
        </div>
    )
}

// ── TAB: Estado de Resultado Integral ─────────────────────────
function TabERI({ eri, year, priorYear, showCompar }) {
    if (!eri) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Sin datos ERI</div>
    const t = eri.totals || {}
    const p = eri.prior_totals || {}
    const un = t.utilidad_neta || 0
    const isLoss = un < 0
    // sc = show comparative: activo solo si showCompar=true Y el backend envió prior_totals
    const sc = showCompar && Object.keys(p).length > 0
    // Subtotales N-1 calculados en engine (Capa 1a del plan)
    const p_bruta = p.utilidad_bruta_prior ?? 0
    const p_ai = p.utilidad_antes_isr_prior ?? 0
    const p_neta = p.utilidad_neta_prior ?? 0
    const p_ri = p.total_resultado_integral_prior ?? 0

    // Fila de subtotal calculado (Utilidad Bruta, UAI) con columna N-1
    function SubtotalRow({ label, current, prior, isGood }) {
        const neg = current < 0
        const negP = prior < 0
        return (
            <tbody>
                <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                    <td style={{ padding: '7px 8px', fontWeight: 800, fontSize: '0.8rem', color: '#fff' }}>
                        {label}
                    </td>
                    {sc && (
                        <td style={{
                            padding: '7px 12px', textAlign: 'right', fontFamily: 'monospace',
                            fontWeight: 700, fontSize: '0.78rem',
                            color: negP ? '#ef4444' : '#6b7280'
                        }}>
                            {fmt(prior)}
                        </td>
                    )}
                    <td style={{
                        padding: '7px 12px 7px 8px', textAlign: 'right', fontFamily: 'monospace',
                        fontWeight: 800, fontSize: '0.82rem',
                        color: neg ? '#ef4444' : (isGood ? '#10b981' : COLORS.ingreso)
                    }}>
                        {fmt(current)}
                    </td>
                </tr>
                <tr><td colSpan={sc ? 3 : 2} style={{ height: 4 }} /></tr>
            </tbody>
        )
    }

    return (
        <div>
            <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Período enero–diciembre {year}
                </span>
                <div style={{
                    padding: '4px 14px', borderRadius: 20,
                    background: isLoss ? 'rgba(239,68,68,0.12)' : 'rgba(16,185,129,0.12)',
                    border: `1px solid ${isLoss ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`,
                    fontSize: '0.75rem', fontWeight: 700,
                    color: isLoss ? '#ef4444' : '#10b981',
                }}>
                    {isLoss ? `📉 Pérdida: ${fmt(un)}` : `📈 Utilidad Neta: ${fmt(un)}`}
                </div>
            </div>

            <div style={{
                background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden',
                border: '1px solid var(--border)', maxWidth: sc ? 780 : 600
            }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    {/* Header comparativo N-1 / N */}
                    {sc && (
                        <thead>
                            <tr style={{ background: 'rgba(255,255,255,0.05)' }}>
                                <th style={{
                                    padding: '7px 8px', textAlign: 'left',
                                    fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600
                                }}>
                                    Partida
                                </th>
                                <th id="eri-col-prior" style={{
                                    padding: '7px 12px', textAlign: 'right',
                                    fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600
                                }}>
                                    N-1 ({priorYear})
                                </th>
                                <th id="eri-col-current" style={{
                                    padding: '7px 12px', textAlign: 'right',
                                    fontSize: '0.72rem', color: 'var(--text-primary)', fontWeight: 700
                                }}>
                                    N ({year})
                                </th>
                            </tr>
                        </thead>
                    )}

                    <StatementSection title="Ingresos de Actividades Ordinarias"
                        color={COLORS.ingreso} lines={eri.ingresos}
                        total={t.total_ingresos} totalLabel="Total Ingresos"
                        showCompar={sc} priorTotal={p.total_ingresos} />

                    <StatementSection title="Costo de Ventas / Servicios"
                        color={COLORS.costo} lines={eri.costos}
                        total={t.total_costo} totalLabel="Total Costo de Ventas"
                        showCompar={sc} priorTotal={p.total_costo} />

                    <SubtotalRow label="Utilidad Bruta"
                        current={t.utilidad_bruta} prior={p_bruta} isGood />

                    <StatementSection title="Gastos Operativos"
                        color={COLORS.gasto} lines={eri.gastos_operativos}
                        total={t.total_gastos_op} totalLabel="Total Gastos Operativos"
                        showCompar={sc} priorTotal={p.total_gastos_op} />

                    <StatementSection title="Gastos Financieros"
                        color={COLORS.gasto} lines={eri.gastos_financieros}
                        total={t.total_gastos_fin} totalLabel="Total Gastos Financieros"
                        showCompar={sc} priorTotal={p.total_gastos_fin} />

                    <SubtotalRow label="Utilidad antes de impuestos"
                        current={t.utilidad_antes_isr} prior={p_ai} />

                    <StatementSection title="Impuesto sobre la Renta (Sec. 29)"
                        color={COLORS.isr} lines={eri.impuesto_renta}
                        total={t.total_isr} totalLabel="Total ISR"
                        showCompar={sc} priorTotal={p.total_isr} />

                    {/* Utilidad / Pérdida Neta */}
                    <tbody>
                        <tr id="eri-utilidad-neta" style={{
                            background: isLoss ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.08)',
                            borderTop: '2px solid rgba(255,255,255,0.15)',
                        }}>
                            <td style={{ padding: '10px 8px', fontWeight: 800, fontSize: '0.85rem', color: '#fff' }}>
                                {isLoss ? '📉 PÉRDIDA NETA DEL PERÍODO' : '📈 UTILIDAD NETA DEL PERÍODO'}
                            </td>
                            {sc && (
                                <td id="eri-utilidad-neta-prior" style={{
                                    padding: '10px 12px', textAlign: 'right',
                                    fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem',
                                    color: p_neta < 0 ? '#ef4444' : '#6b7280',
                                }}>
                                    {fmt(p_neta)}
                                </td>
                            )}
                            <td style={{
                                padding: '10px 12px', textAlign: 'right',
                                fontFamily: 'monospace', fontWeight: 800, fontSize: '0.9rem',
                                color: isLoss ? '#ef4444' : '#10b981'
                            }}>
                                {fmt(un)}
                            </td>
                        </tr>
                    </tbody>

                    {/* ORI — Otro Resultado Integral (3ª Ed. Sec. 5.4) */}
                    {(eri.otro_resultado?.length > 0) && (
                        <>
                            <StatementSection title="Otro Resultado Integral (ORI — Sec. 5.4 NIIF 3ªEd.)"
                                color={COLORS.patrimonio} lines={eri.otro_resultado}
                                total={t.total_ori} totalLabel="Total ORI"
                                showCompar={sc} priorTotal={p.total_ori} />
                            <tbody>
                                <tr style={{
                                    background: 'rgba(139,92,246,0.08)',
                                    borderTop: '2px solid rgba(255,255,255,0.15)',
                                }}>
                                    <td style={{ padding: '10px 8px', fontWeight: 800, fontSize: '0.85rem', color: '#fff' }}>
                                        TOTAL RESULTADO INTEGRAL
                                    </td>
                                    {sc && (
                                        <td style={{
                                            padding: '10px 12px', textAlign: 'right',
                                            fontFamily: 'monospace', fontWeight: 700,
                                            fontSize: '0.85rem', color: '#6b7280'
                                        }}>
                                            {fmt(p_ri)}
                                        </td>
                                    )}
                                    <td style={{
                                        padding: '10px 12px', textAlign: 'right',
                                        fontFamily: 'monospace', fontWeight: 800,
                                        fontSize: '0.9rem', color: COLORS.patrimonio
                                    }}>
                                        {fmt(t.total_resultado_integral)}
                                    </td>
                                </tr>
                            </tbody>
                        </>
                    )}
                </table>
            </div>

            <div style={{
                marginTop: 12, padding: '8px 12px', borderRadius: 8,
                background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem',
                color: 'var(--text-muted)'
            }}>
                📖 NIIF PYMES 3ª Ed. · Sección 5 · Clasificación por función · Sección 23 (Ingresos-contratos) aplicada
            </div>
        </div>
    )
}

// ── TAB: Estado de Cambios en el Patrimonio ───────────────────
function TabECP({ ecp, year }) {
    if (!ecp) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Sin datos ECP</div>
    const t = ecp.totals || {}
    const cols = ecp.columns || []
    const color = '#8b5cf6'

    return (
        <div>
            <div style={{ marginBottom: 12, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Período enero–diciembre {year} · {ecp.niif_ref}
            </div>
            <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'auto', border: '1px solid var(--border)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
                    <thead>
                        <tr style={{ background: `${color}15`, borderBottom: `1px solid ${color}30` }}>
                            <th style={{ padding: '10px 12px', textAlign: 'left', fontSize: '0.72rem', fontWeight: 800, color, letterSpacing: '0.05em' }}>Componente</th>
                            <th style={{ padding: '10px 8px', textAlign: 'right', fontSize: '0.72rem', fontWeight: 800, color }}>Saldo Inicial</th>
                            <th style={{ padding: '10px 8px', textAlign: 'right', fontSize: '0.72rem', fontWeight: 800, color }}>Movimiento</th>
                            <th style={{ padding: '10px 8px', textAlign: 'right', fontSize: '0.72rem', fontWeight: 800, color }}>Saldo Final</th>
                        </tr>
                    </thead>
                    <tbody>
                        {cols.map((col, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.03)'}
                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                            >
                                <td style={{ padding: '7px 12px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                    {col.label}
                                    {col.nota && <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginLeft: 6 }}>({col.nota})</span>}
                                </td>
                                <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                                    {fmt(col.saldo_inicial)}
                                </td>
                                <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace', fontSize: '0.78rem', color: col.movimiento < 0 ? '#ef4444' : col.movimiento > 0 ? '#10b981' : 'var(--text-muted)' }}>
                                    {col.movimiento !== 0 ? (col.movimiento > 0 ? '+' : '') + fmt(col.movimiento) : '—'}
                                </td>
                                <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace', fontSize: '0.78rem', fontWeight: 600, color }}>
                                    {fmt(col.saldo_final)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                    <tfoot>
                        <tr style={{ background: `${color}10`, borderTop: `2px solid ${color}40` }}>
                            <td style={{ padding: '10px 12px', fontWeight: 800, fontSize: '0.8rem', color: '#fff' }}>TOTAL PATRIMONIO</td>
                            <td style={{ padding: '10px 8px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color }}>{fmt(t.total_inicial)}</td>
                            <td style={{ padding: '10px 8px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: t.total_movimiento < 0 ? '#ef4444' : '#10b981' }}>
                                {t.total_movimiento !== 0 ? (t.total_movimiento > 0 ? '+' : '') + fmt(t.total_movimiento) : '—'}
                            </td>
                            <td style={{ padding: '10px 8px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, color }}>{fmt(t.total_final)}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 8, background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                📖 NIIF PYMES 3ª Ed. · Sección 6 · Conciliación de cada componente del patrimonio
            </div>
        </div>
    )
}

// ── TAB: Estado de Flujos de Efectivo ─────────────────────────
function TabEFE({ efe, efePrior, year, priorYear, showCompar }) {
    if (!efe) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Sin datos EFE</div>
    const c = efe.conciliacion || {}
    const cp = efePrior?.conciliacion || {}
    const cashOk = c.efe_cash_matches
    const hasPrior = showCompar && !!efePrior

    function EfeSection({ title, section, sectionPrior, color, icon }) {
        const items = (section?.items || []).filter(i => i.amount !== 0)
        const priorItems = sectionPrior?.items || []
        return (
            <div style={{ marginBottom: 12 }}>
                {/* Encabezado con total N-1 y N */}
                <div style={{
                    padding: '8px 14px', background: `${color}15`, borderLeft: `3px solid ${color}`,
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                }}>
                    <span style={{ fontWeight: 800, fontSize: '0.78rem', color }}>{icon} {title}</span>
                    <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                        {hasPrior && (
                            <span style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: '#6b7280' }}>
                                {fmt(sectionPrior?.total)}
                            </span>
                        )}
                        <span style={{
                            fontFamily: 'monospace', fontWeight: 800, fontSize: '0.82rem',
                            color: section?.total < 0 ? '#ef4444' : color
                        }}>
                            {fmt(section?.total)}
                        </span>
                    </div>
                </div>
                {/* Sub-header N-1 / N */}
                {hasPrior && (
                    <div style={{
                        display: 'flex', justifyContent: 'flex-end', gap: 16, padding: '3px 14px',
                        fontSize: '0.68rem', color: 'var(--text-muted)'
                    }}>
                        <span style={{ minWidth: 105, textAlign: 'right' }}>N-1 ({priorYear})</span>
                        <span style={{ minWidth: 105, textAlign: 'right' }}>N ({year})</span>
                    </div>
                )}
                {/* Items */}
                <div style={{ paddingLeft: 3 }}>
                    {items.map((item, i) => {
                        const priorAmt = priorItems[i]?.amount ?? 0
                        return (
                            <div key={i} style={{
                                display: 'flex', justifyContent: 'space-between',
                                padding: '5px 14px', fontSize: '0.78rem',
                                borderBottom: '1px solid rgba(255,255,255,0.03)',
                                color: 'var(--text-secondary)',
                            }}>
                                <span>{item.label}</span>
                                <div style={{ display: 'flex', gap: 16 }}>
                                    {hasPrior && (
                                        <span style={{
                                            fontFamily: 'monospace', minWidth: 105, textAlign: 'right',
                                            color: priorAmt < 0 ? '#ef4444'
                                                : priorAmt > 0 ? '#6b7280'
                                                    : 'var(--text-muted)'
                                        }}>
                                            {priorAmt > 0 ? '+' : ''}{fmt(priorAmt)}
                                        </span>
                                    )}
                                    <span style={{
                                        fontFamily: 'monospace', minWidth: 105, textAlign: 'right',
                                        color: item.amount < 0 ? '#ef4444'
                                            : item.amount > 0 ? '#10b981'
                                                : 'var(--text-muted)'
                                    }}>
                                        {item.amount > 0 ? '+' : ''}{fmt(item.amount)}
                                    </span>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>
        )
    }

    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Método Indirecto · {efe.niif_ref}
                </span>
                <div id="efe-cash-check" style={{
                    padding: '4px 14px', borderRadius: 20, fontSize: '0.72rem', fontWeight: 700,
                    background: cashOk ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                    border: `1px solid ${cashOk ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                    color: cashOk ? '#10b981' : '#ef4444',
                }}>
                    {cashOk ? '✅ Efectivo cuadra (EFE = ESF.AC.01)' : `❌ Diferencia: ${fmt(c.diferencia)}`}
                </div>
                {hasPrior && (
                    <span id="efe-comparativo-badge" style={{
                        fontSize: '0.7rem', color: '#6b7280',
                        border: '1px solid #6b728040', borderRadius: 12, padding: '3px 10px',
                    }}>
                        + Comparativo N-1 ({priorYear})
                    </span>
                )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16, alignItems: 'start' }}>
                {/* Columna izquierda: Actividades */}
                <div style={{
                    background: 'var(--bg-card)', borderRadius: 12,
                    overflow: 'hidden', border: '1px solid var(--border)'
                }}>
                    <EfeSection title="Actividades de Operación"
                        section={efe.operacion} sectionPrior={efePrior?.operacion}
                        color='#10b981' icon='⚙️' />
                    <EfeSection title="Actividades de Inversión"
                        section={efe.inversion} sectionPrior={efePrior?.inversion}
                        color='#f59e0b' icon='🔧' />
                    <EfeSection title="Actividades de Financiación"
                        section={efe.financiacion} sectionPrior={efePrior?.financiacion}
                        color='#8b5cf6' icon='💰' />
                </div>

                {/* Columna derecha: Conciliación */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{
                        background: 'var(--bg-card)', borderRadius: 12,
                        border: '1px solid var(--border)', overflow: 'hidden'
                    }}>
                        <div style={{
                            padding: '10px 14px', background: 'rgba(255,255,255,0.04)',
                            borderBottom: '1px solid var(--border)'
                        }}>
                            <span style={{ fontWeight: 800, fontSize: '0.78rem', color: '#fff' }}>
                                Conciliación de Efectivo
                            </span>
                        </div>
                        {hasPrior && (
                            <div style={{
                                display: 'flex', justifyContent: 'flex-end', gap: 12,
                                padding: '3px 14px', fontSize: '0.68rem', color: '#6b7280',
                                borderBottom: '1px solid rgba(255,255,255,0.04)'
                            }}>
                                <span>N-1</span>
                                <span style={{ minWidth: 60, textAlign: 'right' }}>N</span>
                            </div>
                        )}
                        {[
                            {
                                label: 'Efectivo inicial',
                                curr: c.efectivo_inicial, prior: cp.efectivo_inicial,
                                color: 'var(--text-secondary)'
                            },
                            {
                                label: '+ Flujo Operación',
                                curr: c.total_actividades_operacion, prior: cp.total_actividades_operacion,
                                color: '#10b981'
                            },
                            {
                                label: '+ Flujo Inversión',
                                curr: c.total_actividades_inversion, prior: cp.total_actividades_inversion,
                                color: '#f59e0b'
                            },
                            {
                                label: '+ Flujo Financiación',
                                curr: c.total_actividades_financiacion, prior: cp.total_actividades_financiacion,
                                color: '#8b5cf6'
                            },
                            {
                                label: 'Cambio neto',
                                curr: c.cambio_neto_efectivo, prior: cp.cambio_neto_efectivo,
                                color: '#06b6d4', bold: true
                            },
                            {
                                label: 'Efectivo final (EFE)',
                                curr: c.efectivo_final_calculado, prior: cp.efectivo_final_calculado,
                                color: '#fff', bold: true
                            },
                            {
                                label: 'Efectivo en Balance (ESF)',
                                curr: c.efectivo_final_esf, prior: cp.efectivo_final_esf,
                                color: '#fff', bold: true
                            },
                        ].map((row, i) => (
                            <div key={i} style={{
                                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                padding: '5px 14px', borderBottom: '1px solid rgba(255,255,255,0.04)',
                                background: row.bold ? 'rgba(255,255,255,0.03)' : 'transparent',
                            }}>
                                <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                                    {row.label}
                                </span>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    {hasPrior && (
                                        <span style={{
                                            fontSize: '0.73rem', fontFamily: 'monospace',
                                            fontWeight: row.bold ? 600 : 400,
                                            color: '#6b7280', minWidth: 70, textAlign: 'right'
                                        }}>
                                            {fmt(row.prior)}
                                        </span>
                                    )}
                                    <span style={{
                                        fontSize: '0.73rem', fontFamily: 'monospace',
                                        fontWeight: row.bold ? 700 : 400,
                                        color: (row.curr ?? 0) < 0 ? '#ef4444' : row.color,
                                        minWidth: 70, textAlign: 'right'
                                    }}>
                                        {fmt(row.curr)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Conciliación pasivos financiación — Sec. 7.14 3ªEd. */}
                    <div style={{
                        background: 'var(--bg-card)', borderRadius: 12,
                        border: '1px solid var(--border)', overflow: 'hidden'
                    }}>
                        <div style={{
                            padding: '10px 14px', background: 'rgba(139,92,246,0.06)',
                            borderBottom: '1px solid var(--border)'
                        }}>
                            <span style={{ fontWeight: 700, fontSize: '0.72rem', color: '#8b5cf6' }}>
                                Pasivos de Financiación (Sec. 7.14)
                            </span>
                        </div>
                        {(efe.conciliacion_pasivos_fin || []).map((row, i) => (
                            <div key={i} style={{
                                display: 'flex', justifyContent: 'space-between',
                                padding: '4px 14px',
                                borderBottom: '1px solid rgba(255,255,255,0.03)'
                            }}>
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{row.label}</span>
                                <span style={{
                                    fontSize: '0.7rem', fontFamily: 'monospace',
                                    color: row.amount < 0 ? '#ef4444' : 'var(--text-secondary)'
                                }}>
                                    {fmt(row.amount)}
                                </span>
                            </div>
                        ))}
                    </div>

                    {efe.warnings?.length > 0 && (
                        <div style={{
                            background: 'rgba(239,68,68,0.08)',
                            border: '1px solid rgba(239,68,68,0.3)',
                            borderRadius: 8, padding: '8px 12px'
                        }}>
                            {efe.warnings.map((w, i) =>
                                <div key={i} style={{ fontSize: '0.75rem', color: '#ef4444' }}>{w}</div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            <div style={{
                marginTop: 12, padding: '8px 12px', borderRadius: 8,
                background: 'rgba(16,185,129,0.07)', fontSize: '0.68rem',
                color: 'var(--text-muted)'
            }}>
                📖 NIIF PYMES 3ª Ed. · Sección 7 · Método Indirecto · Sec. 7.14 Conciliación de pasivos de financiación
            </div>
        </div>
    )
}

// ── TAB: Wizard de Mapeo NIIF ──────────────────────────────────
function TabMapeo({ tenantId, apiBase, token }) {
    const [unmapped, setUnmapped] = useState([])
    const [loading, setLoading] = useState(false)

    const load = useCallback(async () => {
        if (!token) return
        setLoading(true)
        try {
            const r = await fetch(`${apiBase}/reporting/eeff/mapping/unmapped`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) {
                const d = await r.json()
                setUnmapped(d.accounts || [])
            }
        } finally { setLoading(false) }
    }, [token, apiBase])

    useEffect(() => { load() }, [load])

    if (loading) return <div style={{ padding: 24, color: 'var(--text-muted)' }}>Cargando cuentas sin mapear...</div>

    if (!unmapped.length) return (
        <div style={{
            padding: 32, textAlign: 'center',
            background: 'rgba(16,185,129,0.06)', borderRadius: 12,
            border: '1px solid rgba(16,185,129,0.2)',
        }}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>✅</div>
            <div style={{ color: '#10b981', fontWeight: 700, marginBottom: 4 }}>Todas las cuentas tienen mapeo NIIF</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Los EEFF reflejarán correctamente todas las cuentas del catálogo
            </div>
        </div>
    )

    return (
        <div>
            <div style={{
                background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)',
                borderRadius: 10, padding: '12px 16px', marginBottom: 16,
            }}>
                <div style={{ fontWeight: 700, color: '#f59e0b', marginBottom: 4 }}>
                    ⚠️ {unmapped.length} cuenta{unmapped.length > 1 ? 's' : ''} sin mapear a partida NIIF
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Estas cuentas no se incluyen en los EEFF. Asígnales una partida NIIF:
                </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {unmapped.map(acc => (
                    <div key={acc.code} style={{
                        background: 'var(--bg-card)', borderRadius: 8,
                        padding: '10px 14px', border: '1px solid var(--border)',
                        display: 'flex', alignItems: 'center', gap: 12,
                    }}>
                        <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#f59e0b', fontSize: '0.82rem' }}>
                            {acc.code}
                        </span>
                        <span style={{ flex: 1, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                            {acc.name}
                        </span>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                            {acc.type}
                        </span>
                        <span style={{ fontSize: '0.7rem', color: '#f59e0b', fontWeight: 600 }}>
                            Sin mapear → ir a Catálogo
                        </span>
                    </div>
                ))}
            </div>
            <div style={{ marginTop: 12, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                💡 En el módulo Catálogo podrás asignar la partida NIIF a cada cuenta manualmente.
                El auto-mapeo cubre las cuentas del catálogo estándar Genoma.
            </div>
        </div>
    )
}


// ── TAB: Notas a los Estados Financieros ─────────────────────────
const NOTAS_CATALOG = [
    {
        id: 'N-01', sec: 'Sec.8', titulo: 'Políticas Contables Significativas',
        revelaciones: [
            'Base de medición: Costo histórico de conformidad con NIIF PYMES 3ª Ed.',
            'Moneda funcional y de presentación: Colón costarricense (CRC).',
            'Período contable: 1 de enero al 31 de diciembre.',
            'Las estimaciones contables significativas incluyen: vida útil de activos, provisiones y deterioro.',
        ]
    },
    {
        id: 'N-02', sec: 'Sec.10', titulo: 'Efectivo y Equivalentes de Efectivo',
        revelaciones: [
            'Se reconocen como efectivo: caja chica, cuentas corrientes y depósitos a plazo ≤ 90 días.',
            'No existen restricciones sobre el uso del efectivo al cierre del período.',
        ]
    },
    {
        id: 'N-03', sec: 'Sec.11', titulo: 'Instrumentos Financieros Básicos',
        revelaciones: [
            'Las cuentas por cobrar se miden al costo amortizado menos deterioro.',
            'La estimación para cuentas incobrables se calcula con base en la antigüedad de saldos.',
            'Las cuentas por pagar a corto plazo no devengan intereses y se liquidan en fecha acordada.',
        ]
    },
    {
        id: 'N-04', sec: 'Sec.13', titulo: 'Inventarios',
        revelaciones: [
            'Los inventarios se valúan al costo o valor neto realizable, el menor.',
            'Método de costeo: Promedio Ponderado (FIFO disponible en catálogo extendido).',
            'Se reconoce deterioro cuando el VNR es menor al costo en libros.',
        ]
    },
    {
        id: 'N-05', sec: 'Sec.16', titulo: 'Propiedades de Inversión',
        revelaciones: [
            'Las propiedades de inversión se miden inicialmente al costo y posteriormente al modelo de costo menos depreciación acumulada.',
        ]
    },
    {
        id: 'N-06', sec: 'Sec.17', titulo: 'Propiedades, Planta y Equipo (PPE)',
        revelaciones: [
            'Las PPE se reconocen al costo menos depreciación acumulada y pérdidas por deterioro.',
            'Método de depreciación: Línea recta.',
            'Vidas útiles estimadas: Edificios 40 años, Maquinaria 5–15 años, Equipo de cómputo 3–5 años.',
            'Las mejoras que extienden la vida útil se capitalizan; el mantenimiento ordinario se gasta.',
        ]
    },
    {
        id: 'N-07', sec: 'Sec.18', titulo: 'Activos Intangibles',
        revelaciones: [
            'Los intangibles con vida útil definida se amortizan en línea recta.',
            'La plusvalía adquirida en combinaciones de negocios se somete a prueba de deterioro anual.',
        ]
    },
    {
        id: 'N-08', sec: 'Sec.21', titulo: 'Provisiones y Contingencias',
        revelaciones: [
            'Se reconoce una provisión cuando existe una obligación presente, es probable que se requiera de recursos y el monto es estimable.',
            'Las contingencias se revelan cuando son probables pero no medibles.',
        ]
    },
    {
        id: 'N-09', sec: 'Sec.23', titulo: 'Ingresos de Actividades Ordinarias',
        revelaciones: [
            'Los ingresos por venta de bienes se reconocen cuando los riesgos y beneficios se transfieren al comprador.',
            'Los ingresos por servicios se reconocen por el grado de terminación del servicio.',
            'Los ingresos por intereses se reconocen usando el método del interés efectivo.',
        ]
    },
    {
        id: 'N-10', sec: 'Sec.29', titulo: 'Impuesto a las Ganancias',
        revelaciones: [
            'El impuesto corriente se mide con las tasas vigentes aprobadas al cierre del período.',
            'Se reconocen impuestos diferidos por diferencias temporarias usando el método del pasivo.',
        ]
    },
    {
        id: 'N-11', sec: 'Sec.28', titulo: 'Beneficios a Empleados',
        revelaciones: [
            'Los beneficios a corto plazo (salarios, vacaciones, aguinaldo) se acumulan conforme se devengan.',
            'La prestación laboral (Código de Trabajo CR) se reconoce como pasivo corriente.',
            'No existen planes de beneficios post-empleo de beneficio definido al período que se informa.',
        ]
    },
]

function Nota({ nota }) {
    const [open, setOpen] = useState(false)
    return (
        <div style={{
            background: 'var(--bg-card)', borderRadius: 10,
            border: '1px solid var(--border)', overflow: 'hidden',
            marginBottom: 6,
        }}>
            <div
                onClick={() => setOpen(o => !o)}
                style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', cursor: 'pointer',
                    background: open ? 'rgba(139,92,246,0.06)' : 'transparent',
                    transition: 'background 0.15s',
                }}
            >
                <span style={{ fontSize: '0.6rem', opacity: 0.5, transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s', userSelect: 'none' }}>▶</span>
                <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#8b5cf6', minWidth: 40 }}>{nota.id}</span>
                <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginRight: 6 }}>{nota.sec}</span>
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#fff', flex: 1 }}>{nota.titulo}</span>
                <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{open ? 'cerrar' : 'ver'}</span>
            </div>
            {open && (
                <div style={{ padding: '10px 14px 12px 46px', borderTop: '1px solid var(--border)' }}>
                    <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                        {nota.revelaciones.map((r, i) => (
                            <li key={i} style={{
                                fontSize: '0.78rem', color: 'var(--text-secondary)',
                                padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.03)',
                                display: 'flex', gap: 8,
                            }}>
                                <span style={{ color: '#8b5cf6', minWidth: 10 }}>·</span>
                                {r}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

function TabNotas({ data }) {
    if (!data) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Genera los EEFF primero para ver las notas.</div>
    const t = data.eri?.totals || {}
    const esft = data.esf?.totals || {}
    const hasPerd = (t.utilidad_neta || 0) < 0

    return (
        <div>
            {/* Cabecera */}
            <div style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(139,92,246,0.07)', borderRadius: 10, border: '1px solid rgba(139,92,246,0.2)' }}>
                <div style={{ fontWeight: 800, color: '#a78bfa', marginBottom: 4 }}>
                    📋 Notas a los Estados Financieros
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Al 31 de diciembre de {data.year} · NIIF PYMES 3ª Edición (feb. 2025) · IASB.
                    Las notas son parte integral de los estados financieros y deben leerse conjuntamente con ellos.
                </div>
                {/* Tabla resumen rápido */}
                <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
                    {[
                        { label: 'Total Activos', value: esft.total_activos, color: '#10b981' },
                        { label: 'Total Pasivos', value: esft.total_pasivos, color: '#f59e0b' },
                        { label: 'Patrimonio', value: esft.total_patrimonio, color: '#8b5cf6' },
                        { label: hasPerd ? 'Pérdida Neta' : 'Utilidad Neta', value: t.utilidad_neta, color: hasPerd ? '#ef4444' : '#06b6d4' },
                    ].map((kpi, i) => (
                        <div key={i} style={{ background: 'var(--bg-card)', borderRadius: 8, padding: '8px 14px', border: '1px solid var(--border)', minWidth: 110 }}>
                            <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>{kpi.label}</div>
                            <div style={{ fontFamily: 'monospace', fontWeight: 700, color: kpi.color, fontSize: '0.82rem' }}>
                                {new Intl.NumberFormat('es-CR', { style: 'currency', currency: 'CRC', maximumFractionDigits: 0 }).format(kpi.value || 0)}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Notas colapsables */}
            <div>
                {NOTAS_CATALOG.map(nota => (
                    <Nota key={nota.id} nota={nota} />
                ))}
            </div>

            <div style={{ marginTop: 14, padding: '8px 12px', borderRadius: 8, background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                📖 Notas generadas automáticamente con base en las políticas contables estándar NIIF PYMES 3ª Ed.
                El contador debe revisar y personalizar estas revelaciones según las circunstancias específicas de la entidad.
            </div>
        </div>
    )
}

// ═══════════════════════════════════════════════════════════════
// COMPONENTE PRINCIPAL
// ═══════════════════════════════════════════════════════════════
export default function EstadosFinancieros() {
    const { state } = useApp()
    const [activeTab, setActiveTab] = useState('esf')
    const [year, setYear] = useState(String(new Date().getFullYear()))
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [seeded, setSeeded] = useState(false)
    const [showCompar, setShowCompar] = useState(true)

    const API = import.meta.env.VITE_API_URL || 'https://genoma-contabilidad.onrender.com'
    const token = localStorage.getItem('gc_token')

    // Años disponibles para selector (año actual y 3 anteriores)
    const currentYear = new Date().getFullYear()
    const years = [currentYear, currentYear - 1, currentYear - 2, currentYear - 3].map(String)

    // ── Seed automático del mapeo al montar ─────────────────────
    useEffect(() => {
        if (!token || seeded) return
        fetch(`${API}/reporting/eeff/seed-mapping`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        }).then(() => setSeeded(true)).catch(() => { })
    }, [token, seeded, API])

    // ── Cargar EEFF ─────────────────────────────────────────────
    const loadEeff = useCallback(async () => {
        if (!token) return
        setLoading(true)
        setError(null)
        setData(null)
        try {
            const r = await fetch(`${API}/reporting/eeff/${year}`, {
                headers: { Authorization: `Bearer ${token}` },
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail?.message || d.detail || 'Error al cargar EEFF')
            setData(d)
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }, [token, year, API])

    // ── Auto-cargar al cambiar año ──────────────────────────────
    useEffect(() => {
        if (seeded) loadEeff()
    }, [seeded, year, loadEeff])

    // ─── Tabs ────────────────────────────────────────────────────
    const TABS = [
        { id: 'esf', label: '📊 Situación Financiera', badge: data ? 'ESF' : null },
        { id: 'eri', label: '📈 Resultado Integral', badge: data ? 'ERI' : null },
        { id: 'ecp', label: '🏛️ Cambios en Patrimonio', badge: data ? 'ECP' : null },
        { id: 'efe', label: '💧 Flujos de Efectivo', badge: data ? (data.warnings?.efe_cash_matches === false ? '⚠️' : 'EFE') : null },
        { id: 'map', label: '🗺️ Mapeo NIIF', badge: data?.warnings?.unmapped_accounts?.length > 0 ? `⚠️ ${data.warnings.unmapped_accounts.length}` : null },
        { id: 'not', label: '📋 Notas NIIF', badge: null },
    ]


    // ── Exportar EEFF a Excel (CSV BOM UTF-8 — misma técnica que Balance) ──
    function exportToExcel() {
        if (!data) return
        const fmtAcct = (n) => n != null
            ? Number(n).toLocaleString('es-CR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
            : '0'
        const esf = data.esf || {}
        const eri = data.eri || {}
        const ecp = data.ecp || {}
        const t = esf.totals || {}
        const p = esf.prior_totals || {}
        const te = eri.totals || {}
        const comparLabel = (showCompar && data.prior_year) ? data.prior_year : (parseInt(year) - 1)

        const secRows = (lines = [], prior_lines = []) =>
            (lines || []).map(l => [
                l.code || '',
                l.label || '',
                showCompar ? fmtAcct(l.prior_amount ?? 0) : '',
                fmtAcct(l.amount ?? 0),
            ])

        const sep = (txt) => [txt, '', '', '']
        const head = showCompar
            ? ['CÓDIGO NIIF', 'PARTIDA', `${comparLabel} (CRC)`, `${year} (CRC)`]
            : ['CÓDIGO NIIF', 'PARTIDA', `${year} (CRC)`]

        const rows = [
            [`ESTADOS FINANCIEROS — NIIF PYMES 3ª Ed. (Feb 2025)`],
            [`Entidad: ${data.tenant_name || ''}`, `Año: ${year}`, `Generado: ${new Date().toLocaleDateString('es-CR')}`],
            [],
            // ─── ESF ───────────────────────────────────────────────────────
            ['═══ ESTADO DE SITUACIÓN FINANCIERA ═══'],
            head,
            sep('── ACTIVOS ──'),
            sep('Activo Corriente'),
            ...secRows(esf.activo_corriente),
            ['', 'Total Activo Corriente', showCompar ? fmtAcct(p.total_activo_corriente) : '', fmtAcct(t.total_activo_corriente)],
            sep('Activo No Corriente'),
            ...secRows(esf.activo_no_corriente),
            ['', 'Total Activo No Corriente', showCompar ? fmtAcct(p.total_activo_no_corriente) : '', fmtAcct(t.total_activo_no_corriente)],
            ['', 'TOTAL ACTIVOS', showCompar ? fmtAcct(p.total_activos) : '', fmtAcct(t.total_activos)],
            [],
            sep('── PASIVOS ──'),
            sep('Pasivo Corriente'),
            ...secRows(esf.pasivo_corriente),
            ['', 'Total Pasivo Corriente', showCompar ? fmtAcct(p.total_pasivo_corriente) : '', fmtAcct(t.total_pasivo_corriente)],
            sep('Pasivo No Corriente'),
            ...secRows(esf.pasivo_no_corriente),
            ['', 'Total Pasivo No Corriente', showCompar ? fmtAcct(p.total_pasivo_no_corriente) : '', fmtAcct(t.total_pasivo_no_corriente)],
            ['', 'Total Pasivos', showCompar ? fmtAcct(p.total_pasivos) : '', fmtAcct(t.total_pasivos)],
            [],
            sep('── PATRIMONIO ──'),
            ...secRows(esf.patrimonio),
            ['', 'TOTAL PASIVOS + PATRIMONIO', showCompar ? fmtAcct((p.total_pasivos ?? 0) + (p.total_patrimonio ?? 0)) : '', fmtAcct(t.total_pasivo_patrimonio)],
            [],
            // ─── ERI ───────────────────────────────────────────────────────
            ['═══ ESTADO DE RESULTADO INTEGRAL ═══'],
            head,
            sep('Ingresos de Actividades Ordinarias'),
            ...secRows(eri.ingresos),
            ['', 'Total Ingresos', '', fmtAcct(te.total_ingresos)],
            sep('Costo de Ventas / Servicios'),
            ...secRows(eri.costos),
            ['', 'Total Costo de Ventas', '', fmtAcct(te.total_costo)],
            ['', 'Utilidad Bruta', '', fmtAcct(te.utilidad_bruta)],
            sep('Gastos Operativos'),
            ...secRows(eri.gastos_operativos),
            ['', 'Total Gastos Operativos', '', fmtAcct(te.total_gastos_op)],
            sep('Gastos Financieros'),
            ...secRows(eri.gastos_financieros),
            ['', 'Total Gastos Financieros', '', fmtAcct(te.total_gastos_fin)],
            ['', 'Utilidad antes de Impuestos', '', fmtAcct(te.utilidad_antes_isr)],
            sep('ISR (Sec. 29)'),
            ...secRows(eri.impuesto_renta),
            ['', 'UTILIDAD / PÉRDIDA NETA', '', fmtAcct(te.utilidad_neta)],
        ]

        const csv = '\uFEFF' + rows
            .map(r => (r.length === 0 ? '' : r.slice(0, showCompar ? 4 : 3).map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')))
            .join('\r\n')

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `EEFF_${year}_${data?.tenant_name || 'empresa'}.csv`
        a.click()
        URL.revokeObjectURL(url)
    }

    // ── Imprimir EEFF — ventana HTML propia (igual que Balance) ──────────
    function handlePrint() {
        if (!data) return
        const esf = data.esf || {}
        const eri = data.eri || {}
        const t = esf.totals || {}
        const p = esf.prior_totals || {}
        const te = eri.totals || {}
        const fmtN = (n) => n != null ? Number(n).toLocaleString('es-CR', { minimumFractionDigits: 0 }) : '—'
        const comparLabel = data.prior_year || (parseInt(year) - 1)

        const colHeader = showCompar
            ? `<th class="num">${comparLabel}</th><th class="num">${year}</th>`
            : `<th class="num">${year}</th>`

        const lineRow = (l, color) => {
            const prior = showCompar ? `<td class="num" style="color:#777">${fmtN(l.prior_amount ?? 0)}</td>` : ''
            return `<tr><td style="padding-left:20px;color:${color};font-size:10px">${l.code || ''}</td><td>${l.label || ''}</td>${prior}<td class="num" style="color:${color}">${fmtN(l.amount)}</td></tr>`
        }
        const secHead = (txt, color) => `<tr class="sec-head"><td colspan="${showCompar ? 4 : 3}" style="color:${color}">${txt}</td></tr>`
        const totRow = (txt, prior, curr, color) => {
            const priorCell = showCompar ? `<td class="num" style="font-weight:700;color:#555">${fmtN(prior)}</td>` : ''
            return `<tr class="tot-row"><td></td><td style="font-weight:700;color:${color}">${txt}</td>${priorCell}<td class="num" style="font-weight:700;color:${color}">${fmtN(curr)}</td></tr>`
        }
        const grandRow = (txt, prior, curr) => {
            const priorCell = showCompar ? `<td class="num" style="font-weight:900">${fmtN(prior)}</td>` : ''
            return `<tr class="grand-row"><td></td><td>${txt}</td>${priorCell}<td class="num">${fmtN(curr)}</td></tr>`
        }

        const esfRows = [
            secHead('ACTIVOS', '#166534'),
            secHead('Activo Corriente', '#15803d'),
            ...(esf.activo_corriente || []).map(l => lineRow(l, '#166534')),
            totRow('Total Activo Corriente', p.total_activo_corriente, t.total_activo_corriente, '#166534'),
            secHead('Activo No Corriente', '#15803d'),
            ...(esf.activo_no_corriente || []).map(l => lineRow(l, '#166534')),
            totRow('Total Activo No Corriente', p.total_activo_no_corriente, t.total_activo_no_corriente, '#166534'),
            grandRow('TOTAL ACTIVOS', p.total_activos, t.total_activos),
            `<tr><td colspan="${showCompar ? 4 : 3}" style="height:8px;background:#f5f5f5"></td></tr>`,
            secHead('PASIVOS', '#92400e'),
            secHead('Pasivo Corriente', '#b45309'),
            ...(esf.pasivo_corriente || []).map(l => lineRow(l, '#92400e')),
            totRow('Total Pasivo Corriente', p.total_pasivo_corriente, t.total_pasivo_corriente, '#92400e'),
            secHead('Pasivo No Corriente', '#b45309'),
            ...(esf.pasivo_no_corriente || []).map(l => lineRow(l, '#92400e')),
            totRow('Total Pasivos', p.total_pasivos, t.total_pasivos, '#92400e'),
            `<tr><td colspan="${showCompar ? 4 : 3}" style="height:8px;background:#f5f5f5"></td></tr>`,
            secHead('PATRIMONIO', '#4c1d95'),
            ...(esf.patrimonio || []).map(l => lineRow(l, '#4c1d95')),
            grandRow('TOTAL PASIVOS + PATRIMONIO', (p.total_pasivos ?? 0) + (p.total_patrimonio ?? 0), t.total_pasivo_patrimonio),
        ].join('')

        const eriRows = [
            secHead('Ingresos de Actividades Ordinarias', '#065f46'),
            ...(eri.ingresos || []).map(l => lineRow(l, '#065f46')),
            totRow('Total Ingresos', 0, te.total_ingresos, '#065f46'),
            secHead('Costo de Ventas / Servicios', '#991b1b'),
            ...(eri.costos || []).map(l => lineRow(l, '#991b1b')),
            totRow('Total Costo de Ventas', 0, te.total_costo, '#991b1b'),
            grandRow('Utilidad Bruta', 0, te.utilidad_bruta),
            secHead('Gastos Operativos', '#92400e'),
            ...(eri.gastos_operativos || []).map(l => lineRow(l, '#92400e')),
            totRow('Total Gastos Operativos', 0, te.total_gastos_op, '#92400e'),
            secHead('Gastos Financieros', '#92400e'),
            ...(eri.gastos_financieros || []).map(l => lineRow(l, '#92400e')),
            grandRow('Utilidad antes de Impuestos', 0, te.utilidad_antes_isr),
            secHead('ISR (Sec. 29)', '#374151'),
            ...(eri.impuesto_renta || []).map(l => lineRow(l, '#374151')),
            grandRow(te.utilidad_neta < 0 ? '⬇ PÉRDIDA NETA' : '⬆ UTILIDAD NETA DEL PERÍODO', 0, te.utilidad_neta),
        ].join('')

        const html = `<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<title>Estados Financieros ${year} — NIIF PYMES</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: Arial, sans-serif; font-size: 10px; color: #111; margin: 0; padding: 16px; }
  h1 { font-size: 14px; margin: 0 0 2px; }
  h2 { font-size: 11px; margin: 16px 0 4px; padding: 4px 8px; background: #f3f4f6; border-left: 3px solid #374151; }
  .sub { font-size: 9px; color: #555; margin: 2px 0 10px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 4px; }
  th { background: #e5e7eb; padding: 5px 8px; text-align: left; border: 1px solid #d1d5db; font-size: 9px; }
  th.num { text-align: right; }
  td { padding: 3px 8px; border-bottom: 1px solid #f0f0f0; }
  td.num { text-align: right; }
  .sec-head td { background: #f9fafb; font-weight: 700; font-size: 9px; letter-spacing: 0.05em; text-transform: uppercase; padding: 5px 8px; border-top: 1px solid #ddd; }
  .tot-row td { background: #f3f4f6; }
  .grand-row td { background: #1f2937; color: #fff !important; font-weight: 900; font-size: 11px; padding: 7px 8px; border-top: 2px solid #374151; }
  .check { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 9px; font-weight: 700; }
  .ok { background: #dcfce7; color: #166534; } .err { background: #fee2e2; color: #991b1b; }
  @page { margin: 10mm; size: A4 portrait; }
  .page-break { page-break-before: always; }
</style></head><body>
<h1>📊 Estados Financieros — NIIF PYMES 3ª Ed. (Feb 2025)</h1>
<p class="sub">
  Entidad: <strong>${data.tenant_name || ''}</strong> &nbsp;|&nbsp;
  Período: <strong>Al 31 de diciembre de ${year}</strong> &nbsp;|&nbsp;
  Generado: ${new Date().toLocaleDateString('es-CR')} &nbsp;|&nbsp;
  <span class="${t.balanced ? 'ok check' : 'err check'}">${t.balanced ? '✓ ESF cuadrado (A=P+Pat)' : '✗ ESF desbalanceado'}</span>
  ${showCompar ? `&nbsp;|&nbsp; Comparativo: ${comparLabel} vs ${year}` : ''}
</p>

<h2>⚖️ Estado de Situación Financiera</h2>
<table>
  <thead><tr>
    <th style="width:8%">Código</th>
    <th>Partida</th>
    ${showCompar ? `<th class="num" style="width:18%">${comparLabel} (₡)</th>` : ''}
    <th class="num" style="width:18%">${year} (₡)</th>
  </tr></thead>
  <tbody>${esfRows}</tbody>
</table>

<div class="page-break"></div>
<h2>📈 Estado de Resultado Integral</h2>
<table>
  <thead><tr>
    <th style="width:8%">Código</th>
    <th>Partida</th>
    <th class="num" style="width:18%">${year} (₡)</th>
  </tr></thead>
  <tbody>${eriRows}</tbody>
</table>

<p class="sub" style="margin-top:12px">
  📖 NIIF PYMES Sección 3 (Presentación) · Sección 4 (ESF) · Sección 5 (ERI) · Clasificación corriente/no corriente aplicada
</p>
<script>window.onload = () => { window.print(); }<\/script>
</body></html>`

        const win = window.open('', '_blank', 'width=1000,height=750')
        win.document.write(html)
        win.document.close()
    }

    return (
        <div style={{ padding: '24px', maxWidth: 1100, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>
            <PrintStyleInjector />

            {/* ── Header ──────────────────────────────────────── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 800, color: '#fff' }}>
                        Estados Financieros
                    </h1>
                    {state.tenant && (
                        <div style={{ margin: '4px 0 2px', fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.01em' }}>
                            {state.tenant.nombre}
                            {state.tenant.cedula && (
                                <span style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>
                                    · {state.tenant.cedula}
                                </span>
                            )}
                        </div>
                    )}
                    <p style={{ margin: '2px 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        NIIF PYMES 3ª Edición · Feb 2025 · IASB
                    </p>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
                    {/* ── Fila 1: Año + Comparativo + Generar ── */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        {/* Selector de año */}
                        <select
                            id="eeff-year-select"
                            value={year}
                            onChange={e => setYear(e.target.value)}
                            style={{
                                background: 'var(--bg-card)', color: 'var(--text-primary)',
                                border: '1px solid var(--border)', borderRadius: 8,
                                padding: '7px 12px', fontSize: '0.85rem', cursor: 'pointer',
                            }}
                        >
                            {years.map(y => (
                                <option key={y} value={y}>Año {y}</option>
                            ))}
                        </select>
                        {/* Toggle comparativo N-1 — NIIF Sec. 3.14: siempre visible */}
                        <button
                            id="eeff-comparar-btn"
                            onClick={() => setShowCompar(s => !s)}
                            title={data?.has_prior
                                ? `Comparar con ${data.prior_year}`
                                : `Mostrar columna ${data ? parseInt(data.year || year) - 1 : parseInt(year) - 1} (primer año — valores en cero)`}
                            style={{
                                background: showCompar ? 'rgba(6,182,212,0.15)' : 'var(--bg-card)',
                                border: `1px solid ${showCompar ? 'rgba(6,182,212,0.4)' : 'var(--border)'}`,
                                color: showCompar ? '#06b6d4' : 'var(--text-muted)',
                                borderRadius: 8, padding: '7px 14px',
                                fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer',
                            }}
                        >
                            {showCompar
                                ? (data?.has_prior ? '📊 Comparativo ON' : '📊 Comparativo (primer año)')
                                : '📊 Comparativo'}
                        </button>
                        {/* Botón regenerar */}
                        <button
                            id="eeff-reload-btn"
                            onClick={loadEeff}
                            disabled={loading}
                            style={{
                                background: loading ? 'var(--bg-card)' : 'rgba(139,92,246,0.15)',
                                border: '1px solid rgba(139,92,246,0.35)',
                                color: loading ? 'var(--text-muted)' : '#a78bfa',
                                borderRadius: 8, padding: '7px 16px',
                                fontSize: '0.82rem', fontWeight: 600, cursor: loading ? 'default' : 'pointer',
                            }}
                        >
                            {loading ? '⏳ Calculando...' : '🔄 Generar EEFF'}
                        </button>
                    </div>
                    {/* ── Fila 2: Excel + Imprimir (solo si hay datos) ── */}
                    {data && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <button
                                id="eeff-excel-btn"
                                onClick={exportToExcel}
                                title="Exportar EEFF a Excel (CSV)"
                                style={{
                                    display: 'flex', alignItems: 'center', gap: 5,
                                    padding: '7px 14px', borderRadius: 8, cursor: 'pointer',
                                    fontSize: '0.82rem', fontWeight: 600,
                                    border: '1px solid rgba(34,197,94,0.45)',
                                    background: 'rgba(34,197,94,0.12)',
                                    color: '#22c55e',
                                }}
                            >
                                📥 Excel
                            </button>
                            <button
                                id="eeff-imprimir-btn"
                                onClick={handlePrint}
                                title="Imprimir estados financieros"
                                style={{
                                    display: 'flex', alignItems: 'center', gap: 5,
                                    padding: '7px 14px', borderRadius: 8, cursor: 'pointer',
                                    fontSize: '0.82rem', fontWeight: 600,
                                    border: '1px solid rgba(245,158,11,0.45)',
                                    background: 'rgba(245,158,11,0.12)',
                                    color: '#f59e0b',
                                }}
                            >
                                🖨️ Imprimir
                            </button>
                        </div>
                    )}
                </div>
            </div>

            {/* ── Warning de cuentas sin mapear ───────────────── */}
            {data?.warnings?.unmapped_accounts?.length > 0 && (
                <UnmappedWarning accounts={data.warnings.unmapped_accounts} />
            )}

            {/* ── Error ────────────────────────────────────────── */}
            {error && (
                <div style={{
                    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
                    borderRadius: 10, padding: '12px 16px', marginBottom: 16,
                    color: '#ef4444', fontSize: '0.82rem',
                }}>
                    ❌ {error}
                    {error.includes('SIN_MAPEO_NIIF') && (
                        <div style={{ marginTop: 6, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            → El sistema intentará auto-mapear tu catálogo automáticamente al recargar.
                        </div>
                    )}
                </div>
            )}

            {/* ── Metadatos rápidos ────────────────────────────── */}
            {data && (
                <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
                    {[
                        { label: 'Cuentas en BC', value: data.metadata?.total_accounts_in_tb, color: '#6b7280' },
                        { label: 'Mapeadas', value: data.metadata?.mapped_accounts, color: '#10b981' },
                        { label: 'Sin mapear', value: data.metadata?.unmapped_count, color: data.metadata?.unmapped_count ? '#f59e0b' : '#10b981' },
                        { label: 'Período', value: `${data.from_date} → ${data.to_date}`, color: '#8b5cf6' },
                        { label: 'Edición NIIF', value: data.niif_edition, color: '#06b6d4' },
                    ].map((m, i) => (
                        <div key={i} style={{
                            background: 'var(--bg-card)', border: '1px solid var(--border)',
                            borderRadius: 8, padding: '5px 12px',
                            fontSize: '0.72rem', color: 'var(--text-muted)',
                        }}>
                            {m.label}: <strong style={{ color: m.color }}>{m.value}</strong>
                        </div>
                    ))}
                </div>
            )}

            {/* ── Tabs ─────────────────────────────────────────── */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
                {TABS.map(tab => (
                    <button
                        key={tab.id}
                        id={`eeff-tab-${tab.id}`}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                            padding: '8px 18px',
                            background: activeTab === tab.id ? 'rgba(139,92,246,0.15)' : 'transparent',
                            border: 'none',
                            borderBottom: activeTab === tab.id ? '2px solid #8b5cf6' : '2px solid transparent',
                            color: activeTab === tab.id ? '#a78bfa' : 'var(--text-muted)',
                            fontWeight: activeTab === tab.id ? 700 : 400,
                            fontSize: '0.82rem', cursor: 'pointer',
                            borderRadius: '8px 8px 0 0',
                            display: 'flex', alignItems: 'center', gap: 6,
                            transition: 'all 0.15s',
                        }}
                    >
                        {tab.label}
                        {tab.badge && (
                            <span style={{
                                fontSize: '0.6rem', padding: '1px 6px', borderRadius: 10,
                                background: 'rgba(139,92,246,0.2)', color: '#c4b5fd',
                            }}>
                                {tab.badge}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* ── Contenido del Tab ────────────────────────────── */}
            <div id="eeff-tab-content">
                {loading && (
                    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                        <div style={{ fontSize: '2rem', marginBottom: 12 }}>⏳</div>
                        Calculando estados financieros desde el balance de comprobación...
                    </div>
                )}

                {!loading && !data && !error && (
                    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                        <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📊</div>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>Lista para generar</div>
                        <div style={{ fontSize: '0.82rem' }}>Presiona "Generar EEFF" para calcular los estados financieros del año {year}</div>
                    </div>
                )}

                {!loading && data && activeTab === 'esf' && (
                    <TabESF esf={data.esf} year={year} priorYear={data.prior_year} showCompar={showCompar} />
                )}
                {!loading && data && activeTab === 'eri' && (
                    <TabERI eri={data.eri} year={year} priorYear={data.prior_year} showCompar={showCompar} />
                )}
                {!loading && data && activeTab === 'ecp' && (
                    <TabECP ecp={data.ecp} year={year} />
                )}
                {!loading && data && activeTab === 'efe' && (
                    <TabEFE efe={data.efe} efePrior={data.efe_prior}
                        year={year} priorYear={data.prior_year} showCompar={showCompar} />
                )}

                {activeTab === 'map' && (
                    <TabMapeo tenantId={state.tenant?.id} apiBase={API} token={token} />
                )}
                {activeTab === 'not' && (
                    <TabNotas data={data} />
                )}
            </div>
        </div>
    )
}
