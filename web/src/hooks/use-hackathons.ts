"use client";

import useSWR from "swr";
import { fetchHackathons } from "@/lib/api";
import type { Hackathon } from "@/lib/types";

const REFRESH_INTERVAL_MS = 10_000;

export function useHackathons() {
  const { data, error, isLoading, mutate } = useSWR<Hackathon[]>(
    "/api/hackathons",
    fetchHackathons,
    { refreshInterval: REFRESH_INTERVAL_MS },
  );

  return {
    hackathons: data ?? [],
    error,
    isLoading,
    mutate,
  };
}
