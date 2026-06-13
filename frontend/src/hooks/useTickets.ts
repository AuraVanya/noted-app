import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export type TicketColumn = "todo" | "in_progress" | "in_review" | "done";

export interface TicketProject {
  key: string;
  name: string;
  iconUrl: string | null;
}

export interface TicketAssignee {
  email: string;
  displayName: string;
  avatarUrl: string | null;
}

export interface TicketListItem {
  key: string;
  summary: string;
  type: string;
  typeIconUrl: string | null;
  priority: string | null;
  priorityIconUrl: string | null;
  status: string;
  column: TicketColumn;
  project: TicketProject;
  assignee: TicketAssignee | null;
  updatedAt: string | null;
}

export interface TicketsResponse {
  projects: TicketProject[];
  tickets: TicketListItem[];
}

export interface TicketComment {
  id: string;
  author: TicketAssignee;
  body: string;
  bodyHtml: string;
  createdAt: string;
  updatedAt: string;
}

export interface TicketDetail extends TicketListItem {
  description: string;
  descriptionHtml: string;
  comments: TicketComment[];
}

export const useTickets = () =>
  useQuery<TicketsResponse, ApiError>({
    queryKey: ["tickets"],
    queryFn: () => api<TicketsResponse>("/api/tickets"),
  });

export const useTicket = (key: string | undefined) =>
  useQuery<TicketDetail, ApiError>({
    queryKey: ["ticket", key],
    queryFn: () => api<TicketDetail>(`/api/tickets/${key}`),
    enabled: !!key,
  });
