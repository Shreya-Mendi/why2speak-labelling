# When2Speak label audit

A small Streamlit app for auditing the Speak/Silent labels in the When2Speak
dataset. People read short group chats and decide whether an AI assistant should
speak up at that moment or stay quiet. 230 chats from the test split, 12 slots of
60 trials each, every answer saved to Postgres.

This branch holds only the deployed copy. The builder and the analysis live with
the When2Speak paper code.

Deploy: share.streamlit.io, Create app, this repo, branch `when2speak`, main file
`app.py`, Python 3.13 under Advanced settings. Paste the secrets under Settings,
Secrets (layout in `.streamlit/secrets.toml.example`).

- `app.py`: the labeller UI
- `audit_store.py`: Postgres storage, plus a local test mode
- `audit_items_public.json`: the 230 chats, without gold labels
- `audit_plans.json`: which chats each of the 12 slots sees, and in what order
