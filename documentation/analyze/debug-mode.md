# Debug mode

The `--debug` flag saves all LLM interactions to disk so you can inspect what the pipeline sent and received.

## Usage

```bash
uv run spectral analyze capture.zip -o myapp-api --debug
```

## Output location

Debug files are written to a timestamped directory:

```
debug/<timestamp>/
```

Each LLM call produces a file named `<timestamp>_<step-name>`.

## File contents

All debug files use the same plain text format with labeled sections. Simple calls have a prompt and a response. Calls that use tools include additional sections for each tool invocation between the prompt and the final response.

| Section header | Meaning |
|----------------|---------|
| `=== PROMPT ===` | The full prompt sent to the LLM |
| `=== TOOL: <name>(<input>) ===` | A tool call with its input parameters and the result below |
| `=== ASSISTANT TEXT ===` | Reasoning text the LLM produced between tool calls |
| `=== RESPONSE ===` | The final text response from the LLM |

Reading a file from top to bottom follows the LLM's reasoning process: what it was asked, which tools it called and what it learned, and what it concluded.

## When to use debug mode

Debug mode is useful when:

- The pipeline produces an unexpected base URL and you want to see what the LLM considered
- Endpoint grouping looks wrong and you want to understand the LLM's reasoning
- Auth detection missed the authentication flow
- Enrichment descriptions are inaccurate and you want to see what context the LLM received
- You are developing or tuning pipeline prompts

## Performance impact

Debug mode has negligible performance impact. The files are written synchronously after each LLM call completes and are small (a few KB each). The debug directory can be safely deleted after inspection.
