# Runbook : suspendre une entreprise

1. Ouvrir `/admin/companies/{id}` avec un compte plateforme nominatif.
2. Vérifier l'entreprise, le plan et l'Owner.
3. Saisir un motif précis, puis confirmer explicitement.
4. Vérifier le statut `suspended` et l'audit `platform.company.suspended`.
5. Confirmer que les nouvelles connexions tenant sont refusées.

La suspension conserve les données mais révoque toutes les `AuthSession` actives.
Les opérations métier et refresh sont alors refusés. Ne jamais supprimer les données
ni modifier le statut directement en SQL.

Pour réactiver, utiliser l'action dédiée. L'entreprise revient à `active` si son
onboarding est terminé, sinon à `onboarding`. Les anciennes sessions restent révoquées ;
chaque utilisateur doit se reconnecter. Contrôler l'audit
`platform.company.reactivated`.
