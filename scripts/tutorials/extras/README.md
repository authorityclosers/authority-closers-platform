# Tutorials extras

Helpers around the v2 pipeline, run on ac:

- `whatsapp_nudges.py <out>`: WhatsApp messages for Play testers, day 1/3/7/14, in English, Hindi and Marathi (and
  Roman script), with the Alpha opt-in link; `whatsapp_docx.py <out>` (through `uv run --with python-docx`) adds
  Word copies. Only `{name}` is filled in by the sender; no tester's details live here.
- `channel_art.py <out>`: YouTube banner (2560x1440, logo inside the safe area) and avatar (800x800), brand B. Run
  from the workbench as acdev.
- `pulse_tutorials.py [--commit]`: keeps AC's Pulse Work project "Tutorials v2" in step with the coverage map through
  the AC task route. It is dry unless `--commit`; the project and task ids live in `~/sx-tut/pulse-tutorials.json`,
  and existing tasks are only updated by id (the route's `ensure` makes copies when run again).
