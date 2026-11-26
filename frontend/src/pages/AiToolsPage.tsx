/**
 * AI Tools page: OCR, Voice reporting, Translation.
 *
 * OCR runs fully in-browser (tesseract.js, pretrained WASM). Voice uses the
 * Web Speech API where the browser provides it — always labelled with its
 * actual limitations (Chrome sends audio to a cloud service; not offline).
 * Translation keeps ORIGINAL text beside the translated version — legal/
 * regulatory text is never replaced, only supplemented.
 */
import { useRef, useState } from 'react'
import { governanceApi } from '../api/endpoints'
import { runBrowserOcr, startVoiceRecognition, isVoiceSupported, type VoiceRunResult } from '../offline/aiTools'
import { Badge, EmptyState, PageHeader } from '../components/ui'

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

interface OcrState {
  status: 'idle' | 'running' | 'ok' | 'error'
  progress: number
  text: string | null
  message: string | null
  editable: string
}

function OcrPanel() {
  const [state, setState] = useState<OcrState>({ status: 'idle', progress: 0, text: null, message: null, editable: '' })
  const imgRef = useRef<HTMLImageElement>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)

  const run = async (file: File) => {
    setImageUrl(await fileToDataUrl(file))
    setState({ status: 'running', progress: 0, text: null, message: null, editable: '' })
    // Wait for the <img> to actually load so tesseract sees real pixels.
    const waitLoad = () => new Promise<void>((resolve) => {
      const el = imgRef.current
      if (!el || (el.complete && el.naturalWidth > 0)) return resolve()
      el.onload = () => resolve()
      el.onerror = () => resolve()
    })
    await waitLoad()
    if (!imgRef.current) return
    const result = await runBrowserOcr(imgRef.current, (p) => setState((s) => ({ ...s, progress: p })))
    setState({
      status: (result.status === 'ok' ? 'ok' : 'error') as OcrState['status'],
      progress: 1,
      text: result.text,
      message: result.message,
      editable: result.text ?? '',
    })
  }

  return (
    <div className="card">
      <h3>OCR — Document digitization <Badge text="PRETRAINED (browser, tesseract.js)" tone="info" /></h3>
      <p className="muted">
        Pretrained Tesseract runs entirely in your browser. Language data (~15 MB for English) is
        fetched once from the CDN. Extracted text is a SUGGESTION — review and edit before saving as
        an official record. No OCR accuracy is guaranteed.
      </p>
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(f) }}
      />
      {state.status === 'running' && <p>Recognizing… {Math.round(state.progress * 100)}%</p>}
      {imageUrl && <img ref={imgRef} src={imageUrl} alt="document preview" style={{ maxWidth: '100%', maxHeight: 260, marginTop: 8 }} />}
      {state.message && <p className="muted">{state.message}</p>}
      {(state.status === 'ok' || state.editable) && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={state.editable}
            onChange={(e) => setState((s) => ({ ...s, editable: e.target.value }))}
            rows={8}
            style={{ width: '100%' }}
            placeholder="Extracted text (editable)"
          />
          <button className="btn" onClick={() => void navigator.clipboard.writeText(state.editable)}>Copy text</button>
        </div>
      )}
    </div>
  )
}

function VoicePanel() {
  const [state, setState] = useState<VoiceRunResult & { saved: boolean }>(
    { status: 'unavailable', text: null, message: null, provider: 'web-speech-api', saved: false })
  const [lang, setLang] = useState<'en' | 'hi'>('en')
  const [editable, setEditable] = useState('')
  const recorderRef = useRef<{ stop: () => void } | null>(null)

  const start = () => {
    setState({ status: 'unavailable', text: null, message: 'Listening…', provider: 'web-speech-api', saved: false })
    recorderRef.current = startVoiceRecognition(lang, (r) => {
      setState({ ...r, saved: false })
      if (r.text) setEditable(r.text)
    })
  }
  const stop = () => recorderRef.current?.stop()

  return (
    <div className="card">
      <h3>Voice reporting <Badge text={isVoiceSupported() ? 'BROWSER (cloud-backed)' : 'UNAVAILABLE'} tone={isVoiceSupported() ? 'warn' : 'muted'} /></h3>
      <p className="muted">
        Speech-to-text uses your browser's speech engine. In Chrome/Edge this processes audio via a
        cloud service — it does NOT work offline and should not be used for confidential dictation.
        The transcription is a SUGGESTION: review before saving. No regional-language guarantee:
        choose the language you will actually speak.
      </p>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <select value={lang} onChange={(e) => setLang(e.target.value as 'en' | 'hi')}>
          <option value="en">English (en-IN)</option>
          <option value="hi">Hindi (hi-IN)</option>
        </select>
        <button className="btn btn-primary" onClick={start}>Start recording</button>
        <button className="btn" onClick={stop}>Stop</button>
      </div>
      {state.message && <p className="muted">{state.message}</p>}
      {(state.text || editable) && (
        <textarea
          value={editable}
          onChange={(e) => setEditable(e.target.value)}
          rows={4}
          style={{ width: '100%', marginTop: 8 }}
          placeholder="Transcribed report (editable)"
        />
      )}
    </div>
  )
}

function TranslationPanel() {
  const [original, setOriginal] = useState('')
  const [target, setTarget] = useState('hi')
  const [result, setResult] = useState<{ text: string | null; status: string; message: string | null } | null>(null)
  const [busy, setBusy] = useState(false)

  const translate = async () => {
    setBusy(true)
    try {
      const r = await governanceApi.translate(original, target)
      setResult(r)
    } catch (err) {
      setResult({ text: null, status: 'error', message: err instanceof Error ? err.message : 'Translation failed' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3>Translation <Badge text="PROVIDER-ADAPTER (server)" tone="info" /></h3>
      <p className="muted">
        The original text is ALWAYS shown alongside the translation — regulatory text is never
        replaced. Server adapter reports status honestly: if no translation provider is configured
        the original text is shown unchanged.
      </p>
      <textarea value={original} onChange={(e) => setOriginal(e.target.value)} rows={3}
        style={{ width: '100%' }} placeholder="Original text (English)" />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="hi">Hindi</option>
          <option value="en">English</option>
        </select>
        <button className="btn" onClick={translate} disabled={busy || !original.trim()}>Translate</button>
      </div>
      {result && (
        <div style={{ marginTop: 8 }}>
          <p><strong>Original:</strong> {original}</p>
          {result.text
            ? <p><strong>Translated ({target}):</strong> {result.text}</p>
            : <p className="muted">{result.message ?? 'No translation available — original text preserved above.'}</p>}
        </div>
      )}
    </div>
  )
}

export function AiToolsPage() {
  return (
    <div className="page">
      <PageHeader
        title="AI Tools"
        subtitle="OCR, voice reporting and translation. AI output is always a reviewable suggestion — never an automatic official record."
      />
      <OcrPanel />
      <div style={{ height: 16 }} />
      <VoicePanel />
      <div style={{ height: 16 }} />
      <TranslationPanel />
      {!isVoiceSupported() && (
        <EmptyState message="Voice recognition is not available in this browser — typewritten reports remain available." />
      )}
    </div>
  )
}
