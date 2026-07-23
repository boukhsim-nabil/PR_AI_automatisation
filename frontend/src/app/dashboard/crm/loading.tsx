export default function CrmLoading() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Chargement du CRM">
      <div className="h-24 animate-pulse rounded-3xl bg-slate-200" />
      <div className="h-20 animate-pulse rounded-3xl bg-white" />
      <div className="h-96 animate-pulse rounded-3xl bg-white" />
    </div>
  );
}
