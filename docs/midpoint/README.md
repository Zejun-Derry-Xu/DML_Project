# ReturnFlow midpoint check-in report

This directory contains an English LaTeX draft for DSAN 6700 Deliverable 2.
`returnflow-midpoint.tex` is the editable source of truth. The compiled PDF is
`output/pdf/returnflow-midpoint.pdf`; both architecture diagrams are native TikZ
inside the source, so there are no external figure assets to lose or regenerate.

## Scope and evidence

- Six pages: project/status; solution architecture; technical architecture;
  prototype/API/analytic; CI/CD and recovery; evaluation/limits/next steps.
- Recorded installed candidate: `847c7b31785f69afc1b440df6d211b0cceee5848`.
- Implementation snapshot described: `073f31b573f2bafdecce3fd22163c1f4ce7a0dc8`.
  Source links are pinned to this snapshot, not to a moving branch.
- Candidate CI/publication: <https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40016963668>.
- Snapshot CI: <https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40035335912>.
- The normal installed workflow is guided; Qwen trials and the opt-in harness are
  not represented as a qualified production deployment.
- No private raw evaluations, numeric operational model results, secrets, IP
  addresses, private backup paths or infrastructure credentials are included.
- This is a documentation change only. No application code, cloud configuration,
  database, model process or user-owned evaluation files are changed.

## Required edits before submission

1. **Team roster:** confirm `\TeamMembers` and remove/update `\TeamRosterNote`.
   Only Zejun (Derry) Xu is currently known; other names are not invented.
2. **Application URL:** replace `\ApplicationURL` after instructor access is
   actually tested. Neither a loopback address nor the presence of a public IP
   proves external reachability. Leave database and model services private.
3. Confirm the running release and demo path; update `\DeployedCommit` and the
   status statements if a different release is deployed. Do not merely substitute
   a commit string while leaving incompatible claims unchanged.
4. Recheck branch-protection, rollback and release-note status; these are pending
   as of the recorded snapshot, not permanent statements about the project.
5. Decide how the proposed model/analytic is demonstrated, explicitly distinguishing
   guided behavior from experimental real-model behavior. Mocking permission does
   not mean an unimplemented model can be described as deployed.
6. Confirm the course's generative-AI use/disclosure requirements. Remove the
   working-draft banner only after outstanding submission items are resolved.

No new external endpoint should be made public automatically to finish this report.

## Compile and inspect

The document uses standard LaTeX/TikZ packages and fits a single-file LaTeX editor.
The Codex built-in LaTeX compiler can check the saved `.tex` source without a local
TeX installation. For a local exported PDF with Tectonic, run from the repository:

```bash
mkdir -p docs/midpoint/output/pdf
tectonic --outdir docs/midpoint/output/pdf docs/midpoint/returnflow-midpoint.tex
pdfinfo docs/midpoint/output/pdf/returnflow-midpoint.pdf
```

Alternatively run `latexmk -pdf` in an environment with the required packages.
Render the resulting PDF with Poppler and inspect all six pages after edits;
check node labels/arrows, page count, links, tables, overflow and draft markers.
The PDF should not be submitted as-is while URL/roster items are pending.

## Course alignment

The instructor-provided Deliverable 2 brief requires one PDF containing both
solution and technical architecture diagrams, a GitHub URL, a Jetstream2 app URL,
all team names, and an accessible basic input/output prototype. The solution
diagram covers Process, Execution and State; the technical diagram describes
real components, request flow, persistence and delivery boundaries. The supplied
course PDFs are not redistributed in this public repository.
