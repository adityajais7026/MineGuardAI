/**
 * Browser-side AI tools for the field/inspection workflow.
 *
 * Both tools run IN THE BROWSER via pretrained models:
 *  - OCR:    tesseract.js (pretrained Tesseract WASM, Apache-2.0). The
 *            eng traineddata (~15 MB) is fetched once from the jsDelivr CDN
 *            and cached by the browser. Fully client-side: no server, no
 *            training, no fabricated text — errors surface verbatim.
 *  - VOICE:  Web Speech API (SpeechRecognition). NOTE (shown in the UI):
 *            Chrome/Edge route speech to a cloud service — this is NOT
 *            offline. If the API is unavailable or the user denies the
 *            microphone, we surface UNAVAILABLE rather than fake text.
 *
 * Both results are SUGGESTIONS: the user reviews/edits before saving.
 */

export type ToolStatus = 'ok' | 'unavailable' | 'error'

export interface OcrRunResult {
  status: ToolStatus
  text: string | null
  message: string | null
  provider: string
}

export async function runBrowserOcr(
  imageElement: HTMLImageElement | HTMLCanvasElement,
  onProgress?: (p: number) => void,
): Promise<OcrRunResult> {
  try {
    const mod = await import('tesseract.js')
    const { createWorker } = mod
    const worker = await createWorker('eng', 1, {
      logger: (m: { status: string; progress: number }) => {
        if (onProgress && m.status === 'recognizing text') onProgress(m.progress)
      },
    })
    try {
      const { data } = await worker.recognize(imageElement)
      if (data.text == null) {
        return { status: 'error', text: null, message: 'OCR produced no text; try a clearer image.', provider: 'tesseract.js' }
      }
      return {
        status: 'ok',
        text: data.text,
        message: `Extracted ${data.text.trim().length} characters. This is a suggestion — review and edit before saving.`,
        provider: 'tesseract.js',
      }
    } finally {
      await worker.terminate()
    }
  } catch (err) {
    return {
      status: 'error',
      text: null,
      message: `OCR UNAVAILABLE — ${err instanceof Error ? err.message : 'failed to start (language data requires network on first use)'}. No text was extracted.`,
      provider: 'tesseract.js',
    }
  }
}

// ---------------------------------------------------------------------------
// Voice (Web Speech API)
// ---------------------------------------------------------------------------

type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as Record<string, unknown>
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as (new () => SpeechRecognitionLike) | null
}

export interface VoiceRunResult {
  status: ToolStatus
  text: string | null
  message: string | null
  provider: string
}

export function isVoiceSupported(): boolean {
  return getSpeechRecognition() !== null
}

export function startVoiceRecognition(
  language: 'en' | 'hi',
  onDone: (result: VoiceRunResult) => void,
): { stop: () => void } | null {
  const Ctor = getSpeechRecognition()
  if (!Ctor) {
    onDone({
      status: 'unavailable',
      text: null,
      message: 'VOICE RECOGNITION NOT AVAILABLE in this browser. Record audio and type the report manually.',
      provider: 'web-speech-api',
    })
    return null
  }
  const rec = new Ctor()
  rec.lang = language === 'hi' ? 'hi-IN' : 'en-IN'
  rec.continuous = false
  rec.interimResults = false
  let finalText = ''
  rec.onresult = (event) => {
    for (let i = 0; i < event.results.length; i += 1) {
      finalText += `${event.results[i][0].transcript} `
    }
  }
  rec.onerror = (event) => {
    const map: Record<string, string> = {
      'not-allowed': 'Microphone permission denied.',
      'service-not-allowed': 'Speech service unavailable (browser restriction).',
      network: 'Speech service requires network (Chrome processes speech in the cloud).',
      'no-speech': 'No speech detected.',
    }
    onDone({
      status: 'error',
      text: finalText.trim() || null,
      message: `VOICE ERROR — ${map[event.error] ?? event.error}. No transcription${finalText ? ' beyond partial results' : ''}.`,
      provider: 'web-speech-api',
    })
  }
  rec.onend = () => {
    if (finalText.trim()) {
      onDone({
        status: 'ok',
        text: finalText.trim(),
        message: 'Transcribed (suggestion — review before saving). Browser speech services may process audio in the cloud; do not dictate confidential data.',
        provider: 'web-speech-api',
      })
    } else {
      onDone({ status: 'unavailable', text: null, message: 'No speech captured.', provider: 'web-speech-api' })
    }
  }
  try {
    rec.start()
  } catch (err) {
    onDone({
      status: 'error',
      text: null,
      message: `VOICE UNAVAILABLE — ${err instanceof Error ? err.message : 'could not start recognition'}.`,
      provider: 'web-speech-api',
    })
  }
  return { stop: () => rec.stop() }
}
