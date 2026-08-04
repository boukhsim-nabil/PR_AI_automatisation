# Cycle de vie des messages

Le cycle de livraison autorisé est :

```text
draft → queued → sent → delivered → read
   └──────────────┐
queued ───────────┴→ failed
```

- Seul un brouillon est modifiable.
- `draft` et `queued` peuvent passer à `failed`.
- `sent`, `delivered`, `read` et `received` sont immuables dans le service.
- Un message `internal` ne peut pas entrer dans le cycle de livraison client.
- Une réception crée directement un message `received`.
- Un `system_event` passe par la commande interne dédiée et ne peut pas être créé
  avec `MessageDraftCreate`.
- `reply_to_message_id` est vérifié dans le même tenant et la même conversation,
  puis protégé à nouveau par la FK composite PostgreSQL.

`body_html` est une entrée non fiable. `MessageRead` expose explicitement
`html_requires_sanitization=true` lorsque du HTML est présent. Aucun consommateur
ne doit rendre ce contenu sans une bibliothèque de sanitisation adaptée.

Les connecteurs Email et WhatsApp, la livraison réseau et les retries ne font pas
partie de M3.1.
