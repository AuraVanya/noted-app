import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export interface SeriesContextLink {
  projectContextId: number;
  label: string;
  enabled: boolean;
}

export const useSeriesContextLinks = (seriesId: number | undefined) =>
  useQuery<SeriesContextLink[], ApiError>({
    queryKey: ["series-context-links", seriesId],
    queryFn: () =>
      api<SeriesContextLink[]>(`/api/series/${seriesId}/context-links`),
    enabled: seriesId !== undefined && seriesId > 0,
  });

export const useUpdateSeriesContextLinks = (seriesId: number | undefined) => {
  const queryClient = useQueryClient();
  return useMutation<
    SeriesContextLink[],
    ApiError,
    { links: { projectContextId: number; enabled: boolean }[] }
  >({
    mutationFn: ({ links }) =>
      api<SeriesContextLink[]>(`/api/series/${seriesId}/context-links`, {
        method: "PUT",
        body: JSON.stringify({ links }),
      }),
    onSuccess: (data) => {
      // Push the freshly returned list straight into the cache so the UI
      // updates without a refetch
      queryClient.setQueryData(["series-context-links", seriesId], data);
      // The meetings list flag depends on whether *any* series has an
      // enabled link; refresh it too.
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
  });
};
