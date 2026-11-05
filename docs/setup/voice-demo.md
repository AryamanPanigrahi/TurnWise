# Voice loop on a laptop (build phase 2)

Goal: ask a question in Kannada or Hindi, get the right answer spoken back,
and see how long each step took and what it cost. The route engine isn't
built yet, so `voice/fake_engine.py` pretends to be it.

Run every command from the repo root.

## Step 1 — a virtual environment

**What:** a private copy of Python for this project, kept in `.venv/`. Packages
you install go there instead of into your system Python, so projects can't
break each other. `.venv/` is in `.gitignore`.

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

(Run `source .venv/bin/activate` again in every new terminal. `deactivate` leaves it.)

## Step 2 — install the project

**What:** `pip install -e ".[dev]"` reads `pyproject.toml`, installs the
dependencies (PyYAML, plus pytest because of `[dev]`), and links the repo in
"editable" mode (`-e`), so code changes take effect without reinstalling.

```bash
pip install -e ".[dev]"
```

```bash
pytest -q
```

All tests should pass. They use fakes, so no network or API key is needed.

## Step 3 — offline demo (no API key)

Type questions, read answers. Nothing leaves your laptop.

```bash
python -m voice.demo --lang kn --offline
```

Try: `ಫ್ಲೈಓವರ್ ಅಥವಾ ಸರ್ವಿಸ್ ರೋಡ್?`, `ಎಡಕ್ಕೆ ಹೋಗಬೇಕಾ ಬಲಕ್ಕೆ?`, `ಮತ್ತೆ ಹೇಳಿ`,
`ಎಷ್ಟು ಹೊತ್ತು?`. Add `--off-route` to pretend you missed a turn, then ask
`ನಾನು ತಪ್ಪು ದಾರಿಯಲ್ಲಿ ಇದ್ದೀನಾ?`.

Each answer is appended to `voice/logs/answers.jsonl` (intent, facts, latency,
cost; never audio).

## Step 4 — real Sarvam speech

**What:** the API key identifies you to Sarvam and is billed. It lives only in
`.env`, which git ignores. Never paste it into code or chat.

```bash
cp .env.example .env
```

Edit `.env` and set `SARVAM_API_KEY=...`. **Before trusting cost numbers**,
check the model names and prices in `voice/config.py` against docs.sarvam.ai
(they were written without access to the docs) and override them in `.env`.

Typed questions, spoken answers (saved to `voice/out/answer.wav`):

```bash
python -m voice.demo --lang hi
```

A recorded question (16 kHz mono WAV works best):

```bash
python -m voice.demo --lang kn --wav my_question.wav
```

## Step 5 — push-to-talk from the mic (optional)

**What:** `sounddevice` talks to your sound card through PortAudio. It's only
needed for this demo, so it isn't in `pyproject.toml`. On Linux you may first
need `sudo apt install libportaudio2`.

```bash
pip install sounddevice
```

```bash
python -m voice.demo --lang kn --mic
```

Press Enter, ask, press Enter again.

## What to look at

- `latency.total` must stay **≤ 1500 ms** for templated questions (rule #3).
  The demo prints `[OVER BUDGET]` when it doesn't. Expect STT to dominate;
  the second time an answer is spoken, TTS is a cache hit (`voice/cache/`).
- `cost` per question. The cost guard prints a warning once a driver passes
  ₹5 in an IST day.
- Wrong intents: copy the transcript into `CASES` in
  `tests/voice/test_intent_router.py`, then fix the keywords in
  `voice/templates/<lang>.yaml`.
