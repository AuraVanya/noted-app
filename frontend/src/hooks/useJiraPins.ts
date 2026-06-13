import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

interface PinsResponse {
  projectKeys: string[];
}

export const useJiraPins = () =>
  useQuery<PinsResponse, ApiError>({
    queryKey: ["jira-pins"],
    queryFn: () => api<PinsResponse>("/api/me/jira-pins"),
  });

export const useUpdateJiraPins = () => {
  const queryClient = useQueryClient();
  return useMutation<PinsResponse, ApiError, string[]>({
    mutationFn: (projectKeys) =>
      api<PinsResponse>("/api/me/jira-pins", {
        method: "PUT",
        body: JSON.stringify({ projectKeys }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["jira-pins"], data);
    },
  });
};
