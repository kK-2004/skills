---
name: llm-streaming-response
description: Build front-end and back-end LLM streaming response flows. Use when Codex needs to implement or refactor AI chat streaming, SSE, Streamable HTTP-style POST streaming, Spring MVC ResponseBodyEmitter, StreamingResponseBody, Spring WebFlux Flux, Reactor Netty, WebClient upstream LLM streams, or browser/Vue/React front-end code that reads and renders streamed LLM chunks.
---

# LLM Streaming Response

Use this skill to implement LLM streaming end to end with a consistent backend protocol and a frontend that renders chunks incrementally.

Before coding, inspect the project stack and ask the user which backend method they want if it is not already clear. Prefer this decision order:

1. If the project is pure reactive, Netty + WebFlux, choose `Flux`.
2. If the project is traditional Servlet/Tomcat with only a few SSE endpoints, choose `ResponseBodyEmitter`; configure and inject a `ThreadPoolTaskExecutor` for async work instead of using the default `CompletableFuture` common pool.
3. If the stream is binary, large file, or non-JSON output, choose `StreamingResponseBody`.

Read [references/patterns.md](references/patterns.md) before implementing the backend or frontend.

## Protocol

Use the same downstream event shape for every JSON text LLM stream:

```text
data:{"type":"answer","text":"。","done":false}

data:{"type":"done","text":"","done":true}

```

The frontend must treat `done:true` as the only normal completion signal. If the HTTP stream closes before `done:true`, show a broken/aborted connection state.

Do not expose provider-native chunks directly to the browser. Parse upstream provider data, normalize it to the event shape above, and preserve whitespace tokens.

## Backend Workflow

1. Detect whether the server is MVC/Tomcat or pure WebFlux/Netty by checking dependencies, application type, and startup logs.
2. Ask the user which method to use if their preference is not explicit.
3. Normalize LLM chunks into `{type,text,done}` events.
4. Send events as `text/event-stream` using `data:<json>\n\n`.
5. Send exactly one terminal `done:true` event on normal completion.
6. Handle cancellation and errors without emitting fake done events.
7. Verify with `curl -N` and the actual browser frontend.

## Frontend Workflow

Implement the frontend in the project's actual stack, such as Vue 3, React, or static HTML. Use `fetch` with `response.body.getReader()` for POST-based streams.

The reader must:

- Incrementally decode UTF-8 with `TextDecoder`.
- Buffer partial SSE events until `\n\n` or `\r\n\r\n`.
- Parse only `data:` lines.
- Parse JSON payloads into `{type,text,done}`.
- Append `text` exactly as-is for `type:"answer"`.
- Preserve spaces, tabs, and newlines.
- Mark completion only after `done:true`.
- Report a connection break if the stream closes before `done:true`.

For Vue 3, store output in a `ref("")`, append chunks to `.value`, and use a request-local `receivedDone` flag.

## Validation

Always verify:

- The backend compiles and tests pass.
- The response `Content-Type` is `text/event-stream`.
- Browser rendering is incremental, not buffered until completion.
- Markdown-like whitespace is preserved.
- The frontend sees `done:true`; missing done is treated as interruption.
