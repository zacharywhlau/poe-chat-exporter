"""Persisted GraphQL query hashes for Poe's unofficial API.

These hashes change when Poe redeploys queries. If exports start failing with
PersistedQueryNotFound, update the values here (one-file fix).
"""

QUERIES: dict[str, str] = {
    # Conversation list (sidebar history)
    "ChatHistoryListPaginationQuery": (
        "6ce01455b0201e625489da90c65f87a2809d212ea41ab6e39412b6913990e81f"
    ),
    # Messages within one chat (older pages via startCursor)
    # May be auto-updated at runtime from live browser traffic.
    "ChatListPaginationQuery": (
        "c1a8fd96dd6e0a4679814182951b1e256e175587513c81b223addf931833a625"
    ),
    # Single chat page (fallback when pagination query fails)
    "ChatPageQuery": (
        "e7dcf93e713a35a6b5642496b78339c9ef5ff0ae5e7e0c150ef534a738cced8c"
    ),
}
