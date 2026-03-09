/**
 * AsientosPendientes.jsx — Libro Diario (vista + creación de asientos)
 *
 * E1: Agregado formulario "+ Nuevo asiento" manual
 * Contador/Admin: puede crear, aprobar (POSTED) o anular (VOIDED).
 * Asistente: solo visualiza — no puede crear ni aprobar.
 * Todo con audit trail — Reglas de Oro.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useApp } from '../context/AppContext'

const STATUS_CONFIG = {
    DRAFT: { label: 'Borrador', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
    POSTED: { label: 'Aprobado', color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
    VOIDED: { label: 'Anulado', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
}

const SOURCE_ICON = {
    MANUAL: '✍️', FE: '📄', TE: '🧾', NC: '↩️', ND: '➕',
    FEC: '🛒', REP: '💰', RECIBIDO: '📥', CIERRE: '🔒',
    DEPRECIACION: '🏗️', APERTURA: '🔵', REVERSO: '↩️',
}

// Fuentes que son «automáticas» (generadas por el sistema, no por el contador)
const AUTO_SOURCES = new Set(['FE', 'TE', 'NC', 'ND', 'FEC', 'REP', 'RECIBIDO', 'CIERRE', 'DEPRECIACION', 'APERTURA', 'REVERSO'])

const TABS = [
    { id: 'DRAFT', label: 'Borrador', icon: '✏️', color: '#f59e0b' },
    { id: 'POSTED', label: 'Aprobados', icon: '✅', color: '#10b981' },
    { id: 'VOIDED', label: 'Anulados', icon: '↩️', color: '#ef4444' },
    { id: 'AUTO', label: 'Automáticos', icon: '🤖', color: '#3b82f6' },
]

const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

const todayStr = () => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const getCurrentPeriod = () => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const EMPTY_LINE = () => ({ account_code: '', description: '', debit: '', credit: '' })

// ─── Componente principal ────────────────────────────────────────
export default function AsientosPendientes() {
    const { state } = useApp()
    const [entries, setEntries] = useState([])
    const [loading, setLoading] = useState(true)
    const [period, setPeriod] = useState(getCurrentPeriod())
    const [activeTab, setActiveTab] = useState('DRAFT')
    const [expanded, setExpanded] = useState({})
    const [acting, setActing] = useState(null)
    const [voidReason, setVoidReason] = useState('')
    const [voidTarget, setVoidTarget] = useState(null)
    const [revertTarget, setRevertTarget] = useState(null)
    const [revertReason, setRevertReason] = useState('')
    const [deleteTarget, setDeleteTarget] = useState(null)   // para eliminar DRAFT
    const [editEntryId, setEditEntryId] = useState(null)     // null=crear, id=editar
    const [error, setError] = useState(null)
    const [openingMonth, setOpeningMonth] = useState(null) // '2026-01' — del API /ledger/opening-entry

    // ── E1: estado del formulario nuevo asiento ──
    const [showForm, setShowForm] = useState(false)
    // accounts: SOLO cuentas de movimiento (hojas) desde /posteable — con display_code
    const [accounts, setAccounts] = useState([])
    const [saving, setSaving] = useState(false)
    const [formError, setFormError] = useState(null)
    const [form, setForm] = useState({
        date: todayStr(),
        description: '',
        lines: [EMPTY_LINE(), EMPTY_LINE()],
    })
    // Period Lock — verifica si la fecha del asiento cae en un período CERRADO
    const [periodLocked, setPeriodLocked] = useState(false)
    const [periodLockChecking, setPeriodLockChecking] = useState(false)
    // AccountPicker: estado por línea {open, query, highlighted}
    const [pickers, setPickers] = useState({})

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const canWrite = role === 'admin' || role === 'contador'

    // ── Ref para foco post-render (en lugar de setTimeout frágil) ─────────────────
    const pendingFocusRef = useRef(null)
    useEffect(() => {
        if (pendingFocusRef.current) {
            const el = document.getElementById(pendingFocusRef.current)
            if (el) { el.focus(); pendingFocusRef.current = null }
        }
    })  // sin deps: corre después de cada render — seguro por la guarda de la ref

    // Carga todos los asientos del período (sin filtro de status → client-side)
    useEffect(() => { fetchEntries() }, [period])

    // Cargar SOLO cuentas de movimiento (hojas) con display_code — principio NIIF
    useEffect(() => {
        if (!canWrite || !token) return
        fetch(`${apiUrl}/catalog/accounts/posteable`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : [])
            .then(data => setAccounts(Array.isArray(data) ? data : []))
            .catch(() => { })
    }, [canWrite])

    // Fecha de apertura → define el límite inferior del selector de período
    useEffect(() => {
        if (!token) return
        fetch(`${apiUrl}/ledger/opening-entry`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data?.date) {
                    // '2026-01-01' → '2026-01'
                    const ymd = data.date.slice(0, 7)
                    setOpeningMonth(ymd)
                    // Si el período actual es anterior a la apertura, redirigir al mes de apertura
                    setPeriod(p => p < ymd ? ymd : p)
                }
            })
            .catch(() => { })
    }, [token])

    // Colores + abreviaciones por tipo de cuenta
    const TYPE_COLOR = {
        ACTIVO: '#3b82f6', PASIVO: '#ef4444',
        INGRESO: '#10b981', GASTO: '#f59e0b', PATRIMONIO: '#8b5cf6'
    }
    const TYPE_ABBREV = { ACTIVO: 'ACT', PASIVO: 'PAS', INGRESO: 'ING', GASTO: 'GAS', PATRIMONIO: 'PAT' }

    // Refs de los inputs de cuenta (uno por línea) para getBoundingClientRect
    const inputRefs = []
    const getInputRef = (i) => {
        if (!inputRefs[i]) inputRefs[i] = { current: null }
        return inputRefs[i]
    }

    // Fuzzy v2: multi-campo (code, display_code, name, tipo, abrev)
    function fuzzyResults(q) {
        if (!q || !q.trim()) return { items: accounts.slice(0, 12), total: accounts.length }
        const ql = q.toLowerCase().trim()
        const all = accounts.filter(a => {
            const abbrev = TYPE_ABBREV[a.account_type] || ''
            return (
                a.code.toLowerCase().includes(ql) ||
                (a.display_code || '').toLowerCase().includes(ql) ||
                a.name.toLowerCase().includes(ql) ||
                a.account_type?.toLowerCase().includes(ql) ||
                abbrev.toLowerCase().includes(ql)
            )
        })
        return { items: all.slice(0, 12), total: all.length }
    }

    // openPicker v2: calcula posición fixed con flip-up si no hay espacio abajo
    function openPicker(i) {
        const ref = inputRefs[i]
        let top = 0, left = 0, width = 380, dropUp = false
        if (ref?.current) {
            const r = ref.current.getBoundingClientRect()
            const vH = window.innerHeight
            const vW = window.innerWidth
            const dH = 320  // altura del dropdown
            const dW = Math.max(r.width, 380)
            const spaceBelow = vH - r.bottom
            const spaceAbove = r.top
            dropUp = spaceBelow < dH && spaceAbove > spaceBelow
            top = dropUp ? r.top - dH - 4 : r.bottom + 4
            left = Math.min(r.left, vW - dW - 8)
            left = Math.max(left, 8)
            width = dW
        }
        setPickers(p => ({ ...p, [i]: { open: true, query: form.lines[i]?.display_code || '', hi: 0, top, left, width, dropUp } }))
    }
    function closePicker(i) { setPickers(p => ({ ...p, [i]: { ...p[i], open: false } })) }
    function selectAccount(i, acc) {
        setForm(f => {
            const lines = [...f.lines]
            lines[i] = {
                ...lines[i],
                account_code: acc.code,
                display_code: acc.display_code,
                description: lines[i].description || acc.name,
                _accName: acc.name,
                _accType: acc.account_type,
            }
            return { ...f, lines }
        })
        closePicker(i)
    }

    // Trae TODOS los asientos del período — el filtrado es client-side por tab
    async function fetchEntries() {
        setLoading(true); setError(null)
        try {
            const res = await fetch(`${apiUrl}/ledger/entries?period=${period}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) throw new Error('Error al cargar asientos')
            setEntries(await res.json())
        } catch (e) { setError(e.message) }
        finally { setLoading(false) }
    }

    // ── Filtrado client-side según la tab activa ─────────────
    const filteredEntries = useMemo(() => {
        if (activeTab === 'AUTO') return entries.filter(e => AUTO_SOURCES.has(e.source))
        return entries.filter(e => e.status === activeTab)
    }, [entries, activeTab])

    // ── Badge counts para cada tab ────────────────────────────
    const tabCounts = useMemo(() => ({
        DRAFT: entries.filter(e => e.status === 'DRAFT').length,
        POSTED: entries.filter(e => e.status === 'POSTED').length,
        VOIDED: entries.filter(e => e.status === 'VOIDED').length,
        AUTO: entries.filter(e => AUTO_SOURCES.has(e.source)).length,
    }), [entries])

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
            else {
                setVoidTarget(null); setVoidReason('')
                alert('⚠️ Asiento anulado. El asiento de reversión fue creado como BORRADOR — revísalo antes de aprobar.')
                fetchEntries()
            }
        } finally { setActing(null) }
    }

    async function handleRevertToDraft(entryId) {
        if (!revertReason.trim()) { alert('Debes indicar el motivo del regreso a borrador'); return }
        setActing(entryId)
        try {
            const res = await fetch(
                `${apiUrl}/ledger/entries/${entryId}/revert-to-draft?reason=${encodeURIComponent(revertReason)}`,
                { method: 'PATCH', headers: { Authorization: `Bearer ${token}` } }
            )
            if (!res.ok) {
                const e = await res.json()
                alert(e.detail || 'Error al revertir')
            } else {
                setRevertTarget(null); setRevertReason('')
                fetchEntries()
            }
        } finally { setActing(null) }
    }
    async function handleDelete(entryId) {
        setActing(entryId)
        try {
            const res = await fetch(`${apiUrl}/ledger/entries/${entryId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) { const e = await res.json(); alert(e.detail || 'Error al eliminar') }
            else { setDeleteTarget(null); fetchEntries() }
        } finally { setActing(null) }
    }

    function handleEditDraft(entry) {
        // Pre-rellenar el formulario con los datos del asiento existente
        const prefilled = {
            date: entry.date || todayStr(),
            description: entry.description || '',
            lines: (entry.lines || []).map(l => ({
                account_code: l.account_code || '',
                display_code: l.account_code || '',   // se actualiza si el usuario busca
                description: l.description || '',
                debit: l.debit ? String(l.debit) : '',
                credit: l.credit ? String(l.credit) : '',
                _accName: l.description || '',
            }))
        }
        if (prefilled.lines.length < 2) prefilled.lines.push(EMPTY_LINE())
        setEditEntryId(entry.id)
        setForm(prefilled)
        setFormError(null)
        setShowForm(true)
        setTimeout(() => document.getElementById('entry-description')?.focus(), 60)
    }


    const totalDebit = useMemo(() => form.lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0), [form.lines])
    const totalCredit = useMemo(() => form.lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0), [form.lines])
    const isBalanced = Math.abs(totalDebit - totalCredit) < 0.0001 && totalDebit > 0
    const canSave = isBalanced && form.lines.length >= 2 && form.date && form.description.trim().length >= 3
        && !form.lines.some(l => (parseFloat(l.debit) || 0) > 0 && (parseFloat(l.credit) || 0) > 0)
        && !periodLocked && !periodLockChecking

    // Period Lock check: cada vez que cambie la fecha, consulta el estado del período
    useEffect(() => {
        if (!form.date || !token || !showForm) return
        const ym = form.date.slice(0, 7) // 'YYYY-MM'
        setPeriodLockChecking(true)
        setPeriodLocked(false)
        fetch(`${apiUrl}/ledger/period/${ym}/status`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : { status: 'OPEN' })
            .then(d => { setPeriodLocked(d.status === 'CLOSED') })
            .catch(() => setPeriodLocked(false))
            .finally(() => setPeriodLockChecking(false))
    }, [form.date, showForm])

    function updateLine(i, field, value) {
        setForm(f => {
            const lines = [...f.lines]
            lines[i] = { ...lines[i], [field]: value }
            // Si escribe en débito → limpiar crédito automáticamente y viceversa
            if (field === 'debit' && parseFloat(value) > 0) lines[i].credit = ''
            if (field === 'credit' && parseFloat(value) > 0) lines[i].debit = ''
            return { ...f, lines }
        })
    }

    function addLine() {
        setForm(f => ({ ...f, lines: [...f.lines, EMPTY_LINE()] }))
    }

    function addLineAndFocus() {
        // Guarda el ID del campo a foquear; el useEffect lo resuelve DESPUÉS del render
        const newIdx = form.lines.length
        pendingFocusRef.current = `line-account-${newIdx}`
        setForm(f => ({ ...f, lines: [...f.lines, EMPTY_LINE()] }))
    }

    function removeLine(i) {
        if (form.lines.length <= 2) return
        setForm(f => ({ ...f, lines: f.lines.filter((_, idx) => idx !== i) }))
    }

    async function handleSaveEntry() {
        if (!canSave) return
        setSaving(true); setFormError(null)
        try {
            const payload = {
                date: form.date,
                description: form.description.trim(),
                source: 'MANUAL',
                lines: form.lines
                    .filter(l => l.account_code.trim())
                    .map(l => ({
                        account_code: l.account_code.trim().toUpperCase(),
                        description: l.description.trim() || null,
                        debit: parseFloat(l.debit) || 0,
                        credit: parseFloat(l.credit) || 0,
                        deductible_status: 'PENDING',
                    })),
            }
            // Si editEntryId: PATCH (editar); si no: POST (crear)
            const url = editEntryId
                ? `${apiUrl}/ledger/entries/${editEntryId}`
                : `${apiUrl}/ledger/entries`
            const method = editEntryId ? 'PATCH' : 'POST'
            const res = await fetch(url, {
                method,
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || 'Error al guardar el asiento')
            }
            closeForm()
            setActiveTab('DRAFT')
            await fetchEntries()
        } catch (e) {
            setFormError(e.message)
        } finally {
            setSaving(false)
        }
    }

    function closeForm() {
        setShowForm(false)
        setFormError(null)
        setEditEntryId(null)
        setForm({ date: todayStr(), description: '', lines: [EMPTY_LINE(), EMPTY_LINE()] })
    }

    // ── Opciones de período — dinámicas desde la fecha de apertura ─────────────
    // Muestra desde el mes de apertura hasta el mes actual + 3 (planificación).
    // Si no hay apertura (empresa nueva), solo muestra el año en curso.
    const periodOptions = useMemo(() => {
        const now = new Date()
        // Límite inferior: mes de apertura o Enero del año en curso
        const startStr = openingMonth || `${now.getFullYear()}-01`
        const start = new Date(startStr + '-01T00:00:00')
        // Límite superior: 3 meses adelante (planificación anticipada)
        const end = new Date(now.getFullYear(), now.getMonth() + 3, 1)
        const opts = []
        let d = new Date(end)
        while (d >= start) {
            const y = d.getFullYear()
            const m = String(d.getMonth() + 1).padStart(2, '0')
            opts.push({ val: `${y}-${m}`, label: `${MONTHS[d.getMonth()]} ${y}` })
            d = new Date(y, d.getMonth() - 1, 1)
        }
        return opts
    }, [openingMonth])

    const selStyle = {
        padding: '7px 12px', borderRadius: 7, border: '1px solid var(--border-color)',
        background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.85rem'
    }
    const inputStyle = {
        padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color)',
        background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.85rem',
        width: '100%', boxSizing: 'border-box'
    }

    // ── IMPORT CSV — estado ───────────────────────────────────────
    const [importFeedback, setImportFeedback] = useState(null) // {ok, msg}
    const csvInputRef = useRef(null)

    // Descarga la plantilla CSV con un asiento de ejemplo
    function downloadTemplate() {
        const rows = [
            '# Plantilla de importación de asientos — Genoma Contabilidad',
            '# Reglas:',
            '#   FECHA: formato YYYY-MM-DD',
            '#   DESCRIPCION_ASIENTO: texto igual agrupa líneas en el mismo asiento',
            '#   CUENTA: código exacto del catálogo (ej: 1101.01)',
            '#   DEBE y HABER: número decimal con punto (ej: 225932.24)',
            '#   Solo DEBE > 0 ó solo HABER > 0 por línea (partida simple)',
            '#   Elimina estas líneas de comentario antes de importar',
            'FECHA,DESCRIPCION_ASIENTO,CUENTA,DESCRIPCION_LINEA,DEBE,HABER',
            '2026-03-08,Pago servicios de oficina marzo,5210.03,Gasto depreciación vehículo,225932.24,0',
            '2026-03-08,Pago servicios de oficina marzo,1201.04,Depreciación acumulada vehículos,0,225932.24',
            '2026-03-08,Compra suministros de oficina,5901.01,Suministros y representación,44192.00,0',
            '2026-03-08,Compra suministros de oficina,1101.01,Caja General — pago en efectivo,0,44192.00',
        ].join('\r\n')
        const blob = new Blob(['\uFEFF' + rows], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = 'plantilla_asiento.csv'; a.click()
        URL.revokeObjectURL(url)
    }

    // Parsea el texto CSV → array de filas {fecha, desc_asiento, cuenta, desc_linea, debe, haber}
    function parseCsvText(text) {
        const lines = text.split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith('#'))
        if (lines.length < 2) return []
        // Detectar si primera línea es encabezado
        const hdr = lines[0].split(',').map(c => c.trim().replace(/^"|"$/g, '').toUpperCase())
        const isHeader = hdr.some(h => ['FECHA', 'CUENTA', 'DEBE', 'HABER'].includes(h))
        const dataLines = isHeader ? lines.slice(1) : lines
        return dataLines.map(l => {
            const cols = l.split(',').map(c => c.trim().replace(/^"|"$/g, ''))
            const get = (idx) => (cols[idx] || '').trim()
            return {
                fecha: get(0),
                desc_asiento: get(1),
                cuenta: get(2).toUpperCase(),
                desc_linea: get(3),
                debe: parseFloat(get(4)) || 0,
                haber: parseFloat(get(5)) || 0,
            }
        }).filter(r => r.fecha && r.cuenta)
    }

    // Agrupa filas por (fecha + desc_asiento) → array de entries {date, description, lines[]}
    function groupIntoEntries(rows) {
        const map = new Map()
        for (const r of rows) {
            const key = `${r.fecha}||${r.desc_asiento}`
            if (!map.has(key)) map.set(key, { date: r.fecha, description: r.desc_asiento, lines: [] })
            map.get(key).lines.push({
                account_code: r.cuenta,
                description: r.desc_linea || '',
                debit: r.debe > 0 ? String(r.debe) : '',
                credit: r.haber > 0 ? String(r.haber) : '',
            })
        }
        return Array.from(map.values())
    }

    // Valida las entries: balance, mínimo 2 líneas, fecha válida
    function validateImport(entries) {
        const errors = []
        for (let i = 0; i < entries.length; i++) {
            const e = entries[i]
            if (!/^\d{4}-\d{2}-\d{2}$/.test(e.date)) errors.push(`Asiento ${i + 1}: fecha inválida "${e.date}"`)
            if (e.lines.length < 2) errors.push(`Asiento ${i + 1}: necesita mínimo 2 líneas`)
            const dr = e.lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0)
            const cr = e.lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0)
            if (Math.abs(dr - cr) > 0.01) errors.push(`Asiento ${i + 1} "${e.description}": desbalanceado (DR=${dr.toFixed(2)} ≠ CR=${cr.toFixed(2)})`)
        }
        return errors
    }

    // Maneja el input file: parsea, valida y carga el PRIMER asiento en el form
    function handleImportFile(e) {
        const file = e.target.files?.[0]
        if (!file) return
        e.target.value = ''  // permite reimportar el mismo archivo
        const reader = new FileReader()
        reader.onload = (ev) => {
            try {
                const rows = parseCsvText(ev.target.result)
                if (rows.length === 0) {
                    setImportFeedback({ ok: false, msg: 'El archivo no contiene datos válidos. Verifica el formato.' })
                    return
                }
                const entries = groupIntoEntries(rows)
                const errors = validateImport(entries)
                if (errors.length > 0) {
                    setImportFeedback({ ok: false, msg: errors.join(' · ') })
                    return
                }
                // Cargar el primer asiento en el form (si hay varios, se importan todos)
                const first = entries[0]
                setForm({
                    date: first.date,
                    description: first.description,
                    lines: first.lines.length >= 2 ? first.lines : [...first.lines, EMPTY_LINE()],
                })
                const msg = entries.length === 1
                    ? `✅ 1 asiento importado con ${first.lines.length} líneas — revisa y guarda.`
                    : `✅ ${entries.length} asientos detectados — cargado asiento 1 de ${entries.length}. Guarda este y repite para los demás.`
                setImportFeedback({ ok: true, msg })
            } catch {
                setImportFeedback({ ok: false, msg: 'Error al parsear el archivo. Verifica que sea CSV válido.' })
            }
        }
        reader.readAsText(file, 'UTF-8')
    }

    // ────────────────────────────────────────────────────────────
    return (
        <div style={{ padding: '24px', maxWidth: 980, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        📒 Libro Diario
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        {entries.length} asiento{entries.length !== 1 ? 's' : ''} · {period}
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <select id="period-select" value={period} onChange={e => setPeriod(e.target.value)} style={selStyle}>
                        {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label}</option>)}
                    </select>
                    {/* E1: Botón nuevo asiento */}
                    {canWrite && (
                        <button
                            id="btn-nuevo-asiento"
                            onClick={() => setShowForm(true)}
                            style={{
                                padding: '8px 18px', background: '#7c3aed', border: 'none',
                                borderRadius: 8, color: 'white', fontWeight: 700,
                                cursor: 'pointer', fontSize: '0.88rem', display: 'flex',
                                alignItems: 'center', gap: 6, whiteSpace: 'nowrap'
                            }}
                        >
                            ✦ Nuevo asiento
                        </button>
                    )}
                </div>
            </div>

            {/* ── Tabs de estado + Automáticos ── */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--border-color)', paddingBottom: 0 }}>
                {TABS.map(tab => {
                    const isActive = activeTab === tab.id
                    const count = tabCounts[tab.id] ?? 0
                    return (
                        <button
                            key={tab.id}
                            id={`tab-${tab.id.toLowerCase()}`}
                            onClick={() => setActiveTab(tab.id)}
                            style={{
                                display: 'flex', alignItems: 'center', gap: 6,
                                padding: '8px 14px', border: 'none', cursor: 'pointer',
                                background: 'transparent', fontFamily: 'Inter, sans-serif',
                                fontSize: '0.82rem', fontWeight: isActive ? 700 : 500,
                                color: isActive ? tab.color : 'var(--text-secondary)',
                                borderBottom: isActive ? `2px solid ${tab.color}` : '2px solid transparent',
                                marginBottom: -1, transition: 'all 0.15s ease',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            <span>{tab.icon}</span>
                            <span>{tab.label}</span>
                            <span style={{
                                padding: '1px 7px', borderRadius: 10, fontSize: '0.72rem',
                                background: isActive ? tab.color + '22' : 'rgba(255,255,255,0.07)',
                                color: isActive ? tab.color : 'var(--text-muted)',
                                fontWeight: 700, minWidth: 20, textAlign: 'center',
                            }}>
                                {count}
                            </span>
                        </button>
                    )
                })}
            </div>

            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-secondary)' }}>⏳ Cargando asientos...</div>}

            {/* ── Lista de asientos — filtrada por tab activa ── */}
            {!loading && filteredEntries.map(entry => {
                const sc = STATUS_CONFIG[entry.status] || STATUS_CONFIG.DRAFT
                const ico = SOURCE_ICON[entry.source] || '📋'
                const isExpanded = expanded[entry.id]
                const totalDR = entry.lines?.reduce((s, l) => s + (l.debit || 0), 0) || 0
                const totalCR = entry.lines?.reduce((s, l) => s + (l.credit || 0), 0) || 0
                const balanced = Math.abs(totalDR - totalCR) < 0.01

                return (
                    <div key={entry.id} id={`entry-${entry.id}`}
                        style={{ border: `1px solid ${sc.color}40`, borderRadius: 10, marginBottom: 12, background: sc.bg, overflow: 'hidden' }}
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
                                <span style={{ fontSize: '0.75rem', color: balanced ? '#10b981' : '#ef4444' }}>
                                    {balanced ? '⚖️' : '⚠️'} ¢{totalDR.toLocaleString('es-CR', { minimumFractionDigits: 2 })}
                                </span>
                                <span style={{ fontSize: '0.75rem', padding: '3px 10px', background: sc.color + '22', color: sc.color, borderRadius: 12, fontWeight: 600 }}>
                                    {sc.label}
                                </span>
                                {/*
                      * ── BOTONES DE ACCIÓN ──────────────────────────────────
                      * DRAFT:  [✎ Editar]  [✓ Aprobar]  [🗑 Eliminar]
                      * POSTED: [⏪ Revertir]  [Anular]
                      * Jerarquía: Primaria = Aprobar/Revertir | Secundaria = Editar | Peligro = Eliminar/Anular
                      * ──────────────────────────────────────────────────
                      */}
                                {canWrite && entry.status === 'DRAFT' && (
                                    <div style={{ display: 'flex', gap: 5, alignItems: 'center' }} onClick={e => e.stopPropagation()}>
                                        {/* Editar — acento suave */}
                                        <button id={`edit-${entry.id}`}
                                            onClick={() => handleEditDraft(entry)}
                                            title="Editar borrador"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 4,
                                                padding: '4px 11px', border: '1px solid rgba(124,58,237,0.4)',
                                                borderRadius: 6, background: 'rgba(124,58,237,0.1)',
                                                color: '#a78bfa', fontSize: '0.72rem', cursor: 'pointer', fontWeight: 600
                                            }}>
                                            ✎ Editar
                                        </button>
                                        {/* Aprobar — primario */}
                                        <button id={`approve-${entry.id}`}
                                            onClick={() => handleApprove(entry.id)}
                                            disabled={acting === entry.id}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 4,
                                                padding: '4px 12px', border: 'none',
                                                borderRadius: 6, background: '#10b981',
                                                color: 'white', fontSize: '0.72rem', cursor: 'pointer', fontWeight: 700
                                            }}>
                                            {acting === entry.id ? '...' : '✓ Aprobar'}
                                        </button>
                                        {/* Separador visual */}
                                        <span style={{ width: 1, height: 18, background: 'rgba(255,255,255,0.1)' }} />
                                        {/* Eliminar — peligro ghost */}
                                        <button id={`delete-${entry.id}`}
                                            onClick={() => setDeleteTarget(entry.id)}
                                            title="Eliminar borrador (sin audit trail)"
                                            style={{
                                                display: 'flex', alignItems: 'center',
                                                padding: '4px 9px', border: '1px solid rgba(239,68,68,0.3)',
                                                borderRadius: 6, background: 'transparent',
                                                color: '#f87171', fontSize: '0.72rem', cursor: 'pointer'
                                            }}>
                                            🗑
                                        </button>
                                    </div>
                                )}
                                {canWrite && entry.status === 'POSTED' && (
                                    <div style={{ display: 'flex', gap: 5, alignItems: 'center' }} onClick={e => e.stopPropagation()}>
                                        {/* Revertir a Borrador */}
                                        <button id={`revert-${entry.id}`}
                                            onClick={() => { setRevertTarget(entry.id); setRevertReason('') }}
                                            title="Revertir a Borrador (período abierto)"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 4,
                                                padding: '4px 10px', border: '1px solid rgba(245,158,11,0.4)',
                                                borderRadius: 6, background: 'rgba(245,158,11,0.1)',
                                                color: '#fbbf24', fontSize: '0.72rem', cursor: 'pointer', fontWeight: 600
                                            }}>
                                            ⏪ Revertir
                                        </button>
                                        {/* Anular POSTED — genera reversión DRAFT */}
                                        <button id={`void-posted-${entry.id}`}
                                            onClick={() => setVoidTarget(entry.id)}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 4,
                                                padding: '4px 10px', border: '1px solid rgba(239,68,68,0.3)',
                                                borderRadius: 6, background: 'transparent',
                                                color: '#f87171', fontSize: '0.72rem', cursor: 'pointer'
                                            }}>
                                            Anular
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Líneas del asiento */}
                        {isExpanded && entry.lines?.length > 0 && (
                            <div style={{ borderTop: `1px solid ${sc.color}30` }}>
                                <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 110px 110px 80px', gap: 8, padding: '6px 16px', fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700, background: 'rgba(0,0,0,0.05)' }}>
                                    <span>CUENTA</span><span>DESCRIPCIÓN</span>
                                    <span style={{ textAlign: 'right' }}>DÉBITO</span>
                                    <span style={{ textAlign: 'right' }}>CRÉDITO</span>
                                    <span>FISCAL</span>
                                </div>
                                {entry.lines.map((line, i) => (
                                    <div key={line.id} style={{ display: 'grid', gridTemplateColumns: '100px 1fr 110px 110px 80px', gap: 8, padding: '7px 16px', fontSize: '0.8rem', borderTop: '1px solid rgba(255,255,255,0.04)', background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.04)' }}>
                                        <span style={{ fontFamily: 'monospace', color: '#7c3aed', fontWeight: 700 }}>{line.account_code}</span>
                                        <span style={{ color: 'var(--text-secondary)' }}>{line.description || '—'}</span>
                                        <span style={{ textAlign: 'right', color: line.debit > 0 ? '#3b82f6' : 'var(--text-muted)' }}>
                                            {line.debit > 0 ? `¢${Number(line.debit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                                        </span>
                                        <span style={{ textAlign: 'right', color: line.credit > 0 ? '#10b981' : 'var(--text-muted)' }}>
                                            {line.credit > 0 ? `¢${Number(line.credit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                                        </span>
                                        <span style={{ fontSize: '0.68rem', color: line.deductible_status === 'DEDUCTIBLE' ? '#10b981' : line.deductible_status === 'NON_DEDUCTIBLE' ? '#ef4444' : '#6b7280' }}>
                                            {(!line.deductible_status || line.deductible_status === 'PENDING') ? '—' : line.deductible_status.slice(0, 8)}
                                        </span>
                                    </div>
                                ))}
                                <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 110px 110px 80px', gap: 8, padding: '8px 16px', borderTop: `1px solid ${sc.color}40`, fontWeight: 700, fontSize: '0.8rem', background: 'rgba(0,0,0,0.06)' }}>
                                    <span style={{ color: 'var(--text-secondary)' }}>TOTAL</span>
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
            {!loading && filteredEntries.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>
                        {activeTab === 'AUTO' ? '🤖' : '📭'}
                    </div>
                    <p style={{ marginBottom: 8 }}>
                        {activeTab === 'AUTO'
                            ? 'No hay asientos automáticos en ' + period + '.'
                            : `No hay asientos en estado "${TABS.find(t => t.id === activeTab)?.label}" en ${period}.`}
                    </p>
                    {activeTab === 'AUTO' && (
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', maxWidth: 380, margin: '0 auto' }}>
                            Los asientos automáticos se generan desde Activos Fijos, Cierre de Período y documentos electrónicos.
                        </p>
                    )}
                    {canWrite && activeTab === 'DRAFT' && (
                        <button id="btn-nuevo-asiento-empty" onClick={() => setShowForm(true)}
                            style={{ marginTop: 16, padding: '10px 22px', background: '#7c3aed', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.88rem' }}>
                            ✦ Crear primer asiento
                        </button>
                    )}
                </div>
            )}

            {/* ── Modal: Nuevo asiento manual (E1) ──────────────── */}
            {showForm && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', zIndex: 1000, paddingTop: 40, overflowY: 'auto' }}>
                    <div style={{ background: 'var(--bg-elevated)', borderRadius: 16, padding: 28, maxWidth: 780, width: '100%', boxShadow: '0 24px 80px rgba(0,0,0,0.6)', margin: '0 16px 40px' }}>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)', fontWeight: 700 }}>
                                {editEntryId ? '✎ Editar borrador' : '✦ Nuevo asiento manual'}
                            </h2>
                            <button onClick={closeForm} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.4rem', cursor: 'pointer', lineHeight: 1 }}>✕</button>
                        </div>

                        {/* Period Lock Banner — aparece cuando la fecha está en un período CERRADO */}
                        {periodLocked && (
                            <div style={{
                                display: 'flex', alignItems: 'center', gap: 10,
                                padding: '10px 14px', borderRadius: 8, marginBottom: 14,
                                background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.4)',
                                color: '#ef4444', fontSize: '0.82rem'
                            }}>
                                <span style={{ fontSize: '1.1rem' }}>🔒</span>
                                <div>
                                    <strong>Período cerrado</strong> — el mes <code>{form.date?.slice(0, 7)}</code> está CERRADO.
                                    No se pueden agregar asientos en períodos cerrados (Art. 51 Ley Renta CR).
                                </div>
                            </div>
                        )}
                        {periodLockChecking && (
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 10 }}>
                                ⏳ Verificando estado del período...
                            </div>
                        )}

                        {/* Fecha + descripción */}
                        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 12, marginBottom: 16 }}>
                            <div>
                                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha *</label>
                                <input id="entry-date" type="date" value={form.date}
                                    onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                                    style={{ ...inputStyle, borderColor: periodLocked ? '#ef4444' : undefined }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Descripción *</label>
                                <input id="entry-description" type="text" value={form.description} placeholder="Ej: Pago de servicios de oficina marzo 2026"
                                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                                    style={inputStyle} />
                            </div>
                        </div>

                        {/* Tabla de líneas */}
                        <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden', marginBottom: 12 }}>
                            {/* Encabezado */}
                            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px,280px) 1fr 110px 110px 36px', gap: 8, padding: '8px 12px', background: 'rgba(0,0,0,0.1)', fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700 }}>
                                <span>CUENTA *</span><span>DESCRIPCIÓN</span>
                                <span style={{ textAlign: 'right' }}>DÉBITO</span>
                                <span style={{ textAlign: 'right' }}>CRÉDITO</span>
                                <span></span>
                            </div>

                            {form.lines.map((line, i) => (
                                <div key={i} id={`line-row-${i}`} style={{ display: 'grid', gridTemplateColumns: 'minmax(240px,280px) 1fr 110px 110px 36px', gap: 6, padding: '6px 12px', borderTop: '1px solid var(--border-color)', alignItems: 'center', background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)' }}>
                                    {/* ── AccountPicker v2: input + ref, sin dropdown inline ── */}
                                    <div style={{ position: 'relative' }}>
                                        <div style={{
                                            display: 'flex', alignItems: 'center', gap: 4,
                                            border: `1px solid ${line.account_code ? (TYPE_COLOR[line._accType] || 'var(--border-color)') + '80' : 'var(--border-color)'}`,
                                            borderRadius: 6, overflow: 'hidden', background: 'var(--bg-card)'
                                        }}>
                                            {line._accType && (
                                                <span style={{
                                                    fontSize: '0.62rem', fontWeight: 700, padding: '0 5px',
                                                    background: TYPE_COLOR[line._accType] + '20',
                                                    color: TYPE_COLOR[line._accType], whiteSpace: 'nowrap', lineHeight: '28px'
                                                }}>{line._accType?.slice(0, 3)}</span>
                                            )}
                                            <input
                                                id={`line-account-${i}`}
                                                ref={el => { if (!inputRefs[i]) inputRefs[i] = {}; inputRefs[i].current = el }}
                                                value={pickers[i]?.open ? (pickers[i]?.query || '') : (line.display_code || line.account_code || '')}
                                                placeholder="Buscar cuenta..."
                                                onFocus={() => openPicker(i)}
                                                onChange={e => setPickers(p => ({ ...p, [i]: { ...p[i], open: true, query: e.target.value, hi: 0 } }))}
                                                onKeyDown={e => {
                                                    const { items } = fuzzyResults(pickers[i]?.query || '')
                                                    const hi = pickers[i]?.hi || 0
                                                    if (e.key === 'ArrowDown') { e.preventDefault(); setPickers(p => ({ ...p, [i]: { ...p[i], hi: Math.min(hi + 1, items.length - 1) } })) }
                                                    if (e.key === 'ArrowUp') { e.preventDefault(); setPickers(p => ({ ...p, [i]: { ...p[i], hi: Math.max(hi - 1, 0) } })) }
                                                    if (e.key === 'Enter' && items[hi]) { e.preventDefault(); selectAccount(i, items[hi]) }
                                                    if (e.key === 'Tab' && !e.shiftKey) {
                                                        e.preventDefault()
                                                        if (items[hi]) selectAccount(i, items[hi])  // selecciona si hay item resaltado
                                                        else closePicker(i)                          // cierra picker si no
                                                        pendingFocusRef.current = `line-debit-${i}`  // foco al débito siempre
                                                    }
                                                    if (e.key === 'Escape') closePicker(i)
                                                }}
                                                onBlur={() => setTimeout(() => closePicker(i), 180)}
                                                style={{ flex: 1, border: 'none', background: 'transparent', padding: '5px 6px', fontSize: '0.78rem', fontFamily: 'monospace', color: 'var(--text-primary)', outline: 'none', minWidth: 0 }}
                                            />
                                        </div>
                                        {/* NO HAY DROPDOWN AQUI — se renderiza abajo con position:fixed */}
                                    </div>
                                    {/* Descripción línea */}
                                    <input
                                        id={`line-desc-${i}`}
                                        value={line.description}
                                        placeholder="Concepto opcional"
                                        onChange={e => updateLine(i, 'description', e.target.value)}
                                        style={{ ...inputStyle, fontSize: '0.8rem' }}
                                    />
                                    {/* Débito */}
                                    <input
                                        id={`line-debit-${i}`}
                                        type="number" min="0" step="0.01"
                                        value={line.debit}
                                        placeholder="0.00"
                                        onChange={e => updateLine(i, 'debit', e.target.value)}
                                        onKeyDown={e => {
                                            // Tab desde Débito → Crédito de la misma línea
                                            if (e.key === 'Tab' && !e.shiftKey) {
                                                e.preventDefault()
                                                document.getElementById(`line-credit-${i}`)?.focus()
                                            }
                                        }}
                                        style={{ ...inputStyle, textAlign: 'right', color: '#3b82f6', fontSize: '0.85rem' }}
                                    />
                                    {/* Crédito */}
                                    <input
                                        id={`line-credit-${i}`}
                                        type="number" min="0" step="0.01"
                                        value={line.credit}
                                        placeholder="0.00"
                                        onChange={e => updateLine(i, 'credit', e.target.value)}
                                        onKeyDown={e => {
                                            if (e.key === 'Tab' && !e.shiftKey) {
                                                e.preventDefault()
                                                if (i === form.lines.length - 1) {
                                                    // Última línea → crear nueva y hacer foco en su cuenta
                                                    addLineAndFocus()
                                                } else {
                                                    // Línea intermedia → ir a la cuenta de la siguiente
                                                    document.getElementById(`line-account-${i + 1}`)?.focus()
                                                }
                                            }
                                        }}
                                        style={{ ...inputStyle, textAlign: 'right', color: '#10b981', fontSize: '0.85rem' }}
                                    />
                                    {/* Eliminar línea — tabIndex=-1 para no interrumpir el flujo Tab */}
                                    <button onClick={() => removeLine(i)} title="Eliminar línea"
                                        tabIndex={-1}
                                        disabled={form.lines.length <= 2}
                                        style={{ padding: '4px', background: 'transparent', border: 'none', color: form.lines.length <= 2 ? 'var(--text-muted)' : '#ef4444', cursor: form.lines.length <= 2 ? 'not-allowed' : 'pointer', fontSize: '1rem' }}>
                                        ✕
                                    </button>
                                </div>
                            ))}
                        </div>

                        {/* Botones: Agregar línea + Importar CSV + Plantilla */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                            <button id="btn-add-line" onClick={addLine}
                                style={{ padding: '6px 14px', background: 'transparent', border: '1px dashed var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.82rem' }}>
                                + Agregar línea
                            </button>

                            {/* Separador visual */}
                            <span style={{ width: 1, height: 20, background: 'var(--border-color)', flexShrink: 0 }} />

                            {/* Input file oculto */}
                            <input
                                id="csv-file-input"
                                ref={csvInputRef}
                                type="file"
                                accept=".csv,text/csv"
                                onChange={handleImportFile}
                                style={{ display: 'none' }}
                            />

                            {/* Botón Importar CSV */}
                            <button
                                id="btn-import-csv"
                                type="button"
                                onClick={() => { setImportFeedback(null); csvInputRef.current?.click() }}
                                title="Importar líneas desde archivo CSV"
                                style={{
                                    display: 'flex', alignItems: 'center', gap: 5,
                                    padding: '6px 13px', borderRadius: 7, cursor: 'pointer',
                                    fontSize: '0.82rem', fontWeight: 600,
                                    border: '1px solid rgba(124,58,237,0.4)',
                                    background: 'rgba(124,58,237,0.08)', color: '#a78bfa',
                                    transition: 'all 0.15s',
                                }}
                            >
                                📎 Importar CSV
                            </button>

                            {/* Botón Descargar plantilla */}
                            <button
                                id="btn-download-template"
                                type="button"
                                onClick={downloadTemplate}
                                title="Descargar plantilla CSV de ejemplo"
                                style={{
                                    display: 'flex', alignItems: 'center', gap: 5,
                                    padding: '6px 13px', borderRadius: 7, cursor: 'pointer',
                                    fontSize: '0.82rem', fontWeight: 600,
                                    border: '1px solid rgba(16,185,129,0.35)',
                                    background: 'rgba(16,185,129,0.07)', color: '#34d399',
                                    transition: 'all 0.15s',
                                }}
                            >
                                ⬇ Plantilla
                            </button>
                        </div>

                        {/* Banner de feedback del import — éxito o error */}
                        {importFeedback && (
                            <div style={{
                                padding: '8px 14px', borderRadius: 8, marginBottom: 12,
                                fontSize: '0.82rem', fontWeight: 600,
                                background: importFeedback.ok ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                                border: `1px solid ${importFeedback.ok ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)'}`,
                                color: importFeedback.ok ? '#10b981' : '#ef4444',
                                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10,
                            }}>
                                <span>{importFeedback.msg}</span>
                                <button onClick={() => setImportFeedback(null)}
                                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: '0.85rem', flexShrink: 0 }}>✕</button>
                            </div>
                        )}

                        {/* ── Dropdowns position:fixed — flotan sobre todo, independiente del grid ── */}
                        {form.lines.map((_, i) => {
                            const pk = pickers[i]
                            if (!pk?.open) return null
                            const { items, total } = fuzzyResults(pk.query || '')
                            return (
                                <div key={`picker-${i}`} style={{
                                    position: 'fixed',
                                    top: pk.top || 0,
                                    left: pk.left || 0,
                                    width: pk.width || 380,
                                    zIndex: 9999,
                                    background: 'var(--bg-elevated)',
                                    border: '1px solid var(--border-color)',
                                    borderRadius: 12,
                                    boxShadow: '0 16px 56px rgba(0,0,0,0.6)',
                                    maxHeight: 320,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    overflow: 'hidden',
                                }}>
                                    {/* Lista de resultados con scroll */}
                                    <div style={{ overflowY: 'auto', flex: 1 }}>
                                        {items.length === 0 ? (
                                            <div style={{ padding: '14px 16px', fontSize: '0.82rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                                                Sin resultados para &ldquo;{pk.query}&rdquo;
                                            </div>
                                        ) : items.map((a, idx) => (
                                            <div key={a.code}
                                                onMouseDown={() => selectAccount(i, a)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: 10,
                                                    padding: '9px 14px', cursor: 'pointer',
                                                    background: idx === (pk.hi || 0)
                                                        ? (TYPE_COLOR[a.account_type] || '#7c3aed') + '1a'
                                                        : 'transparent',
                                                    borderBottom: '1px solid var(--border-color)',
                                                    transition: 'background 0.1s',
                                                }}>
                                                {/* Badge tipo */}
                                                <span style={{
                                                    fontSize: '0.65rem', fontWeight: 800, padding: '2px 6px',
                                                    borderRadius: 5,
                                                    background: (TYPE_COLOR[a.account_type] || '#9ca3af') + '22',
                                                    color: TYPE_COLOR[a.account_type] || '#9ca3af',
                                                    flexShrink: 0, minWidth: 32, textAlign: 'center'
                                                }}>
                                                    {TYPE_ABBREV[a.account_type] || a.account_type?.slice(0, 3)}
                                                </span>
                                                {/* Código DGCN */}
                                                <span style={{
                                                    fontFamily: 'monospace', fontSize: '0.78rem', fontWeight: 700,
                                                    color: TYPE_COLOR[a.account_type] || '#9ca3af',
                                                    flexShrink: 0, minWidth: 78
                                                }}>
                                                    {a.display_code}
                                                </span>
                                                {/* Nombre completo */}
                                                <span style={{
                                                    fontSize: '0.82rem', color: 'var(--text-primary)',
                                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                                                }}>
                                                    {a.name}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                    {/* Footer: contador */}
                                    <div style={{
                                        padding: '7px 14px',
                                        fontSize: '0.72rem', color: 'var(--text-muted)',
                                        borderTop: '1px solid var(--border-color)',
                                        background: 'rgba(0,0,0,0.15)',
                                        flexShrink: 0,
                                    }}>
                                        {total <= 12
                                            ? `${total} cuenta${total !== 1 ? 's' : ''} disponible${total !== 1 ? 's' : ''}`
                                            : `Mostrando 12 de ${total}  ·  Seguí escribiendo para afinar`
                                        }
                                    </div>
                                </div>
                            )
                        })}

                        {/* Indicador de balance en tiempo real */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderRadius: 8, marginBottom: 16, background: isBalanced ? 'rgba(16,185,129,0.1)' : totalDebit > 0 || totalCredit > 0 ? 'rgba(239,68,68,0.08)' : 'rgba(0,0,0,0.04)', border: `1px solid ${isBalanced ? '#10b981' : totalDebit > 0 || totalCredit > 0 ? '#ef4444' : 'var(--border-color)'}` }}>
                            <div style={{ display: 'flex', gap: 24, fontSize: '0.88rem' }}>
                                <span>Débitos: <strong style={{ color: '#3b82f6' }}>¢{totalDebit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</strong></span>
                                <span>Créditos: <strong style={{ color: '#10b981' }}>¢{totalCredit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</strong></span>
                            </div>
                            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: isBalanced ? '#10b981' : '#ef4444' }}>
                                {isBalanced ? '⚖️ Balanceado' : totalDebit > 0 || totalCredit > 0 ? `⚠️ Diferencia: ¢${Math.abs(totalDebit - totalCredit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                            </span>
                        </div>

                        {/* Error del formulario */}
                        {formError && (
                            <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '8px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.85rem' }}>
                                ⚠️ {formError}
                            </div>
                        )}

                        {/* Botones de acción */}
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={closeForm} style={{ padding: '9px 20px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 8, color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.88rem' }}>
                                Cancelar
                            </button>
                            <button id="btn-save-entry" onClick={handleSaveEntry} disabled={!canSave || saving}
                                style={{ padding: '9px 22px', background: canSave ? '#7c3aed' : 'var(--bg-card)', border: 'none', borderRadius: 8, color: canSave ? 'white' : 'var(--text-muted)', fontWeight: 700, cursor: canSave ? 'pointer' : 'not-allowed', fontSize: '0.88rem', transition: 'all 0.15s' }}>
                                {saving ? '⏳ Guardando...' : editEntryId ? '✎ Guardar cambios' : '💾 Guardar DRAFT'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Modal de anulación ── */}
            {voidTarget && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div style={{ background: 'var(--bg-secondary)', borderRadius: 14, padding: 28, maxWidth: 440, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
                        <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: '#ef4444' }}>⚠️ Anular asiento</h2>
                        <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            Se generará un asiento de reversión como <strong>BORRADOR</strong> para que lo revises antes de aprobar.
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
                            <button id="confirm-void-btn" onClick={() => handleVoid(voidTarget)} disabled={acting === voidTarget}
                                style={{ padding: '8px 20px', background: '#ef4444', border: 'none', borderRadius: 7, color: 'white', fontWeight: 700, cursor: 'pointer' }}>
                                {acting === voidTarget ? 'Anulando...' : 'Confirmar anulación'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Modal revertir a BORRADOR ── */}
            {revertTarget && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div style={{ background: 'var(--bg-secondary)', borderRadius: 14, padding: 28, maxWidth: 440, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
                        <h2 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: '#f59e0b' }}>⏪ Revertir a Borrador</h2>
                        <p style={{ margin: '0 0 6px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            El asiento regresará a <strong>BORRADOR</strong> para corrección.
                            Solo es posible si el período aún no está cerrado.
                        </p>
                        <p style={{ margin: '0 0 16px', fontSize: '0.8rem', color: '#f59e0b' }}>
                            ⚠️ Una vez en borrador, el asiento ya no afecta el balance hasta que lo vuelvas a aprobar.
                        </p>
                        <textarea
                            id="revert-reason-input"
                            placeholder="Motivo del reverso a borrador *"
                            value={revertReason}
                            onChange={e => setRevertReason(e.target.value)}
                            style={{ width: '100%', padding: '10px 12px', border: '1px solid var(--border-color)', borderRadius: 7, background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', resize: 'vertical', minHeight: 80, boxSizing: 'border-box', marginBottom: 16 }}
                        />
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={() => { setRevertTarget(null); setRevertReason('') }}
                                style={{ padding: '8px 16px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                                Cancelar
                            </button>
                            <button id="confirm-revert-btn" onClick={() => handleRevertToDraft(revertTarget)} disabled={acting === revertTarget}
                                style={{ padding: '8px 20px', background: '#f59e0b', border: 'none', borderRadius: 7, color: '#1a1a1a', fontWeight: 700, cursor: 'pointer' }}>
                                {acting === revertTarget ? 'Revirtiendo...' : '⏪ Confirmar reverso'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Modal: Confirmar eliminar DRAFT ── */}
            {deleteTarget && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div style={{ background: 'var(--bg-secondary)', borderRadius: 14, padding: 28, maxWidth: 400, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
                        <h2 style={{ margin: '0 0 10px', fontSize: '1.1rem', color: '#f87171' }}>🗑 Eliminar borrador</h2>
                        <p style={{ margin: '0 0 20px', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                            Este borrador se eliminará permanentemente.
                            <br />
                            <span style={{ color: '#6b7280', fontSize: '0.78rem' }}>Solo los borradores pueden eliminarse. Los asientos aprobados se anulan (generan reversión).</span>
                        </p>
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={() => setDeleteTarget(null)}
                                style={{ padding: '8px 18px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                                Cancelar
                            </button>
                            <button id="confirm-delete-btn" onClick={() => handleDelete(deleteTarget)} disabled={acting === deleteTarget}
                                style={{ padding: '8px 20px', background: '#ef4444', border: 'none', borderRadius: 7, color: 'white', fontWeight: 700, cursor: 'pointer' }}>
                                {acting === deleteTarget ? 'Eliminando...' : '🗑 Sí, eliminar'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

