import { expect, type APIRequestContext } from "@playwright/test";

type ContactItem = { id: string; email: string | null };
type ContactPage = { items: ContactItem[] };
type LeadItem = { id: string; contact_id: string };
type LeadPage = { items: LeadItem[] };
type Assignee = { membership_id: string; status: string; role: string | null };

export type Conversation = {
  id: string;
  subject: string | null;
  status: string;
  priority: string;
  human_takeover: boolean;
  unread_count?: number;
  last_message_at?: string | null;
  assigned_membership_id: string | null;
  archived_at: string | null;
  contact?: { id: string } | null;
  lead?: { id: string } | null;
};

export async function seededTenantAData(api: APIRequestContext) {
  const contactsResponse = await api.get("/v1/crm/contacts", {
    params: { search: "samira.e2e@example.com", page_size: 20 },
  });
  expect(contactsResponse.status()).toBe(200);
  const contacts = (await contactsResponse.json()) as ContactPage;
  const contact = contacts.items.find((item) => item.email === "samira.e2e@example.com");
  expect(contact, "Seeded Contact A must exist").toBeTruthy();

  const leadsResponse = await api.get("/v1/crm/leads", {
    params: { search: "samira.e2e@example.com", page_size: 20 },
  });
  expect(leadsResponse.status()).toBe(200);
  const leads = (await leadsResponse.json()) as LeadPage;
  const lead = leads.items.find((item) => item.contact_id === contact!.id);
  expect(lead, "Seeded Lead A must reference Contact A").toBeTruthy();

  const assigneesResponse = await api.get("/v1/crm/assignees");
  expect(assigneesResponse.status()).toBe(200);
  const assignees = (await assigneesResponse.json()) as Assignee[];
  const support = assignees.find(
    (item) => item.role === "support" && item.status === "active",
  );
  expect(support, "Seeded Support A membership must exist").toBeTruthy();

  return { contact: contact!, lead: lead!, support: support! };
}

export async function createConversation(
  api: APIRequestContext,
  subject: string,
  relation?: { contactId: string; leadId: string },
): Promise<Conversation> {
  const response = await api.post("/v1/inbox/conversations", {
    data: {
      channel: "internal",
      subject,
      priority: "normal",
      ...(relation ? { contact_id: relation.contactId, lead_id: relation.leadId } : {}),
    },
  });
  expect([200, 201]).toContain(response.status());
  return (await response.json()) as Conversation;
}

export async function archiveIfPossible(api: APIRequestContext, conversationId: string) {
  const response = await api.post(`/v1/inbox/conversations/${conversationId}/archive`);
  expect([200, 404, 409]).toContain(response.status());
}
