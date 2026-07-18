# ADR 0003 — Renewal rules are a per-product-line attribute, mapped by plausible behavior

Each `ProductLine` gains a `renewal_rule` (`aep | anniversary | none`): aep=`{medicare_advantage}`;
anniversary=`{medicare_supplement, dental_vision_hearing, health, critical_illness}`;
none=`{final_expense, term_life, whole_life}`. The BRD's Medicare taxonomy (MA/Part D, Hospital
Indemnity/LTC, Life/Annuities) has no matching registry keys, so existing lines are classified by
plausible real-world behavior rather than renamed or extended with new lines — Sunshine alone then
demonstrates all three threads. Chosen over adding BRD-literal product lines (heavy: new seed +
quote templates) and over hard-coding rule sets outside the registry.
Source: tdd-P2.4 §6
