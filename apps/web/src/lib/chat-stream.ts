/** POST a JSON body and consume server-sent events (status / delta / done / error) from the assistant API. */
import { ApiError, buildUrl, parseApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";

export type ChatStreamEvent =
  | { event: "status"; data: { stage: "searching" | "writing" } }
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: unknown }
  | { event: "error"; data: { code: string; message: string; request_id?: string } };

/** Split an SSE buffer into complete events; returns the events and the unconsumed rest. */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(":")) continue; // comment / keep-alive
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

export async function postStream<T>(
  path: string,
  body: unknown,
  opts: { auth?: boolean; signal?: AbortSignal; onEvent?: (e: ChatStreamEvent) => void } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  if (opts.auth) {
    const token = await getAccessToken();
    if (!token) throw new ApiError({ status: 401, code: "not_authenticated", message: "You are not signed in." });
    headers.Authorization = `Bearer ${token}`;
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path), { method: "POST", headers, body: JSON.stringify(body), signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError({ status: 0, code: "network_error", message: "Could not reach the assistant.", kind: "network" });
  }
  if (!res.ok) {
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      /* not JSON */
    }
    throw parseApiError(res.status, payload, res.statusText);
  }
  if (!res.body || !(res.headers.get("content-type") ?? "").includes("text/event-stream")) {
    return (await res.json()) as T; // a proxy that buffers or a non-streaming deployment
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSse(done ? buffer + "\n\n" : buffer);
    buffer = rest;
    for (const e of events) {
      const data = JSON.parse(e.data);
      opts.onEvent?.({ event: e.event, data } as ChatStreamEvent);
      if (e.event === "done") return data as T;
      if (e.event === "error") throw new ApiError({ status: 500, code: data.code, message: data.message });
    }
    if (done) break;
  }
  throw new ApiError({ status: 0, code: "stream_interrupted", message: "The answer was interrupted.", kind: "network" });
}
