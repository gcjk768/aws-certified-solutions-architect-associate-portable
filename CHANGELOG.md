# Changelog

## 2026-11-10
- New: SAA-C03 bot folder, cloned from the SAP-C03 bot (four SAA-C03 domains 30/26/24/20, pass 720).
- `build_csv.py` merges `banks/` (public) and `sources/` (private) into `data/questions.csv` + `data/domains.json` with stable ids.
- Served by the exam portal's second container `exam-portal-sg` at `/saa/`.
