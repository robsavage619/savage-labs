# Body-mesh trial: stopped 2026-11-14

**Verdict: failed validation against tape. Not wired into the app, and should not be.**

The trial fitted Meta's MHR body model (Apache-2.0) to a front and a side progress photo at
a known stature and read tape-style girths off the fitted body. On the first session with
same-morning tape, three front/side photo pairs gave:

| Site | Error against tape | Spread across the three pairs |
|---|---|---|
| Waist, at the navel | +14 cm | 1.8% |
| Chest | +3 cm | 1.2% |
| Mid-thigh | −8 cm | 1.1% |
| Body mass from mesh volume | −0.4% | |

The fit repeats well and is wrong. The total volume is right, and the model puts it in the
wrong places.

## Why it was stopped rather than tuned

1. **Two relaxed photos cannot see most of what the tape measures.**
   - Thigh depth: the far leg shows behind the near one in a side view. The same thigh read
     20% apart across three shots taken minutes apart, while its front width held within 5%.
   - Chest depth: the hanging arm covers the back of the torso in a side view.
   - Flexed arm: not in the photos at all.
   - Only the waist is visible in both views. Wherever a view is blind, the model fills in
     its average body, and the errors above match the average body's errors there.
2. **For the waist, the model adds little.** Front width times side depth, read straight off
   the two outlines as an ellipse, landed 2 to 7 cm under tape with no model at all.
3. **Tape is already the better instrument.** It repeats to about 1 cm in two minutes.

## Known flaw in `fit.py`, left unfixed

The outline loss does not penalise a body that is larger than the silhouette. The coverage
term is met by any body that covers the outline, and the only opposing term costs nothing
where the photo shows an arm. At the navel the fitted torso was 18% too wide and 18% too
deep. Masking the arms out removes the waist's own edges from the fit, so that is not a fix.

## What is here

- `fit.py`: the two-view fit (shared shape, per-photo pose and camera, no renderer).
- `tape.py`: girths, stature and volume from a closed mesh. `uv run python tape.py` checks it
  on shapes with known answers. This part is sound and reusable.
- `compare.py`: scores photo sessions against tape taken within 3 days.
  `uv run python compare.py` runs its self-check.
- `run.py`: fits every session and scores it. Results go to `results/`, which is not committed.

Apple Silicon only: MHR's solver and PyTorch have no Intel-Mac wheels.

## If someone picks this up again

Change the capture before the model: arms held well away from the body, one leg forward in
the side view, and a third photo for the flexed arm. Then replace the outline loss with a
two-sided one. The bar to beat is a tape measure.
