from agent_server.core.oauth_clients import first_party_oauth_client


def test_desktop_clients_require_their_own_exact_callback():
    ids = ("agents-anywhere-desktop", "agents-anywhere-fork-desktop")
    for client_id in ids:
        client = first_party_oauth_client(client_id)
        assert client is not None
        assert client.allows_redirect(f"{client_id}://oauth/callback")
        other = next(value for value in ids if value != client_id)
        assert not client.allows_redirect(f"{other}://oauth/callback")
        for suffix in ("?next=foreign", "#foreign", "/", "\n"):
            assert not client.allows_redirect(f"{client_id}://oauth/callback{suffix}")
