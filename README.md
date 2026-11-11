# AI Code Review and Test Generation

An AI-assisted code reviewer that does more than guess. For each suspected bug it generates tests, runs them in a
sandbox, and reports whether a test **confirmed** the defect. It also proposes a fix and checks it against the same tests.

Built with FastAPI, LangGraph, ChromaDB (RAG), an MCP tool server (bandit, ruff, ESLint) and any LLM provider
(local Ollama, Groq, OpenAI or Anthropic).

## Features

- **Line-level findings** with the exact source line, a failure scenario and a suggested fix.
- **Confirmed vs. suspected.** A finding is confirmed only when a generated test fails or crashes on the code.
- **Fix verification.** The corrected code is tested against the same tests. A fix counts as verified only if a failing
  test now passes, none still fail, and no passing test breaks.
- **Generated edge-case tests** for normal, boundary, empty, invalid-type and malicious inputs, with a retry when
  the generated tests are invalid.
- **Python and JavaScript** support.
- **Regression mode.** Review the same file again and see which issues are new, fixed or still present.
- **Web page** with colour-coded findings, a Markdown download and print-to-PDF.
- **Evaluation harness** that compares four pipeline variants on a labelled benchmark.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # Windows: copy .env.example .env
uvicorn app.main:app --reload                          # then open http://127.0.0.1:8000
```

The default LLM is [Ollama](https://ollama.com) with a free local model:

```bash
ollama pull qwen2.5-coder:7b
```

To use Groq's free tier instead, set `LLM_PROVIDER=groq` and `GROQ_API_KEY` in `.env`.

Set the model with the provider-specific variable (`OLLAMA_MODEL`, `GROQ_MODEL`, ...). Avoid `LLM_MODEL` while
switching providers: it applies to all of them, so a leftover Ollama name sent to Groq fails with "model not found".
Settings are validated at start-up, so a typo such as `SANDBOX_MODE=dokcer` stops the app with a clear error instead
of silently running tests unsandboxed. `GET /health` reports `sandbox_isolated` and `GET /health/llm` checks the
model connection.

JavaScript review needs Node.js and one extra step: `cd tools/js && npm install`.

Run the offline tests (no API key or model needed):

```bash
python -m pytest
```

## Evaluation

The benchmark has 50 files: 14 clean files and 36 with 42 labelled defects across 8 categories, plus JavaScript
files. Each defect's line number is recorded when the benchmark is built, and findings are matched to defects by line.

```bash
python -m eval.run_eval --modes static_only              # no LLM, runs in seconds
python -m eval.run_eval --runs 1 --limit 10 --no-fix     # quick trial with the configured model
```

The evaluation reports precision, recall and F1, recall per defect category, false alarms on clean files, cost and
time, test-generation quality, and fix-verification rate.

Without any LLM, the static tools alone reach 88% precision and 50% recall on the benchmark, with no false alarms on
clean files. Boundary defects are missed entirely, which is the gap the LLM and generated tests are meant to close.

## Sandbox

Generated tests run in a temporary directory with a per-test and whole-run timeout, and API keys are removed from
their environment.

```bash
python -m eval.sandbox_isolation --mode subprocess
```

The subprocess mode is **not a security boundary**: a test can write to paths outside the sandbox. For stronger
isolation, use the Docker mode, which runs with no network, a read-only root filesystem and limited resources.
Both loading the generated tests (pytest collection, which imports the submitted code) and running them use the
selected mode, and a timeout kills the whole process tree:

```bash
docker build -f Dockerfile.sandbox -t code-review-sandbox .
python -m eval.sandbox_isolation --mode docker
```

## Limitations

- Supports Python and JavaScript only. Each review covers one file.
- A generated test can fail for the wrong reason, so a "confirmed" label is evidence, not proof. Spot-check important results.
- The quality score uses fixed severity weights, so it is only as good as the findings behind it.
- Resource limits in subprocess mode do not apply on Windows.
- The Docker sandbox has not been validated across all platforms (mounted-directory permissions in particular).
- Generated tests are rejected before they run if they have no assertions, forget `import pytest`, call functions that
  do not exist, or cannot be linked to a finding. A test that is itself broken never confirms a defect, but a test with
  a *wrong expectation* still can; this is why "confirmed" is evidence, not proof.
- If static analyzers fail to run, the review carries a warning rather than reporting "no findings".
- The LLM's severity and category labels are not verified.
- The evaluation benchmark is small and was written for this project, except where noted in the benchmark builder.

## Acknowledgements

Structure follows the public reference projects
[Bisma474/github-code-review-agent](https://github.com/Bisma474/github-code-review-agent) and
[JayTheCoder77/rio](https://github.com/JayTheCoder77/rio). The code here is written from scratch.

## Licence

Add a licence before making the repository public.