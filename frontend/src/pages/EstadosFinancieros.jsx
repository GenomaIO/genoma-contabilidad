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
    body { background: #fff !important; color: #000 !important; }
    nav, aside, header, .no-print, button, select { display: none !important; }
    #eeff-tab-content { display: block !important; }
    table { page-break-inside: avoid; }
    @page { margin: 1.5cm; size: A4; }
    .print-page-break { page-break-before: always; }
    tr { page-break-inside: avoid; }
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
                {/* Monto N-1 (comparativo) */}
                {showCompar && (
                    <td style={{
                        padding: '6px 8px', textAlign: 'right',
                        fontFamily: 'monospace', fontSize: '0.75rem',
                        color: 'var(--text-muted)', whiteSpace: 'nowrap',
                        borderRight: '1px solid rgba(255,255,255,0.06)',
                    }}>
                        {priorAmount !== undefined ? fmt(priorAmount) : '—'}
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
    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Al 31 de diciembre de {year}
                </span>
                <BalanceCheck balanced={t.balanced} difference={t.difference} />
            </div>

            {/* Tabla */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                {/* Columna ACTIVOS */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    <div style={{ padding: '12px 14px', background: `${COLORS.activo}15`, borderBottom: `1px solid ${COLORS.activo}30`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 800, fontSize: '0.8rem', color: COLORS.activo }}>ACTIVOS</span>
                        <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
                            {showCompar && <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{priorYear}: {fmt(p.total_activos)}</span>}
                            <span style={{ fontFamily: 'monospace', fontWeight: 700, color: COLORS.activo }}>{year}: {fmt(t.total_activos)}</span>
                        </div>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <StatementSection
                            title="Activo Corriente" color={COLORS.activo}
                            lines={esf.activo_corriente}
                            total={t.total_activo_corriente}
                            totalLabel="Total Activo Corriente"
                            showCompar={showCompar}
                            priorTotal={p?.total_activo_corriente}
                        />
                        <StatementSection
                            title="Activo No Corriente" color={COLORS.activo}
                            lines={esf.activo_no_corriente}
                            total={t.total_activo_no_corriente}
                            totalLabel="Total Activo No Corriente"
                            showCompar={showCompar}
                            priorTotal={p?.total_activo_no_corriente}
                        />
                    </table>
                </div>

                {/* Columna PASIVOS + PATRIMONIO */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)', flex: 1 }}>
                        <div style={{ padding: '12px 14px', background: `${COLORS.pasivo}15`, borderBottom: `1px solid ${COLORS.pasivo}30` }}>
                            <span style={{ fontWeight: 800, fontSize: '0.8rem', color: COLORS.pasivo }}>PASIVOS</span>
                            <span style={{ float: 'right', fontFamily: 'monospace', fontWeight: 700, color: COLORS.pasivo }}>
                                {fmt(t.total_pasivos)}
                            </span>
                        </div>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <StatementSection
                                title="Pasivo Corriente" color={COLORS.pasivo}
                                lines={esf.pasivo_corriente}
                                total={t.total_pasivo_corriente}
                                totalLabel="Total Pasivo Corriente"
                            />
                            <StatementSection
                                title="Pasivo No Corriente" color={COLORS.pasivo}
                                lines={esf.pasivo_no_corriente}
                                total={t.total_pasivo_no_corriente}
                                totalLabel="Total Pasivo No Corriente"
                            />
                        </table>
                    </div>

                    <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                        <div style={{ padding: '12px 14px', background: `${COLORS.patrimonio}15`, borderBottom: `1px solid ${COLORS.patrimonio}30` }}>
                            <span style={{ fontWeight: 800, fontSize: '0.8rem', color: COLORS.patrimonio }}>PATRIMONIO</span>
                            <span style={{ float: 'right', fontFamily: 'monospace', fontWeight: 700, color: COLORS.patrimonio }}>
                                {fmt(t.total_patrimonio)}
                            </span>
                        </div>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <StatementSection
                                title="Patrimonio" color={COLORS.patrimonio}
                                lines={esf.patrimonio}
                            />
                        </table>
                    </div>

                    {/* Check total P+Pat */}
                    <div style={{
                        background: 'var(--bg-card)', borderRadius: 10,
                        padding: '10px 14px', border: '1px solid var(--border)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    }}>
                        <span style={{ fontSize: '0.78rem', fontWeight: 800, color: '#fff' }}>
                            TOTAL PASIVOS + PATRIMONIO
                        </span>
                        <span style={{ fontFamily: 'monospace', fontWeight: 800, color: '#fff', fontSize: '0.85rem' }}>
                            {fmt(t.total_pasivo_patrimonio)}
                        </span>
                    </div>
                </div>
            </div>

            {/* Nota NIIF */}
            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 8, background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                📖 NIIF PYMES 3ª Ed. (Feb 2025) · Sección 4 · Clasificación Corriente/No Corriente · Haga clic en una partida para ver el detalle de cuentas
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

            <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)', maxWidth: 600 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <StatementSection title="Ingresos de Actividades Ordinarias"
                        color={COLORS.ingreso} lines={eri.ingresos}
                        total={t.total_ingresos} totalLabel="Total Ingresos" />

                    <StatementSection title="Costo de Ventas / Servicios"
                        color={COLORS.costo} lines={eri.costos}
                        total={t.total_costo} totalLabel="Total Costo de Ventas" />

                    {/* Utilidad Bruta */}
                    <tbody>
                        <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                            <td style={{ padding: '7px 8px', fontWeight: 800, fontSize: '0.8rem', color: '#fff' }}>
                                Utilidad Bruta
                            </td>
                            <td style={{ padding: '7px 12px 7px 8px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, fontSize: '0.82rem', color: isNeg(t.utilidad_bruta) ? '#ef4444' : '#10b981' }}>
                                {fmt(t.utilidad_bruta)}
                            </td>
                        </tr>
                        <tr><td colSpan={2} style={{ height: 4 }} /></tr>
                    </tbody>

                    <StatementSection title="Gastos Operativos"
                        color={COLORS.gasto} lines={eri.gastos_operativos}
                        total={t.total_gastos_op} totalLabel="Total Gastos Operativos" />

                    <StatementSection title="Gastos Financieros"
                        color={COLORS.gasto} lines={eri.gastos_financieros}
                        total={t.total_gastos_fin} totalLabel="Total Gastos Financieros" />

                    {/* UAI */}
                    <tbody>
                        <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                            <td style={{ padding: '7px 8px', fontWeight: 800, fontSize: '0.8rem', color: '#fff' }}>
                                Utilidad antes de impuestos
                            </td>
                            <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, fontSize: '0.82rem', color: isNeg(t.utilidad_antes_isr) ? '#ef4444' : COLORS.ingreso }}>
                                {fmt(t.utilidad_antes_isr)}
                            </td>
                        </tr>
                        <tr><td colSpan={2} style={{ height: 4 }} /></tr>
                    </tbody>

                    <StatementSection title="Impuesto sobre la Renta (Sec. 29)"
                        color={COLORS.isr} lines={eri.impuesto_renta}
                        total={t.total_isr} totalLabel="Total ISR" />

                    {/* Utilidad Neta */}
                    <tbody>
                        <tr style={{ background: isLoss ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.08)', borderTop: '2px solid rgba(255,255,255,0.15)' }}>
                            <td style={{ padding: '10px 8px', fontWeight: 800, fontSize: '0.85rem', color: '#fff' }}>
                                {isLoss ? '📉 PÉRDIDA NETA DEL PERÍODO' : '📈 UTILIDAD NETA DEL PERÍODO'}
                            </td>
                            <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, fontSize: '0.9rem', color: isLoss ? '#ef4444' : '#10b981' }}>
                                {fmt(un)}
                            </td>
                        </tr>
                    </tbody>

                    {/* ORI — Otro Resultado Integral (3ª Ed. Sec. 5.4) */}
                    {(eri.otro_resultado?.length > 0) && (
                        <>
                            <StatementSection title="Otro Resultado Integral (ORI — Sec. 5.4 NIIF 3ªEd.)"
                                color={COLORS.patrimonio} lines={eri.otro_resultado}
                                total={t.total_ori} totalLabel="Total ORI" />
                            <tbody>
                                <tr style={{ background: 'rgba(139,92,246,0.08)', borderTop: '2px solid rgba(255,255,255,0.15)' }}>
                                    <td style={{ padding: '10px 8px', fontWeight: 800, fontSize: '0.85rem', color: '#fff' }}>
                                        TOTAL RESULTADO INTEGRAL
                                    </td>
                                    <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 800, fontSize: '0.9rem', color: COLORS.patrimonio }}>
                                        {fmt(t.total_resultado_integral)}
                                    </td>
                                </tr>
                            </tbody>
                        </>
                    )}
                </table>
            </div>

            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 8, background: 'rgba(139,92,246,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
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
function TabEFE({ efe, year }) {
    if (!efe) return <div style={{ color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>Sin datos EFE</div>
    const c = efe.conciliacion || {}
    const cashOk = c.efe_cash_matches

    function EfeSection({ title, section, color, icon }) {
        const items = (section?.items || []).filter(i => i.amount !== 0)
        return (
            <div style={{ marginBottom: 12 }}>
                <div style={{ padding: '8px 14px', background: `${color}15`, borderLeft: `3px solid ${color}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 800, fontSize: '0.78rem', color }}>{icon} {title}</span>
                    <span style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: '0.82rem', color: section?.total < 0 ? '#ef4444' : color }}>
                        {fmt(section?.total)}
                    </span>
                </div>
                <div style={{ paddingLeft: 3 }}>
                    {items.map((item, i) => (
                        <div key={i} style={{
                            display: 'flex', justifyContent: 'space-between',
                            padding: '5px 14px', fontSize: '0.78rem',
                            borderBottom: '1px solid rgba(255,255,255,0.03)',
                            color: 'var(--text-secondary)',
                        }}>
                            <span>{item.label}</span>
                            <span style={{ fontFamily: 'monospace', color: item.amount < 0 ? '#ef4444' : item.amount > 0 ? '#10b981' : 'var(--text-muted)' }}>
                                {item.amount > 0 ? '+' : ''}{fmt(item.amount)}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Método Indirecto · {efe.niif_ref}</span>
                <div id="efe-cash-check" style={{
                    padding: '4px 14px', borderRadius: 20, fontSize: '0.72rem', fontWeight: 700,
                    background: cashOk ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                    border: `1px solid ${cashOk ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                    color: cashOk ? '#10b981' : '#ef4444',
                }}>
                    {cashOk ? '✅ Efectivo cuadra (EFE = ESF.AC.01)' : `❌ Diferencia: ${fmt(c.diferencia)}`}
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16, alignItems: 'start' }}>
                {/* Columna izquierda: Actividades */}
                <div style={{ background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    <EfeSection title="Actividades de Operación" section={efe.operacion} color='#10b981' icon='⚙️' />
                    <EfeSection title="Actividades de Inversión" section={efe.inversion} color='#f59e0b' icon='🔧' />
                    <EfeSection title="Actividades de Financiación" section={efe.financiacion} color='#8b5cf6' icon='💰' />
                </div>

                {/* Columna derecha: Conciliación */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ background: 'var(--bg-card)', borderRadius: 12, border: '1px solid var(--border)', overflow: 'hidden' }}>
                        <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderBottom: '1px solid var(--border)' }}>
                            <span style={{ fontWeight: 800, fontSize: '0.78rem', color: '#fff' }}>Conciliación de Efectivo</span>
                        </div>
                        {[
                            { label: 'Efectivo inicial', value: c.efectivo_inicial, color: 'var(--text-secondary)' },
                            { label: '+ Flujo Operación', value: c.total_actividades_operacion, color: '#10b981' },
                            { label: '+ Flujo Inversión', value: c.total_actividades_inversion, color: '#f59e0b' },
                            { label: '+ Flujo Financiación', value: c.total_actividades_financiacion, color: '#8b5cf6' },
                            { label: 'Cambio neto', value: c.cambio_neto_efectivo, color: '#06b6d4', bold: true },
                            { label: 'Efectivo final (EFE)', value: c.efectivo_final_calculado, color: '#fff', bold: true },
                            { label: 'Efectivo en Balance (ESF)', value: c.efectivo_final_esf, color: '#fff', bold: true },
                        ].map((row, i) => (
                            <div key={i} style={{
                                display: 'flex', justifyContent: 'space-between',
                                padding: '5px 14px', borderBottom: '1px solid rgba(255,255,255,0.04)',
                                background: row.bold ? 'rgba(255,255,255,0.03)' : 'transparent',
                            }}>
                                <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>{row.label}</span>
                                <span style={{ fontSize: '0.73rem', fontFamily: 'monospace', fontWeight: row.bold ? 700 : 400, color: row.value < 0 ? '#ef4444' : row.color }}>
                                    {fmt(row.value)}
                                </span>
                            </div>
                        ))}
                    </div>

                    {/* Conciliación pasivos financiación — Sec. 7.14 3ªEd. */}
                    <div style={{ background: 'var(--bg-card)', borderRadius: 12, border: '1px solid var(--border)', overflow: 'hidden' }}>
                        <div style={{ padding: '10px 14px', background: 'rgba(139,92,246,0.06)', borderBottom: '1px solid var(--border)' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.72rem', color: '#8b5cf6' }}>Pasivos de Financiación (Sec. 7.14)</span>
                        </div>
                        {(efe.conciliacion_pasivos_fin || []).map((row, i) => (
                            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 14px', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{row.label}</span>
                                <span style={{ fontSize: '0.7rem', fontFamily: 'monospace', color: row.amount < 0 ? '#ef4444' : 'var(--text-secondary)' }}>{fmt(row.amount)}</span>
                            </div>
                        ))}
                    </div>

                    {efe.warnings?.length > 0 && (
                        <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '8px 12px' }}>
                            {efe.warnings.map((w, i) => <div key={i} style={{ fontSize: '0.75rem', color: '#ef4444' }}>{w}</div>)}
                        </div>
                    )}
                </div>
            </div>

            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 8, background: 'rgba(16,185,129,0.07)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
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
                    {/* Toggle comparativo N-1 */}
                    {data?.has_prior && (
                        <button
                            id="eeff-comparar-btn"
                            onClick={() => setShowCompar(s => !s)}
                            style={{
                                background: showCompar ? 'rgba(6,182,212,0.15)' : 'var(--bg-card)',
                                border: `1px solid ${showCompar ? 'rgba(6,182,212,0.4)' : 'var(--border)'}`,
                                color: showCompar ? '#06b6d4' : 'var(--text-muted)',
                                borderRadius: 8, padding: '7px 14px',
                                fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer',
                            }}
                        >
                            {showCompar ? '📊 Comparativo ON' : '📊 Comparativo'}
                        </button>
                    )}
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
                    {/* Botón Imprimir */}
                    {data && (
                        <button
                            id="eeff-imprimir-btn"
                            onClick={() => window.print()}
                            style={{
                                background: 'rgba(245,158,11,0.1)',
                                border: '1px solid rgba(245,158,11,0.3)',
                                color: '#f59e0b', borderRadius: 8,
                                padding: '7px 14px', fontSize: '0.8rem',
                                fontWeight: 600, cursor: 'pointer',
                            }}
                        >
                            🖨️ Imprimir
                        </button>
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
                    <TabESF esf={data.esf} year={year} priorYear={data.prior_year} showCompar={data.has_prior && showCompar} />
                )}
                {!loading && data && activeTab === 'eri' && (
                    <TabERI eri={data.eri} year={year} priorYear={data.prior_year} showCompar={data.has_prior && showCompar} />
                )}
                {!loading && data && activeTab === 'ecp' && (
                    <TabECP ecp={data.ecp} year={year} />
                )}
                {!loading && data && activeTab === 'efe' && (
                    <TabEFE efe={data.efe} year={year} />
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
