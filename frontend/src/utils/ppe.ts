/**
 * Shared PPE presentation helpers — the single source of user-facing PPE text.
 * Raw model class names (Hardhat, NO-Hardhat, ...) never appear in user-facing
 * strings; they are reserved for the Technical Details sections.
 */

/** Event types produced ONLY by the fine-tuned PPE model's own classes. */
export const PPE_VIOLATION_TYPES = new Set([
  'person_without_helmet', 'person_without_safety_vest', 'person_without_gloves',
  'person_without_goggles', 'person_without_mask', 'person_without_harness', 'fall_detected',
])
export const PPE_COMPLIANCE_TYPES = new Set([
  'helmet_detected', 'safety_vest_detected', 'gloves_detected', 'goggles_detected', 'mask_detected',
])

/**
 * PPE status for a persisted event. Violation-family event types stored with
 * 'low' severity are sub-threshold captures (UNDETERMINED — the pipeline never
 * alerts those); at medium/high/critical they are real violations.
 */
export function ppeStatus(
  eventType: string, severity?: string,
): 'VIOLATION' | 'UNDETERMINED' | 'DETECTED' | null {
  if (PPE_VIOLATION_TYPES.has(eventType)) {
    return severity === 'low' ? 'UNDETERMINED' : 'VIOLATION'
  }
  if (PPE_COMPLIANCE_TYPES.has(eventType)) return 'DETECTED'
  return null
}

/** User-facing labels for raw model classes — internal names are never shown. */
const PPE_LABEL: Record<string, string> = {
  hardhat: 'Helmet',
  'no-hardhat': 'No Helmet',
  'safety vest': 'Safety Vest',
  'no-safety vest': 'No Safety Vest',
  gloves: 'Gloves',
  'no-gloves': 'No Gloves',
  goggles: 'Goggles',
  'no-goggles': 'No Goggles',
  mask: 'Mask',
  'no-mask': 'No Mask',
  no_harness: 'No Harness',
  'fall-detected': 'Fall Detected',
  person: 'Person',
  ladder: 'Ladder',
  'safety cone': 'Safety Cone',
}

export function ppeLabel(rawClass: string): string {
  return PPE_LABEL[rawClass.toLowerCase()] ?? rawClass
}

/**
 * Rewrite backend-generated evidence text for users: raw model class names
 * become friendly labels. Display-only — backend strings are untouched.
 * NO- variants are replaced before plain names (longest-first).
 */
export function friendlyEvidence(text: string): string {
  return text
    .replace(/NO-Hardhat/g, 'No Helmet')
    .replace(/NO-Safety Vest/g, 'No Safety Vest')
    .replace(/NO-Gloves/g, 'No Gloves')
    .replace(/NO-Goggles/g, 'No Goggles')
    .replace(/NO-Mask/g, 'No Mask')
    .replace(/Hardhat/g, 'Helmet')
    .replace(/Fall-Detected/g, 'Fall Detected')
    .replace(/No_Harness/g, 'No Harness')
}

export function ruleLabel(rule: string): string {
  const map: Record<string, string> = {
    no_hardhat: 'No Helmet', hardhat_detected: 'Helmet',
    no_safety_vest: 'No Safety Vest', safety_vest_detected: 'Safety Vest',
    no_gloves: 'No Gloves', gloves_detected: 'Gloves',
    no_goggles: 'No Goggles', goggles_detected: 'Goggles',
    no_mask: 'No Mask', mask_detected: 'Mask',
    no_harness: 'No Harness', fall_detected: 'Fall Detected',
    restricted_zone_person: 'Person in restricted zone',
    restricted_zone_vehicle: 'Vehicle in restricted zone',
    crowd_threshold: 'Unsafe crowding',
  }
  return map[rule] ?? rule.replace(/_/g, ' ')
}

/** Findings shape shared by the image/video upload responses and /frame. */
export interface SafetyFinding {
  rule: string
  event_type: string
  severity: string
  evidence: string
  status?: 'violation' | 'undetermined' | 'compliance'
  confidence?: number | null
  /** Owning person's ByteTrack ID (person_anchor strategy only). */
  track_id?: number | null
}

export interface LiveEventOut {
  camera_event_id: string | null
  event_type: string
  rule: string
  ppe_status?: string | null
  recorded: boolean
  reason: string
  track_id?: number | null
}

/** One tracked person from the anchor strategy (yolo11n + ByteTrack). */
export interface TrackedPerson {
  class: 'person'
  class_id: 0
  confidence: number
  bbox: number[]
  track_id: number | null
}

/** Per-person PPE verdict from the backend (association done server-side). */
export interface PersonPpeRow {
  person_index: number
  track_id: number | null
  person_confidence: number
  person_bbox: number[]
  ppe_status: 'VIOLATION' | 'PROTECTED' | 'PARTIAL' | 'UNDETERMINED'
  ppe: { class: string; confidence: number; bbox: number[]; decision: 'violation' | 'compliance' | 'undetermined' }[]
}

export interface AnchorTimings {
  ppe_ms: number
  anchor_ms: number
  policy_ms: number
  crop_ms?: number
  total_response_ms: number
  strategy: string
}

