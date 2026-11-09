import axios from "axios";
import type {
  ExecutionResult,
  ImageUploadResponse,
  SessionDetail,
  SessionSummary,
  TransparencyResponse,
} from "./types";

export const PERMANENT_RENDER_URL = "https://satquery-backend-09p3.onrender.com/api/v1";
export const DEFAULT_RENDER_URL = PERMANENT_RENDER_URL;

export function sanitizeApiUrl(url: string | undefined | null): string | null {
  if (!url || !url.trim()) return null;
  const cleaned = url.trim().replace(/\/+$/, "");
  return cleaned.endsWith("/api/v1") ? cleaned : `${cleaned}/api/v1`;
}

export function getEffectiveApiUrl(): string {
  if (typeof window !== "undefined") {
    try {
      const customGpu = localStorage.getItem("satquery_custom_gpu_url");
      if (customGpu === "render" || customGpu === "RENDER_DEFAULT") {
        return PERMANENT_RENDER_URL;
      }
      const cleaned = sanitizeApiUrl(customGpu);
      if (cleaned) return cleaned;
    } catch {}
  }
  const envGpu = sanitizeApiUrl(process.env.NEXT_PUBLIC_GPU_API_BASE_URL);
  if (envGpu) return envGpu;

  const envApi = sanitizeApiUrl(process.env.NEXT_PUBLIC_API_BASE_URL);
  if (envApi && envApi !== PERMANENT_RENDER_URL) return envApi;

  return PERMANENT_RENDER_URL;
}

export function isUsingGpuBackend(): boolean {
  return getEffectiveApiUrl() !== PERMANENT_RENDER_URL;
}

export function setCustomGpuUrl(url: string | null): void {
  if (typeof window === "undefined") return;
  if (!url || !url.trim()) {
    localStorage.removeItem("satquery_custom_gpu_url");
  } else {
    localStorage.setItem("satquery_custom_gpu_url", url.trim());
  }
}

// Generous timeout for deep neural inference
export const apiClient = axios.create({ baseURL: PERMANENT_RENDER_URL, timeout: 6 * 60 * 1000 });

apiClient.interceptors.request.use((config) => {
  config.baseURL = getEffectiveApiUrl();
  return config;
});

// Auto-failover: if GPU server is offline or fails, automatically retry on Render 24/7 backend
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const currentBase = originalRequest?.baseURL || getEffectiveApiUrl();
    if (
      originalRequest &&
      !originalRequest._isRetry &&
      currentBase !== PERMANENT_RENDER_URL &&
      (error.code === "ECONNABORTED" ||
        error.code === "ERR_NETWORK" ||
        !error.response ||
        error.response.status >= 500)
    ) {
      console.warn(
        `[SatQuery Failover] GPU backend (${currentBase}) failed or timed out. Silently falling back to 24/7 Render backend (${PERMANENT_RENDER_URL})`
      );
      originalRequest._isRetry = true;
      originalRequest.baseURL = PERMANENT_RENDER_URL;
      return axios(originalRequest);
    }
    return Promise.reject(error);
  }
);

export async function createSession(title?: string): Promise<SessionSummary> {
  const { data } = await apiClient.post<SessionSummary>("/sessions", { title });
  return data;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const { data } = await apiClient.get<SessionSummary[]>("/sessions");
  return data;
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const { data } = await apiClient.get<SessionDetail>(`/sessions/${sessionId}`);
  return data;
}

export async function renameSession(sessionId: string, title: string): Promise<SessionSummary> {
  const { data } = await apiClient.patch<SessionSummary>(`/sessions/${sessionId}`, { title });
  return data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/sessions/${sessionId}`);
}

export async function uploadImage(sessionId: string, file: File): Promise<ImageUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<ImageUploadResponse>(
    `/images/upload?session_id=${sessionId}`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export async function submitQuery(
  sessionId: string,
  text: string,
  imageIds: string[]
): Promise<{ execution_id: string; status: string }> {
  const { data } = await apiClient.post<{ execution_id: string; status: string }>("/query", {
    session_id: sessionId,
    text,
    image_ids: imageIds,
  });
  return data;
}

export async function getAnalysis(executionId: string): Promise<ExecutionResult> {
  const { data } = await apiClient.get<ExecutionResult>(`/analysis/${executionId}`);
  return data;
}

export async function getTransparency(executionId: string): Promise<TransparencyResponse> {
  const { data } = await apiClient.get<TransparencyResponse>(`/analysis/${executionId}/transparency`);
  return data;
}

export function evidenceImageUrl(storageKey: string): string {
  return `${getEffectiveApiUrl()}/storage/${storageKey}`;
}

export function reportPdfUrl(executionId: string): string {
  return `${getEffectiveApiUrl()}/analysis/${executionId}/report`;
}

export function reportGeoJsonUrl(executionId: string): string {
  return `${getEffectiveApiUrl()}/analysis/${executionId}/geojson`;
}

export interface ModelRegistryEntry {
  model_id: string;
  capability: string[];
  modalities: string[];
  version: string;
  enabled: boolean;
  resource_requirement: string;
  fallback: string | null;
}

export async function listModels(): Promise<ModelRegistryEntry[]> {
  const { data } = await apiClient.get<{ models: ModelRegistryEntry[] }>("/models");
  return data.models;
}

export interface ModelHealth {
  model_id: string;
  status: string;
  is_mock?: boolean;
  version?: string;
  reason?: string;
}

export async function getModelHealth(modelId: string): Promise<ModelHealth> {
  const { data } = await apiClient.get<ModelHealth>(`/models/${modelId}/health`);
  return data;
}

export interface ProviderStatus {
  provider: string;
  status: "healthy" | "unavailable_no_credentials" | "unavailable_error";
  message: string | null;
}

export async function getProviderStatus(): Promise<ProviderStatus[]> {
  const { data } = await apiClient.get<{ providers: ProviderStatus[] }>("/satellite/providers/status");
  return data.providers;
}
