# KaushalDub IEEE paper

`kaushaldub_ieee.tex` is an IEEE conference paper (IEEEtran, two columns, target 5 pages, limit 6).

## Compile

Overleaf: New Project → Upload Project → `kaushaldub_paper_overleaf.zip` → Recompile (pdfLaTeX). The zip holds the
`.tex` file and `figures/`. The page count shows in the PDF viewer; if a revision goes over 6 pages, shorten Section II
or merge Fig. 4 into Table IV first.

## Where every number comes from

- `compute_metrics.py` → `metrics.json`: computed from `ml/kaushaldub_model/results.json` (training notebook),
  the dub-check notebook outputs (`dub_check_outputs.zip`), `demo/*check*.json` (step model on unseen videos) and the
  30-video batch database. Re-run it after new experiments and update the tables from `metrics.json`.
- `make_figures.py` → `figures/*.pdf`.

## Before submitting

- Fill in the co-authors and the guide in the author block (placeholders in square brackets).
- The text is newly written from this project's own results, and references are cited where ideas come from other
  work. No tool can guarantee a particular plagiarism or AI-detection percentage. Run it through your university's
  checker, revise passages in your own words where needed, and follow RV University's policy on declaring AI
  assistance (for example in the acknowledgement).
- Check each reference once against Google Scholar or IEEE Xplore (page numbers in particular).
- Facts worth stating in a viva: CLIP + BiLSTM has the highest macro-F1 (44.3); the paper explains why MS-TCN is
  deployed anyway (calibration, size, training time, few-shot/correction memory). There was no listening test; that
  is listed as a limitation.
