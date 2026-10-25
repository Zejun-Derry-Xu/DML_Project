# ReturnFlow midpoint report

The editable report is now at the repository root:
[returnflow-midpoint.tex](../../returnflow-midpoint.tex).
The approved architecture diagrams are fixed PNGs at the repository root:
[SA.png](../../SA.png) and [TA.png](../../TA.png). Keep both images beside the
`.tex` source when importing the report into Overleaf or another LaTeX editor.
The report uses `graphicx` and non-floating centered images, not TikZ layouts.

GitHub displays `.tex` source but does not automatically compile a PDF preview.
Open the root source in a LaTeX editor to read the typeset report. The previously
tracked PDF was removed to avoid keeping an outdated duplicate; Git history retains it.

The October 25 revision describes the deployed Qwen3 4B checklist prototype,
its service architecture, manual delivery and representative extraction examples.
Current limitations and future API, interaction and evaluation work are summarized
at the end; planned improvements are not presented as completed results.

The image-based source matches the Overleaf version compiled and visually checked
as three pages on October 25. No generated PDF is committed.

The cloud verification record is [the deployment ledger](../checklist-deployment-20261025.md).
Recheck the public URL before submission: shelving stops access, and unshelving
can change the IP-dependent address. Health checks do not establish model quality.

Team: Zejun Xu, Peixuan Ji, Shuchen Liu.

This directory retains supporting notes, not a second report source or PDF.
