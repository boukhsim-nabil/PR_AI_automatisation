export type LeadStatus =
  | "new"
  | "to_qualify"
  | "qualified"
  | "appointment_scheduled"
  | "proposal_sent"
  | "won"
  | "lost"
  | "archived";

export type LeadPriority = "low" | "medium" | "high";
export type TaskPriority = LeadPriority | "urgent";
export type TaskStatus = "todo" | "in_progress" | "completed" | "cancelled";

export type Contact = {
  id: string;
  first_name: string | null;
  last_name: string;
  email: string | null;
  phone: string | null;
  job_title: string | null;
  organization_name: string | null;
  language: string;
  status: "active" | "inactive" | "archived";
  consent_email: boolean;
  consent_whatsapp: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type LeadListItem = {
  id: string;
  contact_id: string;
  title: string;
  contact_first_name: string | null;
  contact_last_name: string;
  contact_email: string | null;
  organization_name: string | null;
  score: number;
  priority: LeadPriority;
  status: LeadStatus;
  source: "manual" | "form" | "email" | "whatsapp" | "referral" | "api";
  assigned_membership_id: string | null;
  next_action: string | null;
  next_action_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Lead = LeadListItem & {
  contact: Contact;
  need_description: string | null;
  estimated_budget: string | null;
  currency: string;
  urgency: "low" | "medium" | "high" | "critical";
  lost_reason: string | null;
  archived_at: string | null;
};

export type LeadPage = {
  items: LeadListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type CrmSummary = {
  total_leads: number;
  new_leads: number;
  qualified_leads: number;
  won_leads: number;
  overdue_tasks: number;
};

export type CrmActivity = {
  id: string;
  contact_id: string | null;
  lead_id: string | null;
  actor_membership_id: string | null;
  activity_type: string;
  subject: string;
  description: string | null;
  metadata: Record<string, unknown>;
  occurred_at: string;
  created_at: string;
};

export type CrmTask = {
  id: string;
  lead_id: string | null;
  contact_id: string | null;
  title: string;
  description: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  assigned_membership_id: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type Assignee = {
  membership_id: string;
  display_name: string | null;
  status: string;
  role: string | null;
};

export const statusLabels: Record<LeadStatus, string> = {
  new: "Nouveau",
  to_qualify: "À qualifier",
  qualified: "Qualifié",
  appointment_scheduled: "Rendez-vous planifié",
  proposal_sent: "Proposition envoyée",
  won: "Gagné",
  lost: "Perdu",
  archived: "Archivé",
};

export const priorityLabels: Record<LeadPriority, string> = {
  low: "Faible",
  medium: "Moyenne",
  high: "Haute",
};
