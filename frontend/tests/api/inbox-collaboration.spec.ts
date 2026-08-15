import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { authenticatedApi, e2eIdentities } from "./helpers/auth";
import {
  archiveIfPossible,
  createConversation,
  seededTenantAData,
} from "./helpers/inbox";

test("gère notes, tags, assignees, contexte CRM et résumé déterministe", async ({
  playwright,
}) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const seeded = await seededTenantAData(owner);
  const conversation = await createConversation(
    owner,
    `Collaboration E2E ${randomUUID()}`,
    { contactId: seeded.contact.id, leadId: seeded.lead.id },
  );
  const tagName = `Important ${randomUUID()}`;

  try {
    const createdNoteResponse = await owner.post(
      `/v1/inbox/conversations/${conversation.id}/notes`,
      { data: { body: "Note interne Playwright" } },
    );
    expect(createdNoteResponse.status()).toBe(201);
    const note = (await createdNoteResponse.json()) as {
      id: string;
      body: string;
      archived_at: string | null;
    };
    expect(note.body).toBe("Note interne Playwright");

    const notesResponse = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/notes`,
    );
    expect(notesResponse.status()).toBe(200);
    expect((await notesResponse.json()) as Array<{ id: string }>).toContainEqual(
      expect.objectContaining({ id: note.id }),
    );

    const updatedNote = await owner.patch(`/v1/inbox/notes/${note.id}`, {
      data: { body: "Note interne Playwright modifiée" },
    });
    expect(updatedNote.status()).toBe(200);
    expect(((await updatedNote.json()) as { body: string }).body).toBe(
      "Note interne Playwright modifiée",
    );
    const archivedNote = await owner.post(`/v1/inbox/notes/${note.id}/archive`);
    expect(archivedNote.status()).toBe(200);
    expect(((await archivedNote.json()) as { archived_at: string }).archived_at).toBeTruthy();

    const messages = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/messages`,
    );
    expect(messages.status()).toBe(200);
    expect(
      ((await messages.json()) as { items: Array<{ id: string }> }).items.some(
        (item) => item.id === note.id,
      ),
    ).toBe(false);

    const tagResponse = await owner.post("/v1/inbox/tags", {
      data: { name: tagName },
    });
    expect(tagResponse.status()).toBe(201);
    const tag = (await tagResponse.json()) as { id: string; normalized_name: string };
    expect(tag.normalized_name).toBe(tagName.toLowerCase());
    expect(
      (await owner.post(`/v1/inbox/conversations/${conversation.id}/tags/${tag.id}`)).status(),
    ).toBe(200);
    expect(
      (await owner.post(`/v1/inbox/conversations/${conversation.id}/tags/${tag.id}`)).status(),
    ).toBe(200);

    const summaryWithTag = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/summary`,
    );
    expect(summaryWithTag.status()).toBe(200);
    const summary = (await summaryWithTag.json()) as {
      conversation_id: string;
      note_count: number;
      tags: Array<{ id: string }>;
      contact: { id: string };
      lead: { id: string };
      open_task_count: number;
    };
    expect(summary.conversation_id).toBe(conversation.id);
    expect(summary.note_count).toBe(0);
    expect(summary.tags).toContainEqual(expect.objectContaining({ id: tag.id }));
    expect(summary.contact.id).toBe(seeded.contact.id);
    expect(summary.lead.id).toBe(seeded.lead.id);
    expect(summary.open_task_count).toBeGreaterThanOrEqual(1);

    const crmContext = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/crm-context`,
    );
    expect(crmContext.status()).toBe(200);
    const crm = (await crmContext.json()) as {
      contact: { id: string };
      lead: { id: string };
      tasks: Array<{ id: string }>;
      activities: Array<{ id: string }>;
    };
    expect(crm.contact.id).toBe(seeded.contact.id);
    expect(crm.lead.id).toBe(seeded.lead.id);
    expect(crm.tasks.length).toBeGreaterThanOrEqual(1);
    expect(crm.activities.length).toBeGreaterThanOrEqual(1);

    const assignees = await owner.get("/v1/inbox/assignees");
    expect(assignees.status()).toBe(200);
    const members = (await assignees.json()) as Array<{
      membership_id: string;
      role_code: string;
      email?: string;
    }>;
    expect(members).toContainEqual(
      expect.objectContaining({
        membership_id: seeded.support.membership_id,
        role_code: "support",
      }),
    );
    expect(members.every((item) => item.email === undefined)).toBe(true);

    expect(
      (await owner.delete(`/v1/inbox/conversations/${conversation.id}/tags/${tag.id}`)).status(),
    ).toBe(204);
    const summaryWithoutTag = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/summary`,
    );
    expect(
      ((await summaryWithoutTag.json()) as { tags: Array<{ id: string }> }).tags.some(
        (item) => item.id === tag.id,
      ),
    ).toBe(false);
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
  }
});

test("refuse notes et tags en écriture au Viewer", async ({ playwright }) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const viewer = await authenticatedApi(playwright.request, identities.viewerA);
  const conversation = await createConversation(owner, `Viewer collaboration ${randomUUID()}`);
  try {
    expect(
      (
        await viewer.post(`/v1/inbox/conversations/${conversation.id}/notes`, {
          data: { body: "Interdit" },
        })
      ).status(),
    ).toBe(403);
    expect(
      (await viewer.post("/v1/inbox/tags", { data: { name: "Interdit" } })).status(),
    ).toBe(403);
    expect((await viewer.get("/v1/inbox/assignees")).status()).toBe(403);
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
    await viewer.dispose();
  }
});

test("masque les ressources Tenant A au Tenant B", async ({ playwright }) => {
  const identities = e2eIdentities();
  const ownerA = await authenticatedApi(playwright.request, identities.ownerA);
  const ownerB = await authenticatedApi(playwright.request, identities.ownerB);
  const conversation = await createConversation(ownerA, `Tenant isolation ${randomUUID()}`);
  try {
    expect(
      (await ownerB.get(`/v1/inbox/conversations/${conversation.id}/notes`)).status(),
    ).toBe(404);
    expect(
      (await ownerB.get(`/v1/inbox/conversations/${conversation.id}/crm-context`)).status(),
    ).toBe(404);
  } finally {
    await archiveIfPossible(ownerA, conversation.id);
    await ownerA.dispose();
    await ownerB.dispose();
  }
});

test("exige authentification et crm.read pour le contexte CRM", async ({
  playwright,
  request,
}) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const inboxReader = await authenticatedApi(playwright.request, identities.inboxReaderA);
  const conversation = await createConversation(owner, `CRM permission ${randomUUID()}`);
  try {
    expect(
      (await request.get(`/v1/inbox/conversations/${conversation.id}/notes`)).status(),
    ).toBe(401);
    expect(
      (
        await inboxReader.get(`/v1/inbox/conversations/${conversation.id}/crm-context`)
      ).status(),
    ).toBe(403);
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
    await inboxReader.dispose();
  }
});
