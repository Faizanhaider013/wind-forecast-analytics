// Typed endpoint functions. Query parameters are encoded here so pages never
// build URLs by hand.

import { getJson } from "./client";
import type {
  AccuracyResponse,
  AvailableDatesResponse,
  DecisionResponse,
  HorizonResponse,
} from "./types";

export function getAvailableDates(signal?: AbortSignal): Promise<AvailableDatesResponse> {
  return getJson<AvailableDatesResponse>("/api/available-dates", signal);
}

export function getDecision(
  deliveryDate: string,
  cutoffHour: number,
  signal?: AbortSignal,
): Promise<DecisionResponse> {
  const q = new URLSearchParams({ cutoff_hour: String(cutoffHour) });
  return getJson<DecisionResponse>(
    `/api/decision/${encodeURIComponent(deliveryDate)}?${q}`,
    signal,
  );
}

export function getAccuracy(
  from: string,
  to: string,
  cutoffHour: number,
  signal?: AbortSignal,
): Promise<AccuracyResponse> {
  const q = new URLSearchParams({ from, to, cutoff_hour: String(cutoffHour) });
  return getJson<AccuracyResponse>(`/api/accuracy?${q}`, signal);
}

export function getHorizon(
  from: string,
  to: string,
  cutoffHour: number | null,
  signal?: AbortSignal,
): Promise<HorizonResponse> {
  const q = new URLSearchParams({ from, to });
  if (cutoffHour !== null) {
    q.set("cutoff_hour", String(cutoffHour));
  }
  return getJson<HorizonResponse>(`/api/accuracy/by-horizon?${q}`, signal);
}
