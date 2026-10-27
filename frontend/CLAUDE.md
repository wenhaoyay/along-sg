@AGENTS.md

## Words on screen

Every line a visitor reads is one of three things:

- a **fact about this trip**: a figure, a place, a time, a reason;
- an **action**: a button or a link;
- a **warning**: something that could make the plan wrong ("Hours not
  confirmed", "Sample times").

Nothing else: no taglines, no helper lines under controls, no labels that
repeat what the control or its neighbour already says. If a screen needs a
line to make sense, change the layout instead. For example, the bars carry
their line codes, so the diagram needs no key.

- **Hidden, not deleted, when structure needs it.** A heading that only
  names a section stays as `sr-only` (the outline, screen readers and tests
  find it); words dropped from a control stay in its accessible name.
- **Sentences about a result come from the server** (`why_this_wins`,
  `backend/app/services/explain.py`), which checks every claim against what
  was routed. Do not write a second explanation in the page.
- **`e2e/copy-budget.spec.ts` holds the line.** It counts the visible words
  outside controls on the input screen and on a result, and checks that the
  form fits the first screen at 1280×800 and on a phone. Over budget means
  something to cut. Raise a budget only for a new fact, and name it in the
  commit.
- **Tests find things by role and name** (`getByRole`, `getByLabel`), not by
  sentences, so that changing a word does not break a test.
