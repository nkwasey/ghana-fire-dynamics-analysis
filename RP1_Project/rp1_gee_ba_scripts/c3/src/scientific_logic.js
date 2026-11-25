/* RP1 c3: pure logical expressions shared by Earth Engine and synthetic tests. */
// ==================== EXCLUSIVE EVIDENCE STATES AND OVERLAPPING FLAGS ====================
function c3ClassifyEvidence(O, p) {
  // Missingness is retained separately from filled numeric values. One source
  // image has already been admitted; this function does not mosaic images.
  var qaMissing = O.not(p.qaAvailable);
  var burnMissing = O.and(p.qaAvailable, O.not(p.burnAvailable));
  var supported = O.and(O.and(p.qaAvailable, p.burnAvailable), O.and(p.land, p.valid));
  // A positive anomaly is evaluated even when the QA land/valid bits fail.
  // outOfRange includes negatives as a reason; the positive condition here
  // restricts anomalies to positive values above 366 or conflicting codes.
  var anomaly = O.and(O.and(p.qaAvailable, p.burnAvailable),
    O.and(p.positive, O.or(p.outOfRange, p.special)));
  var accepted = O.and(O.and(supported, p.positive), O.not(anomaly));
  var explicitZero = O.and(O.and(supported, p.zero), O.not(p.special));
  var unsupported = O.and(O.and(p.qaAvailable, p.burnAvailable),
    O.not(O.or(accepted, explicitZero)));
  return {
    qa_missing: qaMissing,
    burndate_missing: burnMissing,
    unsupported: unsupported,
    explicit_zero: explicitZero,
    accepted: accepted,
    anomaly: anomaly,
    flag_qa_missing: O.not(p.qaAvailable),
    flag_burndate_masked: O.not(p.burnAvailable),
    flag_qa_nonland: O.and(p.qaAvailable, O.not(p.land)),
    flag_qa_invalid: O.and(p.qaAvailable, O.not(p.valid)),
    flag_shortened: O.and(p.qaAvailable, p.shortened),
    flag_special: O.and(p.qaAvailable, p.special),
    flag_positive_special: O.and(O.and(p.qaAvailable, p.burnAvailable), O.and(p.positive, p.special)),
    flag_unexpected_burndate: O.and(p.burnAvailable, p.outOfRange)
  };
}
// ==================== PERIOD UNION ELIGIBILITY ====================
function c3DomainLogic(O, years) {
  if (!years.length) throw new Error('At least one land-cover year is required.');
  var eligible = years[0].eligible;
  var unknown = years[0].unknown;
  for (var i = 1; i < years.length; i++) {
    eligible = O.or(eligible, years[i].eligible);
    unknown = O.or(unknown, years[i].unknown);
  }
  return {
    eligible: eligible,
    unresolved: O.and(O.not(eligible), unknown),
    excluded: O.and(O.not(eligible), O.not(unknown)),
    any_unknown_year: unknown
  };
}
// ==================== SOURCE COUNT ADMISSION ====================
function c3Admission(counts) {
  var out = [];
  for (var i = 0; i < counts.length; i++) {
    if (counts[i] === 0) out.push('MISSING');
    else if (counts[i] === 1) out.push('ADMITTED');
    else out.push('AMBIGUOUS_MULTIPLE');
  }
  return out;
}
