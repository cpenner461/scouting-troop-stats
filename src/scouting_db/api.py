"""HTTP client for api.scouting.org (stdlib only)."""

import json
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://api.scouting.org"
AUTH_URL = "https://my.scouting.org/api/users/{username}/authenticate"

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def authenticate(username, password):
    """Authenticate with my.scouting.org and return (token, user_id).

    POSTs credentials to the Scoutbook authentication endpoint and returns
    the bearer token and the account's userId from the JSON response.

    Raises ScoutingAPIError on HTTP errors or if the response is missing
    expected fields.
    """
    url = AUTH_URL.format(username=urllib.parse.quote(username, safe=""))
    body = urllib.parse.urlencode({"password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json; version=2")
    req.add_header("User-Agent", _CHROME_UA)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ScoutingAPIError(e.code, body_text) from e

    token = data.get("token")
    user_id = (data.get("account") or {}).get("userId")
    if not token:
        raise ScoutingAPIError(0, f"No token in response: {data}")
    return token, user_id


class ScoutingAPIError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class ScoutingAPI:
    def __init__(self, token=None):
        self.token = token

    def _request(self, path, params=None, method="GET", body=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise ScoutingAPIError(e.code, body_text) from e

    # --- Public endpoints (no auth) ---

    def get_ranks(self, program_id=None, version=2, status="Active"):
        params = {"version": version, "status": status}
        if program_id is not None:
            params["programId"] = program_id
        return self._request("/advancements/ranks", params)

    def get_rank_requirements(self, rank_id):
        return self._request(f"/advancements/ranks/{rank_id}/requirements")

    # --- Auth-required endpoints ---

    def get_youth_ranks(self, user_id):
        return self._request(f"/advancements/v2/youth/{user_id}/ranks")

    def get_youth_merit_badges(self, user_id):
        return self._request(f"/advancements/v2/youth/{user_id}/meritBadges")

    def get_youth_awards(self, user_id):
        return self._request(f"/advancements/v2/youth/{user_id}/awards")

    def get_mb_requirements(self, mb_id):
        """Public endpoint: requirement definitions for a merit badge."""
        return self._request(
            f"/advancements/meritBadges/{mb_id}/requirements"
        )

    def get_youth_mb_requirements(self, user_id, mb_id):
        """Auth endpoint: per-scout MB requirement completion."""
        return self._request(
            f"/advancements/v2/youth/{user_id}/meritBadges/{mb_id}/requirements"
        )

    def get_youth_rank_requirements(self, user_id, rank_id):
        """Auth endpoint: per-scout rank requirement completion."""
        return self._request(
            f"/advancements/v2/youth/{user_id}/ranks/{rank_id}/requirements"
        )

    def get_leadership_history(self, user_id):
        return self._request(
            f"/advancements/youth/{user_id}/leadershipPositionHistory"
        )

    def get_person_profile(self, user_id):
        """Auth endpoint: person profile data (includes birthdate)."""
        return self._request(f"/persons/v2/{user_id}/personprofile")

    def validate_token(self, user_id):
        """Verify the token is valid by making a lightweight auth-required request.

        Uses a Scout's user_id to hit a known auth-required endpoint.
        Raises ScoutingAPIError (status_code == 401) if the token is expired or invalid.
        """
        self._request(f"/advancements/v2/youth/{user_id}/ranks")
