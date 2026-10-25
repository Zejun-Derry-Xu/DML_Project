# ReturnFlow midpoint check-in report

This directory contains an English LaTeX draft for DSAN 6700 Deliverable 2.
`returnflow-midpoint.tex` is the editable source of truth. The compiled PDF is
`output/pdf/returnflow-midpoint.pdf`; both architecture diagrams are native TikZ
inside the source, so there are no external figure assets to lose or regenerate.

**2026-10-25 concise rewrite:** the report now prioritizes two architecture diagrams,
the Process / Execution / State table, and a short interaction example. The selected
target is Qwen3 4B with the checklist-led conversation, not the earlier individual
questions or the deployment template's default 8B. The source and exported PDF are
updated together. The newest local candidate is NOT yet cloud-verified; the historical
HTTPS entry is explicitly labelled and must be rechecked before submission.

## Scope and evidence

- Three pages: solution architecture and design table; technical architecture and
  request/API flow; prototype example, delivery/testing and evidence limits.
- Confirmed team: Zejun Xu, Peixuan Ji, Shuchen Liu.
- Current diagram describes local `e835d76` plus uncommitted candidate changes,
  including checklist declarations and the extraction 2.1 candidate. Historic source
  and cloud commit evidence below must not be treated as validation of these changes.
- Recorded installed candidate: `847c7b31785f69afc1b440df6d211b0cceee5848`.
- Implementation snapshot described: `073f31b573f2bafdecce3fd22163c1f4ce7a0dc8`.
  Source links are pinned to this snapshot, not to a moving branch.
- Candidate CI/publication: <https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40016963668>.
- Snapshot CI: <https://github.com/Zejun-Derry-Xu/DML_Project/actions/runs/40035335912>.
- The normal installed workflow is guided; Qwen trials and the opt-in harness are
  not represented as a qualified production deployment.
- No private raw evaluations, numeric operational model results, secrets, private
  backup paths or infrastructure credentials are included. The explicitly requested
  public application URL contains the current VM IP as part of its proxy hostname.
- The October 24 access change makes only the Nginx binding configurable. The cloud
  frontend was recreated with its unchanged tested image and public binding. API
  loopback binding, database/model exposure and extraction mode were not changed.
  Browser acceptance created one fictional unfinished case; no RMA was submitted.

## Required edits before submission

1. **Team roster:** confirmed as Zejun Xu, Peixuan Ji, Shuchen Liu. Recheck spelling
   with the team before the final submission.
2. **Application URL:** HTTPS interaction was verified on October 24 at
   <https://http-149-165-174-228-5173.proxy-js2-iu.exosphere.app/> without an SSH
   tunnel. Recheck it before submission; shelving stops the VM and unshelving may
   change the IP-dependent hostname. Do not use the raw IP/HTTP link for the current
   interactive UI. Leave database and model services private.
3. Confirm the running release and demo path; update the deployment evidence and
   status statements if a different release is deployed. Do not merely substitute
   a commit string while leaving incompatible claims unchanged.
4. Recheck branch-protection, rollback and release-note status; these are pending
   as of the recorded snapshot, not permanent statements about the project.
5. Deploy the selected 4B/checklist candidate only after its matching checks and
   real-model cloud acceptance. Explicitly set `LLM_MODEL=qwen3:4b` and LLM mode in
   the private operator config; do not assume the template already selects 4B or
   bypass `deploy_release.py`'s qualification gate. Benchmark work is paused, not
   replaced by an unsupported claim of model qualification.
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
Render the resulting PDF with Poppler and inspect all three pages after edits;
check node labels/arrows, page count, links, tables, overflow and draft markers.
The PDF should not be submitted as-is while URL/roster items are pending.

## Course alignment

The instructor-provided Deliverable 2 brief requires one PDF containing both
solution and technical architecture diagrams, a GitHub URL, a Jetstream2 app URL,
all team names, and an accessible basic input/output prototype. The solution
diagram covers Process, Execution and State; the technical diagram describes
real components, request flow, persistence and delivery boundaries. The supplied
course PDFs are not redistributed in this public repository.
