-- Clinical observations from insole wear-pattern analysis (2026-04-22)
-- Both insoles (ALL DAY brand) showed complete foam blowthrough at the
-- 2nd-3rd metatarsal head zone (bilateral), and asymmetric heel breakdown
-- (right > left), observed after high-frequency pickleball play.

INSERT INTO conditions (id, icd10, name, onset, status, valid_from) VALUES
(
    'obs-forefoot-overload-2026-04-22',
    'M77.40',
    'Forefoot pressure overload risk – bilateral 2nd/3rd metatarsal heads (pickleball insole wear analysis)',
    '2026-04-22',
    'monitor',
    now()
),
(
    'obs-gait-asymmetry-2026-04-22',
    'R26.89',
    'Gait asymmetry – right heel strike dominant vs left (insole wear analysis, right heel breakdown greater than left)',
    '2026-04-22',
    'monitor',
    now()
)
ON CONFLICT (id) DO NOTHING;

-- Sport context and footwear follow-up flags
INSERT INTO athlete_profile (key, value) VALUES
    ('primary_sport',             'pickleball'),
    ('footwear_insole_brand',     'ALL DAY (OTC, general-purpose)'),
    ('footwear_assessment_date',  '2026-04-22'),
    ('footwear_recommendation',   'Court-specific insole with metatarsal pad/dome; formal pedobarograph if forefoot pain develops; palpate 2nd-3rd MTP joints at next visit'),
    ('pickleball_load_note',      'High-frequency play — forefoot/metatarsal stress risk is cumulative; monitor for metatarsalgia, callus at 2nd-3rd MTP, or stress reaction')
ON CONFLICT (key) DO UPDATE SET value = excluded.value;

INSERT INTO schema_version (version) VALUES (4) ON CONFLICT DO NOTHING;
