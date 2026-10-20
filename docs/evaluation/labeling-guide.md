# Labeling guide: hand-verifying the gold set

How a person turns the silver gold set into hand labels (`gold_hand`). Applies to
`data/gold/gold_set_review.csv`, `eval/build_gold.py --promote` and the `labels` table.

Related: [gold-set datasheet](../data/datasheet-gold-set.md), ADR-0005 (labels and the switch to hand
labels), ADR-0040 (silver labels), ADR-0044 (severity silver rules), ADR-0045 (recall silver rule),
[human review workflow](../hitl/review-workflow.md) (labels from the review queue, a different source).

Status: no row has been hand-labelled yet. Every evaluation result in this repository is agreement with
silver labels.

## 1. Why hand labels

The silver labels copy NHTSA's intake coding and keyword rules. 175 of the 200 gold rows are flagged
`needs_hand_review = true` because their severity came from a keyword rule or the default. Hand labels
measure what a quality engineer would conclude from the complaint text, which is what the triage agent is
asked to do.

## 2. What you label

Open `data/gold/gold_set_review.csv` in a spreadsheet. Each row is one gold complaint. Read
`summary_redacted` and the vehicle, then fill three columns; leave every other column unchanged.

| Column | Value | Rule |
|---|---|---|
| `hand_component` | One canonical component from `components` in `config/settings.yaml`, upper case, exactly as spelled there | The component whose failure the owner describes as the cause. If several are named, pick the one the owner's main safety or usability problem comes from. `OTHER` only when no listed component fits |
| `hand_severity` | `S1`, `S2`, `S3` or `S4` | The rubric in section 3, judged from the text only |
| `hand_recall` | Campaign numbers separated by `\|`, or `NONE` | Only campaigns from `candidate_recalls` whose defect matches what the owner describes. Leave empty if you did not check |
| `reviewer_note` | Free text, optional | Why you disagreed with the silver label, or what was ambiguous |

A row is promoted only when both `hand_component` and `hand_severity` are filled. Partially reviewed files
are fine: unfilled rows stay silver.

## 3. Severity rubric

The same definitions the triage prompt receives (`severity.levels` in `config/settings.yaml`):

| Level | Definition |
|---|---|
| S1 | Critical: crash, fire, injury or death occurred, or total loss of braking, steering or motive power while moving |
| S2 | High: safety-relevant malfunction without an incident (unintended acceleration or braking, intermittent loss of power at speed, ADAS acting on its own, warning of brake or steering failure) |
| S3 | Medium: functional defect that impairs use but is not an immediate safety risk (charging failure, no-start in park, 12V battery drain, camera or display outage) |
| S4 | Low: comfort, cosmetic or convenience issue (rattles, trim, infotainment glitches with no safety impact) |

Judgement rules:

- **Judge the text, not the flags.** The silver S1 rule uses NHTSA's crash and fire flags. If the text
  describes a crash, fire, injury or death, label S1 even when the flags are empty, and say so in
  `reviewer_note`. If a flag is set but the text describes no such event, label from the text and note it.
- **Moving versus parked.** Total loss of power, braking or steering is S1 only while the vehicle is
  moving. The same failure in park or at start-up is S3.
- **Repeated or intermittent** problems take the level of the worst single occurrence described.
- **Recall remedy complaints** (the owner says a recall repair did not fix the problem) take the level of
  the underlying defect.
- **When torn between two levels,** pick the higher one and write both in `reviewer_note`.

## 4. Process

1. Label the 25 S1-by-flag rows and the 75 rows with a silver known recall first; they carry the S1 and
   recall metrics.
2. Label without looking at model predictions. The silver columns are visible in the file; read the text
   before them.
3. Record every disagreement with the silver label in `reviewer_note`; those notes feed rubric changes.
4. For a second reviewer, copy the file, label independently, and compare before promoting. Report
   agreement (Cohen's kappa) for component and severity alongside any result that uses hand labels.

## 5. Promote

```bash
python eval/build_gold.py --promote data/gold/gold_set_review.csv --reviewer <your-name>
```

The command validates every filled value (an unknown component or severity stops it with the row number),
writes `gold_hand` rows to `labels`, replacing earlier hand rows for the same complaints, and adds the hand
fields to `data/gold/gold_set.jsonl`. Re-running after more rows are filled is safe.

Rebuilding the gold set (`python eval/build_gold.py` without `--promote`) does not overwrite a review file
that has any hand label filled; it writes `gold_set_review.new.csv` beside it instead. A rebuild does
rewrite `gold_set.jsonl` without the hand fields, so promote again after any rebuild.

## 6. After promotion

- `eval/run_eval.py` scores against the silver labels only; it does not read `gold_hand` rows yet. Scoring
  against hand labels needs a change to the harness's label loader, then a re-score of every provider on
  gold (stored predictions are reused, so no new model calls are needed).
- Update the gold-set datasheet: the number of hand-labelled rows, agreement with silver labels, and which
  metric is now the headline (ADR-0005, "Revisit when").
- Change the severity rubric only by bumping `silver_rules_version` and recording the change in an ADR.
