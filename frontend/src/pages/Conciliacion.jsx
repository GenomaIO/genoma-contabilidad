import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useApp } from '../context/AppContext'
import * as pdfjsLib from 'pdfjs-dist'

// Worker de pdf.js — debe apuntar al archivo del paquete instalado
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url
).href

const API = import.meta.env.VITE_API_URL || ''
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

/* ── Estado del período post-cierre ───────────────────────────────── */
function getPeriodStatus(period) {
    if (!period || period.length < 6) return 'DESCONOCIDO'
    const year = parseInt(period.slice(0, 4))
    const month = parseInt(period.slice(4, 6))
    if (isNaN(year) || isNaN(month)) return 'DESCONOCIDO'
    const today = new Date()
    const curY = today.getFullYear()
    const curM = today.getMonth() + 1
    const curD = today.getDate()
    if (year > curY || (year === curY && month > curM)) return 'FUTURO'
    if (year === curY && month === curM) return 'ABIERTO'
    const diff = (curY - year) * 12 + (curM - month)
    if (diff === 1 && curD <= 10) return 'RECIENTE'  // D-270 aún en plazo
    return 'CERRADO'
}

const PERIOD_BANNER = {
    FUTURO: {
        bg: 'rgba(148,163,184,0.12)', border: '#94a3b8', color: '#475569',
        emoji: '📅',
        titulo: 'Período futuro',
        texto: 'Este período aún no ha iniciado. Puedes preparar la conciliación con anticipación.',
        acciones: [],
    },
    ABIERTO: {
        bg: 'rgba(34,197,94,0.08)', border: '#16a34a', color: '#15803d',
        emoji: '🟢',
        titulo: 'Período abierto — Ventana óptima',
        texto: 'Estás en el momento ideal. Podés emitir FE faltantes, crear asientos y corregir todo antes del cierre.',
        acciones: ['✅ Emitir FE faltantes (aún en período corriente)', '✅ Crear asientos correctivos', '✅ Configurar Bank Rules para el futuro'],
    },
    RECIENTE: {
        bg: 'rgba(251,191,36,0.10)', border: '#d97706', color: '#b45309',
        emoji: '🟡',
        titulo: 'Período cerrado — D-270 aún en plazo',
        texto: 'El mes ya cerró pero el plazo para presentar la D-270 no ha vencido (día 10 del mes siguiente).',
        acciones: ['✅ Ver score CENTINELA (solo lectura)', '✅ Exportar D-270 → subir a Tribu-CR ANTES del día 10', '⚠️ Emitir FE extemporánea previo análisis con tu contador', '❌ No se pueden agregar asientos al período cerrado'],
    },
    CERRADO: {
        bg: 'rgba(239,68,68,0.08)', border: '#dc2626', color: '#b91c1c',
        emoji: '🔴',
        titulo: 'Período cerrado — Revisión preventiva',
        texto: 'El período está cerrado y el plazo D-270 venció. Esta revisión es preventiva para identificar patrones y corregir en el período actual.',
        acciones: ['✅ Score CENTINELA como referencia histórica', '✅ Identificar patrones para NO repetir', '⚠️ FE extemporánea posible con multa (consultar norma)', '❌ D-270 fuera de plazo ordinario — aplica D-270 extemporánea'],
    },
    DESCONOCIDO: {
        bg: 'var(--bg-secondary)', border: 'var(--border)', color: 'var(--text-muted)',
        emoji: 'ℹ️', titulo: 'Ingresa un período válido', texto: 'Escribe el período en formato YYYYMM (ej: 202601 = enero 2026).', acciones: [],
    },
}

