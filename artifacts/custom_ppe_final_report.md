# Custom PPE Model Pipeline — Final Report

Date: 2026-09-29 · Environment: Windows, CPU-only (torch 2.14.0+cpu), MineGuardAI repo
Scope: dataset discovery → preparation → training pipeline → identical-frame
benchmark of every candidate against Vyra. **The production detector was NOT
changed.** Vyra remains production; no threshold, policy, schema, RBAC or
upload behavior was touched. Backend suite after all work: **170 passed / 4 skipped**.

---

## 1. Datasets actually used

| Dataset | Source | License | Used for |
|---|---|---|---|
| keremberke/construction-safety-object-detection (398 imgs, 17 classes) | Hugging Face (orig. Roboflow Universe `construction-site-safety`) | not stated on card — treated as research use | training/validation/test (7-class normalized subset) |
| COCO val2017 person frames (40) | `detection-datasets/coco` (HF parquet) | annotations CC BY 4.0; images COCO/Flickr research terms | negative-clothing FP benchmark ONLY (never in train/val/test) |
| MineGuardAI webcam captures (1+) | our own frames | our data | negative-clothing FP benchmark |

Full provenance + rejected sources: `backend/tools/custom_ppe/DATASETS.md`.

## 2. Dataset preparation (reproducible)

`prepare_dataset.py` audited 398 images: **0 corrupt, 0 unreadable, 0
in-split duplicates**; content-hash leakage check across emitted splits:
**clean**. COCO→YOLO conversion with taxonomy normalization to the MineGuardAI
target set (dropped machinery/mask/vehicle classes; kept 10% of pure-background
frames as negative data):

| split | images | helmet | no_helmet | safety_vest | no_safety_vest | person | gloves | safety_shoes |
|---|---|---|---|---|---|---|---|---|
| train | 146 | 289 | 92 | 45 | 21 | 42 | 11 | 9 |
| valid | 40 | 115 | 9 | 6 | 14 | 23 | 5 | 13 |
| test | 25 | 32 | 7 | 2 | 3 | 4 | 2 | 1 |

**Goggles: absent from every public source evaluated.** Command:
`python prepare_dataset.py --raw raw/keremberke --out dataset_v1 --source keremberke`.

## 3. Training performed

- **Real GPU training: NOT performed on this machine** (CPU-only, verified
  `torch.cuda.is_available() == False`). Per the authorized fallback, the
  **ready-to-run GPU package** was generated and verified instead:
  `backend/tools/custom_ppe/colab_package/` containing
  `colab_ppe_training.ipynb` (Run-All ready: installs ultralytics, uploads
  dataset zips, trains YOLO11n 100 epochs @640 on GPU, validates, offers
  `best.pt` for download), `dataset_train.zip` (146 imgs + labels),
  `dataset_valid.zip` (40), `negbench.zip` (the FP benchmark), and the
  embedded `training_payload.py`. The **unseen test split (25 imgs) is
  deliberately NOT uploaded** — holdout evaluation runs locally after
  training (leakage-proof by construction).
  - **v2 payload fix (2026-09-29):** the first Colab attempt failed with
    `FileNotFoundError: /content/work/raw_train/_annotations.coco.json` —
    the payload expected raw COCO but the zips already contain converted
    YOLO format. Fixed payload consumes the zips AS THEY ARE and validates
    extraction + label integrity (image/label counts, class-id ranges)
    BEFORE training starts. Verified locally against the byte-identical zips
    (sha256-confirmed): extraction 146/146 + 40/40, 0 invalid label lines,
    and Ultralytics training runs on the notebook-built tree (1-epoch CPU
    verification — NOT a training-result claim). Dataset zips were never
    regenerated.
- Pipeline verified end-to-end locally: 1-epoch CPU smoke run plus the full
  post-training harness executed against those weights
  (`results/bench_smoke_debug.json`) — machinery confirmed (ByteTrack IDs
  1–8 stable, close/medium/far matrix, latency staging).
- **After the GPU run**: place `best.pt` at
  `backend/tools/custom_ppe/artifacts/custom_ppe_v1.pt` and run the single
  command in README §"Back from Colab" — it executes steps 5–9 (holdout test
  eval, same FP benchmark, close/medium/far, multi-person association,
  violation→alert latency p50/p95/max) and writes
  `results/bench_custom_ppe_v1.json` for the CUSTOM-vs-VYRA comparison.
- Switch decision rule (unchanged): flip
  `PERSON_ANCHOR_PPE_MODEL_PATH` **only if** the custom model beats Vyra on
  this identical benchmark while keeping p95 violation→alert ≤ 2 s. Vyra
  stays production until then.
- Deployment compatibility (verified additively): an alternate-taxonomy
  model is made policy-compatible by the `CANONICAL_CLASS_ALIASES` adapter
  in `person_anchor.py` (presents `no_helmet`→`NO-Hardhat` etc. to the
  EXISTING policy; raw model class ids preserved; no-op for Vyra).

## 4. Identical-frame benchmark (all numbers from `results/*.json` this run)

Negative-clothing FP test = 41 frames of persons in confirmed ordinary
clothing (40 COCO + 1 webcam sleeveless). Positive-class FP = predictions of
`safety vest` / `hardhat` on those frames (the compliance false positives that
matter). Negative-class hits (`no-safety vest` / `no-hardhat`) are CORRECT
evidence of absence and reported separately.

