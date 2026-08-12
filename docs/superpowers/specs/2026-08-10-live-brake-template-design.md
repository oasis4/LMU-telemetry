# Live brake template — design

Date: 2026-08-10
Branch: `feature/brake-shape-coaching`

## Goal

The panel says "There is more corner speed here" and the driver cannot act on
it. It is a diagnosis, not a handgrip: it names what was wrong without saying
what to do differently, and it arrives after the corner, when nothing can be
done about it anyway.

This adds a **template**: shortly before each braked corner, a strip appears
under the delta showing the reference lap's brake and throttle traces in grey,
with the driver's own lines drawn over them as they happen, and a tone at the
reference brake point. The driver stops being told they were slow and starts
being shown where the pedal went.

This reverses a decision in
[2026-08-07-brake-shape-coaching-design.md](2026-08-07-brake-shape-coaching-design.md),
which said "no live shout during the braking zone; the statement comes after
the corner". The driver asked for exactly that shout after using the tool.
Their call, recorded here so it is a decision and not a drift.

## The alignment problem, and why distance settles it

A template that does not line up is worse than none: it would have the driver
braking to a mark that is not where they are.

Measured on two laps of one Monza race session, 2.700 s apart:

| corner | reference brakes | driver brakes | time lost by then |
|---|---|---|---|
| Variante del Rettifilo 1 | 778 m | 772 m | +0.081 s |
| Variante della Roggia 1 | 2006 m | 2010 m | +1.051 s |
| Curva di Lesmo 1 | 2444 m | 2458 m | +1.372 s |
| Curva di Lesmo 2 | 2792 m | 2756 m | +1.507 s |
| Variante Ascari 1 | 3816 m | 3818 m | +1.856 s |
| Curva Parabolica | 5026 m | 5020 m | +1.837 s |

By Ascari the driver has lost 1.86 s and still brakes within 2 m of the
reference. Braking happens at a **place**, and the place does not move because
time was lost earlier. Plotted against time the template would sit 1.86 s out
by Ascari — about 130 m — and be useless exactly where it is needed most.

So the x axis is distance. Everything else follows from that: both traces are
already on the same 2 m grid, so they line up by construction rather than by
correction, and nothing accumulates over a lap.

### What does not follow, and is not corrected

Entry speed differs between the two laps by −9.3 to +6.9 km/h. A car arriving
slower can brake later — braking distance goes with the square of speed, so
6 km/h off 173 is about 7 % less distance, roughly 7 m on a 100 m braking
zone. Small, but not nothing.

The strip therefore **shows the entry-speed difference and does not move the
brake point for it.** Correcting it would mean a braking model, which cannot
be checked against this corpus, and the result would be a made-up number
sitting in the picture looking exactly like a measured one. The reference stays
what it is: a lap the driver actually drove. The difference beside it says
which way the grey line is optimistic today, without claiming a precision that
is not there.

## What is shown

Two strips under the delta figure, brake above and throttle below:

- **Grey**: the reference lap over this corner's window.
- **Coloured**: the driver's own lines, growing to their current position.
- **A vertical mark** at the reference brake point.
- **The entry-speed difference**, as text, once the corner's start is passed.

The window is `corner.start_m - APPROACH_M` to `corner.end_m`. `APPROACH_M` is
250 m and already exists — it is the span the brake point is searched over. The
same number for both, so the strip shows the same brake point the sentence
afterwards talks about.

The vertical scale is fixed at 0 to 100 % and never auto-scaled. Auto-scaling
would draw a 60 % brake application and a 90 % one at the same height, which
would make the template pretty and wrong.

The driver's line is taken from `buffer.trace()`, the same interpolation the
corner figures come from, not from the raw samples. Two routes to one curve are
two chances for the strip and the sentence to disagree about one corner.

## When it appears

Armed on entering the window; a fresh approach always takes the panel's one
optional slot, sentence or no sentence, because an 11 s sentence
(`SENTENCE_SECONDS`) must not swallow the next corner's strip. That much
shipped as planned.

What did not ship as planned is the *other* end - held until about 1.5 s
past the corner's end, then the sentence takes over, as this section
originally said. A braking event's window ends at the same distance
`CornerWatch.advance` completes the corner at, so the redraw immediately
after a finding fires sees the *same* corner's held strip, not a later
one - "the strip wins whenever it is due" therefore reversed the ordinary
case rather than only covering the gap it was meant for: the sentence, the
tool's actual advice, was gone within about 67 ms of arriving, for 8 of 11
corners at Monza. A driver reported it as the panel "growing, shrinking and
shifting."

The shipped rule instead: **a sentence wins the slot the instant it is
computed, and holds it until `SENTENCE_SECONDS` or a fresh window evicts
it.** `TEMPLATE_HOLD_S` (about 1.5 s) is still real and still runs, but for
the common case - a corner whose comparison produced a sentence - the
sentence has already taken the slot by the time the hold would otherwise
show, so the hold is not visible there. It is visibly reachable only for a
corner whose comparison produced no sentence at all: that corner still gets
to sit on screen briefly after it is over, rather than the panel dropping to
the delta alone at the same instant the corner ends. Recorded here so it is
a decision and not a drift, the same as the reversal above.

Only corners the **reference braked for** are armed. A flat-out corner has
nothing to teach here, and arming every corner would put eleven strips a lap
on screen at Monza instead of seven.

Nothing is shown on an out lap, by the rule added for the same reason the
sentences are suppressed there.

## The tone

Fires once per armed corner, when the driver's distance crosses the reference
brake point. At 250 km/h with a 50 Hz reader that lands within about 1.4 m.

It plays asynchronously. `winsound.Beep` blocks, and an 80 ms block in the
50 Hz read loop is four lost samples in the middle of a braking zone — which
is the one place the reader must not stall.

## Structure

- `live/template.py` — the arming logic, the window, and where the tone
  belongs, as plain values. No window, so it is testable without the game.
- `live/overlay.py` — draws what the template hands it, on a `tk.Canvas`.
- `live/__main__.py` — feeds it, and plays the tone.

The split is the same one `watch.py` and the panel already keep: the part with
behaviour in it stays testable, and the part that draws stays dumb.

## Testing

- The window, including a corner whose approach crosses the start/finish line.
- Arming and disarming at the right distances; the hold after the corner.
- The tone fires once per corner, and not at all for a corner the reference
  took flat.
- A recorded lap driven through the template: reference and driver samples
  land on the same metres, which is the property the whole thing rests on.
- Nothing is armed on a lap marked unusable.

## Out of scope

- **A speed trace.** It shows the outcome, not the action. One more line to
  read while driving that does not say what to do.
- **Correcting the brake point for entry speed.** See above.
- **A second window**, auto-scaling, and any history of previous corners.