function PeriodBanner({ period }) {
    const [open, setOpen] = React.useState(true)
    const status = getPeriodStatus(period)
    const cfg = PERIOD_BANNER[status] || PERIOD_BANNER.DESCONOCIDO
    if (status === 'ABIERTO' && !open) return null
    return (
        <div style={{
            border: `1px solid ${cfg.border}40`,
            background: cfg.bg, borderRadius: 10,
            padding: '12px 16px', marginBottom: 18,
            display: 'flex', gap: 12, alignItems: 'flex-start',
        }}>
            <div style={{ fontSize: '1.3rem', flexShrink: 0 }}>{cfg.emoji}</div>
            <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', color: cfg.color, marginBottom: 3 }}>
                    {cfg.titulo}
                </div>
                <div style={{ fontSize: '0.78rem', color: cfg.color, opacity: 0.85, marginBottom: cfg.acciones.length ? 8 : 0 }}>
                    {cfg.texto}
                </div>
                {cfg.acciones.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.75rem', color: cfg.color, opacity: 0.8 }}>
                        {cfg.acciones.map((a, i) => <li key={i} style={{ marginBottom: 2 }}>{a}</li>)}
                    </ul>
                )}
            </div>
            <button onClick={() => setOpen(false)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: cfg.color, fontSize: '1rem', opacity: 0.5, flexShrink: 0, padding: 0,
            }}>✕</button>
        </div>
    )
}

function authH(token) {
    return { Authorization: `Bearer ${token}` }
}
function authJ(token) {
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
}
function formatCRC(n) {
    if (n == null || isNaN(n)) return '₡0'
    return '₡' + Number(n).toLocaleString('es-CR', { minimumFractionDigits: 0 })
}
function currentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}

/* ── Semáforo de estado ──────────────────────────────────────────────── */
const ESTADO_COLOR = {
    CONCILIADO: { bg: 'rgba(34,197,94,0.12)', color: '#16a34a', label: '✅ Conciliado' },
    PROBABLE: { bg: 'rgba(251,191,36,0.15)', color: '#d97706', label: '🟡 Probable' },
    SIN_ASIENTO: { bg: 'rgba(239,68,68,0.12)', color: '#dc2626', label: '🔴 Sin asiento' },
    SOLO_LIBROS: { bg: 'rgba(139,92,246,0.12)', color: '#7c3aed', label: '🟣 Solo libros' },
    PENDIENTE: { bg: 'rgba(148,163,184,0.15)', color: '#64748b', label: '⏳ Pendiente' },
}
function Badge({ estado }) {
    const cfg = ESTADO_COLOR[estado] || ESTADO_COLOR.PENDIENTE
    return (
        <span style={{
            fontSize: '0.72rem', fontWeight: 700, padding: '3px 8px',
            borderRadius: 20, background: cfg.bg, color: cfg.color,
            whiteSpace: 'nowrap',
        }}>
            {cfg.label}
        </span>
    )
}

