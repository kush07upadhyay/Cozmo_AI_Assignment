# Fix Loop Diff: Opening Over-Detection

Regenerate with `python -m fix_loop.run_fix_loop`.

| Room | Detected (before) | Detected (after) | Ground truth |
|------|--------------------|--------------------|---------------|
| repeat_room_a | 13 | 2 | 2 |
| repeat_room_b | 14 | 2 | 2 |
| living_room | 9 | 2 | 2 |
| hallway | 6 | 2 | 2 |
| bedroom | 9 | 2 | 2 |
| den | 10 | 2 | 2 |

| Metric | Before | After |
|--------|--------|-------|
| Opening detection rate (gate: >=85%) | 100.0% | 100.0% |
| Opening width within 2cm rate | 0.0% | 41.7% |
| Mean width error (m) | 0.3667 | 0.0236 |
| Total false-positive opening detections (sum over rooms) | 49 | 0 |
