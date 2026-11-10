-- Questions were retired as REFUTED whenever the point estimate pointed the
-- wrong way, however wide its range. lab._gate_refuted now requires the range
-- to rule out the hypothesised effect. Re-open every question retired on a
-- refutation so it runs again under that gate and earns its answer.
UPDATE lab_questions
SET enabled = TRUE, retired_at = NULL
WHERE retired_at IS NOT NULL
  AND id IN (
      SELECT question_id FROM (
          SELECT question_id, verdict,
                 ROW_NUMBER() OVER (PARTITION BY question_id ORDER BY run_at DESC) AS rn
          FROM lab_findings
      ) WHERE rn = 1 AND verdict = 'refuted'
  );
