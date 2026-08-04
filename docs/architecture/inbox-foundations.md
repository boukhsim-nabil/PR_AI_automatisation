# Fondations de l’Inbox M3.1

M3.1 livre uniquement la persistance, les invariants de domaine, les schémas et
les contrôles de sécurité. Il ne publie aucune route Inbox.

## Couches

1. Les modèles SQLAlchemy décrivent les sept tables et leurs enums stables.
2. Alembic installe les contraintes, index, permissions et policies RLS.
3. Les services de domaine appliquent les transitions et modifient les objets
   dans la transaction fournie, sans effectuer de commit.
4. Les schémas Pydantic séparent les commandes publiques, les commandes internes
   et les projections de lecture.
5. PostgreSQL constitue la dernière barrière avec les FK composites, CHECK,
   index uniques tenant-aware et RLS forcé.

Les schémas publics refusent les champs supplémentaires et ne contiennent aucun
`company_id`. Les lectures n’exposent ni metadata interne, ni message d’erreur
technique complet, ni `storage_key`, checksum, secret ou token.

## Hors périmètre

Les routes publiques, le frontend, Gmail, WhatsApp, le stockage de fichiers,
MinIO/S3, n8n et les agents IA sont explicitement absents. Les futurs adapters
devront appeler les mêmes services dans une transaction authentifiée et traduire
les erreurs de domaine vers le protocole concerné.
