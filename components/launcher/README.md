# BacklotOS Launcher

The Launcher is the non-technical entry point for BacklotOS. A user supplies a
publicly reachable novel URL or uploads an ebook, chooses production type,
visual format (live action or animation), episode count, episode duration, and
aspect ratio, then starts the pipeline.

```bash
backlotos start
```

The browser form supports URL import and `.txt`, `.md`, `.html`, `.pdf`,
`.epub`, and `.docx` uploads. It stores an immutable source copy, normalized
text, SHA-256 provenance, an episode plan, and append-only events. It never
publishes finished media.

For a novel index URL, the importer recognizes same-book chapter links, follows
the formal full-directory order, fetches at most four pages concurrently with
retry/backoff, removes duplicate chapter bodies, and records URL/SHA provenance
for every stored page. A partial crawl blocks Story Agent generation.

The default page is a persistent production workbench showing every project's
stage, every episode's story/visual/media/edit/review state, source-import
progress, and append-only consumed/refunded/net credit totals.

Command-line automation is also available:

```bash
backlotos create --file novel.pdf --type short_drama --visual live_action \
  --episodes 200 --episode-minutes 3 --aspect 9:16
backlotos status /path/to/project
backlotos run /path/to/project
```

If no Story Agent model backend is configured, the project remains safely in
`WAITING_FOR_MODEL`; the import and episode plan remain complete and resumable.