/* ── Tabla de transacciones ──────────────────────────────────────────── */
function TxnTable({ txns, onApprove }) {
    const [filter, setFilter] = useState('TODOS')

    const filtered = filter === 'TODOS' ? txns
        : txns.filter(t => t.match_estado === filter || (!t.match_estado && filter === 'PENDIENTE'))

    const tabs = [
        { k: 'TODOS', label: 'Todos', color: 'var(--text-secondary)' },
        { k: 'CONCILIADO', label: '✅ Conciliados', color: '#16a34a' },
        { k: 'PROBABLE', label: '🟡 Probables', color: '#d97706' },
        { k: 'SIN_ASIENTO', label: '🔴 Sin asiento', color: '#dc2626' },
    ]

    return (
        <div>
            {/* Pestañas */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                {tabs.map(t => (
                    <button key={t.k} onClick={() => setFilter(t.k)} style={{
                        ...btnChoice,
                        background: filter === t.k ? 'var(--bg-3)' : 'transparent',
                        color: filter === t.k ? t.color : 'var(--text-muted)',
                        borderColor: filter === t.k ? t.color : 'transparent',
                        fontSize: '0.78rem',
                    }}>
                        {t.label}
                        <span style={{ marginLeft: 5, opacity: 0.7 }}>
                            ({txns.filter(tx => t.k === 'TODOS' || tx.match_estado === t.k).length})
                        </span>
                    </button>
                ))}
            </div>

            {/* Tabla */}
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                    <thead>
                        <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                            <th style={th}>Fecha</th>
                            <th style={th}>Descripción</th>
                            <th style={{ ...th, textAlign: 'right' }}>Monto</th>
                            <th style={th}>Moneda</th>
                            <th style={th}>Tel.</th>
                            <th style={th}>Estado</th>
                            <th style={th}>Conf.</th>
                            <th style={th}>Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.length === 0 ? (
                            <tr>
                                <td colSpan={8} style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)' }}>
                                    Sin transacciones en esta categoría
                                </td>
                            </tr>
                        ) : filtered.map((t, i) => (
                            <tr key={t.id || i} style={{
                                borderBottom: '1px solid var(--border)',
                                background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)',
                            }}>
                                <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                                    {t.fecha}
                                </td>
                                <td style={{ ...td, maxWidth: 280 }}>
                                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {t.descripcion}
                                    </div>
                                    {t.fuga_tipo && (
                                        <div style={{ fontSize: '0.7rem', color: '#dc2626', marginTop: 2 }}>
                                            ⚠️ Fuga tipo {t.fuga_tipo}
                                        </div>
                                    )}
                                </td>
                                <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                                    <span style={{ color: t.tipo === 'CR' ? '#16a34a' : '#dc2626' }}>
                                        {t.tipo === 'CR' ? '+' : '-'}{formatCRC(t.monto_crc || t.monto)}
                                    </span>
                                    {t.monto_orig_usd && (
                                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                            ${t.monto_orig_usd} @{t.tc_bccr}
                                        </div>
                                    )}
                                </td>
                                <td style={{ ...td, textAlign: 'center' }}>
                                    <span style={{
                                        fontSize: '0.72rem', padding: '2px 6px', borderRadius: 4,
                                        background: t.moneda === 'USD' ? 'rgba(59,130,246,0.15)' : 'transparent',
                                        color: t.moneda === 'USD' ? '#3b82f6' : 'var(--text-muted)',
                                    }}>
                                        {t.moneda || 'CRC'}
                                    </span>
                                </td>
                                <td style={{ ...td, color: '#7c3aed', fontSize: '0.75rem' }}>
                                    {t.telefono && `📞 ${t.telefono}`}
                                </td>
                                <td style={td}>
                                    <Badge estado={t.match_estado || 'PENDIENTE'} />
                                </td>
                                <td style={{ ...td, textAlign: 'center' }}>
                                    {t.match_confianza > 0 && (
                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                            {t.match_confianza}%
                                        </span>
                                    )}
                                </td>
                                <td style={td}>
                                    {t.match_estado === 'SIN_ASIENTO' && (
                                        <button
                                            onClick={() => onApprove(t)}
                                            style={{ ...btnPrimary, fontSize: '0.72rem', padding: '3px 8px' }}
                                        >
                                            + Asiento
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

/* ── Estadísticas de la conciliación ────────────────────────────────── */
function StatsBar({ stats, saldoDiff }) {
    if (!stats) return null
    const items = [
        { label: 'Total banco', value: stats.total_banco, color: 'var(--text-primary)' },
        { label: 'Conciliados', value: stats.conciliados, color: '#16a34a' },
        { label: 'Probables', value: stats.probables, color: '#d97706' },
        { label: 'Sin asiento', value: stats.sin_asiento, color: '#dc2626' },
        { label: 'Solo libros', value: stats.solo_libros, color: '#7c3aed' },
    ]
    return (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            {items.map(it => (
                <div key={it.label} style={{
                    flex: 1, minWidth: 100, background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px', textAlign: 'center',
                }}>
                    <div style={{ fontSize: '1.6rem', fontWeight: 800, color: it.color }}>{it.value}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>{it.label}</div>
                </div>
            ))}
            {saldoDiff && (
                <div style={{
                    flex: 2, minWidth: 200, background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px',
                }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>Diferencia saldo</div>
                    <div style={{ fontWeight: 700, color: saldoDiff.estado === 'CUADRADO' ? '#16a34a' : '#dc2626' }}>
                        {saldoDiff.observacion}
                    </div>
                </div>
            )}
        </div>
    )
}

/* ── Upload de archivo ───────────────────────────────────────────────── */
function FileUploader({ token, onTransacciones, onPeriodChange }) {
    const [banco, setBanco] = useState('')
    const [period, setPeriod] = useState(currentPeriod())
    const [entidades, setEntidades] = useState([])
    const [files, setFiles] = useState([])          // ← array multi-archivo
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)
    const fileRef = useRef()

    useEffect(() => {
        fetch(`${API}/conciliacion/entidades`, { headers: authH(token) })
            .then(r => r.json())
            .then(d => {
                setEntidades(d.entidades || [])
                if (d.entidades?.length > 0) setBanco(d.entidades[0].clave)
            })
            .catch(() => { })
    }, [token])

    function handleFile(e) {
        const f = Array.from(e.target.files || [])
        if (!f.length) return
        setFiles(f)
        setMsg(null)
    }

    // Procesa UN archivo y retorna su resultado estándar
    async function parsearArchivo(file, idx, total) {
        const fname = file.name.toLowerCase()
        if (total > 1) {
            setMsg({ ok: true, text: `⏳ Procesando ${idx + 1}/${total}: ${file.name}` })
        }

        if (fname.endsWith('.csv') || fname.endsWith('.txt')) {
            const text = await file.text()
            const r = await fetch(`${API}/conciliacion/parse`, {
                method: 'POST',
                headers: authJ(token),
                body: JSON.stringify({ text, banco }),
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error CSV: ${file.name}`)
            return d
        }

        if (fname.endsWith('.pdf')) {
            // PDF → pdfplumber en el backend (tablas BN correctamente)
            // pdf.js client-side desordena columnas de tablas → 0 txns
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/parse-file`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error PDF: ${file.name}`)
            return d
        }

        if (fname.endsWith('.xlsx') || fname.endsWith('.xls')) {
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/parse-file`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error Excel: ${file.name}`)
            return d
        }

        if (fname.match(/\.(jpg|jpeg|png|webp)$/)) {
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/ocr-image`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error OCR: ${file.name}`)
            return d
        }

        throw new Error(`Formato no soportado: ${file.name}`)
    }

    async function parsear() {
        if (!files.length || !banco) {
            setMsg({ ok: false, text: 'Selecciona banco y al menos un archivo' })
            return
        }
        setLoading(true); setMsg(null)
        try {
            // Procesar todos los archivos secuencialmente
            let todosLasTxns = []
            let todosPeriodos = new Set()
            let saldoInicial = 0, saldoFinal = 0
            let usaGemini = false
            const errores = []

            for (let i = 0; i < files.length; i++) {
                try {
                    const d = await parsearArchivo(files[i], i, files.length)
                    todosLasTxns = todosLasTxns.concat(d.transacciones || [])
                        ; (d.periodos_detectados || []).forEach(p => todosPeriodos.add(p))
                    if (i === 0) saldoInicial = d.saldo_inicial || 0
                    saldoFinal = d.saldo_final || saldoFinal
                    if (d.fuente === 'gemini-vision') usaGemini = true
                } catch (err) {
                    errores.push(`${files[i].name}: ${err.message}`)
                }
            }

            // Deduplicar: misma fecha + mismo monto + misma descripción = duplicado
            const seen = new Set()
            const txnsFusionadas = todosLasTxns.filter(t => {
                const key = `${t.fecha}|${t.monto}|${t.descripcion?.slice(0, 60)}`
                if (seen.has(key)) return false
                seen.add(key)
                return true
            })

            // Ordenar por fecha
            txnsFusionadas.sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''))

            const periodosStr = [...todosPeriodos].sort().join(', ')
            const fuenteStr = usaGemini ? ' (OCR Gemini ✨)' : ''
            const errorStr = errores.length ? ` | ⚠️ ${errores.length} error(es)` : ''

            if (txnsFusionadas.length === 0) {
                // 0 txns: nunca avanzar al Paso 2, mostrar advertencia clara
                const errMsg = errores.length
                    ? `Error procesando archivos: ${errores.join('; ')}`
                    : `⚠️ Se procesaron ${files.length} archivo(s) pero no se encontraron transacciones. ` +
                    `Verifica que el banco seleccionado (${banco}) coincide con el archivo cargado.`
                setMsg({ ok: false, text: errMsg })
            } else {
                setMsg({
                    ok: true,
                    text: `✅ ${txnsFusionadas.length} transacciones de ${files.length} archivo(s)${fuenteStr} | Períodos: ${periodosStr || period}${errorStr}`,
                })
                onTransacciones(txnsFusionadas, banco, period, saldoInicial, saldoFinal)
            }


        } catch (e) {
            setMsg({ ok: false, text: String(e.message || e) })
        }
        setLoading(false)
    }

    const tipoEntidad = banco
        ? (entidades.find(e => e.clave === banco)?.tipo || '')
        : ''

    return (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            {/* Banco */}
            <div>
                <label style={labelStyle}>Entidad bancaria</label>
                <select value={banco} onChange={e => setBanco(e.target.value)} style={inputStyle}>
                    <optgroup label="── Estatales">
                        {entidades.filter(e => e.tipo === 'Estatal').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Privados">
                        {entidades.filter(e => e.tipo === 'Privado').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Cooperativas">
                        {entidades.filter(e => e.tipo === 'Cooperativa').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Financieras">
                        {entidades.filter(e => e.tipo === 'Financiera').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                </select>
                {tipoEntidad && (
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                        {tipoEntidad}
                    </div>
                )}
            </div>

            {/* Período */}
            <div>
                <label style={labelStyle}>Período (YYYYMM)</label>
                <input
                    type="text"
                    placeholder="202601"
                    value={period}
                    onChange={e => {
                        const v = e.target.value
                        setPeriod(v)
                        if (onPeriodChange && v.length === 6) onPeriodChange(v)
                    }}
                    maxLength={6}
                    style={inputStyle}
                />
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {period?.length === 6
                        ? `${MESES[parseInt(period.slice(4, 6)) - 1]} ${period.slice(0, 4)}`
                        : 'Ej: 202601 = enero 2026'
                    }
                </div>
            </div>

            {/* Archivo — drop zone multi-select */}
            <div>
                <label style={labelStyle}>Estado de cuenta</label>
                <div style={{
                    border: '2px dashed var(--border)', borderRadius: 10,
                    padding: '18px', textAlign: 'center', cursor: 'pointer',
                    background: files.length ? 'rgba(34,197,94,0.05)' : 'var(--bg-secondary)',
                    transition: 'all 0.2s',
                }} onClick={() => fileRef.current?.click()}>
                    <div style={{ fontSize: '1.5rem', marginBottom: 4 }}>
                        {files.length ? '📂' : '📂'}
                    </div>
                    {files.length === 0 ? (
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                            CSV, XLSX, PDF o imagen<br />
                            <span style={{ fontSize: '0.7rem', opacity: 0.7 }}>
                                Podés seleccionar varios a la vez
                            </span>
                        </div>
                    ) : (
                        <div style={{ textAlign: 'left', fontSize: '0.75rem' }}>
                            {files.map((f, i) => (
                                <div key={i} style={{ color: '#16a34a', marginBottom: 2 }}>
                                    📄 {f.name}
                                    <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
                                        ({(f.size / 1024).toFixed(0)} KB)
                                    </span>
                                </div>
                            ))}
                            <div style={{ marginTop: 6, fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                Clic para cambiar / agregar más
                            </div>
                        </div>
                    )}
                </div>
                <input ref={fileRef} type="file" multiple
                    accept=".csv,.txt,.xlsx,.xls,.pdf,.jpg,.jpeg,.png,.webp"
                    style={{ display: 'none' }}
                    onChange={handleFile} />
            </div>

            {/* Botón + mensaje */}
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: 8 }}>
                <button onClick={parsear} disabled={loading || !files.length || !banco} style={btnPrimary}>
                    {loading ? '⏳ Procesando...' : `🏦 Parsear${files.length > 1 ? ` ${files.length} archivos` : ' estado de cuenta'}`}
                </button>
                {msg && (
                    <div style={{
                        fontSize: '0.8rem', padding: '6px 10px', borderRadius: 7,
                        background: msg.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                        color: msg.ok ? '#16a34a' : '#dc2626',
                    }}>
                        {msg.text}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Página principal ────────────────────────────────────────────────── */
export default function Conciliacion() {
    const { state } = useApp()
    const token = state.token || localStorage.getItem('gc_token')

    const [txns, setTxns] = useState([])
    const [reconId, setReconId] = useState(null)
    const [stats, setStats] = useState(null)
    const [saldoDiff, setSaldoDiff] = useState(null)
    const [matching, setMatching] = useState(false)
    const [matchMsg, setMatchMsg] = useState(null)
    const [step, setStep] = useState('upload') // upload | review | done
    const [period, setPeriodPage] = useState(currentPeriod()) // para el banner

    function handleTransacciones(data, banco, per, saldoIni, saldoFin) {
        setTxns(data.map((t, i) => ({ ...t, id: t.id || `tmp_${i}`, match_estado: 'PENDIENTE' })))
        if (per) setPeriodPage(per)
        setStep('review')
        setReconId(null)
        setStats(null)
        setSaldoDiff(null)
    }

    async function runMatch() {
        if (!reconId) {
            setMatchMsg({ ok: false, text: 'Guarda las transacciones primero' })
            return
        }
        setMatching(true); setMatchMsg(null)
        try {
            const r = await fetch(`${API}/conciliacion/match/${reconId}`, {
                method: 'POST', headers: authH(token)
            })
            const d = await r.json()
            if (r.ok) {
                setStats(d.stats)
                setSaldoDiff(d.saldo_diff)
                setStep('done')
                setMatchMsg({ ok: true, text: `Matching completado — ${d.stats.conciliados} conciliados` })
            } else {
                setMatchMsg({ ok: false, text: d.detail || 'Error en matching' })
            }
        } catch (e) { setMatchMsg({ ok: false, text: String(e) }) }
        setMatching(false)
    }

    function handleApprove(txn) {
        // Abre modal de asiento — fase siguiente
        alert(`Crear asiento para: ${txn.descripcion}\nMonto: ${formatCRC(txn.monto)}`)
    }

    const porcentajeConciliado = stats
        ? Math.round((stats.conciliados / Math.max(stats.total_banco, 1)) * 100)
        : 0

    return (
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 20px' }}>

            {/* Header */}
            <div style={{ marginBottom: 24, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                        🏦 Conciliación Bancaria
                    </h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 5 }}>
                        Carga tu estado de cuenta (CSV, Excel o PDF) y compáralo automáticamente con el Libro Diario.
                    </p>
                </div>
                {step !== 'upload' && (
                    <button onClick={() => { setStep('upload'); setTxns([]); setStats(null) }} style={btnSecondary}>
                        ↩ Nueva conciliación
                    </button>
                )}
            </div>

            {/* Banner de estado del período */}
            <PeriodBanner period={period} />

            {/* Steps indicator */}
            <div style={{ display: 'flex', gap: 0, marginBottom: 24, background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {[
                    { k: 'upload', n: 1, label: 'Cargar archivo' },
                    { k: 'review', n: 2, label: 'Revisar transacciones' },
                    { k: 'done', n: 3, label: 'Resultado conciliación' },
                ].map((s, i, arr) => (
                    <div key={s.k} style={{
                        flex: 1, padding: '10px 16px', textAlign: 'center',
                        background: step === s.k ? 'var(--accent)' : 'transparent',
                        color: step === s.k ? '#fff' : 'var(--text-muted)',
                        fontSize: '0.8rem', fontWeight: step === s.k ? 700 : 400,
                        borderRight: i < arr.length - 1 ? '1px solid var(--border)' : 'none',
                        transition: 'all 0.2s',
                    }}>
                        <span style={{ opacity: 0.7, marginRight: 6 }}>{s.n}.</span>{s.label}
                    </div>
                ))}
            </div>

            {/* PASO 1: Cargar */}
            {step === 'upload' && (
                <div style={cardStyle}>
                    <div style={cardHeader}>📂 Paso 1 — Cargar estado de cuenta</div>
                    <div style={{ padding: '20px 24px' }}>
                        <FileUploader token={token} onTransacciones={handleTransacciones} onPeriodChange={setPeriodPage} />
                        <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--bg-secondary)', borderRadius: 10, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            💡 <strong>Formatos aceptados:</strong> CSV (BAC, BCR, cooperativas) · Excel XLSX (BN Virtual) · PDF — El sistema detecta el banco automáticamente por el formato del archivo.
                        </div>
                    </div>
                </div>
            )}

            {/* PASO 2: Revisar */}
            {step === 'review' && (
                <div style={cardStyle}>
                    <div style={{ ...cardHeader, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span>📋 Paso 2 — Revisar {txns.length} transacciones</span>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            {matchMsg && (
                                <span style={{ fontSize: '0.78rem', color: matchMsg.ok ? '#16a34a' : '#dc2626' }}>
                                    {matchMsg.text}
                                </span>
                            )}
                            <button onClick={runMatch} disabled={matching} style={btnPrimary}>
                                {matching ? '⏳ Analizando...' : '⚖️ Conciliar vs Libro Diario'}
                            </button>
                        </div>
                    </div>
                    <div style={{ padding: '16px 20px' }}>
                        <TxnTable txns={txns} onApprove={handleApprove} />
                    </div>
                </div>
            )}

            {/* PASO 3: Resultado */}
            {step === 'done' && (
                <>
                    {/* Barra de progreso */}
                    <div style={{ ...cardStyle, marginBottom: 16, padding: '16px 20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 700 }}>Resultado de conciliación</span>
                            <span style={{ fontSize: '0.85rem', color: porcentajeConciliado >= 80 ? '#16a34a' : '#d97706', fontWeight: 700 }}>
                                {porcentajeConciliado}% conciliado
                            </span>
                        </div>
                        <div style={{ height: 10, background: 'var(--bg-secondary)', borderRadius: 20, overflow: 'hidden' }}>
                            <div style={{
                                height: '100%', width: `${porcentajeConciliado}%`,
                                background: porcentajeConciliado >= 80 ? 'linear-gradient(90deg,#16a34a,#22c55e)' : 'linear-gradient(90deg,#d97706,#f59e0b)',
                                borderRadius: 20, transition: 'width 0.8s ease',
                            }} />
                        </div>
                    </div>

                    <StatsBar stats={stats} saldoDiff={saldoDiff} />

                    <div style={cardStyle}>
                        <div style={{ ...cardHeader, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span>📋 Detalle de transacciones</span>
                            <a
                                href={reconId ? `${API}/centinela/analyze/${reconId}` : '#'}
                                style={{ ...btnAccent, textDecoration: 'none', fontSize: '0.8rem', padding: '5px 14px' }}
                            >
                                🛡️ Analizar con CENTINELA
                            </a>
                        </div>
                        <div style={{ padding: '16px 20px' }}>
                            <TxnTable txns={txns} onApprove={handleApprove} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

/* ── Estilos ─────── */
const inputStyle = {
    background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 7,
    padding: '7px 10px', color: 'var(--text-primary)', fontSize: '0.85rem',
    outline: 'none', width: '100%', boxSizing: 'border-box',
}
const labelStyle = {
    display: 'block', fontSize: '0.75rem', fontWeight: 600,
    color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em',
}
const btnPrimary = {
    background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 8,
    padding: '8px 18px', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer',
}
const btnSecondary = {
    background: 'var(--bg-3)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '7px 14px', fontSize: '0.83rem', fontWeight: 600, cursor: 'pointer',
}
const btnAccent = {
    background: 'linear-gradient(135deg,#f59e0b,#d97706)', color: '#fff', border: 'none',
    borderRadius: 8, padding: '7px 16px', fontSize: '0.83rem', fontWeight: 700, cursor: 'pointer',
}
const btnChoice = {
    border: '1px solid transparent', borderRadius: 8, padding: '5px 12px',
    fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
}
const cardStyle = {
    background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 14, overflow: 'hidden',
}
const cardHeader = {
    padding: '12px 20px', borderBottom: '1px solid var(--border-color)',
    fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-secondary)',
    background: 'var(--bg-secondary)',
}
const th = { padding: '8px 10px', textAlign: 'left', fontWeight: 600 }
const td = { padding: '8px 10px', color: 'var(--text-primary)' }
