# utils/graph_mail.py
import msal, requests
from django.conf import settings

AUTHORITY = f"https://login.microsoftonline.com/{settings.GRAPH_TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]

def _get_access_token():
    app = msal.ConfidentialClientApplication(
        settings.GRAPH_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=settings.GRAPH_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result}")
    return result["access_token"]

def send_graph_mail(subject: str, body_text: str, to):
    """
    Send a simple text email via Graph as GRAPH_SENDER.
    `to` can be a string or list of strings.
    """
    if isinstance(to, str):
        to = [to]
    token = _get_access_token()

    url = f"https://graph.microsoft.com/v1.0/users/{settings.GRAPH_SENDER}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            "from": {"emailAddress": {"address": settings.GRAPH_SENDER}},
        },
        "saveToSentItems": False,
    }
    r = requests.post(
        url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=20
    )
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Graph sendMail failed ({r.status_code}): {r.text}")
