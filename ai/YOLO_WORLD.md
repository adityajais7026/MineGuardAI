# YOLO-World PPE detector (EXPERIMENTAL — opt-in only)

> **Status: EXPERIMENTAL.** This backend is **not** the production detector and
> must not be presented as production-ready. **Vyra (`vyra_yolov8m_ppe.pt`,
> `AI_DETECTOR=yolo`) remains the production/default detector.** Nothing in the
> Vyra path changed; YOLO-World is an additional, explicitly opt-in backend for
> benchmarking against Vyra.

## What it is

An open-vocabulary **YOLO-World** model built from `yolov8s-world.pt` using
text-prompted classes (`model.set_classes([...])`) and saved as
`custom_yolov8s_mining.pt`. It is **not fine-tuned** on any MineGuardAI
dataset — no training was run.

Configured classes (exact, order-sensitive):

| id | class | canonical name in MineGuardAI |
|----|-----------------|-------------------------------|
| 0 | person | `Person` |
| 1 | hard hat | `Hardhat` |
| 2 | gloves | `Gloves` |
| 3 | safety glasses | `Goggles` |
| 4 | safety vest | `Safety Vest` |
| 5 | safety shoes | `Safety Shoes` |

The loader verifies this exact six-class inventory on load and **refuses the
model** (HTTP 503 with a clear message) if anything differs. Class ids are
never remapped silently.

## Known limitations (from current testing)

Colab smoke test on a mining video:

* `person`, `hard hat`, `gloves` — detected reliably.
* `safety glasses`, `safety vest`, `safety shoes` — **inconsistent / not
  reliably observed**. Treat any "no PPE" conclusion for these as
  UNDETERMINED, which is exactly what the policy layer does.
* ~480 ms/frame at 640 in Colab; ~1700 ms at 1280. **640 is the default**
  here; 1280 is never applied automatically.
* The model has **only positive classes** — there are no `NO-*` classes, and
  none are invented. Missing PPE is reported as missing evidence (per-person
  status `UNDETERMINED`), never as a fabricated violation, and no alert can
  fire from a missed detection. This matches the project's honesty rules in
  `app/services/safety_rules.py` and `app/services/ppe_policy.py`.
* Per-person PPE association and ByteTrack ids work like the person_anchor
  strategy, but quality is unbenchmarked (see limitations above).

## Install the model

Place the weights at the project's model convention path (the same folder as
Vyra; weights are gitignored and never committed):

```
ai/yolo/models/custom_yolov8s_mining.pt
```

If you built the model elsewhere, copy it there:

```
cp /path/to/custom_yolov8s_mining.pt ai/yolo/models/custom_yolov8s_mining.pt
```

No download happens automatically; nothing is fetched from the internet.

## Enable (experimental)

In `backend/.env` (or your environment):

```
AI_DETECTOR=yolo_world
AI_DETECTOR_YOLO_WORLD_MODEL_PATH=ai/yolo/models/custom_yolov8s_mining.pt
```

That's the only switch. Image upload, video upload and the live webcam
endpoint (`POST /api/ai/detect/frame`) all run through the SAME detector
abstraction and the SAME policy/alert pipeline — there is no separate
YOLO-World pipeline. The live response carries `"detector": "yolo_world"`,
`"experimental": true` and `yolo_world:<weights>.pt` model labels; the
`GET /api/ai/detector` probe reports the backend under `yolo_world` with
`experimental: true`.

## Switch back to Vyra (production)

```
AI_DETECTOR=yolo
```

Restart the backend. Every default path is byte-identical to before this
feature existed (`render.yaml` and the deployed defaults are untouched).

## Files

* `backend/app/services/detectors/yolo_world.py` — the experimental detector
  (YoloService-compatible image/video surface + anchor-compatible live
  `detect()` with per-session ByteTrack).
* `backend/app/services/live_adapter.py` — the shared person-aware live flow
  (parameterized version of the person_anchor strategy's flow).
* `backend/app/services/detectors/__init__.py` — `resolve_media_detector()`
  dispatch (`yolo` → Vyra, `yolo_world` → experimental, else None/503).
* `backend/tests/test_yolo_world.py` — focused integration tests (runtime
  tests skip honestly when weights/torch are unavailable).

## Benchmarking notes

Measure against Vyra on the same fixtures: model load time, inference ms at
640, end-to-end `/frame` latency, detections/frame, and per-class recall on
mining footage. Do not promote this backend to production defaults on the
basis of a single video; the deployment config (`render.yaml`) intentionally
does not reference it.
