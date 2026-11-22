import { ApiError, buildUrl, parseApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";

/**
 * Multipart upload with progress (fetch cannot report upload progress). Sends the Supabase
 * access token like api.ts; errors are parsed into the same ApiError shape.
 */
export async function uploadWithProgress<T>(
  path: string,
  formData: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  const url = buildUrl(path);
  const token = await getAccessToken();
  if (!token) throw new ApiError({ status: 401, code: "not_authenticated", message: "You are not signed in." });
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onerror = () =>
      reject(new ApiError({ kind: "network", status: 0, code: "network_error", message: "Upload failed: the API could not be reached." }));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(body as T);
      } else {
        reject(parseApiError(xhr.status, body, xhr.statusText));
      }
    };
    xhr.send(formData);
  });
}

/** Fetch a protected binary (original file / screenshot) with the bearer token and return an object URL. */
export async function fetchBlobUrl(path: string): Promise<{ url: string; type: string }> {
  const token = await getAccessToken();
  if (!token) throw new ApiError({ status: 401, code: "not_authenticated", message: "You are not signed in." });
  let res: Response;
  try {
    res = await fetch(buildUrl(path), { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  } catch {
    throw new ApiError({ kind: "network", status: 0, code: "network_error", message: "The API could not be reached." });
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    throw parseApiError(res.status, body, res.statusText);
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type || res.headers.get("content-type") || "" };
}
