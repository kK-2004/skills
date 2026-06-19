# LLM Streaming Patterns

## Common Event Model

Use this Java shape unless the project already has an equivalent DTO:

```java
public record AiStreamChunk(String type, String text, boolean done) {
}
```

All downstream JSON text streams should emit SSE events:

```text
data:{"type":"answer","text":"hello","done":false}

data:{"type":"done","text":"","done":true}

```

Preserve whitespace tokens. Do not skip `content` just because it is blank; only skip `null` or empty strings when the provider truly emitted no content field.

## Choosing the Backend

Choose in this order:

1. Pure reactive Netty + WebFlux: use `Flux`.
2. Servlet/Tomcat with a few SSE endpoints: use `ResponseBodyEmitter` and a named `ThreadPoolTaskExecutor`.
3. Binary, large file, or non-JSON streams: use `StreamingResponseBody`.

If uncertain, ask the user.

## Flux with WebClient

Use this for pure WebFlux/Netty, and it can also work in MVC as Spring's reactive return-value adapter. In MVC, it is not full end-to-end Netty reactive.

```java
@PostMapping(value = "/chat/flux", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<AiStreamChunk> streamFlux() {
    return webClient.post()
            .uri("/v1/chat/completions")
            .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_NDJSON, MediaType.APPLICATION_JSON)
            .header("Authorization", "Bearer " + token)
            .bodyValue(requestBody)
            .retrieve()
            .bodyToFlux(String.class)
            .takeUntil(this::isProviderDone)
            .filter(raw -> !isProviderDone(raw))
            .flatMapIterable(this::parseProviderContent)
            .map(text -> new AiStreamChunk("answer", text, false))
            .concatWith(Mono.just(new AiStreamChunk("done", "", true)));
}
```

Do not wrap a blocking `HttpClient.send()` loop inside `Flux.create()` unless there is no reactive client option. That pattern often buffers, blocks worker threads, and gives worse cancellation behavior.

For macOS Reactor Netty DNS warnings, add the matching runtime dependency:

```xml
<dependency>
    <groupId>io.netty</groupId>
    <artifactId>netty-resolver-dns-native-macos</artifactId>
    <classifier>osx-aarch_64</classifier>
    <scope>runtime</scope>
</dependency>
```

Use `osx-x86_64` on Intel Macs.

## ResponseBodyEmitter for MVC

Use this for Servlet/Tomcat projects when the team wants MVC-style code.

```java
@PostMapping(value = "/chat/emitter", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public ResponseBodyEmitter streamEmitter() {
    ResponseBodyEmitter emitter = new ResponseBodyEmitter(0L);
    streamExecutor.execute(() -> {
        try {
            // Open upstream LLM stream.
            // For each parsed content chunk:
            emitter.send(formatSseJson(new AiStreamChunk("answer", text, false)), MediaType.TEXT_EVENT_STREAM);
            // On normal provider done:
            emitter.send(formatSseJson(new AiStreamChunk("done", "", true)), MediaType.TEXT_EVENT_STREAM);
            emitter.complete();
        } catch (Exception ex) {
            emitter.completeWithError(ex);
        }
    });
    return emitter;
}
```

Configure a named executor:

```java
@Bean
public ThreadPoolTaskExecutor streamExecutor() {
    ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
    executor.setThreadNamePrefix("llm-stream-");
    executor.setCorePoolSize(4);
    executor.setMaxPoolSize(16);
    executor.setQueueCapacity(100);
    executor.initialize();
    return executor;
}
```

Do not use `CompletableFuture.runAsync(...)` without passing this executor.

## StreamingResponseBody

Use this when the output is binary, file-like, or otherwise needs direct `OutputStream` control. For JSON text streams, still emit the common SSE JSON event shape if a browser client consumes it.

```java
@PostMapping(value = "/chat/streamable", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public StreamingResponseBody streamable(HttpServletResponse response) {
    response.setCharacterEncoding(StandardCharsets.UTF_8.name());
    response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("X-Accel-Buffering", "no");

    return outputStream -> {
        // Open upstream LLM stream.
        // For each parsed content chunk:
        outputStream.write(formatSseJson(new AiStreamChunk("answer", text, false)).getBytes(StandardCharsets.UTF_8));
        outputStream.flush();
        response.flushBuffer();
        // On normal provider done:
        outputStream.write(formatSseJson(new AiStreamChunk("done", "", true)).getBytes(StandardCharsets.UTF_8));
        outputStream.flush();
        response.flushBuffer();
    };
}
```

## SSE JSON Formatting

Use a real JSON serializer when the project has one. If not, escape text carefully:

```java
private String formatSseJson(AiStreamChunk chunk) {
    return "data:" + objectMapper.writeValueAsString(chunk) + "\n\n";
}
```

If hand-rolling for a tiny demo, escape backslash, quote, newline, carriage return, and tab.

## Frontend Reader

Use the project's real frontend stack. For Vue 3:

```js
const output = ref("");
const status = ref("idle");

async function startStream(url) {
  output.value = "";
  status.value = "streaming";
  let receivedDone = false;
  let buffer = "";
  const decoder = new TextDecoder("utf-8");
  const response = await fetch(url, { method: "POST" });
  const reader = response.body.getReader();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer = parseSseBuffer(buffer + decoder.decode(value, { stream: true }), event => {
      const chunk = JSON.parse(event);
      if (chunk.done) {
        receivedDone = true;
      } else if (chunk.type === "answer") {
        output.value += chunk.text;
      }
    });
  }

  buffer = parseSseBuffer(buffer + decoder.decode(), event => {
    const chunk = JSON.parse(event);
    if (chunk.done) receivedDone = true;
    else if (chunk.type === "answer") output.value += chunk.text;
  });

  status.value = receivedDone ? "done" : "aborted";
}

function parseSseBuffer(buffer, onEvent) {
  const events = buffer.split(/\r?\n\r?\n/);
  const rest = events.pop();
  for (const eventText of events) {
    const data = eventText
      .split(/\r?\n/)
      .filter(line => line.startsWith("data:"))
      .map(line => line.startsWith("data: ") ? line.slice(6) : line.slice(5))
      .join("\n");
    if (data) onEvent(data);
  }
  return rest;
}
```

Never use `await response.text()` or `await response.json()` for streaming UI; those wait for the full response.
