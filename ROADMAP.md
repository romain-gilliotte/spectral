# Roadmap

## Tracker and third-party noise filtering

Captures are polluted by trackers, debug tools, A/B testing, ads, analytics, etc. (Datadog, Sentry, Google Analytics, LinkedIn Ads, usejimo...). These traces are pure noise for analysis: they waste tokens and mislead the LLM.

The idea is to reuse standard adblocker filter lists (EasyList, EasyPrivacy) to automatically filter out these requests at capture time, both in the MITM proxy and in the Chrome extension listener. A shared helper centralizes the logic, both capture paths call it.

## MCP request error recovery

The auto-correction mechanism is already implemented for login and works very well. The goal is to generalize it to all MCP server requests: when a generated tool fails at execution, Spectral corrects its definition and retries.

The `--auto-correct-attempts=N` option on `spectral mcp stdio` controls how many correction attempts are made before giving up.

## Community tool catalog

Creating and testing tools is laborious. Once a user has working, validated tools, they should be able to publish them for others to use.

- `spectral catalog login` / `spectral catalog logout` for authentication
- `spectral catalog publish <app>` publishes a tool collection
- `spectral catalog search <app or domain>` finds the most popular public collections
- `spectral catalog install <user>/<app>` installs a published tool collection locally
- A dedicated GitHub repo hosts the definitions: each addition goes through a reviewed pull request before becoming available
- Tools are scoped per user but public (security implications), which requires a website to browse them
- When a published tool fails, Spectral reports it back to the central server

## Auth extract with refresh token discovery

`auth extract` currently grabs auth headers from captured traffic, but the extracted tokens expire and aren't renewable. The idea is to use the LLM to also find a refresh token in the captured traces, so that `auth extract` produces a renewable token out of the box — no need to fall back to `auth analyze` + `auth login`.

## Request template engine improvements

The current tool definition format is too minimalistic for complex protocols (e.g. Algolia). It needs to support transformations on parameters and responses, while keeping the format simple and declarative. No request chaining, but the ability to transform data between the MCP call and the underlying HTTP request.

## OpenClaw integration

Provide an OpenClaw skill or plugin to showcase the synergy between the two tools. The exact format (skill vs plugin) depends on OpenClaw's architecture.

## Multi-provider LLM support

Spectral currently only supports the Anthropic API. Add support for OpenAI and OpenRouter to avoid locking users into a single provider. The `spectral config` command should allow choosing the provider and model.
