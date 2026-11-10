# AWS Certified Solutions Architect – Associate (SAA-C03) Portable

Self-hosted study bot and question bank for the AWS Certified Solutions Architect – Associate exam (SAA-C03: 65 questions, 130 minutes, pass 720/1000). It is the SAA sibling of [aws-certified-solutions-architect-professional-portable](https://github.com/gcjk768/aws-certified-solutions-architect-professional-portable): the same `bot.py` (Telegram quiz, Claude tutor with AWS-icon diagrams, weekly readiness report), with the four SAA-C03 domains and weights.

In practice it is served on the web by [exam-portal](https://github.com/gcjk768/exam-portal) (container `exam-portal-sg`, link `/saa/`), which imports this `bot.py` and shares its `data/state.json`.

## Domains (exam guide)

| Domain | Weight |
|---|---|
| Design Secure Architectures | 30% |
| Design Resilient Architectures | 26% |
| Design High-Performing Architectures | 24% |
| Design Cost-Optimized Architectures | 20% |

The predicted score weights each domain's first-try accuracy by these numbers, on the 1000 scale.

## Bank

```sh
python -I build_csv.py     # banks/*.csv + sources/*_bank.csv -> data/questions.csv + data/domains.json
python test_bot.py
```

- `banks/` — committed: AWS official sample questions and open-licensed community items (each row names its source). No exam dumps: ExamTopics-style "most-voted answer" collections are excluded on purpose, because using them breaks the AWS certification agreement.
- `sources/` — private and gitignored: the owner's own paid practice tests (e.g. Tutorials Dojo, parsed by `parse_td.py`). The portal hides these from its public link (`PUBLIC_HIDDEN_SOURCES`).

Ids stay stable across rebuilds (matched by stem), so progress survives a bank refresh.

## Run as a Telegram bot (optional)

Copy `bot.env.example` to `bot.env`, fill in the token from @BotFather and your user ID, then `docker compose up -d --build`.

## License

MIT for the code. Question rows keep their source's licence; they are practice items, not real exam questions.
