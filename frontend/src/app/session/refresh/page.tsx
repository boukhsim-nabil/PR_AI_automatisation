import { RefreshClient } from "./refresh-client";


export default async function SessionRefreshPage({
  searchParams,
}: {
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const requestedPath = (await searchParams).returnTo;
  const returnTo =
    requestedPath?.startsWith("/") && !requestedPath.startsWith("//")
      ? requestedPath
      : "/dashboard";
  return <RefreshClient returnTo={returnTo} />;
}
