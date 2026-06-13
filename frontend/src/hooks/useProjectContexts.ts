import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export interface ProjectContext {
  id: number;
  label: string;
  driveFolderId: string;
  driveFolderUrl: string | null;
  docCount: number;
  createdAt: string;
}

export interface DriveFolderResult {
  id: string;
  name: string;
  url: string | null;
}

export interface CreateProjectContextInput {
  label: string;
  mode: "create" | "existing";
  folderId?: string;
}

export const useProjectContexts = () =>
  useQuery<ProjectContext[], ApiError>({
    queryKey: ["project-contexts"],
    queryFn: () => api<ProjectContext[]>("/api/project-contexts"),
  });

export const useCreateProjectContext = () => {
  const queryClient = useQueryClient();
  return useMutation<ProjectContext, ApiError, CreateProjectContextInput>({
    mutationFn: (input) =>
      api<ProjectContext>("/api/project-contexts", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-contexts"] });
    },
  });
};

export interface DeleteProjectContextResponse {
  id: number;
  driveFolderTrashed: boolean;
  driveFolderId: string;
  driveFolderError: string | null;
}

export const useDeleteProjectContext = () => {
  const queryClient = useQueryClient();
  return useMutation<
    DeleteProjectContextResponse,
    ApiError,
    { id: number; deleteDriveFolder?: boolean }
  >({
    mutationFn: ({ id, deleteDriveFolder = true }) =>
      api<DeleteProjectContextResponse>(
        `/api/project-contexts/${id}?deleteDriveFolder=${deleteDriveFolder}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-contexts"] });
    },
  });
};

export const searchDriveFolders = (q: string) =>
  api<DriveFolderResult[]>(`/api/drive/folders?q=${encodeURIComponent(q)}`);

// --- filing / docs ----------------------------------------------------------

export interface FileItem {
  type: "meeting" | "ticket";
  ref: string;
}

export interface FilingResult {
  type: "meeting" | "ticket";
  ref: string;
  status: "success" | "skipped" | "failed";
  driveDocId: string | null;
  driveDocUrl: string | null;
  error: string | null;
}

export interface FileResponse {
  projectContextId: number;
  results: FilingResult[];
}

export interface FiledDoc {
  id: number;
  itemType: "meeting" | "ticket";
  itemRef: string;
  driveDocId: string | null;
  driveDocUrl: string | null;
  status: "success" | "failed";
  error: string | null;
  trigger: "manual" | "auto";
  createdAt: string;
  updatedAt: string;
}

export const useFiledDocs = (projectContextId: number | undefined) =>
  useQuery<FiledDoc[], ApiError>({
    queryKey: ["project-context-docs", projectContextId],
    queryFn: () =>
      api<FiledDoc[]>(`/api/project-contexts/${projectContextId}/docs`),
    enabled: projectContextId !== undefined && projectContextId > 0,
  });

export const useFileIntoContexts = () => {
  const queryClient = useQueryClient();
  return useMutation<
    FileResponse,
    ApiError,
    { projectContextId: number; items: FileItem[] }
  >({
    mutationFn: ({ projectContextId, items }) =>
      api<FileResponse>(`/api/project-contexts/${projectContextId}/file`, {
        method: "POST",
        body: JSON.stringify({ items }),
      }),
    onSuccess: (_data, variables) => {
      // Refresh the docs list for this context, and the list view's docCounts.
      queryClient.invalidateQueries({
        queryKey: ["project-context-docs", variables.projectContextId],
      });
      queryClient.invalidateQueries({ queryKey: ["project-contexts"] });
    },
  });
};

export interface DeleteFiledDocResponse {
  id: number;
  driveTrashed: boolean;
  driveDocId: string | null;
  driveError: string | null;
}

export const useDeleteFiledDoc = () => {
  const queryClient = useQueryClient();
  return useMutation<
    DeleteFiledDocResponse,
    ApiError,
    { projectContextId: number; docId: number; deleteDriveFile?: boolean }
  >({
    mutationFn: ({ projectContextId, docId, deleteDriveFile = true }) =>
      api<DeleteFiledDocResponse>(
        `/api/project-contexts/${projectContextId}/docs/${docId}?deleteDriveFile=${deleteDriveFile}`,
        { method: "DELETE" },
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["project-context-docs", variables.projectContextId],
      });
      queryClient.invalidateQueries({ queryKey: ["project-contexts"] });
    },
  });
};
