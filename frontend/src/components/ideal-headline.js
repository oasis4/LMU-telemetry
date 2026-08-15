/**
 * What the headline may claim about an ideal lap.
 *
 * `IdealLap.sound` is an `all()` and not a count, and core/blocks.py says why:
 * one join that does not hold makes the whole time a claim the laps do not
 * support. So an unsound ideal lap does not get to put its gain in large type
 * looking like a lap that was nearly driven.
 *
 * This is not a hypothetical. Of 34 recordings in a corpus sample that could
 * build an ideal lap at all, five had a join that did not hold - and the
 * largest gain of the whole sample was one of the five, with 20 km/h of spread
 * at one join. The most exciting number was the worst supported one.
 *
 * Qualified, not hidden. The numbers travel on and the block table shows them.
 * A driver who wants the figure can have it; what they must not get is the
 * figure without the doubt attached.
 *
 * A function rather than a branch in the template because this is the rule the
 * feature turns on, and a conditional that suppresses a number is exactly what
 * later reads as dead weight and gets tidied away. Here, tidying it away turns
 * something red.
 */

export function headlineFor(ideal) {
  if (!ideal) {
    return { idealS: null, bestS: null, gainS: null, qualified: false, worstSeam: null }
  }
  const bad = (ideal.seams ?? []).filter((seam) => !seam.sound)
  // The worst one, not the first: the first is wherever the lap happens to
  // start, and the driver needs the join that costs the claim the most.
  const worstSeam = bad.length
    ? bad.reduce((a, b) => (b.speed_spread_kmh > a.speed_spread_kmh ? b : a))
    : null
  return {
    idealS: ideal.ideal_s,
    bestS: ideal.best_lap_s,
    gainS: ideal.gain_s,
    // The served flag, not a recount. The server computes it with
    // SEAM_SPEED_KMH and sends the limit alongside so the two cannot drift;
    // deriving it again here would be a second opinion, and one day a
    // differing one.
    qualified: !ideal.sound,
    worstSeam,
  }
}
