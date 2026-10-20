-- Applied to the project's built-in automatic-RLS event trigger on 2026-10-21.
-- Keep the event trigger working; remove unnecessary Data API execution grants.
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;
