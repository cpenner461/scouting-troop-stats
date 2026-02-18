"""HTTP client for api.scouting.org (stdlib only)."""

import json
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://api.scouting.org"


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
