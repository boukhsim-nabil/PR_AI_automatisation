# Isolation multi-tenant de l’Inbox

Les sept tables Inbox portent un `company_id` obligatoire :

- `conversations` ;
- `messages` ;
- `conversation_participants` ;
- `conversation_notes` ;
- `conversation_tags` ;
- `conversation_tag_links` ;
- `message_attachments`.

Toutes activent et forcent PostgreSQL Row-Level Security. Les policies comparent
`company_id` à la variable transactionnelle `app.current_company_id`. Sans
contexte, les lectures ne retournent aucune ligne et les écritures sont refusées.
`SET LOCAL` garantit l’effacement du contexte au commit ou rollback et empêche sa
fuite lors de la réutilisation d’une connexion du pool.

Toutes les relations métier sont des clés étrangères composites contenant
`company_id`. Cette défense interdit notamment de rattacher une conversation à un
contact, lead ou membership étranger, un message à une autre conversation, un tag
à une conversation étrangère ou une pièce jointe à un message étranger.

`automation_app` ne possède ni `SUPERUSER`, ni `BYPASSRLS`, ni privilège de
suppression sur ces tables. `automation_migrator` reste le rôle technique séparé.
Les services filtrent également par tenant, mais ne remplacent jamais RLS.
