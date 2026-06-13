import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export interface AtlassianIdentity {
  accountId: string;
  email: string;
  displayName: string;
  avatarUrl: string | null;
}

export const useAtlassianIdentity = (enabled: boolean) =>
  useQuery<AtlassianIdentity, ApiError>({
    queryKey: ["atlassian-identity"],
    queryFn: () => api<AtlassianIdentity>("/api/me/atlassian-identity"),
    enabled,
    staleTime: 5 * 60 * 1000, // 5 min — identity doesn't change often
    retry: false,
  });