/**
 * Honesty notes for PPE classes that must NEVER be presented as working
 * capabilities: benchmarked models either lack the class entirely (Boots) or
 * the class exists but never fires on verified imagery (Gloves).
 */
export const PPE_RELIABILITY_NOTES: Record<string, string> = {
  'No Boots': 'unsupported — no tested model provides Boots detection',
  'Boots': 'unsupported — no tested model provides Boots detection',
  'No Gloves': 'unreliable — class exists in the model but does not fire on verified imagery',
  'Gloves': 'unreliable — class exists in the model but does not fire on verified imagery',
}

export interface LiveFrameResult {
  source: 'live_webcam'
  detector: string
  model: string
  mine_id: string
  zone: { id: string; name: string } | null
  camera_id: string
  detections: { class: string; class_id: number; confidence: number; bbox: number[] }[]
  detection_count: number
  classes_detected: string[]
  safety_findings: SafetyFinding[]
  events: LiveEventOut[]
  camera_event_ids: string[]
  alerts: { id: string; title: string; severity: string; source: string; track_id?: number | null }[]
  annotated_image_url?: string | null
  storage_provider: string
  captured_by: string
  // --- person_anchor strategy extensions (absent on the default strategy) ---
  strategy?: 'person_anchor'
  persons?: TrackedPerson[]
  person_ppe_report?: PersonPpeRow[] | null
  timings?: AnchorTimings
  evidence_upload?: 'async' | null
}

export interface PpeSummaryState {
  title: string
  lines: string[]
}

/**
 * 2–3 second PPE verdict: compliant / violation / insufficient evidence.
 *
 * VERDICT HONESTY RULE (hardened after a measured false positive: a dark
 * sleeveless shirt was detected as 'Safety Vest' and the frame showed
 * 'PPE COMPLIANT'): COMPLIANT requires positive evidence for BOTH priority
 * classes — helmet AND safety vest. Evidence for only one PPE class is
 * 'INSUFFICIENT PPE EVIDENCE' (the unobserved class is simply unknown:
 * single detections have measured false-positive modes, e.g. ordinary
 * clothing misread as a vest). Zero evidence stays 'NO PPE EVIDENCE'.
 */
export function buildPpeSummary(
  findings: SafetyFinding[], alertCount: number, hasEvidence = true,
): PpeSummaryState {
  const violations = findings.filter((f) => f.status === 'violation')
  const undetermined = findings.filter((f) => f.status === 'undetermined')
  const helmets = findings.filter((f) => f.rule === 'hardhat_detected').length
  const vests = findings.filter((f) => f.rule === 'safety_vest_detected').length
  const compliantBits: string[] = []
  if (helmets) compliantBits.push(`${helmets} helmet${helmets > 1 ? 's' : ''} detected`)
  if (vests) compliantBits.push(`${vests} safety vest${vests > 1 ? 's' : ''} detected`)

  if (violations.length > 0 && compliantBits.length > 0) {
    return {
      title: '🟠 ATTENTION REQUIRED',
      lines: [
        ...compliantBits.map((s) => `${s}.`),
        `${violations.length} PPE violation${violations.length > 1 ? 's' : ''} detected.`,
      ],
    }
  }
  if (violations.length > 0) {
    const single = violations.length === 1 ? violations[0].rule : null
    const what =
      single === 'no_hardhat' ? '1 person without helmet.'
      : single === 'no_safety_vest' ? '1 person without safety vest.'
      : `${violations.length} PPE violation${violations.length > 1 ? 's' : ''} detected.`
    const anyHigh = violations.some((f) => f.severity === 'high' || f.severity === 'critical')
    const alertLine = alertCount > 0
      ? (anyHigh ? 'High alert generated.' : 'Alert generated.')
      : 'No new alert (already active or suppressed).'
    return { title: '🔴 PPE VIOLATION', lines: [what, alertLine] }
  }
  if (undetermined.length > 0) {
    return {
      title: '🟠 ATTENTION REQUIRED',
      lines: [
        `${undetermined.length} PPE signal${undetermined.length > 1 ? 's' : ''} need manual review.`,
        'No alert generated.',
      ],
    }
  }
  if (!hasEvidence) {
    return {
      title: '🟡 NO PPE EVIDENCE',
      lines: [
        'No PPE classes detected — model may not recognise this scene.',
        'This is not a compliance confirmation.',
      ],
    }
  }
  // Compliance claim ONLY with both priority classes positively evidenced.
  if (helmets > 0 && vests > 0) {
    return {
      title: '🟢 PPE COMPLIANT',
      lines: [`${compliantBits.join(', ')}.`, 'No PPE violation detected.'],
    }
  }
  return {
    title: '🟠 INSUFFICIENT PPE EVIDENCE',
    lines: [
      ...(compliantBits.length ? [`${compliantBits.join(', ')}.`] : []),
      helmets === 0 && vests === 0
        ? 'PPE classes detected, but not the priority ones.'
        : `Only one priority PPE class evidenced — ${helmets > 0 ? 'vest' : 'helmet'} state unknown.`,
      'Not a compliance confirmation — manual review recommended.',
    ],
  }
}
