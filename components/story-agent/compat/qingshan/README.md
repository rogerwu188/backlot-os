# Project compat layer (青山) — de-identified only

This directory is the ONLY place project-specific adaptation may live, and it must
contain **no copyright text** from the source novel/scripts.

- Allowed: de-identified structural fixtures (generic names), a field-mapping note
  showing how project canon is passed into `spec.canon` at call time.
- Forbidden: 原著/剧本 verbatim text, character-name-bearing plot, palettes tied to the IP.

Real 《青山》 canon is supplied by the project repo at runtime via the `spec.canon`
argument; it is never copied into this generic package.