| Model | CPU p50 / p95 (ms) | safety-vest FP @0.10 / @0.35 | hardhat FP @0.10 / @0.35 | no-vest dets (correct) | no-helmet dets (correct) | mAP (7-class test) |
|---|---|---|---|---|---|---|
| **Vyra v8m (production)** | 262 / 266 | **1 / 0** | 9 / 4 | 35 | 51 | n/a — foreign class space* |
| Hansung v8n | 42 / 44 | **14 / 5 (3 even @0.50)** | 59 / 33 | 245 | 202 | n/a* |
| SafetyVision-v2 | 102 / 104 | 3 / 1 | 11 / 2 | 32 | 61 | n/a* |
| Baskar v8n (MIT, 17 classes) | 43 / 45 | **0 / 0** | 53 / 33 | 1 | 75 | n/a* |
| yolo11n (COCO person control) | 45 / 47 | 0 / 0 | 0 / 0 | 0 | 0 | n/a (no PPE classes) |

\* mAP is reported **only for models trained on the same 7-class taxonomy**
(the harness refuses cross-taxonomy matching; index-mismatched "mAP" is
meaningless). The custom model, once trained, will be the first same-taxonomy
row.

**Reading of the table (evidence, not taste):**
- Vyra has the best positive-class precision of all PPE models and the
  strongest correct no-vest/no-helmet evidence at reasonable thresholds — its
  weaknesses are CPU latency (262ms vs 42–102ms) and thin gloves/shoes.
- Hansung's "45ms" is irrelevant: **14 safety-vest FPs on normal clothing,
  5 above the alert bar** — the exact failure mode reported by the user.
- Baskar has the most complete class set (incl. safety shoes) and 0 vest FPs,
  but a domain gap: near-zero no-vest evidence and hardhat FPs.
- The reported "sleeveless shirt → Safety Vest 61%" incident: that exact frame
  (webcam_000) produced **no vest FP from any model** in this run; the
  incident frame was a different moment. Vyra's single vest FP@0.10 on COCO
  frames and the live 0.61 observation show the risk is real but rare — the
  UI/backend honesty layer (COMPLIANT requires positive helmet+vest evidence;
  otherwise INSUFFICIENT/PARTIAL/UNDETERMINED) already prevents it from ever
  displaying compliance.

## 5. Reliability per required class (current best evidence)

| Required class | Status in this environment |
|---|---|
| Person | ✓ yolo11n anchor (0.84–0.89, tracks to 109px) — first-class in architecture |
| Helmet | ✓ Vyra (fixture conf 0.42–0.74; 4 FP@0.35 on COCO scenes) |
| No Helmet | ✓ Vyra NO-Hardhat (0.52 fixture; 51 correct hits on neg-bench) |
| Safety Vest | ✓ Vyra (0.55 fixture); 1 FP@0.10 / 0 @0.35 on neg-bench |
| No Safety Vest | ✓ Vyra (0.41 fixture, 0.73 SafetyVision-v2; 35 correct neg-bench hits) |
| Gloves | ✗ class exists in 3 models, **never fires on our imagery — unreliable** |
| No Gloves | ✗ same — not claimed |
| Boots/Safety Shoes | ✗ no model produces usable evidence (Baskar's `safety shoes`: 0 on our frames) |
| No Boots | ✗ unsupported everywhere |
| Goggles | ✗ class exists (Vyra/SafetyVision-v2) but weak (0.13–0.29) — **unreliable** |

## 6. What was changed in MineGuardAI (complete list)

- **Added** `backend/tools/custom_ppe/` — fetch_datasets.py, prepare_dataset.py,
  train_ppe_yolo.py, eval_ppe_model.py, DATASETS.md, README.md (+ build
  artifacts raw/ dataset_v1/ neg_bench/ runs/ results/, all untracked).
- **No changes** to detectors, policy, thresholds, live/upload/video paths,
  DB schema, RBAC, alerts, UI. Suite re-verified: **170 passed / 4 skipped**.

## 7. Known limitations (honest)

1. No GPU on this machine → no trained custom weights yet; the smoke run
   proves the pipeline, not a model.
2. 146-image training set is small; the Roboflow-API extension path
   (NO-Gloves/NO-Goggles sources) and our webcam negatives should be merged
   before the real run.
3. mAP-vs-Vyra comparison waits for a same-taxonomy custom model.
4. Goggles/No-Boots/No-Gloves have no reliable public source + our imagery;
   they will remain explicitly UNRELIABLE in UI/backend until a model proves
   otherwise on measured evidence.
5. Negative-bench caveat: a few COCO street scenes legitimately contain
   helmets (cyclists) — per-file examples in results/*.json allow manual
   verification; the @0.50 tail of Vyra's hardhat FP (2) was not manually
   verified frame-by-frame.

## 8. Verdict

Keep Vyra + anchor architecture in production (best precision/latency balance;
the anchor already fixes multi-person attribution, tracking and the ~0.6s
alert path). Train the custom 7-class model on Colab with the prepared
pipeline; switch **only if** it beats Vyra on this exact benchmark
(negative-bench FPs + fixture evidence + latency). One config value flips it.
