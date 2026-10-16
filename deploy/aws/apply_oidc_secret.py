"""Repair beeview/entra-oidc if a Windows shell stripped the JSON quotes, then push the
credentials into the ALB's OIDC listener action. Never prints the secret value."""
import json
import os
import re
import subprocess

os.environ.setdefault("AWS_PROFILE", "sso-standard-user-414678956813")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
TENANT = "fcb2b37b-5da0-466b-9b83-0014b67a7c78"
EXPECTED_CLIENT = "69e86b34-e61c-4fd9-a140-658731119be2"


def aws(*args):
    return subprocess.run(["aws", *args], check=True, capture_output=True, text=True).stdout.strip()


raw = aws("secretsmanager", "get-secret-value", "--secret-id", "beeview/entra-oidc", "--query", "SecretString", "--output", "text")
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    m = re.match(r"""\{\s*['"]?client_id['"]?\s*[:=]\s*['"]?([^,'"\s}]+)['"]?\s*,\s*['"]?client_secret['"]?\s*[:=]\s*['"]?(.+?)['"]?\s*\}\s*$""", raw.strip().strip("'"))
    if not m:
        raise SystemExit("stored value is neither JSON nor a recognisable {client_id:..,client_secret:..} form")
    data = {"client_id": m.group(1), "client_secret": m.group(2)}
    fixed = json.dumps(data)
    aws("secretsmanager", "put-secret-value", "--secret-id", "beeview/entra-oidc", "--secret-string", fixed, "--query", "VersionId", "--output", "text")
    print("secret rewritten as valid JSON")

cid, csec = data["client_id"], data["client_secret"]
is_guid = bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", csec))
print(f"client_id ok: {cid == EXPECTED_CLIENT} | secret length {len(csec)} | secret looks like a GUID (wrong column): {is_guid}")
if is_guid:
    raise SystemExit("the stored client_secret is still the Secret ID, not the Value")

lb = aws("elbv2", "describe-load-balancers", "--names", "beeview", "--query", "LoadBalancers[0].LoadBalancerArn", "--output", "text")
listener = aws("elbv2", "describe-listeners", "--load-balancer-arn", lb, "--query", "Listeners[0].ListenerArn", "--output", "text")
tg = aws("elbv2", "describe-target-groups", "--names", "beeview", "--query", "TargetGroups[0].TargetGroupArn", "--output", "text")
actions = [
    {
        "Type": "authenticate-oidc",
        "Order": 1,
        "AuthenticateOidcConfig": {
            "Issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "AuthorizationEndpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
            "TokenEndpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            "UserInfoEndpoint": "https://graph.microsoft.com/oidc/userinfo",
            "ClientId": cid,
            "ClientSecret": csec,
            "Scope": "openid offline_access",
            "SessionTimeout": 43200,
            "OnUnauthenticatedRequest": "authenticate",
        },
    },
    {"Type": "forward", "Order": 2, "TargetGroupArn": tg},
]
out = aws("elbv2", "modify-listener", "--listener-arn", listener, "--default-actions", json.dumps(actions), "--query", "Listeners[0].DefaultActions[].Type", "--output", "text")
print("listener actions:", out)
