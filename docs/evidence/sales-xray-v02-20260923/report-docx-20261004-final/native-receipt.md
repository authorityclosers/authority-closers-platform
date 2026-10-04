# AUT-983 final native DOCX verification

The final fictional DOCX renders cleanly into six A4 pages. Analysis fits on page 4, Coaching starts on page 5, and the transcript appendix is page 6. The previously isolated Analysis paragraph is resolved.

- Exact DOCX SHA-256: `870d97ea9c743892949306a14ee0941755a8fe5f2790c6240ceeadf14282a959`; 14,748 bytes. Preview/download byte equality passed at 390×844 and 1440×900.
- All 140 nonempty source paragraphs retained; all three English quotes appear in evidence and the final appendix. Both Devanagari rows render and survive read-back.
- All table cells retained; each complete fixture table stays on one page. Native footers resolve Page 1–6 of 6. No text bounds outside A4.
- All six PNG pages inspected: no clipping, missing glyphs, orphan headings, broken tables or overlapping cells. The final raster files match the inspected files byte for byte.
- Generator implementation commit: `931350e`; body after-spacing 4 pt, Heading 2 before/after 6/4 pt. Font sizes, line spacing, A4, 1.9 cm margins, chapter breaks and report content retained.
- Browser preview run styles now retain the specified Calibri/Arial fallback. Real browser checks verify the fallback, byte equality and Blob reuse on zoom; zero page errors and external requests.
- Portable LibreOffice 24.2.7.2 and Poppler 24.02.0 reproduced from the reviewed support scripts of [AUT-1095](/AUT/issues/AUT-1095). Packages were downloaded and extracted only to run-owned scratch, with no installation, maintainer scripts, root commands, service or host changes.
- Carlito substitutes for unavailable Calibri; Noto Sans Devanagari supplies Devanagari glyphs. Conversion/rasterization/read-back all exit 0. Nonfatal Java/liblangtag warnings are retained in the support logs.

| Page | Content                                        | Result           |
| ---- | ---------------------------------------------- | ---------------- |
| 1    | Title, call details, verdict, chapter list     | Intact           |
| 2    | Overview                                       | Intact           |
| 3    | Moments and English/Devanagari source evidence | Intact           |
| 4    | Analysis, including final inference line       | Fits on one page |
| 5    | Coaching                                       | Intact           |
| 6    | Transcript appendix                            | Final section    |

Word, Google Docs and Pages were not tested. Browser font metrics, automatic overflow pagination and field evaluation can differ from native viewers; the preview and download always use one generated Blob. This receipt verifies file structure and rendering, not product semantics or scoring. No real calls or sample employee report were accessed.
