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
    "ChatListPaginationQuery": (
        "c1a8fd96dd6e0a4679814182951b1e256e175587513c81b223addf931833a625"
    ),
}
