import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export interface Me {
  id: number;
  email: string;
  displayName: string;
  avatarInitials: string;
  connections: {
    google: boolean;
    atlassian: boolean;
  };
}

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => api<Me>("/api/me"),
  });
}
