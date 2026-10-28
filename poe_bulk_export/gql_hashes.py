"""Persisted GraphQL query hashes for Poe's unofficial API.

Poe changes these when it redeploys queries. The client also learns the
current hash of every query the page itself sends, so live values override
these defaults. If listing fails with PersistedQueryNotFound, update the value
here.
"""

QUERIES: dict[str, str] = {
    # Conversation list (sidebar history), paged forward with endCursor.
    "ChatHistoryListPaginationQuery": (
        "6ce01455b0201e625489da90c65f87a2809d212ea41ab6e39412b6913990e81f"
    ),
    # Messages of one chat, paged backward (older) with startCursor while
    # pageInfo.hasPreviousPage is true. Only used when scrolling the page does
    # not load older messages by itself.
    "ChatListPaginationQuery": (
        "c1a8fd96dd6e0a4679814182951b1e256e175587513c81b223addf931833a692"
    ),
}
